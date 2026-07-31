#!/usr/bin/env python3
"""Run the reels Code nodes for real against stubbed S3 / OpenRouter / composer.

validate_workflow.py only proves the JavaScript parses. That is not enough: a
node can parse cleanly and still blow up on a missing helper the moment it
runs, which is exactly what happened when the compose-session helpers were
split out of the shared S3 bundle. This executes the nodes.

    python3 build/test_reels_nodes.py
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

BUILD_DIR = Path(__file__).resolve().parent
if str(BUILD_DIR) not in sys.path:
    sys.path.insert(0, str(BUILD_DIR))

from paths import MAIN_WORKFLOW_JSON
from reel_timing import CLIP_COUNT, CLIP_SEC, TOTAL_SEC, WORDS_PER_CLIP

# A fake bucket and fake upstreams behind the same this.helpers.httpRequest
# surface the Code nodes use, so the nodes run unmodified.
HARNESS = r"""
const BUCKET = new Map();
let COMPOSER_PAYLOAD = null;
let COMPOSER_JOB = null;
const failures = [];
const key = (url) => decodeURIComponent(new URL(url).pathname.replace(/^\//, ''));

const helpers = { httpRequest: async (o) => {
  if (o.url.includes('openrouter.ai')) { OPENROUTER_REQUEST = o.body; return { choices: [{ message: { content: OPENROUTER_REPLY } }] }; }
  if (o.url.includes('/v1/render')) { COMPOSER_PAYLOAD = o.body; return { job_id: 'job-1', status: 'queued' }; }
  if (o.url.includes('/v1/jobs/')) return COMPOSER_JOB;
  const k = key(o.url);
  if (o.method === 'PUT') { BUCKET.set(k, Buffer.isBuffer(o.body) ? o.body.toString('utf8') : String(o.body)); return ''; }
  if (o.url.includes('list-type=2')) {
    const prefix = new URL(o.url).searchParams.get('prefix') || '';
    const keys = [...BUCKET.keys()].filter((x) => x.startsWith(prefix));
    return `<R>${keys.map((x) => `<Key>${x}</Key>`).join('')}</R>`;
  }
  if (!BUCKET.has(k)) { const e = new Error('NoSuchKey'); e.statusCode = 404; throw e; }
  return BUCKET.get(k);
}};

let OPENROUTER_REPLY = '{}';
let OPENROUTER_REQUEST = null;
let INPUT = null;
const $input = { first: () => INPUT };

// Nodes that read an earlier step by name, e.g. $('Prepare Voiceover').
let NODE_CONTEXT = {};
const $ = (name) => ({ first: () => NODE_CONTEXT[name] || { json: {} } });

async function runNode(name, item) {
  INPUT = item;
  const $json = item.json || {};
  const body = NODES[name];
  if (body == null) throw new Error(`no such node: ${name}`);
  const fn = new Function('$input', '$json', 'helpers', '$',
    '"use strict"; return (async function(){ ' + body + '\n}).call({ helpers });');
  return await fn($input, $json, helpers, $);
}

function check(label, actual, expected) {
  const ok = JSON.stringify(actual) === JSON.stringify(expected);
  if (!ok) failures.push(`${label}\n      expected ${JSON.stringify(expected)}\n      got      ${JSON.stringify(actual)}`);
  console.log(`  ${ok ? 'pass' : 'FAIL'}  ${label}`);
}

const mp3Bytes = (sec) => Math.round((sec * 128000) / 8);
// An exactly-on-budget scene for whatever grid reel_timing.py currently sets,
// so these assertions stay meaningful if CLIP_SEC changes.
const WORDS = Array.from({ length: WORDS_PER_CLIP }, (_, i) => `w${i + 1}`).join(' ');
const ON_BUDGET_SEC = Number((WORDS_PER_CLIP * CLIP_COUNT / 2.6).toFixed(2));

async function main() {
  // ---- the generate pipeline: script -> timing -> sync map ----------------
  console.log('\nscript timing and sync');
  const scenes = Array.from({ length: CLIP_COUNT }, (_, i) => ({
    narrative_beat: ['HOOK', 'SETUP', 'PROOF', 'EMOTION', 'CTA'][i],
    voiceover_segment: (i === 0 ? '[cut to machine] ' : '') + WORDS,
    visual_brief: 'brief', on_screen_text: '', what_happened_before: 'b',
    what_happens_next: 'n', end_frame_state: 'e', transition_out: 'cut',
  }));
  let ctx = (await runNode('Normalize Script Timing', { json: {
    run_id: 'R1', topic_slug: 't', chat_id: '9',
    selected_topic: { title: 'T' },
    script: { scenes, production_bible: {}, elevenlabs_voice_name: 'Rachel' },
  }}))[0].json;

  check('stage directions are stripped before TTS', ctx.script.scenes[0].voiceover_segment.includes('['), false);
  check('voiceover text is exactly the scene segments joined',
    ctx.script.full_script === ctx.script.scenes.map((s) => s.voiceover_segment).join(' '), true);
  check('word budget counted per scene', ctx.script.scenes.map((s) => s.word_count), Array(CLIP_COUNT).fill(WORDS_PER_CLIP));

  ctx = (await runNode('Build Sync Map', { json: { ...ctx,
    voiceover_bytes: mp3Bytes(ON_BUDGET_SEC),
    voiceover_url: 'https://b/vo.mp3',
    matched_scenes: Array.from({ length: CLIP_COUNT }, (_, i) => ({ scene_index: i, reference_image_name: `part${i + 1} shot`, reference_image_url: `https://b/i${i}` })),
  }}))[0].json;

  check('voiceover length read from the mp3', ctx.voiceover_sec, ON_BUDGET_SEC);
  check('clip windows are contiguous',
    ctx.sync_windows.every((w, i, a) => i === 0 || w.vo_start === a[i - 1].vo_end), true);
  check('last window ends on the last word', ctx.sync_windows[CLIP_COUNT - 1].vo_end, ctx.voiceover_sec);
  check('picture outlasts the voiceover so -shortest cannot clip it', ctx.render_drift_sec > 0, true);
  check('an on-budget script needs no speed change', ctx.sync_windows.map((w) => w.render.speed), Array(CLIP_COUNT).fill(1));
  check('subtitles were generated from that same timeline', ctx.subtitles_srt.split('\n\n').length > 5, true);
  check('no sync warnings on an on-budget script', ctx.sync_warnings, []);

  // An over-long scene must be reported, not silently mangled.
  const longScenes = scenes.map((s, i) => (i === 2 ? { ...s, voiceover_segment: WORDS + ' ' + WORDS } : s));
  let over = (await runNode('Normalize Script Timing', { json: { run_id: 'R2', script: { scenes: longScenes, production_bible: {} } } }))[0].json;
  over = (await runNode('Build Sync Map', { json: { ...over, voiceover_bytes: mp3Bytes(ON_BUDGET_SEC * 1.2), matched_scenes: [] } }))[0].json;
  check('an over-long scene is reported', over.sync_warnings.some((w) => w.includes('runs long')), true);
  check('and so is the resulting short video', over.sync_warnings.some((w) => w.includes('before the voiceover')), true);

  // ---- the split follows speech length, not word count --------------------
  console.log('\nspeech-weighted timing');
  // Same word count in every scene, but scene 3 is all long words. Splitting by
  // word count would hand all five scenes an identical window; splitting by how
  // long they take to say must give scene 3 more room.
  const SHORT = Array.from({ length: WORDS_PER_CLIP }, () => 'go').join(' ');
  const LONG = Array.from({ length: WORDS_PER_CLIP }, () => 'extraordinary').join(' ');
  const mixed = Array.from({ length: CLIP_COUNT }, (_, i) => ({
    narrative_beat: ['HOOK', 'SETUP', 'PROOF', 'EMOTION', 'CTA'][i],
    voiceover_segment: i === 2 ? LONG : SHORT,
    visual_brief: 'b', on_screen_text: '',
  }));
  let uneven = (await runNode('Normalize Script Timing', { json: { run_id: 'R3', script: { scenes: mixed, production_bible: {} } } }))[0].json;
  check('every scene still has the same word count',
    uneven.script.scenes.every((s) => s.word_count === WORDS_PER_CLIP), true);
  check('but the long-word scene carries more speech',
    uneven.script.scenes[2].speech_units > uneven.script.scenes[0].speech_units * 2, true);

  uneven = (await runNode('Build Sync Map', { json: { ...uneven, voiceover_bytes: mp3Bytes(ON_BUDGET_SEC), matched_scenes: [] } }))[0].json;
  const longWindow = uneven.sync_windows[2].vo_seconds;
  const shortWindow = uneven.sync_windows[0].vo_seconds;
  check('so it is given a longer window than the short-word scenes', longWindow > shortWindow * 2, true);
  check('the windows still cover the whole voiceover exactly',
    uneven.sync_windows[CLIP_COUNT - 1].vo_end, uneven.voiceover_sec);

  // A caption wider than the frame is unreadable on the device it is made for.
  const cueLines = ctx.subtitles_srt.split('\n\n')
    .map((b) => b.split('\n').slice(2).join(' '))
    .filter(Boolean);
  check('no subtitle cue is wider than the frame allows',
    cueLines.every((l) => l.length <= 42), true);
  check('cues cover every spoken word',
    cueLines.join(' ').split(/\s+/).length,
    ctx.script.full_script.split(/\s+/).length);

  // ---- TTS: audio and word timestamps -------------------------------------
  console.log('\ncartesia sse');
  const VO_RATE = 44100;
  NODE_CONTEXT['Prepare Voiceover'] = { json: { run_id: 'R1', topic_slug: 't', _voiceover_text: 'x' } };

  // /tts/sse speaks raw PCM, and it dribbles the timestamps out a few words at
  // a time — so the fixture splits both across several events on purpose.
  const pcmChunk = Buffer.alloc(VO_RATE * 2 / 4, 7);   // quarter of a second
  const sseEvents = [
    { type: 'chunk', data: pcmChunk.toString('base64'), done: false, status_code: 206 },
    { type: 'timestamps', word_timestamps: { words: ['Vending', 'machines'], start: [0.11, 0.44], end: [0.44, 0.9] }, done: false, status_code: 206 },
    { type: 'chunk', data: pcmChunk.toString('base64'), done: false, status_code: 206 },
    { type: 'timestamps', word_timestamps: { words: ['pay'], start: [0.9], end: [1.2] }, done: false, status_code: 206 },
    { type: 'chunk', data: pcmChunk.toString('base64'), done: false, status_code: 206 },
    { type: 'chunk', data: pcmChunk.toString('base64'), done: false, status_code: 206 },
    { type: 'done', done: true, status_code: 200 },
  ];
  const sseBody = sseEvents.map((e) => `data: ${JSON.stringify(e)}\n`).join('\n') + '\n';

  const sse = (await runNode('Parse Cartesia SSE', { json: { data: sseBody } }))[0];
  check('the stream is accepted', sse.json.tts_ok, true);
  const wav = Buffer.from(sse.binary.voiceover.data, 'base64');
  check('the PCM is wrapped in a WAV container', [wav.slice(0, 4).toString(), wav.slice(8, 12).toString()], ['RIFF', 'WAVE']);
  check('with the sample rate it was requested at', wav.readUInt32LE(24), VO_RATE);
  check('mono 16-bit', [wav.readUInt16LE(22), wav.readUInt16LE(34)], [1, 16]);
  check('the declared data length matches the audio', wav.readUInt32LE(40), pcmChunk.length * 4);
  check('the header is not counted as audio', wav.length, pcmChunk.length * 4 + 44);
  check('duration is measured from the samples', sse.json.voiceover_measured_sec, 1);
  check('timestamps are gathered from every event, not just the first',
    sse.json.word_timings.map((t) => t.word), ['Vending', 'machines', 'pay']);
  check('and it is uploaded as a wav', [sse.json.voiceover_ext, sse.json.tts_provider], ['wav', 'cartesia']);

  // A stream that stops early would produce a voiceover missing its last words.
  const truncated = (await runNode('Parse Cartesia SSE', { json: { data: sseBody.replace(/data: \{"type":"done".*\n/, '') } }))[0];
  check('a stream with no done event is rejected', truncated.json.tts_ok, false);
  check('and says why', truncated.json.tts_error.includes('truncated'), true);

  const errored = (await runNode('Parse Cartesia SSE', { json: { data: 'data: {"type":"error","error":"voice not found"}\n' } }))[0];
  check('an error event is rejected', errored.json.tts_ok, false);
  check('carrying the API message', errored.json.tts_error.includes('voice not found'), true);

  const empty = (await runNode('Parse Cartesia SSE', { json: { data: '' } }))[0];
  check('an empty body is rejected rather than shipped as silence', empty.json.tts_ok, false);

  console.log('\nelevenlabs timestamps');
  // ElevenLabs times characters, not words, so the words have to be rebuilt.
  const phrase = 'Go now';
  const chars = phrase.split('');
  const el = (await runNode('Parse ElevenLabs TTS', { json: {
    audio_base64: Buffer.from('fake-mp3').toString('base64'),
    alignment: {
      characters: chars,
      character_start_times_seconds: chars.map((_, i) => i * 0.1),
      character_end_times_seconds: chars.map((_, i) => (i + 1) * 0.1),
    },
  } }))[0];
  check('words are rebuilt from the character spans', el.json.word_timings.map((t) => t.word), ['Go', 'now']);
  check('a word spans its first and last character',
    [Number(el.json.word_timings[0].start.toFixed(2)), Number(el.json.word_timings[0].end.toFixed(2))], [0, 0.2]);
  check('the second word starts after the space',
    Number(el.json.word_timings[1].start.toFixed(2)), 0.3);
  check('the audio comes through as binary', el.binary.voiceover.mimeType, 'audio/mpeg');
  check('labelled as the fallback provider', el.json.tts_provider, 'elevenlabs');

  // ---- captions cut to measured words -------------------------------------
  console.log('\ncaptions on measured words');
  // Words at a deliberately uneven pace: the estimate would spread them evenly,
  // measured timings must not.
  const timedScenes = Array.from({ length: CLIP_COUNT }, (_, i) => ({
    narrative_beat: ['HOOK', 'SETUP', 'PROOF', 'EMOTION', 'CTA'][i],
    voiceover_segment: Array.from({ length: 8 }, (_, k) => `s${i}w${k}`).join(' '),
    visual_brief: 'b', on_screen_text: '',
  }));
  let timedCtx = (await runNode('Normalize Script Timing', { json: { run_id: 'R4', script: { scenes: timedScenes, production_bible: {} } } }))[0].json;

  const allWords = timedCtx.script.full_script.split(/\s+/);
  // Scene 2 is spoken slowly, everything else quickly.
  let t = 0;
  const timings = allWords.map((w) => {
    const slow = w.startsWith('s2');
    const dur = slow ? 1.0 : 0.25;
    const item = { word: w, start: Number(t.toFixed(3)), end: Number((t + dur * 0.8).toFixed(3)) };
    t += dur;
    return item;
  });
  const totalSpoken = Number(t.toFixed(3));

  const timed = (await runNode('Build Sync Map', { json: { ...timedCtx,
    word_timings: timings, voiceover_measured_sec: totalSpoken,
    word_timing_source: 'cartesia word timestamps', matched_scenes: [] } }))[0].json;

  check('the timings lined up with the script', timed.word_timings_aligned, true);
  check('and captions say so', timed.caption_timing_source, 'cartesia word timestamps');
  const round2 = (n) => Number(Number(n).toFixed(2));
  check('each clip starts exactly where its first word is spoken',
    timed.sync_windows.map((w) => w.vo_start),
    // Eight words per scene, and clip 1 starts at zero so the leading silence
    // belongs to it rather than to nothing.
    Array.from({ length: CLIP_COUNT }, (_, i) => (i === 0 ? 0 : round2(timings[i * 8].start))));
  check('the slowly-spoken scene gets the longest window',
    timed.sync_windows[2].vo_seconds > timed.sync_windows[0].vo_seconds * 2, true);
  check('the windows still cover the whole voiceover', timed.sync_windows[CLIP_COUNT - 1].vo_end, timed.voiceover_sec);

  // Every cue must open on the exact moment its first word is spoken.
  const cueStarts = timed.subtitles_srt.split('\n\n').map((b) => {
    const [mm, ss, ms] = b.split('\n')[1].split(' --> ')[0].split(/[:,]/).slice(1);
    return Number(mm) * 60 + Number(ss) + Number(ms) / 1000;
  });
  const firstWords = timed.subtitles_srt.split('\n\n').map((b) => b.split('\n')[2].split(' ')[0]);
  const wordStart = Object.fromEntries(timings.map((x) => [x.word, x.start]));
  check('every cue opens on the word it shows',
    cueStarts.every((s, i) => Math.abs(s - wordStart[firstWords[i]]) < 0.02 || (i === 0 && s === 0)), true);

  // Timings that do not match the script must not be trusted.
  const mismatched = (await runNode('Build Sync Map', { json: { ...timedCtx,
    word_timings: timings.slice(0, 5).map((x) => ({ ...x, word: 'different' })),
    voiceover_measured_sec: totalSpoken, matched_scenes: [] } }))[0].json;
  check('timings that do not match the script are not trusted', mismatched.word_timings_aligned, false);
  check('and the fallback is reported rather than silent',
    mismatched.sync_warnings.some((w) => w.includes('did not line up')), true);
  check('the estimate still covers the whole voiceover',
    mismatched.sync_windows[CLIP_COUNT - 1].vo_end, mismatched.voiceover_sec);

  // ---- flow prompts -------------------------------------------------------
  console.log('\nflow prompts');
  OPENROUTER_REPLY = JSON.stringify({
    production_bible_summary: 'Warm office documentary.',
    clip_prompts: [1, 2, 3, 4, 5].map((i) => ({
      clip_number: `${i}/5`,
      prompt_text: 'REFERENCE IMAGE: a name the model invented\nSHOT: medium\nAUDIO: ambient only',
    })),
  });
  // Flow always generates a full clip, but the edit keeps only the window the
  // sync map worked out. A director who does not know that writes a move whose
  // payoff lands after the cut.
  await runNode('OpenRouter Flow Prompts', { json: ctx });
  const brief = OPENROUTER_REQUEST.messages[1].content;
  check('the director is told how much of each clip is actually used',
    ctx.sync_windows.every((w) => brief.includes(`ON SCREEN: the first ${w.render.trim_end}s`)), true);
  check('and that the end frame has to land inside it',
    OPENROUTER_REQUEST.messages[0].content.includes('end of the ON SCREEN window'), true);

  const flow = (await runNode('Parse Flow Prompts', { json: { ...ctx, choices: [{ message: { content: OPENROUTER_REPLY } }] } }))[0].json;
  check('the locked image name overrides whatever the model wrote',
    flow.clip_prompts.every((p, i) => p.prompt_text.includes(`REFERENCE IMAGE: part${i + 1} shot`)), true);
  check('no invented names survive', flow.flow_prompts_text.includes('a name the model invented'), false);
  check('no signed URLs are pasted into Flow prompts', flow.flow_prompts_text.includes('X-Amz-Signature'), false);
  check('each clip carries the filename to save it as',
    flow.clip_prompts.map((p) => p.save_as), [1, 2, 3, 4, 5].map((i) => `R1-clip${i}.mp4`));

  // ---- manifest -----------------------------------------------------------
  console.log('\nmanifest');
  await runNode('Upload Manifest to S3', { json: flow });
  const written = JSON.parse(BUCKET.get('reels-manifests/R1.json'));
  check('the manifest records the voiceover length the plan assumed', written.voiceover_sec, ctx.voiceover_sec);
  check('and how that length was arrived at', written.voiceover_duration_source, ctx.voiceover_duration_source);
  check('and both edit constants the composer needs to rescale',
    [written.transition_sec, written.tail_sec], [ctx.transition_sec, ctx.tail_sec]);
  check('the render plan is one entry per clip', written.render_plan.length, CLIP_COUNT);

  // ---- telegram package ---------------------------------------------------
  console.log('\ntelegram package');
  const pkg = await runNode('Format Final Package', { json: { ...flow,
    manifest_url: 'https://b/m.json', unique_images_text: '1. img\nhttps://b/i1',
    image_links_text: 'Clip 1/5: img\nhttps://b/i1' } });
  const all = pkg.map((m) => m.json.telegram_message).join('\n');
  check('every message fits inside Telegram limits', pkg.every((m) => m.json.telegram_message.length < 4096), true);
  check('the package tells you how to name the clips', all.includes('NAME YOUR CLIPS'), true);
  check('and lists the exact filenames', all.includes('R1-clip3.mp4'), true);
  check('and how to compose', all.includes('/compose R1'), true);

  // ---- compose ------------------------------------------------------------
  console.log('\ncompose session');
  const manifest = { run_id: 'R1', selected_topic: { title: 'T' }, voiceover_key: 'reels-voiceovers/x.mp3',
    voiceover_sec: ON_BUDGET_SEC, transition_sec: 0.3, tail_sec: 0.25,
    subtitles_srt: '1\n00:00:00,000 --> 00:00:02,000\nhi',
    production_bible: {}, sync_windows: ctx.sync_windows.map((w) => ({ clip_number: w.clip_number, narrative_beat: w.narrative_beat, vo_seconds: w.vo_seconds, spoken_text: w.spoken_text })),
    render_plan: ctx.sync_windows.map((w) => w.render) };
  BUCKET.set('reels-manifests/R1.json', JSON.stringify(manifest));

  const start = await runNode('Handle Compose Start', { json: { chat_id: '9', run_id: 'R1' } });
  check('a session is opened', BUCKET.has('reels-compose-sessions/9.json'), true);
  check('the reply explains the naming rule', start[0].json.reply_text.includes('clip1.mp4'), true);

  let unknown = null;
  try { await runNode('Handle Compose Start', { json: { chat_id: '9', run_id: 'ghost' } }); }
  catch (e) { unknown = e.message; }
  check('an unknown run id fails loudly', String(unknown).includes('Manifest not found'), true);

  const fake = Buffer.from('mp4').toString('base64');
  const send = (msgId, fileName, caption) => runNode('Handle Clip Upload WF1', {
    json: { chat_id: '9', clip_file_name: fileName, caption_index: caption ?? null, message: { message_id: msgId, chat: { id: 9 } } },
    binary: { data: { mimeType: 'video/mp4', fileName, data: fake } },
  });

  for (const [id, n] of [[11, 3], [12, 1], [13, 5], [14, 2], [15, 4]]) await send(id, `R1-clip${n}.mp4`);
  let session = JSON.parse(BUCKET.get('reels-compose-sessions/9.json'));
  session.clips.sort((a, b) => a.index - b.index);
  check('clips sent out of order land in the right slots',
    session.clips.map((c) => c.s3_key),
    [1, 2, 3, 4, 5].map((i) => `reels-clips/R1/clip-0${i}.mp4`));
  check('every slot was resolved from the filename', session.clips.every((c) => c.index_source === 'filename'), true);

  const again = await send(11, 'R1-clip3.mp4');
  check('resending a message does not duplicate it', again[0].json.reply_text.includes('already saved'), true);

  const status = await runNode('Handle Status Cancel', { json: { chat_id: '9', compose_action: 'status' } });
  check('status reports a full set', status[0].json.reply_text.includes('Clips: 5/5'), true);

  // ---- render -------------------------------------------------------------
  console.log('\nrender');
  OPENROUTER_REPLY = JSON.stringify({
    style_name: 'warm office documentary',
    color: { saturation: 1.12, contrast: 1.06, brightness: 0.01 },
    transitions: [{ type: 'xfade', duration_ms: 320 }],
    subtitles: { mode: 'burn', font: 'Helvetica', size: 54, color: '#FFFFFF', outline_color: '#101010' },
    audio: { voiceover_gain_db: 1, fade_in_ms: 200, fade_out_ms: 400 },
    per_clip_zoom: [1.06, 1, 1, 1.04, 1.08],
  });
  const directed = (await runNode('OpenRouter Render Director', { json: { chat_id: '9' } }))[0].json;
  check('the director only chose a look', directed.style.style_name, 'warm office documentary');

  await runNode('Start Render', { json: directed });
  check('per-clip timing comes from the manifest, not the model',
    COMPOSER_PAYLOAD.recipe.per_clip.map((p) => [p.trim_end, p.speed]),
    manifest.render_plan.map((p) => [p.trim_end, p.speed]));
  check('the look comes from the director', COMPOSER_PAYLOAD.recipe.per_clip.map((p) => p.zoom), [1.06, 1, 1, 1.04, 1.08]);
  check('clip audio is muted so only the voiceover is heard', COMPOSER_PAYLOAD.recipe.audio.clip_audio_gain_db, -60);
  check('the generated subtitles reach the renderer', COMPOSER_PAYLOAD.subtitles_srt.length > 0, true);
  // The composer reprobes the mp3 and rescales the plan against these two, so a
  // render sent without them silently loses the correction.
  check('the composer is told what voiceover length the plan assumed',
    [COMPOSER_PAYLOAD.voiceover_sec, COMPOSER_PAYLOAD.tail_sec], [ON_BUDGET_SEC, 0.25]);

  // ---- QC comes back from the composer ------------------------------------
  console.log('\nquality gate');
  BUCKET.set('reels-compose-sessions/9.json', JSON.stringify({ run_id: 'R1', clips: [], manifest }));
  COMPOSER_JOB = { status: 'done', output_url: 'https://b/final.mp4', output_key: 'reels-final/R1.mp4',
    duration_sec: ON_BUDGET_SEC, qc: { ok: true, duration_sec: ON_BUDGET_SEC, voiceover_sec: ON_BUDGET_SEC, drift_sec: 0.02, problems: [] },
    timing: { applied: true, reason: 'plan rescaled 1.0400x' } };
  const passed = (await runNode('Poll Render Job', { json: { chat_id: '9', run_id: 'R1', job_id: 'job-1', recipe: { style_name: 'warm' } } }))[0].json;
  check('a reel that passes QC is announced as ready', passed.reply_text.includes('Your reel is ready'), true);
  check('and a rescale is reported rather than hidden', passed.reply_text.includes('plan rescaled'), true);
  check('the session is closed once the reel is good',
    JSON.parse(BUCKET.get('reels-compose-sessions/9.json')).deleted, true);

  BUCKET.set('reels-compose-sessions/9.json', JSON.stringify({ run_id: 'R1', clips: [], manifest }));
  COMPOSER_JOB = { status: 'done', output_url: 'https://b/final.mp4', output_key: 'reels-final/R1.mp4',
    duration_sec: 20, qc: { ok: false, duration_sec: 20, voiceover_sec: ON_BUDGET_SEC, drift_sec: -6,
      problems: ['video ends 6.00s before the voiceover — the closing words are cut off'] } };
  const flagged = (await runNode('Poll Render Job', { json: { chat_id: '9', run_id: 'R1', job_id: 'job-1', recipe: { style_name: 'warm' } } }))[0].json;
  check('a reel that fails QC is not announced as ready', flagged.reply_text.includes('Your reel is ready'), false);
  check('the problem is spelled out', flagged.reply_text.includes('closing words are cut off'), true);
  check('the download is still offered', flagged.reply_text.includes('https://b/final.mp4'), true);
  check('and the session stays open so the clips need not be re-sent',
    JSON.parse(BUCKET.get('reels-compose-sessions/9.json')).deleted, undefined);

  // A styling failure must not block a render that is otherwise ready.
  OPENROUTER_REPLY = 'not json at all';
  const fallback = (await runNode('OpenRouter Render Director', { json: { chat_id: '9' } }))[0].json;
  check('a broken style response falls back instead of failing', fallback.style.style_name, 'clean commercial');

  const cancelled = await runNode('Handle Status Cancel', { json: { chat_id: '9', compose_action: 'cancel' } });
  check('cancel clears the session', JSON.parse(BUCKET.get('reels-compose-sessions/9.json')).deleted, true);
  check('and says so', cancelled[0].json.reply_text.includes('cancelled'), true);

  const orphan = await runNode('Handle Clip Upload WF1', {
    json: { chat_id: '404', clip_file_name: 'clip1.mp4', message: { message_id: 1, chat: { id: 404 } } },
    binary: { data: { mimeType: 'video/mp4', data: fake } } });
  check('a clip with no session gets a useful reply', orphan[0].json.reply_text.includes('/compose'), true);

  console.log('');
  if (failures.length) {
    console.log(`${failures.length} failure(s):`);
    failures.forEach((f) => console.log('  ✗ ' + f));
    process.exit(1);
  }
  console.log('all node checks passed');
}

main().catch((e) => { console.error('harness crashed:', e.stack); process.exit(1); });
"""


def main():
    workflow = json.loads(Path(MAIN_WORKFLOW_JSON).read_text(encoding="utf-8"))
    code = {
        n["name"]: n["parameters"]["jsCode"]
        for n in workflow["nodes"]
        if n.get("parameters", {}).get("jsCode")
    }
    # The harness asserts against the current grid, so hand it the same
    # constants the builder used rather than repeating 5 / 10 / 26 in JS.
    preamble = "\n".join([
        f"const CLIP_COUNT = {CLIP_COUNT};",
        f"const CLIP_SEC = {CLIP_SEC};",
        f"const TOTAL_SEC = {TOTAL_SEC};",
        f"const WORDS_PER_CLIP = {WORDS_PER_CLIP};",
        f"const NODES = {json.dumps(code)};",
    ])
    script = f"{preamble}\n{HARNESS}"
    with tempfile.NamedTemporaryFile("w", suffix=".mjs", delete=False, encoding="utf-8") as f:
        f.write(script)
        path = f.name
    try:
        return subprocess.run(["node", path]).returncode
    finally:
        Path(path).unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
