#!/usr/bin/env python3
"""Optional: generate legacy standalone compose workflow in automations/archive/."""
import json
import sys
import uuid
from pathlib import Path

BUILD_DIR = Path(__file__).resolve().parent
if str(BUILD_DIR) not in sys.path:
    sys.path.insert(0, str(BUILD_DIR))

from config import *  # noqa: F403
from paths import ARCHIVE_DIR

OPENROUTER_MODEL_HEAVY = "anthropic/claude-sonnet-5"
RENDER_POLL_MAX_ATTEMPTS = 40  # 40 x 15s wait ≈ 10 min

TELEGRAM_ESCAPE_HTML_JS = """
function escapeHtml(text) {
  return String(text || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}
"""


def nid():
    return str(uuid.uuid4())


def compose_action_if(action_value):
    return {
        "conditions": {
            "options": {"caseSensitive": True, "leftValue": "", "typeValidation": "loose", "version": 2},
            "conditions": [
                {
                    "id": nid(),
                    "leftValue": "={{ $json.compose_action || $json.action }}",
                    "rightValue": action_value,
                    "operator": {"type": "string", "operation": "equals"},
                },
            ],
            "combinator": "and",
        },
        "looseTypeValidation": True,
        "options": {},
    }


def status_cancel_help_if():
    """One IF for the three session-control commands that share a handler."""
    return {
        "conditions": {
            "options": {"caseSensitive": True, "leftValue": "", "typeValidation": "loose", "version": 2},
            "conditions": [
                {
                    "id": nid(),
                    "leftValue": "={{ $json.compose_action || $json.action }}",
                    "rightValue": action,
                    "operator": {"type": "string", "operation": "equals"},
                }
                for action in ("status", "cancel", "help")
            ],
            "combinator": "or",
        },
        "looseTypeValidation": True,
        "options": {},
    }


