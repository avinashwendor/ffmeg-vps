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
const failures = [];
const key = (url) => decodeURIComponent(new URL(url).pathname.replace(/^\//, ''));

const helpers = { httpRequest: async (o) => {
  if (o.url.includes('openrouter.ai')) return { choices: [{ message: { content: OPENROUTER_REPLY } }] };
  if (o.url.includes('/v1/render')) { COMPOSER_PAYLOAD = o.body; return { job_id: 'job-1', status: 'queued' }; }
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
let INPUT = null;
const $input = { first: () => INPUT };

async function runNode(name, item) {
  INPUT = item;
  const $json = item.json || {};
  const body = NODES[name];
  if (body == null) throw new Error(`no such node: ${name}`);
  const fn = new Function('$input', '$json', 'helpers',
    '"use strict"; return (async function(){ ' + body + '\n}).call({ helpers });');
  return await fn($input, $json, helpers);
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

  // ---- flow prompts -------------------------------------------------------
  console.log('\nflow prompts');
  OPENROUTER_REPLY = JSON.stringify({
    production_bible_summary: 'Warm office documentary.',
    clip_prompts: [1, 2, 3, 4, 5].map((i) => ({
      clip_number: `${i}/5`,
      prompt_text: 'REFERENCE IMAGE: a name the model invented\nSHOT: medium\nAUDIO: ambient only',
    })),
  });
  const flow = (await runNode('Parse Flow Prompts', { json: { ...ctx, choices: [{ message: { content: OPENROUTER_REPLY } }] } }))[0].json;
  check('the locked image name overrides whatever the model wrote',
    flow.clip_prompts.every((p, i) => p.prompt_text.includes(`REFERENCE IMAGE: part${i + 1} shot`)), true);
  check('no invented names survive', flow.flow_prompts_text.includes('a name the model invented'), false);
  check('no signed URLs are pasted into Flow prompts', flow.flow_prompts_text.includes('X-Amz-Signature'), false);
  check('each clip carries the filename to save it as',
    flow.clip_prompts.map((p) => p.save_as), [1, 2, 3, 4, 5].map((i) => `R1-clip${i}.mp4`));

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
    voiceover_sec: ON_BUDGET_SEC, transition_sec: 0.3, subtitles_srt: '1\n00:00:00,000 --> 00:00:02,000\nhi',
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
