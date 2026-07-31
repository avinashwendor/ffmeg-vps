#!/usr/bin/env python3
"""Build reels_compose_automation.json — Telegram clip upload + FFmpeg compose."""
import json
import uuid

from build_workflow import (
    OPENROUTER_KEY,
    OPENROUTER_MODEL_HEAVY,
    s3_common_js,
)

# Deploy reels-composer/ to Railway (builds FFmpeg from git.ffmpeg.org), then set URL.
COMPOSER_URL = "https://YOUR-COMPOSER-SERVICE.up.railway.app"
# Optional: set AUTH_TOKEN env on Railway and match here (Authorization: Bearer ...)
COMPOSER_AUTH_TOKEN = ""

nodes = []
connections = {}


def nid():
    return str(uuid.uuid4())


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


PARSE_INCOMING_JS = """
const staticData = $getWorkflowStaticData('global');
if (!staticData.sessions) staticData.sessions = {};

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

ROUTE_IF = {
    "conditions": {
        "options": {"caseSensitive": True, "leftValue": "", "typeValidation": "loose", "version": 2},
        "conditions": [
            {"id": nid(), "leftValue": "={{ $json.action }}", "rightValue": "compose_start", "operator": {"type": "string", "operation": "equals"}},
        ],
        "combinator": "and",
    },
    "looseTypeValidation": True,
    "options": {},
}

HANDLE_COMPOSE_START_JS = s3_common_js() + """
const chatId = $json.chat_id;
const runId = $json.run_id;
if (!runId) throw new Error('Usage: /compose RUN_ID (example: /compose 2026-07-30-0930)');

const staticData = $getWorkflowStaticData('global');
if (!staticData.sessions) staticData.sessions = {};

const key = `reels-manifests/${runId}.json`;
const manifestUrl = presignGetUrl(key);
let manifest;
try {
  const raw = await this.helpers.httpRequest({ method: 'GET', url: manifestUrl, json: false, timeout: 60000 });
  const text = typeof raw === 'string' ? raw : JSON.stringify(raw);
  manifest = JSON.parse(text);
} catch (err) {
  throw new Error(`Manifest not found for run_id "${runId}". Run the reels generator first, or check the run_id. (${err.message || err})`);
}

staticData.sessions[chatId] = {
  state: 'collecting',
  run_id: runId,
  chat_id: chatId,
  manifest,
  clips: [],
  started_at: Date.now(),
  expires_at: Date.now() + 2 * 60 * 60 * 1000,
};

const title = manifest.selected_topic?.title || manifest.run_id;
return [{
  json: {
    chat_id: chatId,
    reply_text: `Compose session started\\nTopic: ${title}\\nRun: ${runId}\\n\\nUpload 5 Flow clips (caption optional: 1-5).\\nSend done when finished.\\n/cancel to abort.`,
  },
}];
"""

HANDLE_CLIP_UPLOAD_JS = s3_common_js() + """
const staticData = $getWorkflowStaticData('global');
const chatId = $json.chat_id;
const session = staticData.sessions?.[chatId];
if (!session || session.state !== 'collecting') {
  return [{ json: { chat_id: chatId, reply_text: 'No active compose session. Send /compose RUN_ID first.' } }];
}
if (Date.now() > session.expires_at) {
  delete staticData.sessions[chatId];
  throw new Error('Session expired. Send /compose RUN_ID again.');
}

const binary = $input.first().binary || {};
const binKey = Object.keys(binary)[0];
if (!binKey) throw new Error('No video binary on message. Enable Download Images/Files on Telegram Trigger.');

const raw = binary[binKey];
let bytes;
if (typeof raw.data === 'string') bytes = fromBase64(raw.data);
else if (raw.data?.type === 'Buffer') bytes = Uint8Array.from(raw.data.data);
else throw new Error('Unexpected binary format from Telegram');

const used = new Set((session.clips || []).map((c) => c.index));
let index = $json.caption_index;
if (!index || index < 1 || index > 5 || used.has(index)) {
  for (let i = 1; i <= 5; i++) {
    if (!used.has(i)) { index = i; break; }
  }
}
if (!index) throw new Error('All 5 clip slots are filled. Send done or /cancel.');