def build_compose_handlers(s3_session_js, compose_clip_upload_js):
    """s3_session_js must supply the S3 primitives *and* the compose-session
    helpers — every handler here loads or saves a session."""
    s3 = s3_session_js()
    for required in ("loadComposeSession", "saveComposeSession", "deleteComposeSession"):
        if f"function {required}" not in s3:
            raise SystemExit(f"build_compose_handlers: session helper {required}() missing from the S3 bundle")

    handle_compose_start_js = TELEGRAM_ESCAPE_HTML_JS + s3 + """
function parseManifestText(text) {
  const trimmed = String(text || '').trim();
  if (!trimmed) throw new Error('Manifest file is empty');
  const outer = JSON.parse(trimmed);
  if (outer && outer.type === 'Buffer' && Array.isArray(outer.data)) {
    const inner = new TextDecoder().decode(Uint8Array.from(outer.data));
    return JSON.parse(inner);
  }
  return outer;
}

const chatId = $json.chat_id;
const runId = $json.run_id;
if (!runId) throw new Error('Usage: /compose RUN_ID (example: /compose 2026-07-30-0930)');

const key = `reels-manifests/${runId}.json`;
let manifest;
try {
  const text = await getObject.call(this, key);
  manifest = parseManifestText(text);
} catch (err) {
  throw new Error(`Manifest not found for run_id "${runId}". Run the reels generator first, or check the run_id. (${err.message || err})`);
}

const session = {
  state: 'collecting',
  run_id: runId,
  chat_id: chatId,
  manifest,
  clips: [],
  started_at: Date.now(),
  // Generating and downloading five Flow clips is not a two-hour job in practice.
  expires_at: Date.now() + 12 * 60 * 60 * 1000,
};
await saveComposeSession.call(this, chatId, session);

const title = manifest.selected_topic?.title || manifest.topic_slug || runId;
return [{
  json: {
    chat_id: chatId,
    reply_text: [
      `Compose session started`,
      `Topic: ${escapeHtml(title)}`,
      `Run: ${escapeHtml(runId)}`,
      ``,
      `Send me the 5 Flow clips (album is fine, any order).`,
      `Name each file with its clip number — clip1.mp4 … clip5.mp4 — and I place it in the right slot.`,
      `No number in the name? Send the clip with caption 1-5 instead.`,
      ``,
      `/status to see progress · done when all 5 are in · /cancel to abort`,
    ].join('\\n'),
  },
}];
"""

    handle_status_cancel_js = TELEGRAM_ESCAPE_HTML_JS + s3 + """
const chatId = $json.chat_id;

const action = $json.compose_action || $json.action;
if (action === 'cancel') {
  await deleteComposeSession.call(this, chatId);
  return [{ json: { chat_id: chatId, reply_text: 'Compose session cancelled.' } }];
}
if (action === 'help') {
  return [{ json: { chat_id: chatId, reply_text: [
    '<b>Reels bot</b>',
    '',
    '<b>Make a video package</b>',
    '/generate — research topics, then reply 1-5 to pick one',
    '/generate 3 — skip the picker, take topic #3',
    '/generate your own topic — skip research entirely',
    '',
    '<b>Turn Flow clips into the final reel</b>',
    '/compose RUN_ID — start collecting (run id is in the package message)',
    'then send the 5 clips named clip1.mp4 … clip5.mp4',
    'done — render · /status — progress · /cancel — abort',
  ].join('\\n') } }];
}

const session = await loadComposeSession.call(this, chatId);
if (!session) {
  return [{ json: { chat_id: chatId, reply_text: 'No active session. /compose RUN_ID to start.' } }];
}

const byIndex = new Map();
for (const c of session.clips || []) {
  if (c && c.url) byIndex.set(Number(c.index), c);
}
const lines = [1, 2, 3, 4, 5]
  .map((i) => (byIndex.has(i) ? `Clip ${i}/5  received` : `Clip ${i}/5  waiting`))
  .join('\\n');
const missing = [1, 2, 3, 4, 5].filter((i) => !byIndex.has(i));
const nextStep = missing.length
  ? `Still need: ${missing.map((i) => `clip${i}.mp4`).join(', ')}`
  : 'All 5 in. Send done to render.';
return [{
  json: {
    chat_id: chatId,
    reply_text: [
      `Session: ${escapeHtml(session.run_id)}`,
      `Clips: ${byIndex.size}/5`,
      '',
      lines,
      '',
      nextStep,
    ].join('\\n'),
  },
}];
"""

    openrouter_render_director_js = f"""
{s3}
async function clipsFromS3(runId) {{
  const keys = await listObjects.call(this, `reels-clips/${{runId}}/`);
  return keys
    .filter((k) => /clip-\\d+\\.mp4$/i.test(k))
    .map((key) => {{
      const m = key.match(/clip-(\\d+)\\.mp4$/i);
      const index = m ? Number(m[1]) : 0;
      return {{ index, s3_key: key, url: presignGetUrl(key) }};
    }})
    .filter((c) => c.index >= 1 && c.index <= 5)
    .sort((a, b) => a.index - b.index);
}}

const chatId = $json.chat_id;
let session = await loadComposeSession.call(this, chatId);
if (!session) throw new Error('No active session. /compose RUN_ID first.');

let clips = (session.clips || []).filter((c) => c.url && c.s3_key);
if (clips.length < 5) {{
  const fromS3 = await clipsFromS3.call(this, session.run_id);
  if (fromS3.length > clips.length) clips = fromS3;
}}
if (clips.length < 5) {{
  throw new Error(`Need 5 clips before done. Session has ${{clips.length}}/5. Upload clips — you should get "Clip X/5 saved" replies. Try /status.`);
}}

const manifest = session.manifest;

// Only the creative decisions go to the model. Clip order and per-clip timing
// are computed from the measured voiceover in Start Render — a model guessing
// trim points is exactly how a reel ends up out of sync.
const userContent = JSON.stringify({{
  topic: manifest.selected_topic?.title,
  production_bible: manifest.production_bible,
  voiceover_seconds: manifest.voiceover_sec,
  beats: (manifest.sync_windows || []).map((w) => ({{
    clip: w.clip_number,
    beat: w.narrative_beat,
    seconds: w.vo_seconds,
    voiceover: w.spoken_text,
  }})),
}}, null, 2);

const body = {{
  model: {json.dumps(OPENROUTER_MODEL_HEAVY)},
  response_format: {{ type: 'json_object' }},
  messages: [
    {{
      role: 'system',
      content: `You are a post-production colourist and title designer for vertical short-form video. You are given the beats of a 9:16 short and you choose how it should look. Timing, clip order and trims are already fixed by the edit — do not attempt to set them.

Return ONE valid JSON object with exactly these keys:
  style_name          short name for the look, e.g. "warm office documentary"
  color               {{ saturation, contrast, brightness }}
                      saturation 0.9-1.25, contrast 0.95-1.2, brightness -0.05-0.05
  transitions         [{{ type: "xfade", duration_ms }}] — one entry, 250-400ms
  subtitles           {{ mode: "burn", font, size, color, outline_color }}
                      font is a common sans face: Arial, Helvetica, Impact, Verdana
                      size 44-60 for a 1080x1920 frame
                      color and outline_color are hex, high contrast, readable on any frame
  audio               {{ voiceover_gain_db, fade_in_ms, fade_out_ms }}
                      gain -2 to 2, fades 150-500ms
  per_clip_zoom       array of 5 numbers, 1.0-1.12, a gentle push where the beat wants energy

Match the look to the script: a hard-numbers business short wants clean neutral grade and a plain bold caption; a lifestyle or freedom beat can take warmth and a softer face. Keep it premium and legible — never neon, never a decorative script font.`,
    }},
    {{ role: 'user', content: userContent }},
  ],
}};

const res = await this.helpers.httpRequest({{
  method: 'POST',
  url: 'https://openrouter.ai/api/v1/chat/completions',
  headers: {{
    Authorization: 'Bearer {OPENROUTER_KEY}',
    'Content-Type': 'application/json',
    'HTTP-Referer': 'https://n8n.io',
    'X-Title': 'Reels Compose Automation',
  }},
  body,
  json: true,
  timeout: 300000,
}});

// A styling miss should not block a render that is otherwise ready to go.
const DEFAULT_STYLE = {{
  style_name: 'clean commercial',
  color: {{ saturation: 1.06, contrast: 1.04, brightness: 0 }},
  transitions: [{{ type: 'xfade', duration_ms: 300 }}],
  subtitles: {{ mode: 'burn', font: 'Arial', size: 52, color: '#FFFFFF', outline_color: '#000000' }},
  audio: {{ voiceover_gain_db: 0, fade_in_ms: 200, fade_out_ms: 400 }},
  per_clip_zoom: [1, 1, 1, 1, 1],
}};

let style = DEFAULT_STYLE;
let style_source = 'director';
const content = res?.choices?.[0]?.message?.content || '';
try {{
  const parsed = JSON.parse(content.replace(/```json\\n?/gi, '').replace(/```\\n?/g, '').trim());
  style = {{ ...DEFAULT_STYLE, ...parsed }};
}} catch (e) {{
  style_source = `fell back to defaults (${{String(e.message || e).slice(0, 80)}})`;
}}

return [{{
  json: {{
    chat_id: chatId,
    run_id: session.run_id,
    manifest,
    clips,
    style,
    style_source,
    reply_text: `Rendering your reel in a "${{style.style_name}}" look. I will send it here when it is done, usually 2-5 minutes.`,
  }},
}}];
"""

    start_render_js = f"""
{s3}
const ctx = $input.first().json;
const composerUrl = {json.dumps(COMPOSER_URL)};
if (composerUrl.includes('YOUR-COMPOSER-SERVICE')) {{
  throw new Error('Set COMPOSER_URL in build_compose_workflow.py after deploying reels-composer/ to Railway.');
}}

const voiceKey = ctx.manifest?.voiceover_key;
if (!voiceKey) throw new Error('Manifest missing voiceover_key — re-run reels generator for this run_id.');
const voiceover_url = presignGetUrl(voiceKey);

const manifest = ctx.manifest || {{}};
const style = ctx.style || {{}};
const zooms = Array.isArray(style.per_clip_zoom) ? style.per_clip_zoom : [];

// The generator already worked out, from the measured voiceover, how long each
// clip has to be on screen. Use that verbatim; the model only picked the look.
const plan = Array.isArray(manifest.render_plan) && manifest.render_plan.length
  ? manifest.render_plan
  : ctx.clips.map((c) => ({{ index: c.index, trim_start: 0, trim_end: null, speed: 1 }}));

const per_clip = plan.map((p, i) => ({{
  index: Number(p.index ?? i + 1),
  trim_start: Number(p.trim_start || 0),
  trim_end: p.trim_end == null ? null : Number(p.trim_end),
  speed: Number(p.speed || 1),
  zoom: Math.min(1.15, Math.max(1, Number(zooms[i]) || 1)),
}}));

const transition_ms = Math.round(
  Number(style.transitions?.[0]?.duration_ms) || (manifest.transition_sec || 0.3) * 1000
);

const recipe = {{
  style_name: style.style_name || 'clean commercial',
  clip_order: per_clip.map((p) => p.index),
  per_clip,
  transitions: [{{ after_clip: 1, type: 'xfade', duration_ms: transition_ms }}],
  audio: {{
    voiceover_gain_db: Number(style.audio?.voiceover_gain_db || 0),
    clip_audio_gain_db: -60,
    fade_in_ms: Number(style.audio?.fade_in_ms || 200),
    fade_out_ms: Number(style.audio?.fade_out_ms || 400),
  }},
  subtitles: {{ mode: 'burn', ...(style.subtitles || {{}}) }},
  color: {{ saturation: 1.06, contrast: 1.04, brightness: 0, ...(style.color || {{}}) }},
}};

const body = {{
  run_id: ctx.run_id,
  clips: ctx.clips.map((c) => ({{ index: c.index, url: c.url, s3_key: c.s3_key }})),
  voiceover_url,
  // The generator derived this from the mp3's byte size before the file was ever
  // probed. The composer downloads the real thing, measures it, and rescales the
  // plan if the two disagree — so it has to know what the plan assumed.
  voiceover_sec: manifest.voiceover_sec,
  // The director may pick a different crossfade than the plan assumed, and a
  // longer one eats more of every clip. The composer needs both to correct it.
  transition_sec: manifest.transition_sec,
  tail_sec: manifest.tail_sec,
  subtitles_srt: manifest.subtitles_srt || '',
  recipe,
  output_key: `reels-final/${{ctx.run_id}}.mp4`,
}};

const headers = {{ 'Content-Type': 'application/json' }};
const token = {json.dumps(COMPOSER_AUTH_TOKEN)};
if (token) headers.Authorization = `Bearer ${{token}}`;

const res = await this.helpers.httpRequest({{
  method: 'POST',
  url: `${{composerUrl.replace(/\\/$/, '')}}/v1/render`,
  headers,
  body,
  json: true,
  timeout: 120000,
}});

let session = await loadComposeSession.call(this, ctx.chat_id);
if (session) {{
  session.job_id = res.job_id;
  session.render_status = 'processing';
  await saveComposeSession.call(this, ctx.chat_id, session);
}}

return [{{ json: {{ ...ctx, recipe, job_id: res.job_id, render_status: res.status, poll_attempt: 0 }} }}];
"""

    poll_render_js = f"""
{TELEGRAM_ESCAPE_HTML_JS}
{s3}
const ctx = $input.first().json;
const composerUrl = {json.dumps(COMPOSER_URL)};
const jobId = ctx.job_id;
if (!jobId) throw new Error('Missing job_id');

const poll_attempt = (ctx.poll_attempt || 0) + 1;
const MAX_POLL_ATTEMPTS = {RENDER_POLL_MAX_ATTEMPTS};

const headers = {{}};
const token = {json.dumps(COMPOSER_AUTH_TOKEN)};
if (token) headers.Authorization = `Bearer ${{token}}`;

const job = await this.helpers.httpRequest({{
  method: 'GET',
  url: `${{composerUrl.replace(/\\/$/, '')}}/v1/jobs/${{jobId}}`,
  headers,
  json: true,
  timeout: 60000,
}});

if (job.status === 'failed') throw new Error(job.error || 'Render failed');
if (job.status !== 'done') {{
  if (poll_attempt >= MAX_POLL_ATTEMPTS) {{
    throw new Error(`Render timed out after ~${{MAX_POLL_ATTEMPTS * 15}}s. Job ${{jobId}} still "${{job.status}}". Check the composer service or retry /compose.`);
  }}
  return [{{ json: {{ ...ctx, poll_again: true, poll_attempt, job_status: job.status }} }}];
}}

// The composer checks the finished file before handing it over: length against
// the voiceover it actually measured, one audio track, a 1080x1920 frame.
const qc = job.qc || {{}};
const qc_ok = qc.ok !== false;
const problems = Array.isArray(qc.problems) ? qc.problems : [];

// A reel that failed QC is still uploaded — but the session stays open so the
// clips do not have to be sent again to try another render.
if (qc_ok) await deleteComposeSession.call(this, ctx.chat_id);

const header = qc_ok
  ? 'Your reel is ready.'
  : 'Your reel rendered, but it did not pass the final check. Look before you post it.';

const lines = [
  header,
  `Run: ${{escapeHtml(ctx.run_id)}}`,
  `Look: ${{escapeHtml(ctx.recipe?.style_name || 'default')}}`,
  `Length: ${{(Number(job.duration_sec) || 0).toFixed(1)}}s against a ${{qc.voiceover_sec ?? ctx.manifest?.voiceover_sec ?? '?'}}s voiceover`,
];
// Only worth saying when the byte-size estimate turned out to be wrong.
if (job.timing?.applied) lines.push(`Timing: ${{escapeHtml(job.timing.reason || '')}}`);
if (!qc_ok) {{
  lines.push('', 'PROBLEMS');
  for (const p of problems) lines.push(`• ${{escapeHtml(p)}}`);
  lines.push('', 'Send "done" again to re-render, or /cancel to drop the session.');
}}
lines.push('Download:', `<code>${{String(job.output_url || '').replace(/&/g, '&amp;')}}</code>`);

return [{{ json: {{
  ...ctx,
  poll_again: false,
  output_url: job.output_url,
  output_key: job.output_key,
  duration_sec: job.duration_sec,
  qc,
  qc_ok,
  reply_text: lines.join('\\n'),
}} }}];
"""

    return {
        "HANDLE_COMPOSE_START_JS": handle_compose_start_js,
        "HANDLE_CLIP_UPLOAD_JS": compose_clip_upload_js(),
        "HANDLE_STATUS_CANCEL_JS": handle_status_cancel_js,
        "OPENROUTER_RENDER_DIRECTOR_JS": openrouter_render_director_js,
        "START_RENDER_JS": start_render_js,
        "POLL_RENDER_JS": poll_render_js,
    }


