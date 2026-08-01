/**
 * The look engine — motion, cuts and captions.
 *
 * Everything here is a pure function over a plan, so it is checked without
 * touching ffmpeg. The one thing a unit test cannot prove is that a filter
 * string is *valid* ffmpeg, so the last section actually runs each motion
 * through ffmpeg against a two-second clip.
 *
 *   node reels-composer/test/looks.test.mjs
 */
import { spawn } from 'node:child_process';
import { promises as fs } from 'node:fs';
import { join } from 'node:path';
import { tmpdir } from 'node:os';

import {
  CAPTION_PRESET_NAMES,
  MOTION_NAMES,
  buildAss,
  finishFilters,
  motionFilter,
  motionSequence,
  normalizeCues,
  parseSrtCues,
  pickTransitions,
  resolveCaptionStyle,
  resolveMotion,
  scaleCues,
  wrapCue,
} from '../src/looks.js';
import { xfadeTransitions } from '../src/renderJob.js';

const failures = [];
const check = (label, ok, detail = '') => {
  console.log(`  ${ok ? 'pass' : 'FAIL'}  ${label}${detail ? `  (${detail})` : ''}`);
  if (!ok) failures.push(label);
};

function sh(cmd, args) {
  return new Promise((resolve, reject) => {
    const p = spawn(cmd, args, { stdio: ['ignore', 'pipe', 'pipe'] });
    let err = '';
    p.stderr.on('data', (d) => { err += d; });
    p.on('close', (code) => (code === 0 ? resolve() : reject(new Error(err.slice(-500)))));
  });
}

console.log('\nmotion');
{
  const still = motionFilter(resolveMotion('hold'), 4);
  check('a static shot is one crop and no resampling', /crop=1080:1920:\d+:\d+$/.test(still) && !still.includes('zoompan'), still.slice(-40));

  const pan = motionFilter(resolveMotion('pan_right'), 6);
  check('a pan at fixed zoom scales once and moves the crop', pan.startsWith('scale=1166:2074') && pan.includes("crop=1080:1920:x='"), pan.slice(0, 22));
  check('the pan finishes exactly at the end of the clip', pan.includes('min(1\\,t/6.000)'), pan.slice(pan.indexOf('crop=1080:1920')));

  const push = motionFilter(resolveMotion('push_in'), 5);
  // zoompan is the obvious filter here and is ~50% slower for the same result.
  check('a zoom move resizes per frame rather than reaching for zoompan', push.includes('eval=frame') && !push.includes('zoompan'));
  check('the zoom runs over the clip length', push.includes('min(1\\,t/5.000)'));
  check('the frame is squared to 9:16 before the zoom', push.startsWith('scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,'), push.slice(0, 30));
  check('and the final crop is the output frame', push.trimEnd().includes('crop=1080:1920:x='));

  // The director's per-clip zoom biases the preset rather than replacing it.
  const gentle = resolveMotion('push_in', 1);
  const harder = resolveMotion('push_in', 1.1);
  check('a per-clip zoom deepens the push instead of flattening it', harder.z1 > gentle.z1 && harder.z1 <= 1.2, `${gentle.z1} → ${harder.z1}`);
  check('an absurd zoom is clamped', resolveMotion('push_in', 9).z1 <= 1.2);
  check('an unknown motion name still produces a move', motionFilter(resolveMotion('nonsense'), 4).length > 0);

  const seq = motionSequence(5, 2);
  check('a default sequence covers every clip', seq.length === 5 && seq.every((m) => MOTION_NAMES.includes(m)), seq.join('/'));
  check('neighbouring clips do not repeat the same move', seq.every((m, i) => i === 0 || m !== seq[i - 1]), seq.join('/'));
  check('the seed changes the sequence', motionSequence(5, 0).join() !== motionSequence(5, 1).join());
}

