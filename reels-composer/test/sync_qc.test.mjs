/**
 * The reel has to end on the voiceover's last word — no matter what the
 * generator predicted the voiceover's length would be.
 *
 * The workflow plans against a duration it worked out before this service ever
 * saw the file, and against the crossfade it assumed the director would pick.
 * Both can be wrong on arrival. This renders the cases that matter: a plan that
 * matches, a plan built for a voiceover 10% shorter than the one that turns up,
 * and a director who chose a longer crossfade than was budgeted for.
 *
 * The primary TTS path uploads a WAV the workflow built around raw PCM and the
 * fallbacks upload mp3, so both containers are rendered here.
 *
 *   node reels-composer/test/sync_qc.test.mjs
 *
 * Needs ffmpeg on PATH. No network — it renders from local files.
 */
import { spawn } from 'node:child_process';
import { promises as fs } from 'node:fs';
import { createServer } from 'node:http';
import { join } from 'node:path';
import { tmpdir } from 'node:os';

import {
  renderReel,
  qcReel,
  wrapCue,
  scaleSrt,
  rescalePerClip,
  voiceoverScale,
  ffmpegHasFilter,
} from '../src/renderJob.js';

// Burning captions needs an ffmpeg built with libass. Production has one; a
// developer machine often does not, and the timing assertions below are worth
// running either way — so drop the burn step rather than the whole test.
const CAN_BURN = await ffmpegHasFilter('subtitles');

const CLIPS = 5;
const FOOTAGE_SEC = 5;
const TRANSITION_SEC = 0.3;
const TAIL_SEC = 0.25;

const failures = [];
const check = (label, ok, detail = '') => {
  console.log(`  ${ok ? 'pass' : 'FAIL'}  ${label}${detail ? `  (${detail})` : ''}`);
  if (!ok) failures.push(label);
};

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

// Mirrors Build Sync Map: split the voiceover across the clips, then give each
// clip the crossfade overlap on top of its share (the last one gets the tail).
function planFor(voiceoverSec) {
  const share = voiceoverSec / CLIPS;
  return Array.from({ length: CLIPS }, (_, i) => ({
    index: i + 1,
    trim_start: 0,
    trim_end: Number((share + (i === CLIPS - 1 ? TAIL_SEC : TRANSITION_SEC)).toFixed(3)),
    speed: 1,
    zoom: 1,
  }));
}

function srtFor(voiceoverSec) {
  const share = voiceoverSec / CLIPS;
  const stamp = (t) => {
    const mm = String(Math.floor(t / 60)).padStart(2, '0');
    const ss = String(Math.floor(t % 60)).padStart(2, '0');
    const ms = String(Math.round((t - Math.floor(t)) * 1000)).padStart(3, '0');
    return `00:${mm}:${ss},${ms}`;
  };
  return Array.from({ length: CLIPS }, (_, i) =>
    `${i + 1}\n${stamp(i * share)} --> ${stamp((i + 1) * share)}\nline number ${i + 1} of the voiceover`
  ).join('\n\n');
}

if (!CAN_BURN) {
  console.log('\nnote: this ffmpeg has no libass, so the render cases run without burned captions');
}

console.log('\npure timing functions');

// voiceoverScale
{
  const near = voiceoverScale(12, 13.2);
  check('a 10% longer voiceover rescales the plan', near.applied && Math.abs(near.scale - 1.1) < 1e-6, `scale ${near.scale.toFixed(4)}`);
  const exact = voiceoverScale(12, 12.02);
  check('a duration within 1% is left alone', !exact.applied, exact.reason);
  const wild = voiceoverScale(12, 40);
  check('a wildly different file does not stretch the edit', !wild.applied && wild.scale === 1, wild.reason);
  const missing = voiceoverScale(0, 12);
  check('a missing planned duration falls back to the plan as-is', !missing.applied && missing.scale === 1);
}

