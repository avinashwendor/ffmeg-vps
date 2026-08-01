import { spawn } from 'node:child_process';
import { promises as fs } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { downloadToFile } from './s3.js';
import {
  buildAss,
  finishFilters,
  motionFilter,
  motionSequence,
  normalizeCues,
  pickTransitions,
  resolveCaptionStyle,
  resolveMotion,
  scaleCues,
  wrapCue,
} from './looks.js';

export { wrapCue, buildAss, normalizeCues, scaleCues, pickTransitions, motionFilter } from './looks.js';
export { LOGO_WIDTH, LOGO_MARGIN_X, LOGO_MARGIN_TOP };

// ffmpeg sizes its thread pools from the *host* core count, not the container's
// memory limit. On a big host that means x264 keeps (threads + lookahead)
// 1080x1920 frames in flight — hundreds of MB — and the OOM killer takes the
// process out mid-encode, which surfaces here as a null exit code. Capping
// threads is what keeps a multi-clip render alive in a small container.
const FFMPEG_THREADS = String(Number(process.env.FFMPEG_THREADS) || 2);
const X264_PRESET = process.env.FFMPEG_PRESET || 'veryfast';
const X264_CRF = String(Number(process.env.FFMPEG_CRF) || 21);

function encodeArgs() {
  return [
    '-c:v', 'libx264',
    '-preset', X264_PRESET,
    '-crf', X264_CRF,
    '-threads', FFMPEG_THREADS,
    // Without a bounded lookahead x264 still buffers frames per thread.
    '-x264-params', `threads=${FFMPEG_THREADS}:lookahead-threads=1:sliced-threads=0:rc-lookahead=20`,
    '-pix_fmt', 'yuv420p',
  ];
}

function filterThreadArgs() {
  return ['-filter_threads', FFMPEG_THREADS, '-filter_complex_threads', FFMPEG_THREADS];
}