console.log('\ntransitions');
{
  const available = new Set(['fade', 'dissolve', 'smoothleft']);
  const picked = pickTransitions(4, { available, seed: 0 });
  check('only transitions this ffmpeg has are used', picked.every((t) => available.has(t)), picked.join('/'));
  check('one type per cut', picked.length === 4);

  const requested = pickTransitions(4, {
    requested: [{ type: 'circleopen' }, { type: 'dissolve' }],
    available: new Set(['fade', 'dissolve', 'circleopen', 'smoothleft']),
  });
  check("the director's choices are honoured where they are valid", requested[0] === 'circleopen' && requested[1] === 'dissolve', requested.join('/'));

  const bogus = pickTransitions(2, { requested: [{ type: 'teleport' }], available: new Set(['fade']) });
  check('an invented transition name falls back rather than failing the render', bogus.every((t) => t === 'fade'), bogus.join('/'));
  check('no cuts means no transitions', pickTransitions(0, {}).length === 0);

  const varied = pickTransitions(4, { available: null, seed: 1 });
  check('the cuts are not all the same', new Set(varied).size > 1, varied.join('/'));
}

console.log('\ncaption styles');
{
  const style = resolveCaptionStyle({ preset: 'karaoke_gold' });
  check('a preset supplies a full style', style.animation === 'karaoke' && style.highlight_color === '#FFC53D');
  const overridden = resolveCaptionStyle({ preset: 'karaoke_gold', color: '#00FF00', size: 70 });
  check('the director can override one field of a preset', overridden.color === '#00FF00' && overridden.size === 70 && overridden.animation === 'karaoke');
  check('an unknown preset falls back to the plain one', resolveCaptionStyle({ preset: 'disco' }).preset === 'clean_bold');
  check('an unknown animation falls back to none', resolveCaptionStyle({ animation: 'explode' }).animation === 'none');
  check('a caption too big for the frame is clamped', resolveCaptionStyle({ size: 400 }).size <= 110);

  // Every preset now sits in the lower third by default — this is what
  // actually fixes captions reading as hovering mid-frame.
  const defaultMargin = resolveCaptionStyle({ preset: 'clean_bold' }).margin_v;
  check('the default position is the lower third, not the very edge and not the middle', defaultMargin === 420, defaultMargin);

  // "center"/"upper" only belong to word-punch, where one big word fills the
  // shot on purpose. A normal caption asked to float mid-frame — whether by a
  // bad preset choice or a bad override — is pulled back down, both by name
  // and by an explicit margin_v that tries to sneak past the name change.
  const wanderingCenter = resolveCaptionStyle({ preset: 'clean_bold', position: 'center' });
  check('a normal caption cannot be placed mid-frame by name', wanderingCenter.position === 'lower', wanderingCenter.position);
  // Not just capped — ignored outright. A ceiling still left a normal caption
  // able to read as "floating" instead of "in the lower third".
  const wanderingMargin = resolveCaptionStyle({ preset: 'clean_bold', margin_v: 900 });
  check('nor by an explicit margin_v at all — it is derived, not honoured', wanderingMargin.margin_v === 420, wanderingMargin.margin_v);
  const wordPunchCenter = resolveCaptionStyle({ preset: 'word_punch' });
  check('word-punch keeps its center placement — that one is deliberate', wordPunchCenter.position === 'center', wordPunchCenter.position);
}

