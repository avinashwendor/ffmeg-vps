/**
 * The reel must carry the TTS voiceover and nothing else.
 *
 * Gemini Omni generates speech and sound effects with every clip. If any of it
 * survives into the render it fights the voiceover, so this builds clips with a
 * loud tone baked in and asserts the audio is gone by the first pass.
 *
 *   node reels-composer/test/audio_isolation.test.mjs
 *
 * Needs ffmpeg on PATH. No network — it renders from local files.
 */
import { spawn } from 'node:child_process';
import { promises as fs } from 'node:fs';
import { createServer } from 'node:http';
import { join } from 'node:path';
import { tmpdir } from 'node:os';

import { renderReel } from '../src/renderJob.js';

const CLIPS = 3;
const CLIP_SEC = 10;

function sh(cmd, args) {
  return new Promise((resolve, reject) => {
    const p = spawn(cmd, args, { stdio: ['ignore', 'pipe', 'pipe'] });
    let out = '';
    let err = '';
    p.stdout.on('data', (d) => { out += d; });
    p.stderr.on('data', (d) => { err += d; });
    p.on('close', (code) => (code === 0 ? resolve({ out, err }) : reject(new Error(err.slice(-600)))));
  });
}

async function audioStreams(file) {
  const { out } = await sh('ffprobe', [
    '-v', 'error', '-select_streams', 'a',
    '-show_entries', 'stream=codec_name', '-of', 'csv=p=0', file,
  ]);
  return out.trim() ? out.trim().split('\n') : [];
}

const dir = join(tmpdir(), `audio-isolation-${Date.now()}`);
await fs.mkdir(dir, { recursive: true });
const failures = [];
const check = (label, ok) => {
  console.log(`  ${ok ? 'pass' : 'FAIL'}  ${label}`);
  if (!ok) failures.push(label);
};

try {
  // Clips with a loud 1 kHz tone standing in for Omni's generated dialogue.
  for (let i = 1; i <= CLIPS; i++) {
    await sh('ffmpeg', [
      '-nostdin', '-v', 'error', '-y',
      '-f', 'lavfi', '-i', `color=c=blue:size=360x640:rate=30`,
      '-f', 'lavfi', '-i', 'sine=frequency=1000:sample_rate=44100',
      '-t', String(CLIP_SEC), '-c:v', 'libx264', '-preset', 'ultrafast',
      '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-shortest', join(dir, `clip${i}.mp4`),
    ]);
  }
  await sh('ffmpeg', ['-nostdin', '-v', 'error', '-y', '-f', 'lavfi',
    '-i', 'sine=frequency=440', '-t', '25', '-c:a', 'libmp3lame', '-b:a', '128k', join(dir, 'voice.mp3')]);

  check('the source clips really do carry audio', (await audioStreams(join(dir, 'clip1.mp4'))).length === 1);

  // renderReel fetches over http, so serve the fixtures locally.
  const server = createServer(async (req, res) => {
    try {
      res.end(await fs.readFile(join(dir, req.url.replace(/^\//, ''))));
    } catch {
      res.statusCode = 404;
      res.end();
    }
  });
  await new Promise((r) => server.listen(0, '127.0.0.1', r));
  const base = `http://127.0.0.1:${server.address().port}`;

  const workDir = join(dir, 'work');
  await fs.mkdir(workDir, { recursive: true });

  const { finalPath } = await renderReel({
    workDir,
    clipUrls: Array.from({ length: CLIPS }, (_, i) => ({ index: i + 1, url: `${base}/clip${i + 1}.mp4` })),
    voiceoverUrl: `${base}/voice.mp3`,
    subtitlesSrt: '',
    recipe: {
      clip_order: Array.from({ length: CLIPS }, (_, i) => i + 1),
      per_clip: Array.from({ length: CLIPS }, (_, i) => ({ index: i + 1, trim_start: 0, trim_end: 8, speed: 1, zoom: 1 })),
      transitions: [{ after_clip: 1, type: 'xfade', duration_ms: 300 }],
      audio: { voiceover_gain_db: 0, fade_in_ms: 200, fade_out_ms: 400 },
      subtitles: { mode: 'none' },
      color: { saturation: 1, contrast: 1, brightness: 0 },
    },
  });
  server.close();

  check('clip audio is gone after the first pass', (await audioStreams(join(workDir, 'clip-1-norm.mp4'))).length === 0);
  check('and never reaches the concatenated video', (await audioStreams(join(workDir, 'concat.mp4'))).length === 0);
  check('the finished reel has exactly one audio track', (await audioStreams(finalPath)).length === 1);

  // The surviving track has to be the voiceover: 440 Hz present, 1 kHz absent.
  async function tone(freq) {
    const { err } = await sh('ffmpeg', ['-hide_banner', '-nostats', '-i', finalPath,
      '-af', `bandpass=f=${freq}:width_type=h:w=40,volumedetect`, '-f', 'null', '-']).catch((e) => ({ err: String(e) }));
    const m = err.match(/mean_volume:\s*(-?\d+(?:\.\d+)?) dB/);
    return m ? Number(m[1]) : null;
  }
  const voice = await tone(440);
  const clip = await tone(1000);
  console.log(`        voiceover 440Hz ${voice}dB vs clip 1kHz ${clip}dB`);
  check('the voiceover is the audible track', voice !== null && clip !== null && voice - clip > 25);
} finally {
  await fs.rm(dir, { recursive: true, force: true });
}

if (failures.length) {
  console.log(`\n${failures.length} failure(s)`);
  process.exit(1);
}
console.log('\nonly the voiceover survives the render');