const runId = session.run_id;
const s3Key = `reels-clips/${runId}/clip-${String(index).padStart(2, '0')}.mp4`;
await putObject.call(this, s3Key, bytes, 'video/mp4');
const url = presignGetUrl(s3Key);

session.clips = (session.clips || []).filter((c) => c.index !== index);
session.clips.push({ index, s3_key: s3Key, url, uploaded_at: Date.now() });
session.clips.sort((a, b) => a.index - b.index);
staticData.sessions[chatId] = session;

return [{
  json: {
    chat_id: chatId,
    reply_text: `Clip ${index}/5 saved (${session.clips.length}/5 total). Send more clips or type done.`,
  },
}];
"""

HANDLE_STATUS_CANCEL_JS = """
const staticData = $getWorkflowStaticData('global');
const chatId = $json.chat_id;
const session = staticData.sessions?.[chatId];

if ($json.action === 'cancel') {
  delete staticData.sessions[chatId];
  return [{ json: { chat_id: chatId, reply_text: 'Compose session cancelled.' } }];
}

if (!session) {
  return [{ json: { chat_id: chatId, reply_text: 'No active session. /compose RUN_ID to start.' } }];
}

const clips = session.clips || [];
const lines = clips.map((c) => `• Clip ${c.index}: ${c.s3_key}`).join('\\n') || 'No clips yet.';
return [{
  json: {
    chat_id: chatId,
    reply_text: `Session: ${session.run_id}\\nClips: ${clips.length}/5\\n${lines}`,
  },
}];
"""

OPENROUTER_RENDER_DIRECTOR_JS = f"""
const staticData = $getWorkflowStaticData('global');
const chatId = $json.chat_id;
const session = staticData.sessions?.[chatId];
if (!session) throw new Error('No active session. /compose RUN_ID first.');

const clips = session.clips || [];
if (clips.length < 5) {{
  throw new Error(`Need 5 clips before done. Currently have ${{clips.length}}/5.`);
}}

const manifest = session.manifest;
const userContent = JSON.stringify({{
  manifest,
  clips: clips.map((c) => ({{ index: c.index, s3_key: c.s3_key, url: c.url }})),
}}, null, 2);