console.log('\ncaption rendering');
const srt = '1\n00:00:01,000 --> 00:00:03,000\nprofits stall in month three\n\n2\n00:00:03,000 --> 00:00:05,500\nvending pays for itself\n';
const cues = [
  {
    start: 1, end: 3, text: 'profits stall in month three',
    words: [
      { start: 1.0, end: 1.4, text: 'profits' },
      { start: 1.4, end: 1.8, text: 'stall' },
      { start: 1.8, end: 2.0, text: 'in' },
      { start: 2.0, end: 2.5, text: 'month' },
      { start: 2.5, end: 3.0, text: 'three' },
    ],
  },
];
{
  const parsed = parseSrtCues(srt);
  check('an srt parses back into cues', parsed.length === 2 && Math.abs(parsed[0].end - 3) < 1e-9, JSON.stringify(parsed[0]?.text));
  check('cues take priority over the srt when both arrive', normalizeCues(cues, srt).length === 1);
  check('the srt is used when there are no measured cues', normalizeCues([], srt).length === 2);

  const scaled = scaleCues(cues, 1.1);
  check('scaling moves the words with the cue', Math.abs(scaled[0].words[0].end - 1.54) < 1e-9, String(scaled[0].words[0].end));
  check('a scale of 1 is a no-op', scaleCues(cues, 1) === cues);

  const plain = buildAss(normalizeCues([], srt), { preset: 'clean_bold' });
  check('a plain caption carries no override tags', !plain.includes('{\\'), plain.split('\n').find((l) => l.startsWith('Dialogue')));
  check('captions sit in the lower third, clear of the Reels furniture', plain.includes(',420,1'), plain.split('\n').find((l) => l.startsWith('Style:')));

  const pop = buildAss(normalizeCues([], srt), { preset: 'pop_punch' });
  check('a pop caption scales in and settles', pop.includes('\\fscx76') && pop.includes('\\t(130,210'));
  check('all-caps is applied to the text', pop.includes('PROFITS STALL'));

  const karaoke = buildAss(cues, { preset: 'karaoke_gold' });
  check('karaoke emits one fill per word', (karaoke.match(/\\kf\d+/g) || []).length === 5, String((karaoke.match(/\\kf\d+/g) || []).length));
  check('the fill lengths match the measured words', karaoke.includes('\\kf40}PROFITS'), karaoke.split('\n').find((l) => l.startsWith('Dialogue'))?.slice(-60));
  check('the highlight colour is what the sung word turns', karaoke.includes('&H003DC5FF'), karaoke.split('\n').find((l) => l.startsWith('Style:')));

  const karaokeNoWords = buildAss(normalizeCues([], srt), { preset: 'karaoke_gold' });
  check('karaoke without word timings degrades to a pop, not to nothing', karaokeNoWords.includes('\\fscx76') && !karaokeNoWords.includes('\\kf'));

  const word = buildAss(cues, { preset: 'word_punch' });
  const dialogues = word.split('\n').filter((l) => l.startsWith('Dialogue'));
  check('word-punch puts every word on its own beat', dialogues.length === 5, `${dialogues.length} events`);
  check('and centres them', word.includes(',5,60,60,'), word.split('\n').find((l) => l.startsWith('Style:'))?.slice(-24));
  check('the last word holds to the end of the cue', dialogues[4].includes('0:00:03.00'), dialogues[4]);

  const rise = buildAss(normalizeCues([], srt), { preset: 'rise_clean' });
  check('a rising caption moves up into place', rise.includes('\\move(540,1546,540,1500,0,200)'), rise.split('\n').find((l) => l.startsWith('Dialogue')));

  const boxed = buildAss(normalizeCues([], srt), { preset: 'boxed_news' });
  check('a boxed caption uses an opaque box border style', /Style: Default,[^\n]*,3,4,2,/.test(boxed));

  // Times past a minute are where a naive centisecond format breaks.
  const late = buildAss([{ start: 61.999, end: 63.5, text: 'late cue' }], {});
  check('cues past a minute carry into the minutes field', late.includes('0:01:02.00'), late.split('\n').find((l) => l.startsWith('Dialogue')));

  check('no cues produces a valid but empty file', buildAss([], {}).includes('[Events]'));
}

console.log('\nwrapping');
{
  const long = wrapCue('vending machines pay for themselves in under eleven months flat', 52);
  const lines = long.split('\\N');
  check('a long cue is wrapped rather than left to overflow', lines.length > 1, `${lines.length} lines`);
  check('the last line is not a single stranded word', lines[lines.length - 1].split(' ').length > 1, JSON.stringify(lines.at(-1)));

  const wrappedKaraoke = buildAss([{
    start: 0, end: 4,
    text: 'vending machines pay for themselves in under eleven months flat',
    words: 'vending machines pay for themselves in under eleven months flat'.split(' ')
      .map((text, i) => ({ text, start: i * 0.4, end: (i + 1) * 0.4 })),
  }], { preset: 'karaoke_mint' });
  check('a wrapped karaoke cue keeps every word', (wrappedKaraoke.match(/\\kf\d+/g) || []).length === 10);
  check('and breaks lines inside the event', wrappedKaraoke.includes('\\N'));
}

console.log('\nfinish');
{
  check('nothing is applied by default', finishFilters({}).length === 0);
  check('grain and vignette are separate filters', finishFilters({ grain: 4, vignette: 1 }).length === 2);
  check('grain is capped', finishFilters({ grain: 900 })[0].includes('alls=12'));
}