// rescalePerClip — the invariant that matters: after rescaling, the concatenated
// video must come out at voiceover + tail.
{
  // What the concatenated video comes out at, given the crossfade actually used.
  const concatLength = (plan, transitionSec) =>
    plan.reduce((n, p) => n + p.trim_end - p.trim_start, 0) - transitionSec * (plan.length - 1);

  const planned = 12;
  const actual = 13.2;
  const scaled = rescalePerClip(planFor(planned), {
    scale: actual / planned, plannedTransitionSec: TRANSITION_SEC, transitionSec: TRANSITION_SEC, tailSec: TAIL_SEC,
  });
  check(
    'rescaled clips concatenate to the real voiceover plus the tail',
    Math.abs(concatLength(scaled, TRANSITION_SEC) - (actual + TAIL_SEC)) < 0.005,
    `${concatLength(scaled, TRANSITION_SEC).toFixed(3)}s vs ${(actual + TAIL_SEC).toFixed(3)}s`,
  );
  const overlapsIntact = scaled.every((p, i) => p.trim_end > (i === CLIPS - 1 ? TAIL_SEC : TRANSITION_SEC));
  check('the fixed crossfade overlap is not scaled with the speech', overlapsIntact);

  const untouched = rescalePerClip(planFor(12), { scale: 1, plannedTransitionSec: TRANSITION_SEC, tailSec: TAIL_SEC });
  check('a scale of 1 returns the plan unchanged', untouched[0].trim_end === planFor(12)[0].trim_end);

  const openEnded = rescalePerClip([{ index: 1, trim_start: 0, trim_end: null }], { scale: 1.2 });
  check('an open-ended clip stays open-ended', openEnded[0].trim_end === null);

  // The render director is allowed to pick a 250-400ms crossfade. A longer one
  // eats more of every clip than the plan budgeted for, so without a correction
  // the reel finishes before the voiceover does.
  {
    const LONG_TRANSITION = 0.4;
    const uncorrected = concatLength(planFor(12), LONG_TRANSITION);
    check(
      'a longer crossfade than planned would otherwise cut the reel short',
      uncorrected < 12,
      `${uncorrected.toFixed(3)}s against a 12s voiceover`,
    );
    const corrected = rescalePerClip(planFor(12), {
      scale: 1, plannedTransitionSec: TRANSITION_SEC, transitionSec: LONG_TRANSITION, tailSec: TAIL_SEC,
    });
    check(
      'swapping the overlap puts it back on the voiceover',
      Math.abs(concatLength(corrected, LONG_TRANSITION) - (12 + TAIL_SEC)) < 0.005,
      `${concatLength(corrected, LONG_TRANSITION).toFixed(3)}s vs ${(12 + TAIL_SEC).toFixed(3)}s`,
    );
    const both = rescalePerClip(planFor(12), {
      scale: 13.2 / 12, plannedTransitionSec: TRANSITION_SEC, transitionSec: 0.25, tailSec: TAIL_SEC,
    });
    check(
      'a rescale and a shorter crossfade correct together',
      Math.abs(concatLength(both, 0.25) - (13.2 + TAIL_SEC)) < 0.005,
      `${concatLength(both, 0.25).toFixed(3)}s vs ${(13.2 + TAIL_SEC).toFixed(3)}s`,
    );
  }
}

// scaleSrt
{
  const scaled = scaleSrt('1\n00:00:10,000 --> 00:00:20,000\nhello\n', 1.1);
  check('subtitle cues scale with the plan', scaled.includes('00:00:11,000 --> 00:00:22,000'), scaled.split('\n')[1]);
  const past60 = scaleSrt('1\n00:00:50,000 --> 00:00:55,000\nhello\n', 1.2);
  check('cues past a minute carry correctly', past60.includes('00:01:00,000 --> 00:01:06,000'), past60.split('\n')[1]);
  check('a scale of 1 leaves the srt untouched', scaleSrt('1\n00:00:10,000 --> 00:00:20,000\nx', 1).includes('00:00:10,000'));
}

// wrapCue
{
  const long = wrapCue('vending machines pay for themselves in under eleven months flat', 52);
  const lines = long.split('\\N');
  check('a long cue is wrapped rather than left to overflow', lines.length > 1, `${lines.length} lines`);
  check('no wrapped line exceeds the frame width', lines.every((l) => l.length <= 34), lines.map((l) => l.length).join('/'));
  const stranded = lines[lines.length - 1].split(' ').length > 1;
  check('the last line is not a single stranded word', stranded, JSON.stringify(lines[lines.length - 1]));
  check('a short cue stays on one line', !wrapCue('profits stall', 52).includes('\\N'));
  check('an empty cue produces nothing', wrapCue('   ', 52) === '');
}

// qcReel
{
  const good = { videoStreams: 1, audioStreams: 1, width: 1080, height: 1920 };
  check('a clean reel passes', qcReel({ duration: 12.1, voiceoverSec: 12, streams: good }).ok);

  const short = qcReel({ duration: 10.5, voiceoverSec: 12, streams: good });
  check('a reel that ends before the voiceover fails', !short.ok && /closing words are cut off/.test(short.problems[0]), short.problems[0]);

  const long = qcReel({ duration: 14, voiceoverSec: 12, streams: good });
  check('a reel that ends on silence fails', !long.ok && /ends on silence/.test(long.problems[0]), long.problems[0]);

  const twoTracks = qcReel({ duration: 12, voiceoverSec: 12, streams: { ...good, audioStreams: 2 } });
  check('surviving clip audio fails', !twoTracks.ok && /1 audio track/.test(twoTracks.problems[0]), twoTracks.problems[0]);

  const square = qcReel({ duration: 12, voiceoverSec: 12, streams: { ...good, width: 1080, height: 1080 } });
  check('a non-vertical frame fails', !square.ok && /1080x1920/.test(square.problems[0]), square.problems[0]);

  const empty = qcReel({ duration: 0, voiceoverSec: 12, streams: good });
  check('an empty render fails', !empty.ok && /no duration/.test(empty.problems[0]));
}