def inject_compose_delegate_into_wf1(s3_session_js, compose_clip_upload_js, wf_add_node, wf_connect, delegate_if_name, reply_node_name):
    """Inline compose_start / done / status / cancel / help into WF1 (no sub-workflow)."""
    h = build_compose_handlers(s3_session_js, compose_clip_upload_js)

    wf_add_node("IF Compose Start", "n8n-nodes-base.if", compose_action_if("compose_start"), 2.2)
    wf_add_node("IF Done", "n8n-nodes-base.if", compose_action_if("done"), 2.2)
    wf_add_node("IF Status Cancel", "n8n-nodes-base.if", status_cancel_help_if(), 2.2)

    wf_add_node("Handle Compose Start", "n8n-nodes-base.code", {"jsCode": h["HANDLE_COMPOSE_START_JS"]}, 2)
    wf_add_node("Handle Status Cancel", "n8n-nodes-base.code", {"jsCode": h["HANDLE_STATUS_CANCEL_JS"]}, 2)
    wf_add_node("OpenRouter Render Director", "n8n-nodes-base.code", {"jsCode": h["OPENROUTER_RENDER_DIRECTOR_JS"]}, 2)
    wf_add_node("Start Render", "n8n-nodes-base.code", {"jsCode": h["START_RENDER_JS"]}, 2)
    wf_add_node("Wait For Render", "n8n-nodes-base.wait", {"amount": 15, "unit": "seconds"}, 1.1)
    wf_add_node("Poll Render Job", "n8n-nodes-base.code", {"jsCode": h["POLL_RENDER_JS"]}, 2)
    wf_add_node("IF Poll Again", "n8n-nodes-base.if", {
        "conditions": {
            "options": {"caseSensitive": True, "leftValue": "", "typeValidation": "loose", "version": 2},
            "conditions": [
                {"id": nid(), "leftValue": "={{ $json.poll_again }}", "rightValue": True, "operator": {"type": "boolean", "operation": "true"}},
            ],
            "combinator": "and",
        },
        "looseTypeValidation": True,
        "options": {},
    }, 2.2)

    wf_connect(delegate_if_name, "IF Compose Start", 0)
    wf_connect(delegate_if_name, "IF Done", 0)
    wf_connect(delegate_if_name, "IF Status Cancel", 0)

    wf_connect("IF Compose Start", "Handle Compose Start", 0)
    wf_connect("Handle Compose Start", reply_node_name)

    wf_connect("IF Status Cancel", "Handle Status Cancel", 0)
    wf_connect("Handle Status Cancel", reply_node_name)

    wf_connect("IF Done", "OpenRouter Render Director", 0)
    wf_connect("OpenRouter Render Director", "Start Render")
    wf_connect("Start Render", reply_node_name)
    wf_connect("Start Render", "Wait For Render")
    wf_connect("Wait For Render", "Poll Render Job")
    wf_connect("Poll Render Job", "IF Poll Again")
    wf_connect("IF Poll Again", "Wait For Render", 0)
    wf_connect("IF Poll Again", reply_node_name, 1)


