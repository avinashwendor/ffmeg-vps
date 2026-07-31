import { spawn } from 'node:child_process';
import { promises as fs } from 'node:fs';
import { dirname, join } from 'node:path';
import { downloadToFile } from './s3.js';

function run(cmd, args, opts = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(cmd, args, { stdio: ['ignore', 'pipe', 'pipe'], ...opts });
    let stdout = '';
    let stderr = '';
    child.stdout.on('data', (d) => { stdout += d; });
    child.stderr.on('data', (d) => { stderr += d; });
    child.on('close', (code) => {
      if (code === 0) resolve({ stdout, stderr });
      else reject(new Error(`${cmd} exited ${code}: ${stderr.slice(-1200)}`));
    });
  });
}

export async function ffprobeDuration(filePath) {
  const { stdout } = await run('ffprobe', [
    '-v', 'error',
    '-show_entries', 'format=duration',
    '-of', 'default=noprint_wrappers=1:nokey=1',
    filePath,
  ]);
  return Number(stdout.trim()) || 0;
}

function escapePath(p) {
  return p.replace(/\\/g, '/').replace(/:/g, '\\:').replace(/'/g, "'\\''");
}

function srtTimeToAss(t) {
  const [h, m, rest] = t.trim().split(':');
  const [s, ms] = rest.split(',');
  const cs = String(Math.floor(Number(ms) / 10)).padStart(2, '0');
  return `${h}:${m}:${s}.${cs}`;
}

// ASS wants &HAABBGGRR — blue and red swapped relative to hex, alpha first.
function hexToAss(hex, fallback) {
  const m = String(hex || '').trim().match(/^#?([0-9a-f]{6})$/i);
  if (!m) return fallback;
  const [r, g, b] = [0, 2, 4].map((i) => m[1].slice(i, i + 2).toUpperCase());
  return `&H00${b}${g}${r}`;
}

export function srtToAss(srt, style = {}) {
  const font = style.font || 'Arial';
  const size = style.size || 52;
  const primary = hexToAss(style.color, '&H00FFFFFF');
  const outline = hexToAss(style.outline_color, '&H00000000');
  const blocks = String(srt || '').trim().split(/\n\n+/);
  const events = [];
  for (const block of blocks) {
    const lines = block.split('\n');
    const timeLine = lines.find((l) => l.includes('-->'));
    if (!timeLine) continue;
    const [start, end] = timeLine.split('-->').map((s) => s.trim());
    const text = lines.slice(lines.indexOf(timeLine) + 1).join(' ').trim();
    if (!text) continue;
    events.push(`Dialogue: 0,${srtTimeToAss(start)},${srtTimeToAss(end)},Default,,0,0,0,,${text.replace(/\n/g, '\\N')}`);
  }
  return `[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,${font},${size},${primary},&H000000FF,${outline},&H80000000,-1,0,0,0,100,100,0,0,1,3,1,2,40,40,120,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
${events.join('\n')}
`;
}

function defaultRecipe() {
  return {
    clip_order: [1, 2, 3, 4, 5],
    per_clip: [1, 2, 3, 4, 5].map((index) => ({ index, trim_start: 0, trim_end: null, speed: 1 })),
    transitions: [{ after_clip: 1, type: 'xfade', duration_ms: 300 }],
    audio: { voiceover_gain_db: 0, clip_audio_gain_db: -20, fade_in_ms: 200, fade_out_ms: 400 },
    subtitles: { mode: 'burn', font: 'Arial', size: 52, color: '#FFFFFF', outline_color: '#000000' },
    color: { saturation: 1.08, contrast: 1.05, brightness: 0.01 },
  };
}

export function normalizeRecipe(recipe) {
  const base = defaultRecipe();
  if (!recipe || typeof recipe !== 'object') return base;
  return {
    ...base,
    ...recipe,
    per_clip: Array.isArray(recipe.per_clip) && recipe.per_clip.length ? recipe.per_clip : base.per_clip,
    transitions: Array.isArray(recipe.transitions) ? recipe.transitions : base.transitions,
    audio: { ...base.audio, ...(recipe.audio || {}) },
    subtitles: { ...base.subtitles, ...(recipe.subtitles || {}) },
    color: { ...base.color, ...(recipe.color || {}) },
  };
}

async function normalizeClip(inputPath, outputPath, clipSpec, color) {
  const trimStart = Number(clipSpec.trim_start || 0);
  const trimEnd = clipSpec.trim_end != null ? Number(clipSpec.trim_end) : null;
  const speed = Number(clipSpec.speed || 1) || 1;
  const zoom = Number(clipSpec.zoom || 1) || 1;
  const sat = Number(color.saturation || 1);
  const con = Number(color.contrast || 1);
  const bri = Number(color.brightness || 0);

  // setpts has to live in this same chain: -filter:v and -vf are aliases, so
  // passing both silently drops the first one and the clip plays at 1x.
  const vf = [
    speed !== 1 ? `setpts=PTS/${speed}` : null,
    `scale=1080:1920:force_original_aspect_ratio=increase`,
    `crop=1080:1920`,
    zoom !== 1 ? `scale=iw*${zoom}:ih*${zoom},crop=1080:1920` : null,
    `fps=30`,
    `eq=saturation=${sat}:contrast=${con}:brightness=${bri}`,
    `setsar=1`,
  ].filter(Boolean).join(',');

  const args = ['-y', '-ss', String(trimStart)];
  // -t (duration) rather than -to, so the window is unambiguous once -ss has
  // already moved the input position.
  if (trimEnd != null && trimEnd > trimStart) args.push('-t', String(trimEnd - trimStart));
  args.push('-i', inputPath, '-an', '-vf', vf);
  args.push('-c:v', 'libx264', '-preset', 'fast', '-crf', '20', '-pix_fmt', 'yuv420p', outputPath);
  await run('ffmpeg', args);
}

async function concatClips(clipPaths, outputPath, transitionMs = 300) {
  if (clipPaths.length === 1) {
    await fs.copyFile(clipPaths[0], outputPath);
    return;
  }
  if (clipPaths.length === 2) {
    const d0 = await ffprobeDuration(clipPaths[0]);
    const offset = Math.max(0, d0 - transitionMs / 1000);
    await run('ffmpeg', [
      '-y', '-i', clipPaths[0], '-i', clipPaths[1],
      '-filter_complex', `[0:v][1:v]xfade=transition=fade:duration=${transitionMs / 1000}:offset=${offset}[v]`,
      '-map', '[v]', '-c:v', 'libx264', '-preset', 'fast', '-crf', '20', '-pix_fmt', 'yuv420p', '-an', outputPath,
    ]);
    return;
  }

  // Chain xfade for 3+ clips
  let current = clipPaths[0];
  const tmpDir = dirname(outputPath);
  for (let i = 1; i < clipPaths.length; i++) {
    const nextOut = join(tmpDir, `xfade_${i}.mp4`);
    const d = await ffprobeDuration(current);
    const offset = Math.max(0, d - transitionMs / 1000);
    await run('ffmpeg', [
      '-y', '-i', current, '-i', clipPaths[i],
      '-filter_complex', `[0:v][1:v]xfade=transition=fade:duration=${transitionMs / 1000}:offset=${offset}[v]`,
      '-map', '[v]', '-c:v', 'libx264', '-preset', 'fast', '-crf', '20', '-pix_fmt', 'yuv420p', '-an', nextOut,
    ]);
    current = nextOut;
  }
  await fs.copyFile(current, outputPath);
}

async function muxVoiceover(videoPath, voicePath, outputPath, audioSpec) {
  const fadeIn = Number(audioSpec.fade_in_ms || 0) / 1000;
  const fadeOut = Number(audioSpec.fade_out_ms || 0) / 1000;
  const voGain = Number(audioSpec.voiceover_gain_db || 0);

  const dur = await ffprobeDuration(videoPath);
  const fadeOutStart = Math.max(0, dur - fadeOut);
  const af = voGain === 0
    ? `afade=t=in:st=0:d=${fadeIn},afade=t=out:st=${fadeOutStart}:d=${fadeOut}`
    : `volume=${voGain}dB,afade=t=in:st=0:d=${fadeIn},afade=t=out:st=${fadeOutStart}:d=${fadeOut}`;

  await run('ffmpeg', [
    '-y', '-i', videoPath, '-i', voicePath,
    '-map', '0:v:0', '-map', '1:a:0',
    '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k',
    '-af', af,
    '-shortest', outputPath,
  ]);
}

async function burnSubtitles(videoPath, assPath, outputPath) {
  const vf = `subtitles='${escapePath(assPath)}'`;
  await run('ffmpeg', [
    '-y', '-i', videoPath,
    '-vf', vf,
    '-c:v', 'libx264', '-preset', 'fast', '-crf', '20',
    '-c:a', 'copy',
    outputPath,
  ]);
}

export async function renderReel({ workDir, clipUrls, voiceoverUrl, subtitlesSrt, recipe }) {
  const r = normalizeRecipe(recipe);
  const order = (r.clip_order || [1, 2, 3, 4, 5]).map(Number);
  const clipMap = new Map((clipUrls || []).map((c) => [Number(c.index), c.url || c]));

  const normalized = [];
  for (const index of order) {
    const url = clipMap.get(index);
    if (!url) throw new Error(`Missing clip URL for index ${index}`);
    const rawPath = join(workDir, `clip-${index}-raw.mp4`);
    const normPath = join(workDir, `clip-${index}-norm.mp4`);
    await downloadToFile(url, rawPath);
    const spec = r.per_clip.find((p) => Number(p.index) === index) || { index, trim_start: 0 };
    if (spec.trim_end == null) {
      const dur = await ffprobeDuration(rawPath);
      spec.trim_end = dur;
    }
    await normalizeClip(rawPath, normPath, spec, r.color);
    normalized.push(normPath);
  }

  const transitionMs = Number(r.transitions?.[0]?.duration_ms || 300);
  const concatPath = join(workDir, 'concat.mp4');
  await concatClips(normalized, concatPath, transitionMs);

  const voicePath = join(workDir, 'voiceover.mp3');
  await downloadToFile(voiceoverUrl, voicePath);
  const withAudioPath = join(workDir, 'with-audio.mp4');
  await muxVoiceover(concatPath, voicePath, withAudioPath, r.audio);

  let finalPath = withAudioPath;
  if (r.subtitles?.mode === 'burn' && subtitlesSrt) {
    const assPath = join(workDir, 'subs.ass');
    await fs.writeFile(assPath, srtToAss(subtitlesSrt, r.subtitles), 'utf8');
    const subsPath = join(workDir, 'final.mp4');
    await burnSubtitles(withAudioPath, assPath, subsPath);
    finalPath = subsPath;
  }

  const duration = await ffprobeDuration(finalPath);
  return { finalPath, duration };
}