function run(cmd, args, opts = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(cmd, args, { stdio: ['ignore', 'pipe', 'pipe'], ...opts });
    let stdout = '';
    let stderr = '';
    child.stdout.on('data', (d) => { stdout += d; });
    child.stderr.on('data', (d) => { stderr += d; });
    child.on('error', (err) => reject(new Error(`${cmd} failed to start: ${err.message}`)));
    child.on('close', (code, signal) => {
      if (code === 0) { resolve({ stdout, stderr }); return; }
      if (code === null) {
        // Killed rather than exited — almost always the container OOM killer.
        reject(new Error(
          `${cmd} was killed by ${signal || 'the OS'} — the container ran out of memory. ` +
          `Raise the service memory or lower FFMPEG_THREADS (currently ${FFMPEG_THREADS}).`
        ));
        return;
      }
      reject(new Error(`${cmd} exited ${code}: ${stderr.slice(-1200)}`));
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

// Structural read of the finished file. A reel that is the right length but has
// two audio tracks, or came out 1080x1080, is still not shippable.
export async function ffprobeStreams(filePath) {
  const { stdout } = await run('ffprobe', [
    '-v', 'error',
    '-show_entries', 'stream=codec_type,width,height',
    '-of', 'json',
    filePath,
  ]);
  const streams = JSON.parse(stdout).streams || [];
  const video = streams.find((s) => s.codec_type === 'video') || null;
  return {
    videoStreams: streams.filter((s) => s.codec_type === 'video').length,
    audioStreams: streams.filter((s) => s.codec_type === 'audio').length,
    width: video ? Number(video.width) : 0,
    height: video ? Number(video.height) : 0,
  };
}

// Burning subtitles needs an ffmpeg built with libass. Debian's ffmpeg package
// has it; a stripped static build does not, and the filter is simply absent —
// which surfaces as an unhelpful filtergraph parse error at the very last step,
// after every clip has already been encoded. Checked once, up front.
let filterCache = null;
export async function ffmpegHasFilter(name) {
  if (!filterCache) {
    filterCache = run('ffmpeg', ['-hide_banner', '-filters'])
      .then(({ stdout }) => stdout)
      .catch(() => '');
  }
  const listing = await filterCache;
  return new RegExp(`^\\s*\\S+\\s+${name}\\s`, 'm').test(listing);
}

// xfade grew most of its catalogue across ffmpeg 5.x, and naming a transition
// this build does not have fails the filtergraph at the very last step — after
// every clip has already been encoded. Read what is actually compiled in.
let xfadeCache = null;
export async function xfadeTransitions() {
  if (!xfadeCache) {
    xfadeCache = run('ffmpeg', ['-hide_banner', '-h', 'filter=xfade'])
      .then(({ stdout }) => new Set(
        [...stdout.matchAll(/^\s{5}(\w+)\s+-?\d+\s+\.\.FV/gm)].map((m) => m[1].toLowerCase())
      ))
      .catch(() => new Set(['fade']));
  }
  return xfadeCache;
}

function escapePath(p) {
  return p.replace(/\\/g, '/').replace(/:/g, '\\:').replace(/'/g, "'\\''");
}

// Every cue time scales by the same factor, because the whole timeline is one
// proportional split of a single voiceover. Used when the probed voiceover
// turns out longer or shorter than the manifest predicted.
export function scaleSrt(srt, scale) {
  if (!(scale > 0) || Math.abs(scale - 1) < 1e-6) return srt;
  return String(srt || '').replace(/(\d{2}):(\d{2}):(\d{2}),(\d{3})/g, (_m, h, m, s, ms) => {
    const total = (Number(h) * 3600 + Number(m) * 60 + Number(s) + Number(ms) / 1000) * scale;
    const hh = Math.floor(total / 3600);
    const mm = Math.floor((total % 3600) / 60);
    const ss = Math.floor(total % 60);
    const mmm = Math.round((total - Math.floor(total)) * 1000);
    return `${String(hh).padStart(2, '0')}:${String(mm).padStart(2, '0')}:${String(ss).padStart(2, '0')},${String(mmm).padStart(3, '0')}`;
  });
}

// Each clip is on screen for its share of the voiceover plus the overlap the
// crossfade eats from it — the last clip carries a short tail instead.
//
// Two things can differ from what the generator planned, and both move the cut
// off the words. The voiceover can turn out longer or shorter than the byte-size
// estimate, which scales the speech share. And the render director is allowed to
// pick a 250-400ms transition, while the plan was built assuming whatever
// transition_sec the manifest recorded — a longer crossfade eats more of each
// clip, so the reel finishes before the voiceover does. The overlap is a
// constant of the edit and never scales; it is swapped, not stretched.
export function rescalePerClip(perClip, options = {}) {
  const {
    scale = 1,
    plannedTransitionSec = 0.3,
    transitionSec = plannedTransitionSec,
    tailSec = 0.25,
  } = options;
  if (!Array.isArray(perClip) || !(scale > 0)) return perClip;
  const sameScale = Math.abs(scale - 1) < 1e-6;
  const sameTransition = Math.abs(transitionSec - plannedTransitionSec) < 1e-6;
  if (sameScale && sameTransition) return perClip;

  const last = perClip.length - 1;
  return perClip.map((p, i) => {
    if (p.trim_end == null) return p;
    const start = Math.max(0, Number(p.trim_start || 0));
    const plannedOverlap = i === last ? tailSec : plannedTransitionSec;
    const actualOverlap = i === last ? tailSec : transitionSec;
    const voPart = Math.max(0, Number(p.trim_end) - start - plannedOverlap);
    return { ...p, trim_end: Number((start + voPart * scale + actualOverlap).toFixed(3)) };
  });
}

// The manifest's voiceover length is derived from the mp3's byte size, which an
// ID3 tag or a provider quietly ignoring the requested bitrate can throw off.
// Here the file is on disk and ffprobe has read it, so this is ground truth —
// but a wild ratio means the plan belongs to a different run, and stretching
// the edit to match would do more damage than leaving it alone.
export function voiceoverScale(plannedSec, actualSec) {
  const planned = Number(plannedSec) || 0;
  const actual = Number(actualSec) || 0;
  if (planned <= 0 || actual <= 0) {
    return { scale: 1, applied: false, reason: 'no planned duration to compare against' };
  }
  const scale = actual / planned;
  if (scale < 0.5 || scale > 2) {
    return { scale: 1, applied: false, reason: `probed ${actual.toFixed(2)}s vs planned ${planned.toFixed(2)}s is too far apart to be the same voiceover — plan left as-is` };
  }
  if (Math.abs(scale - 1) < 0.01) {
    return { scale: 1, applied: false, reason: 'planned duration matched the file' };
  }
  return { scale, applied: true, reason: `plan rescaled ${scale.toFixed(4)}x — voiceover is really ${actual.toFixed(2)}s, plan assumed ${planned.toFixed(2)}s` };
}

function defaultRecipe() {
  return {
    clip_order: [1, 2, 3, 4, 5],
    per_clip: [1, 2, 3, 4, 5].map((index) => ({ index, trim_start: 0, trim_end: null, speed: 1 })),
    transitions: [{ after_clip: 1, type: 'xfade', duration_ms: 300 }],
    audio: { voiceover_gain_db: 0, clip_audio_gain_db: -20, fade_in_ms: 200, fade_out_ms: 400 },
    subtitles: { mode: 'burn', preset: 'clean_bold' },
    color: { saturation: 1.08, contrast: 1.05, brightness: 0.01 },
    // Empty means "choose for me" — a reel where nothing moves reads as a
    // slideshow, so a missing motion plan is filled in rather than left static.
    motion: [],
    finish: { vignette: 0, grain: 0, sharpen: 0 },
    // Rotates the default motion and cut sequences so two runs of the same
    // script do not come back as the same edit.
    look_seed: 0,
    // Not part of the "look" — this is brand identity, not a creative choice,
    // so it is never described to the render director. `enabled: false` exists
    // purely as a manual override for a one-off unbranded export.
    branding: { enabled: true },
  };
}

// The generator plans against an assumed clip length, but the clip that
// actually turns up decides what is possible: Veo returns 8s, Gemini Omni 10s,
// and an extended clip can be much longer. What the plan really asks for is
// "keep clip N on screen for this many seconds" — so honour that against the
// real footage, and only slow the clip down when there genuinely is not enough.
export function fitToFootage(spec, actualDuration) {
  const trimStart = Math.max(0, Number(spec.trim_start || 0));
  const speed = Number(spec.speed) > 0 ? Number(spec.speed) : 1;
  const planned = spec.trim_end == null ? null : Number(spec.trim_end) - trimStart;
  const actual = Number(actualDuration) || 0;

  // No duration probe and no plan: use the whole clip as-is.
  if (!actual) return { ...spec, trim_start: trimStart, speed };

  const wanted = planned == null ? actual / speed : planned / speed;
  const available = Math.max(0, actual - trimStart);

  if (available >= wanted) {
    // Enough footage — take exactly what is needed and drop the slow-motion.
    return { ...spec, trim_start: trimStart, trim_end: trimStart + wanted, speed: 1 };
  }
  // Short clip: use all of it and stretch to fill, but not into a visible stutter.
  return {
    ...spec,
    trim_start: trimStart,
    trim_end: actual,
    speed: Math.max(0.5, available / wanted),
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
    motion: Array.isArray(recipe.motion) ? recipe.motion : base.motion,
    finish: { ...base.finish, ...(recipe.finish || {}) },
    look_seed: Number(recipe.look_seed) || base.look_seed,
    branding: { ...base.branding, ...(recipe.branding || {}) },
  };
}

async function normalizeClip(inputPath, outputPath, clipSpec, color, look = {}) {
  const trimStart = Number(clipSpec.trim_start || 0);
  const trimEnd = clipSpec.trim_end != null ? Number(clipSpec.trim_end) : null;
  const speed = Number(clipSpec.speed || 1) || 1;
  const sat = Number(color.saturation || 1);
  const con = Number(color.contrast || 1);
  const bri = Number(color.brightness || 0);

  // The move has to complete over the clip's *rendered* length, which is what
  // is left after the trim and the speed change.
  const sourceLen = trimEnd != null && trimEnd > trimStart ? trimEnd - trimStart : null;
  const renderedLen = sourceLen != null ? sourceLen / speed : Number(look.durationSec) || 4;
  const motion = resolveMotion(look.motion, clipSpec.zoom);

  // setpts has to live in this same chain: -filter:v and -vf are aliases, so
  // passing both silently drops the first one and the clip plays at 1x. It also
  // has to come *before* the motion, so the move is timed against the sped-up
  // clip rather than the original.
  const vf = [
    speed !== 1 ? `setpts=PTS/${speed}` : null,
    motionFilter(motion, renderedLen),
    `fps=30`,
    `eq=saturation=${sat}:contrast=${con}:brightness=${bri}`,
    ...finishFilters(look.finish),
    `setsar=1`,
  ].filter(Boolean).join(',');

  const args = ['-y', ...filterThreadArgs(), '-ss', String(trimStart)];
  // -t (duration) rather than -to, so the window is unambiguous once -ss has
  // already moved the input position.
  if (trimEnd != null && trimEnd > trimStart) args.push('-t', String(trimEnd - trimStart));
  args.push('-i', inputPath, '-an', '-vf', vf, ...encodeArgs(), outputPath);
  await run('ffmpeg', args);
}

// `transitions` is one type per cut, in order. Their *duration* is deliberately
// shared: the whole plan was built against a single transition_sec, and a cut
// that overlaps more than budgeted takes the extra out of the voiceover.
async function concatClips(clipPaths, outputPath, transitionMs = 300, transitions = []) {
  if (clipPaths.length === 1) {
    await fs.copyFile(clipPaths[0], outputPath);
    return;
  }
  // Chain xfade pairwise. A single filter_complex over all five would decode
  // every clip at once, which is the opposite of what a memory-capped
  // container wants.
  let current = clipPaths[0];
  const tmpDir = dirname(outputPath);
  for (let i = 1; i < clipPaths.length; i++) {
    const isLast = i === clipPaths.length - 1;
    const nextOut = isLast ? outputPath : join(tmpDir, `xfade_${i}.mp4`);
    const d = await ffprobeDuration(current);
    const offset = Math.max(0, d - transitionMs / 1000);
    const type = transitions[i - 1] || 'fade';
    await run('ffmpeg', [
      '-y', ...filterThreadArgs(), '-i', current, '-i', clipPaths[i],
      '-filter_complex', `[0:v][1:v]xfade=transition=${type}:duration=${transitionMs / 1000}:offset=${offset}[v]`,
      '-map', '[v]', '-an', ...encodeArgs(), nextOut,
    ]);
    if (current !== clipPaths[0]) await fs.rm(current, { force: true });
    current = nextOut;
  }
}

async function muxVoiceover(videoPath, voicePath, outputPath, audioSpec) {
  const fadeIn = Number(audioSpec.fade_in_ms || 0) / 1000;
  const fadeOut = Number(audioSpec.fade_out_ms || 0) / 1000;
  const voGain = Number(audioSpec.voiceover_gain_db || 0);

  const dur = await ffprobeDuration(videoPath);
  const fadeOutStart = Math.max(0, dur - fadeOut);
  // Bring the voiceover to the loudness social platforms normalise to. Without
  // this, a quiet TTS take gets turned up by the platform along with its noise
  // floor, and a hot one gets pulled down mid-sentence.
  const af = [
    voGain === 0 ? null : `volume=${voGain}dB`,
    'loudnorm=I=-16:TP=-1.5:LRA=11',
    `afade=t=in:st=0:d=${fadeIn}`,
    `afade=t=out:st=${fadeOutStart}:d=${fadeOut}`,
  ].filter(Boolean).join(',');

  // Explicit maps are the second guarantee that no clip audio reaches the reel:
  // video comes from the concat, audio only ever from the voiceover file. The
  // first guarantee is -an in normalizeClip, which strips each clip's generated
  // dialogue before it is ever seen again. Do not replace these with defaults.
  await run('ffmpeg', [
    '-y', '-i', videoPath, '-i', voicePath,
    '-map', '0:v:0', '-map', '1:a:0',
    '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k',
    '-af', af,
    '-shortest', outputPath,
  ]);
}

// ── BRAND WATERMARK ─────────────────────────────────────────────────────────
//
// The wendor mark sits top-right on every reel, always, with no way for a
// director prompt or a bad recipe to turn it off by accident — it is a brand
// requirement, not a creative choice, so it never goes near the JSON the model
// fills in. `recipe.branding.enabled` exists only as a manual escape hatch.
const LOGO_WIDTH = 260;
const LOGO_MARGIN_X = 40;
// Top-right is clear of the caption/handle/button furniture Reels and Shorts
// draw across the *bottom* of the frame, so the mark does not need the same
// safe-zone math the captions do — just enough margin to clear a status bar.
const LOGO_MARGIN_TOP = 84;

function defaultLogoPath() {
  const here = dirname(fileURLToPath(import.meta.url));
  return join(here, '..', 'assets', 'wendor-logo.png');
}

// Baked into the Docker image at build time, so this is a fixed answer for the
// life of the process — resolved once and cached, not re-checked per render.
let logoPathCache;
export async function findLogo() {
  if (logoPathCache !== undefined) return logoPathCache;
  const path = process.env.WENDOR_LOGO_PATH || defaultLogoPath();
  try {
    await fs.access(path);
    logoPathCache = path;
  } catch {
    logoPathCache = null;
  }
  return logoPathCache;
}

// Subtitles and the logo are two different overlays on the same frame, and
// each is its own full re-encode — so they are combined into one filter graph
// and one encode rather than run as two passes back to back. Called only when
// at least one of assPath/logoPath is set.
async function finishVideo(videoPath, outputPath, { assPath, logoPath }) {
  const inputs = ['-i', videoPath];
  const filterParts = [];
  let videoLabel = '0:v';

  if (assPath) {
    filterParts.push(`[${videoLabel}]subtitles='${escapePath(assPath)}'[subbed]`);
    videoLabel = 'subbed';
  }
  if (logoPath) {
    const logoInputIndex = inputs.length / 2;
    inputs.push('-i', logoPath);
    // -2 rather than -1: the auto-computed height must come out even, or some
    // ffmpeg builds reject the intermediate frame once it is composited onto
    // a yuv420p output.
    filterParts.push(`[${logoInputIndex}:v]scale=${LOGO_WIDTH}:-2[logo]`);
    filterParts.push(`[${videoLabel}][logo]overlay=x=W-w-${LOGO_MARGIN_X}:y=${LOGO_MARGIN_TOP}[branded]`);
    videoLabel = 'branded';
  }

  await run('ffmpeg', [
    '-y', ...filterThreadArgs(),
    ...inputs,
    '-filter_complex', filterParts.join(';'),
    '-map', `[${videoLabel}]`,
    '-map', '0:a',
    ...encodeArgs(),
    '-c:a', 'copy',
    outputPath,
  ]);
}

const QC_TOLERANCE_SEC = Number(process.env.QC_TOLERANCE_SEC) || 0.75;

// The last gate before a reel is handed to anyone. Everything checked here is
// something that has actually shipped broken at some point: a desynced cut, a
// surviving clip audio track, a frame that is not 9:16.
export function qcReel({ duration, voiceoverSec, streams, toleranceSec = QC_TOLERANCE_SEC }) {
  const problems = [];
  const drift = Number((Number(duration) - Number(voiceoverSec)).toFixed(3));

  if (!(Number(duration) > 0)) {
    problems.push('the rendered file has no duration');
  } else if (Math.abs(drift) > toleranceSec) {
    // -shortest ends the mux on whichever track runs out first, so a healthy
    // reel lands on the voiceover. Short means the picture ran out first and
    // the closing words were cut — the one failure that ruins the reel.
    problems.push(drift < 0
      ? `video ends ${Math.abs(drift).toFixed(2)}s before the voiceover — the closing words are cut off`
      : `video runs ${drift.toFixed(2)}s past the voiceover — it ends on silence`);
  }
  if (streams.audioStreams !== 1) {
    problems.push(`expected exactly 1 audio track (the voiceover), found ${streams.audioStreams}`);
  }
  if (streams.videoStreams !== 1) {
    problems.push(`expected exactly 1 video track, found ${streams.videoStreams}`);
  }
  if (streams.width !== 1080 || streams.height !== 1920) {
    problems.push(`expected a 1080x1920 vertical frame, got ${streams.width}x${streams.height}`);
  }

  return {
    ok: problems.length === 0,
    duration_sec: Number(Number(duration).toFixed(2)),
    voiceover_sec: Number(Number(voiceoverSec).toFixed(2)),
    drift_sec: drift,
    problems,
  };
}

export async function renderReel({
  workDir,
  clipUrls,
  voiceoverUrl,
  subtitlesSrt,
  captionCues,
  recipe,
  voiceoverSec,
  transitionSec: plannedTransitionSec,
  tailSec = 0.25,
}) {
  const r = normalizeRecipe(recipe);
  const order = (r.clip_order || [1, 2, 3, 4, 5]).map(Number);
  const clipMap = new Map((clipUrls || []).map((c) => [Number(c.index), c.url || c]));
  const transitionMs = Number(r.transitions?.[0]?.duration_ms || 300);

  // Word-level cues when the TTS measured them, an SRT when it did not. The
  // caption animations that need per-word timing degrade to a whole-cue pop
  // rather than disappearing.
  const cues = normalizeCues(captionCues, subtitlesSrt);
  const burningSubs = r.subtitles?.mode === 'burn' && cues.length > 0;
  if (burningSubs && !(await ffmpegHasFilter('subtitles'))) {
    throw new Error(
      'This ffmpeg has no "subtitles" filter, so captions cannot be burned — it was built without libass. '
      + 'Install a libass-enabled ffmpeg (Debian\'s ffmpeg package has it) or set subtitles.mode to "none".'
    );
  }

  // The voiceover is what every other duration is measured against, so fetch and
  // probe it before spending minutes in ffmpeg: a dead link fails in seconds,
  // and the plan gets corrected against the real file rather than the byte-size
  // estimate the generator made before the mp3 existed.
  // The primary TTS path returns PCM the workflow wraps as WAV; the fallbacks
  // return mp3. ffmpeg probes content rather than the name, but keeping the
  // real extension makes a work directory readable when a render is debugged.
  const voiceExt = (String(voiceoverUrl).split('?')[0].match(/\.(wav|mp3|m4a|aac|flac|ogg)$/i) || [, 'mp3'])[1];
  const voicePath = join(workDir, `voiceover.${voiceExt.toLowerCase()}`);
  await downloadToFile(voiceoverUrl, voicePath);
  const voiceoverActualSec = await ffprobeDuration(voicePath);
  if (!voiceoverActualSec) {
    throw new Error('Voiceover downloaded but ffprobe found no duration — the file is not playable audio.');
  }

  const timing = voiceoverScale(voiceoverSec, voiceoverActualSec);
  const perClip = rescalePerClip(r.per_clip, {
    scale: timing.scale,
    // Fall back to the transition being rendered, which makes this a no-op —
    // an older manifest without transition_sec is left exactly as it was.
    plannedTransitionSec: Number(plannedTransitionSec) > 0 ? Number(plannedTransitionSec) : transitionMs / 1000,
    transitionSec: transitionMs / 1000,
    tailSec,
  });
  const scaledCues = scaleCues(cues, timing.scale);

  // A move per clip, and a different one on either side of every cut. The
  // director may name them; anything it left out comes from the rotating
  // default sequence so no reel is ever five static shots in a row.
  const defaults = motionSequence(order.length, r.look_seed);
  const motions = order.map((_, i) => r.motion[i] || defaults[i]);
  const transitions = pickTransitions(Math.max(0, order.length - 1), {
    requested: r.transitions,
    available: await xfadeTransitions(),
    seed: r.look_seed,
  });

  const normalized = [];
  for (let i = 0; i < order.length; i++) {
    const index = order[i];
    const url = clipMap.get(index);
    if (!url) throw new Error(`Missing clip URL for index ${index}`);
    const rawPath = join(workDir, `clip-${index}-raw.mp4`);
    const normPath = join(workDir, `clip-${index}-norm.mp4`);
    await downloadToFile(url, rawPath);
    const spec = perClip.find((p) => Number(p.index) === index) || { index, trim_start: 0 };
    const actual = await ffprobeDuration(rawPath);
    await normalizeClip(rawPath, normPath, fitToFootage(spec, actual), r.color, {
      motion: motions[i],
      finish: r.finish,
    });
    // Raw footage is the biggest thing on disk and is finished with once the
    // normalized copy exists; a small container should not hold five of them.
    await fs.rm(rawPath, { force: true });
    normalized.push(normPath);
  }

  const concatPath = join(workDir, 'concat.mp4');
  await concatClips(normalized, concatPath, transitionMs, transitions);

  const withAudioPath = join(workDir, 'with-audio.mp4');
  await muxVoiceover(concatPath, voicePath, withAudioPath, r.audio);

  const captionStyle = resolveCaptionStyle(r.subtitles);
  const wantsBranding = r.branding?.enabled !== false;
  const logoPath = wantsBranding ? await findLogo() : null;

  let assPath = null;
  if (burningSubs) {
    assPath = join(workDir, 'subs.ass');
    await fs.writeFile(assPath, buildAss(scaledCues, r.subtitles), 'utf8');
  }

  // Captions and the logo are two overlays on the same frame — combined into
  // one filter graph so a branded, captioned reel costs one re-encode, not two.
  let finalPath = withAudioPath;
  if (assPath || logoPath) {
    const finishedPath = join(workDir, 'final.mp4');
    await finishVideo(withAudioPath, finishedPath, { assPath, logoPath });
    finalPath = finishedPath;
  }

  const duration = await ffprobeDuration(finalPath);
  const qc = qcReel({
    duration,
    voiceoverSec: voiceoverActualSec,
    streams: await ffprobeStreams(finalPath),
  });

  // What the reel actually ended up looking like, so the Telegram reply can say
  // it rather than repeating back what the director asked for.
  const look = {
    motions,
    transitions,
    caption_preset: captionStyle.preset,
    caption_animation: cues.some((c) => c.words?.length) || !['karaoke', 'word'].includes(captionStyle.animation)
      ? captionStyle.animation
      : 'pop',
    caption_words_measured: cues.some((c) => c.words?.length),
    finish: r.finish,
    branding: wantsBranding
      ? { applied: Boolean(logoPath), reason: logoPath ? null : 'wendor-logo.png was not found on the composer service — check the Docker image includes reels-composer/assets/' }
      : { applied: false, reason: 'disabled for this render' },
  };

  return { finalPath, duration, qc, timing, look };
}