console.log('\nevery motion is valid ffmpeg');
{
  const dir = join(tmpdir(), `looks-${Date.now()}`);
  await fs.mkdir(dir, { recursive: true });
  try {
    // Burning captions needs libass, which a developer machine often lacks. The
    // *file* can still be checked: ffmpeg's ass demuxer is separate from the
    // libass-backed subtitles filter, so ffprobe reading a preset back as an
    // "ass" stream proves the header, style line and event syntax are well
    // formed even where the burn itself cannot be run.
    for (const preset of CAPTION_PRESET_NAMES) {
      const assPath = join(dir, `${preset}.ass`);
      await fs.writeFile(assPath, buildAss(cues, { preset }), 'utf8');
      let codec = '';
      try {
        codec = await new Promise((resolve, reject) => {
          const p = spawn('ffprobe', ['-v', 'error', '-show_entries', 'stream=codec_name', '-of', 'csv=p=0', assPath]);
          let o = '';
          p.stdout.on('data', (d) => { o += d; });
          p.on('close', (c) => (c === 0 ? resolve(o.trim()) : reject(new Error('probe failed'))));
        });
      } catch (err) {
        codec = String(err.message).slice(0, 60);
      }
      check(`${preset} produces a well-formed ASS file`, codec === 'ass', codec);
    }

    const src = join(dir, 'src.mp4');
    await sh('ffmpeg', ['-nostdin', '-v', 'error', '-y', '-f', 'lavfi',
      '-i', 'testsrc2=size=540x960:rate=30:duration=2',
      '-c:v', 'libx264', '-preset', 'ultrafast', '-pix_fmt', 'yuv420p', src]);

    for (const name of MOTION_NAMES) {
      const out = join(dir, `${name}.mp4`);
      const vf = `${motionFilter(resolveMotion(name), 2)},fps=30,setsar=1`;
      let ok = true;
      let detail = '';
      try {
        await sh('ffmpeg', ['-nostdin', '-v', 'error', '-y', '-i', src, '-an', '-vf', vf,
          '-c:v', 'libx264', '-preset', 'ultrafast', '-pix_fmt', 'yuv420p', out]);
        const { stdout } = await new Promise((resolve, reject) => {
          const p = spawn('ffprobe', ['-v', 'error', '-select_streams', 'v:0',
            '-show_entries', 'stream=width,height', '-of', 'csv=p=0', out]);
          let o = '';
          p.stdout.on('data', (d) => { o += d; });
          p.on('close', (c) => (c === 0 ? resolve({ stdout: o }) : reject(new Error('probe failed'))));
        });
        detail = stdout.trim();
        ok = detail === '1080,1920';
      } catch (err) {
        ok = false;
        detail = String(err.message).slice(0, 90);
      }
      check(`${name} renders a 1080x1920 frame`, ok, detail);
    }

    // The finish filters go into the same chain, so they have to survive it too.
    let finishOk = true;
    let finishDetail = '';
    try {
      const vf = [motionFilter(resolveMotion('push_in'), 2), 'fps=30', ...finishFilters({ vignette: 1, grain: 4, sharpen: 0.6 }), 'setsar=1'].join(',');
      await sh('ffmpeg', ['-nostdin', '-v', 'error', '-y', '-i', src, '-an', '-vf', vf,
        '-c:v', 'libx264', '-preset', 'ultrafast', '-pix_fmt', 'yuv420p', join(dir, 'finish.mp4')]);
    } catch (err) {
      finishOk = false;
      finishDetail = String(err.message).slice(0, 90);
    }
    check('vignette, grain and sharpen chain onto a move', finishOk, finishDetail);

    // And every transition the catalogue offers has to exist in this build or be
    // filtered out before it reaches a filtergraph.
    const available = await xfadeTransitions();
    const picked = pickTransitions(4, { available, seed: 3 });
    let xfadeOk = true;
    let xfadeDetail = picked.join('/');
    try {
      await sh('ffmpeg', ['-nostdin', '-v', 'error', '-y', '-i', src, '-i', src,
        '-filter_complex', `[0:v][1:v]xfade=transition=${picked[0]}:duration=0.3:offset=1.7[v]`,
        '-map', '[v]', '-an', '-c:v', 'libx264', '-preset', 'ultrafast', '-pix_fmt', 'yuv420p', join(dir, 'xfade.mp4')]);
    } catch (err) {
      xfadeOk = false;
      xfadeDetail = String(err.message).slice(0, 90);
    }
    check('the chosen cut is a transition this ffmpeg has', xfadeOk, xfadeDetail);
  } finally {
    await fs.rm(dir, { recursive: true, force: true });
  }
}

if (failures.length) {
  console.log(`\n${failures.length} failure(s)`);
  process.exit(1);
}
console.log('\nthe look holds together');