const dir = join(tmpdir(), `sync-qc-${Date.now()}`);
await fs.mkdir(dir, { recursive: true });

try {
  for (let i = 1; i <= CLIPS; i++) {
    await sh('ffmpeg', [
      '-nostdin', '-v', 'error', '-y',
      '-f', 'lavfi', '-i', `color=c=blue:size=360x640:rate=30:duration=${FOOTAGE_SEC}`,
      '-c:v', 'libx264', '-preset', 'ultrafast', '-pix_fmt', 'yuv420p',
      join(dir, `clip${i}.mp4`),
    ]);
  }

  const server = createServer(async (req, res) => {
    try {
      res.end(await fs.readFile(join(dir, req.url.replace(/^\//, '').split('?')[0])));
    } catch {
      res.statusCode = 404;
      res.end();
    }
  });
  await new Promise((r) => server.listen(0, '127.0.0.1', r));
  const base = `http://127.0.0.1:${server.address().port}`;

  const clipUrls = Array.from({ length: CLIPS }, (_, i) => ({ index: i + 1, url: `${base}/clip${i + 1}.mp4` }));

  async function render(label, {
    audioSec, plannedSec, workName, renderTransitionSec = TRANSITION_SEC, format = 'mp3',
  }) {
    // The primary TTS path uploads a WAV the workflow built itself around raw
    // PCM; the fallbacks upload mp3. Both have to render identically.
    const codec = format === 'wav' ? ['-c:a', 'pcm_s16le'] : ['-c:a', 'libmp3lame', '-b:a', '128k'];
    await sh('ffmpeg', ['-nostdin', '-v', 'error', '-y', '-f', 'lavfi',
      '-i', 'sine=frequency=440', '-t', String(audioSec), '-ac', '1', '-ar', '44100',
      ...codec, join(dir, `${workName}.${format}`)]);
    const workDir = join(dir, workName);
    await fs.mkdir(workDir, { recursive: true });
    return renderReel({
      workDir,
      clipUrls,
      voiceoverUrl: `${base}/${workName}.${format}`,
      voiceoverSec: plannedSec,
      transitionSec: TRANSITION_SEC,
      tailSec: TAIL_SEC,
      subtitlesSrt: srtFor(plannedSec),
      recipe: {
        clip_order: [1, 2, 3, 4, 5],
        per_clip: planFor(plannedSec),
        transitions: [{ after_clip: 1, type: 'xfade', duration_ms: Math.round(renderTransitionSec * 1000) }],
        audio: { voiceover_gain_db: 0, fade_in_ms: 200, fade_out_ms: 400 },
        subtitles: CAN_BURN
          ? { mode: 'burn', font: 'Arial', size: 52, color: '#FFFFFF', outline_color: '#000000' }
          : { mode: 'none' },
        color: { saturation: 1, contrast: 1, brightness: 0 },
      },
    });
  }

  console.log('\nrender: the plan matches the voiceover (wav from the primary TTS path)');
  {
    const { qc, timing } = await render('honest', { audioSec: 12, plannedSec: 12, workName: 'honest', format: 'wav' });
    check('no rescale was needed', !timing.applied, timing.reason);
    check('the reel passes QC', qc.ok, JSON.stringify(qc.problems));
    check('it lands on the voiceover', Math.abs(qc.drift_sec) < 0.4, `drift ${qc.drift_sec}s`);
    check('it is 1080x1920 with one audio track', qc.problems.length === 0);
  }

  console.log('\nrender: the manifest under-estimated the voiceover by 10%');
  {
    const { qc, timing } = await render('lying', { audioSec: 13.2, plannedSec: 12, workName: 'lying' });
    check('the probe caught the discrepancy', timing.applied, timing.reason);
    check('the reel still passes QC', qc.ok, JSON.stringify(qc.problems));
    check('it lands on the real voiceover, not the predicted one', Math.abs(qc.drift_sec) < 0.4, `drift ${qc.drift_sec}s`);
    check(
      'the reel is as long as the audio that actually arrived',
      Math.abs(qc.duration_sec - 13.2) < 0.4,
      `${qc.duration_sec}s vs 13.2s`,
    );
  }

  console.log('\nrender: the director picked a longer crossfade than the plan assumed');
  {
    const { qc } = await render('slowfade', {
      audioSec: 12, plannedSec: 12, workName: 'slowfade', renderTransitionSec: 0.4,
    });
    check('the reel passes QC anyway', qc.ok, JSON.stringify(qc.problems));
    check('it still ends on the voiceover', Math.abs(qc.drift_sec) < 0.4, `drift ${qc.drift_sec}s`);
  }

  console.log('\nrender: word-level captions, a move on every clip and a different cut at each');
  {
    // The look engine is unit-tested on its own; this is the one that proves
    // libass accepts the karaoke tags, that a per-frame zoom survives a real
    // encode, and that none of it moves the reel off the voiceover.
    const share = 12 / CLIPS;
    const captionCues = Array.from({ length: CLIPS }, (_, i) => {
      const start = i * share;
      const words = ['line', `number`, `${i + 1}`, 'of', 'the', 'voiceover'];
      const step = share / words.length;
      return {
        start,
        end: start + share,
        text: words.join(' '),
        words: words.map((text, w) => ({ text, start: start + w * step, end: start + (w + 1) * step })),
      };
    });

    const workDir = join(dir, 'animated');
    await fs.mkdir(workDir, { recursive: true });
    const { qc, look } = await renderReel({
      workDir,
      clipUrls,
      voiceoverUrl: `${base}/honest.wav`,
      voiceoverSec: 12,
      transitionSec: TRANSITION_SEC,
      tailSec: TAIL_SEC,
      captionCues,
      recipe: {
        clip_order: [1, 2, 3, 4, 5],
        per_clip: planFor(12),
        transitions: [
          { type: 'smoothleft', duration_ms: 300 },
          { type: 'circleopen', duration_ms: 300 },
          { type: 'dissolve', duration_ms: 300 },
          { type: 'slideup', duration_ms: 300 },
        ],
        motion: ['push_in', 'pan_right', 'pull_out', 'tilt_up', 'rise'],
        finish: { vignette: 0.5, grain: 3 },
        subtitles: CAN_BURN ? { mode: 'burn', preset: 'karaoke_gold' } : { mode: 'none' },
        color: { saturation: 1, contrast: 1, brightness: 0 },
      },
    });

    check('every clip got its own move', look.motions.join('/') === 'push_in/pan_right/pull_out/tilt_up/rise', look.motions.join('/'));
    check('no two neighbouring cuts are the same', new Set(look.transitions).size === 4, look.transitions.join('/'));
    if (CAN_BURN) {
      check('the captions animate off the measured words', look.caption_words_measured && look.caption_animation === 'karaoke', look.caption_animation);
    }
    check('the reel still passes QC with all of it applied', qc.ok, JSON.stringify(qc.problems));
    // The whole point of keeping motion out of the timing code.
    check('a move on every clip does not shift the reel off the voiceover', Math.abs(qc.drift_sec) < 0.4, `drift ${qc.drift_sec}s`);
  }

  console.log('\nrender: an ffmpeg that cannot burn captions says so up front');
  {
    const workDir = join(dir, 'nolibass');
    await fs.mkdir(workDir, { recursive: true });
    let message = '';
    try {
      await renderReel({
        workDir, clipUrls, voiceoverUrl: `${base}/honest.wav`, voiceoverSec: 12,
        subtitlesSrt: srtFor(12),
        recipe: { per_clip: planFor(12), subtitles: { mode: 'burn' } },
      });
    } catch (err) {
      message = err.message;
    }
    if (CAN_BURN) {
      check('libass is present, so the burn is attempted', message === '', message.slice(0, 80));
    } else {
      check('the missing filter is named before any encoding starts', /built without libass/.test(message), message.slice(0, 90));
    }
  }

  console.log('\nrender: a dead voiceover link fails fast');
  {
    const workDir = join(dir, 'dead');
    await fs.mkdir(workDir, { recursive: true });
    const started = Date.now();
    let message = '';
    try {
      await renderReel({
        workDir, clipUrls, voiceoverUrl: `${base}/nope.mp3`, voiceoverSec: 12,
        subtitlesSrt: '', recipe: { per_clip: planFor(12) },
      });
    } catch (err) {
      message = err.message;
    }
    const elapsed = Date.now() - started;
    check('it throws rather than rendering silently', /Download failed 404/.test(message), message.slice(0, 80));
    check('and it does so before encoding any clips', elapsed < 20000, `${(elapsed / 1000).toFixed(1)}s`);
  }

  server.close();
} finally {
  await fs.rm(dir, { recursive: true, force: true });
}

if (failures.length) {
  console.log(`\n${failures.length} failure(s)`);
  process.exit(1);
}
console.log('\nthe reel ends on the voiceover, whatever the manifest predicted');