const body = {{
  model: {json.dumps(OPENROUTER_MODEL_HEAVY)},
  response_format: {{ type: 'json_object' }},
  messages: [
    {{
      role: 'system',
      content: `You are a Shorts post-production director. Given a manifest (script, SRT, sync windows, production bible) and 5 clip URLs, output ONLY valid JSON for an FFmpeg render recipe.

Required keys: style_name (string), clip_order (array of 1-5), per_clip (array of {{index, trim_start, trim_end, speed, zoom}}), transitions (array of {{after_clip, type, duration_ms}}), audio ({{voiceover_gain_db, clip_audio_gain_db, fade_in_ms, fade_out_ms}}), subtitles ({{mode: burn, font, size, color, outline_color}}), color ({{saturation, contrast, brightness}}).

Rules:
- 9:16 vertical Short, premium cinematic look
- Use subtitles_srt cues only — never invent dialogue
- trim_end null means use full clip length
- Prefer xfade transitions 250-400ms
- Hook energy in clip 1, CTA feel in clip 5`,
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

let recipe;
const content = res?.choices?.[0]?.message?.content || '';
try {{
  recipe = JSON.parse(content.replace(/```json\\n?/gi, '').replace(/```\\n?/g, '').trim());
}} catch (e) {{
  throw new Error(`Render director returned invalid JSON: ${{String(content).slice(0, 300)}}`);
}}

return [{{
  json: {{
    chat_id: chatId,
    run_id: session.run_id,
    manifest,
    clips,
    recipe,
    reply_text: 'Rendering your reel… I will message you when it is ready (usually 2-5 min).',
  }},
}}];
"""

START_RENDER_JS = f"""
const ctx = $input.first().json;
const composerUrl = {json.dumps(COMPOSER_URL)};
if (composerUrl.includes('YOUR-COMPOSER-SERVICE')) {{
  throw new Error('Set COMPOSER_URL in build_compose_workflow.py after deploying reels-composer/ to Railway.');
}}

const body = {{
  run_id: ctx.run_id,
  clips: ctx.clips.map((c) => ({{ index: c.index, url: c.url, s3_key: c.s3_key }})),
  voiceover_url: ctx.manifest.voiceover_url,
  subtitles_srt: ctx.manifest.subtitles_srt || ctx.manifest.script?.subtitles_srt || '',
  recipe: ctx.recipe,
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

const staticData = $getWorkflowStaticData('global');
const session = staticData.sessions?.[ctx.chat_id] || {{}};
session.job_id = res.job_id;
session.render_status = 'processing';
staticData.sessions[ctx.chat_id] = session;

return [{{ json: {{ ...ctx, job_id: res.job_id, render_status: res.status }} }}];
"""

POLL_RENDER_JS = f"""
const ctx = $input.first().json;
const composerUrl = {json.dumps(COMPOSER_URL)};
const jobId = ctx.job_id;
if (!jobId) throw new Error('Missing job_id');

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
  return [{{ json: {{ ...ctx, poll_again: true, job_status: job.status }} }}];
}}

const staticData = $getWorkflowStaticData('global');
delete staticData.sessions?.[ctx.chat_id];

return [{{ json: {{
  ...ctx,
  poll_again: false,
  output_url: job.output_url,
  output_key: job.output_key,
  duration_sec: job.duration_sec,
  reply_text: `Your reel is ready!\\nRun: ${{ctx.run_id}}\\nDuration: ${{Math.round(job.duration_sec || 0)}}s\\nDownload: ${{job.output_url}}`,
}} }}];
"""

x, y, dx = 0, 300, 280

add_node("Telegram Trigger", "n8n-nodes-base.telegramTrigger", {
    "updates": ["message"],
    "additionalFields": {"download": True},
}, [x, y], 1.2, {"webhookId": nid()})

add_node("Parse Incoming", "n8n-nodes-base.code", {"jsCode": PARSE_INCOMING_JS}, [x + dx, y], 2)

add_node("IF Compose Start", "n8n-nodes-base.if", ROUTE_IF, [x + 2 * dx, y], 2.2)

add_node("IF Clip Upload", "n8n-nodes-base.if", {
    "conditions": {
        "options": {"caseSensitive": True, "leftValue": "", "typeValidation": "loose", "version": 2},
        "conditions": [
            {"id": nid(), "leftValue": "={{ $json.action }}", "rightValue": "clip_upload", "operator": {"type": "string", "operation": "equals"}},
        ],
        "combinator": "and",
    },
    "looseTypeValidation": True, "options": {},
}, [x + 2 * dx, y + 120], 2.2)

add_node("IF Done", "n8n-nodes-base.if", {
    "conditions": {
        "options": {"caseSensitive": True, "leftValue": "", "typeValidation": "loose", "version": 2},
        "conditions": [
            {"id": nid(), "leftValue": "={{ $json.action }}", "rightValue": "done", "operator": {"type": "string", "operation": "equals"}},
        ],
        "combinator": "and",
    },
    "looseTypeValidation": True, "options": {},
}, [x + 2 * dx, y + 240], 2.2)

add_node("IF Status Cancel", "n8n-nodes-base.if", {
    "conditions": {
        "options": {"caseSensitive": True, "leftValue": "", "typeValidation": "loose", "version": 2},
        "conditions": [
            {"id": nid(), "leftValue": "={{ $json.action }}", "rightValue": "status", "operator": {"type": "string", "operation": "equals"}},
            {"id": nid(), "leftValue": "={{ $json.action }}", "rightValue": "cancel", "operator": {"type": "string", "operation": "equals"}},
        ],
        "combinator": "or",
    },
    "looseTypeValidation": True, "options": {},
}, [x + 2 * dx, y + 360], 2.2)

add_node("Handle Compose Start", "n8n-nodes-base.code", {"jsCode": HANDLE_COMPOSE_START_JS}, [x + 3 * dx, y - 60], 2)
add_node("Handle Clip Upload", "n8n-nodes-base.code", {"jsCode": HANDLE_CLIP_UPLOAD_JS}, [x + 3 * dx, y + 120], 2)
add_node("Handle Status Cancel", "n8n-nodes-base.code", {"jsCode": HANDLE_STATUS_CANCEL_JS}, [x + 3 * dx, y + 360], 2)

add_node("OpenRouter Render Director", "n8n-nodes-base.code", {"jsCode": OPENROUTER_RENDER_DIRECTOR_JS}, [x + 4 * dx, y + 240], 2)
add_node("Start Render", "n8n-nodes-base.code", {"jsCode": START_RENDER_JS}, [x + 5 * dx, y + 240], 2)
add_node("Wait For Render", "n8n-nodes-base.wait", {"amount": 15, "unit": "seconds"}, [x + 6 * dx, y + 240], 1.1)
add_node("Poll Render Job", "n8n-nodes-base.code", {"jsCode": POLL_RENDER_JS}, [x + 7 * dx, y + 240], 2)
add_node("IF Poll Again", "n8n-nodes-base.if", {
    "conditions": {
        "options": {"caseSensitive": True, "leftValue": "", "typeValidation": "loose", "version": 2},
        "conditions": [
            {"id": nid(), "leftValue": "={{ $json.poll_again }}", "rightValue": True, "operator": {"type": "boolean", "operation": "true"}},
        ],
        "combinator": "and",
    },
    "looseTypeValidation": True, "options": {},
}, [x + 8 * dx, y + 240], 2.2)

add_node("Reply Processing", "n8n-nodes-base.telegram", {
    "chatId": "={{ $json.chat_id }}",
    "text": "={{ $json.reply_text }}",
    "additionalFields": {"appendAttribution": False},
}, [x + 5 * dx, y + 80], 1.2, {"webhookId": nid()})

add_node("Reply Final", "n8n-nodes-base.telegram", {
    "chatId": "={{ $json.chat_id }}",
    "text": "={{ $json.reply_text }}",
    "additionalFields": {"appendAttribution": False},
}, [x + 9 * dx, y + 320], 1.2, {"webhookId": nid()})

nodes.append({
    "parameters": {
        "content": f"""## Reels Compose Automation

**Composer API:** `{COMPOSER_URL}`
**FFmpeg:** built from official `git.ffmpeg.org/ffmpeg.git` in Docker

### Setup
1. Railway → New Service → root dir `reels-composer/` (4 vCPU / 4 GB)
2. Env: `S3_*` creds (same bucket as reels workflow), optional `AUTH_TOKEN`
3. Set `COMPOSER_URL` in build_compose_workflow.py → run `python3 build_compose_workflow.py`
4. Import `reels_compose_automation.json` + Telegram credentials

### Usage
`/compose RUN_ID` → upload 5 clips → `done` → final MP4 link

### Commands
- `/compose RUN_ID` — start (loads manifest from S3)
- `done` — render
- `/status` — progress
- `/cancel` — abort""",
        "height": 420,
        "width": 420,
    },
    "type": "n8n-nodes-base.stickyNote",
    "typeVersion": 1,
    "position": [-220, 60],
    "id": nid(),
    "name": "Setup Notes",
})

connect("Telegram Trigger", "Parse Incoming")
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

with open("reels_compose_automation.json", "w", encoding="utf-8") as f:
    json.dump({
        "name": "Reels Compose Automation",
        "nodes": nodes,
        "connections": connections,
        "pinData": {},
        "settings": {"executionOrder": "v1"},
        "meta": {"templateCredsSetupCompleted": False, "instanceId": nid()},
    }, f, indent=2, ensure_ascii=False)

print(f"Done: {len(nodes)} nodes -> reels_compose_automation.json")