def build_standalone_compose_workflow():
    from build_workflow import compose_clip_upload_js, s3_session_js

    handlers = build_compose_handlers(s3_session_js, compose_clip_upload_js)
    nodes = []
    connections = {}

    def add_node(name, node_type, params, position, type_version=1, extra=None):
        node = {
            "parameters": params,
            "type": node_type,
            "typeVersion": type_version,
            "position": position,
            "id": nid(),
            "name": name,
        }
        if extra:
            node.update(extra)
        nodes.append(node)
        return name

    def connect(src, dst, out_index=0, in_index=0):
        connections.setdefault(src, {}).setdefault("main", [])
        while len(connections[src]["main"]) <= out_index:
            connections[src]["main"].append([])
        connections[src]["main"][out_index].append({"node": dst, "type": "main", "index": in_index})

    parse_incoming_js = """
const msg = $json.message || {};
const chatId = String(msg.chat?.id || '');
const text = String(msg.text || msg.caption || '').trim();
const from = msg.from || {};

if (from.is_bot) {
  return [{ json: { action: 'reply', chat_id: chatId, reply_text: 'Use your personal Telegram account, not a bot.' } }];
}
if (!chatId) return [];

const video = msg.video;
const doc = msg.document;
const isVideoDoc = doc && /^video\\//i.test(String(doc.mime_type || ''));
const isClip = !!(video || isVideoDoc);

let action = 'ignore';
if (/^\\/compose\\b/i.test(text)) action = 'compose_start';
else if (/^done$/i.test(text)) action = 'done';
else if (/^\\/cancel$/i.test(text)) action = 'cancel';
else if (/^\\/status$/i.test(text)) action = 'status';
else if (isClip) action = 'clip_upload';

const runIdMatch = text.match(/^\\/compose\\s+(\\S+)/i);
const captionIndex = text.match(/^(?:clip\\s*)?(\\d)\\s*$/i) || text.match(/^(\\d)\\s*\\/\\s*5$/);

return [{
  json: {
    action,
    chat_id: chatId,
    text,
    run_id: runIdMatch ? runIdMatch[1].trim() : null,
    caption_index: captionIndex ? Number(captionIndex[1]) : null,
    file_id: video?.file_id || doc?.file_id || null,
    file_name: doc?.file_name || `clip-${Date.now()}.mp4`,
    message: msg,
  },
  binary: $input.first().binary,
}];
"""

    x, y, dx = 0, 300, 280

    add_node("When Called by WF1", "n8n-nodes-base.executeWorkflowTrigger", {"inputSource": "passthrough"}, [x, y], 1.1)
    add_node("Parse Incoming", "n8n-nodes-base.code", {"jsCode": parse_incoming_js}, [x + dx, y], 2)
    add_node("IF Compose Start", "n8n-nodes-base.if", compose_action_if("compose_start"), [x + 2 * dx, y], 2.2)
    add_node("IF Clip Upload", "n8n-nodes-base.if", compose_action_if("clip_upload"), [x + 2 * dx, y + 120], 2.2)
    add_node("IF Done", "n8n-nodes-base.if", compose_action_if("done"), [x + 2 * dx, y + 240], 2.2)
    add_node("IF Status Cancel", "n8n-nodes-base.if", status_cancel_help_if(), [x + 2 * dx, y + 360], 2.2)

    add_node("Handle Compose Start", "n8n-nodes-base.code", {"jsCode": handlers["HANDLE_COMPOSE_START_JS"]}, [x + 3 * dx, y - 60], 2)
    add_node("Handle Clip Upload", "n8n-nodes-base.code", {"jsCode": handlers["HANDLE_CLIP_UPLOAD_JS"]}, [x + 3 * dx, y + 120], 2)
    add_node("Handle Status Cancel", "n8n-nodes-base.code", {"jsCode": handlers["HANDLE_STATUS_CANCEL_JS"]}, [x + 3 * dx, y + 360], 2)
    add_node("OpenRouter Render Director", "n8n-nodes-base.code", {"jsCode": handlers["OPENROUTER_RENDER_DIRECTOR_JS"]}, [x + 4 * dx, y + 240], 2)
    add_node("Start Render", "n8n-nodes-base.code", {"jsCode": handlers["START_RENDER_JS"]}, [x + 5 * dx, y + 240], 2)
    add_node("Wait For Render", "n8n-nodes-base.wait", {"amount": 15, "unit": "seconds"}, [x + 6 * dx, y + 240], 1.1)
    add_node("Poll Render Job", "n8n-nodes-base.code", {"jsCode": handlers["POLL_RENDER_JS"]}, [x + 7 * dx, y + 240], 2)
    add_node("IF Poll Again", "n8n-nodes-base.if", {
        "conditions": {
            "options": {"caseSensitive": True, "leftValue": "", "typeValidation": "loose", "version": 2},
            "conditions": [
                {"id": nid(), "leftValue": "={{ $json.poll_again }}", "rightValue": True, "operator": {"type": "boolean", "operation": "true"}},
            ],
            "combinator": "and",
        },
        "looseTypeValidation": True,
        "options": {},
    }, [x + 8 * dx, y + 240], 2.2)

    add_node("Reply Processing", "n8n-nodes-base.telegram", {
        "chatId": "={{ $json.chat_id }}",
        "text": "={{ $json.reply_text }}",
        "additionalFields": {"appendAttribution": False, "parse_mode": "HTML"},
    }, [x + 5 * dx, y + 80], 1.2, {"webhookId": nid(), "onError": "continueRegularOutput"})

    add_node("Reply Final", "n8n-nodes-base.telegram", {
        "chatId": "={{ $json.chat_id }}",
        "text": "={{ $json.reply_text }}",
        "additionalFields": {"appendAttribution": False, "parse_mode": "HTML"},
    }, [x + 9 * dx, y + 320], 1.2, {"webhookId": nid()})

    connect("When Called by WF1", "Parse Incoming")
    connect("Parse Incoming", "IF Compose Start")
    connect("Parse Incoming", "IF Clip Upload")
    connect("Parse Incoming", "IF Done")
    connect("Parse Incoming", "IF Status Cancel")
    connect("IF Compose Start", "Handle Compose Start", 0)
    connect("Handle Compose Start", "Reply Processing")
    connect("IF Clip Upload", "Handle Clip Upload", 0)
    connect("Handle Clip Upload", "Reply Processing")
    connect("IF Status Cancel", "Handle Status Cancel", 0)
    connect("Handle Status Cancel", "Reply Processing")
    connect("IF Done", "OpenRouter Render Director", 0)
    connect("OpenRouter Render Director", "Start Render")
    connect("Start Render", "Reply Processing")
    connect("Start Render", "Wait For Render")
    connect("Wait For Render", "Poll Render Job")
    connect("Poll Render Job", "IF Poll Again")
    connect("IF Poll Again", "Wait For Render", 0)
    connect("IF Poll Again", "Reply Final", 1)

    return nodes, connections


if __name__ == "__main__":
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    nodes, connections = build_standalone_compose_workflow()
    out = ARCHIVE_DIR / "reels_compose_automation.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump({
            "name": "Reels Compose Automation",
            "nodes": nodes,
            "connections": connections,
            "pinData": {},
            "settings": {"executionOrder": "v1"},
            "meta": {"templateCredsSetupCompleted": False, "instanceId": nid()},
        }, f, indent=2, ensure_ascii=False)
    print(f"Done: {len(nodes)} nodes -> {out}")
