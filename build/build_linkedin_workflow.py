#!/usr/bin/env python3
"""Generate automations/linkedin_post_automation.json."""
import json
import sys
from pathlib import Path

BUILD_DIR = Path(__file__).resolve().parent
if str(BUILD_DIR) not in sys.path:
    sys.path.insert(0, str(BUILD_DIR))

from config import (  # noqa: F401
    LINKEDIN_API_VERSION,
    LINKEDIN_ORG_ID,
    LINKEDIN_CREDENTIAL_TYPE,
    LINKEDIN_PUBLISH_AS,
    LINKEDIN_PERSON_URN,
    LINKEDIN_SEARCH_QUERY,
    TAVILY_KEY,
    TELEGRAM_LINKEDIN_CHAT_ID,
)
from paths import LINKEDIN_WORKFLOW_JSON, LINKEDIN_WORKFLOW_NAME
from workflow_common import (
    OPENROUTER_MODEL_FAST,
    OPENROUTER_MODEL_HEAVY,
    PARSE_OPENROUTER_JS,
    READ_TELEGRAM_REPLY_JS,
    S3_IMAGES_PREFIX,
    RAILWAY_S3_BUCKET,
    WorkflowBuilder,
    s3_common_js,
    s3_linkedin_session_js,
)

b = WorkflowBuilder()

# Fixed layout — no overlapping nodes (DX=320 between columns)
DX = 320
ROW_SCHED = 180
ROW_TG = 520
ROW_TG_CMD = 820
ROW_CUSTOM = 1120
ROW_MAIN = 1480
ROW_PUBLISH = 1820

NODE_POSITIONS = {
    "Schedule Trigger": [0, ROW_SCHED],
    "Set Scheduled Context": [DX, ROW_SCHED],
    "Tavily Search": [DX * 2, ROW_SCHED],
    "Attach Run Context": [DX * 3, ROW_SCHED],
    "OpenRouter Top 5 Topics": [DX * 4, ROW_SCHED],
    "Parse Top 5 Topics": [DX * 5, ROW_SCHED],
    "Send Topic Picker": [DX * 6, ROW_SCHED],
    "Restore Topic Context": [DX * 7, ROW_SCHED],
    "Wait For Topic Selection": [DX * 8, ROW_SCHED],
    "Parse Topic Selection": [DX * 9, ROW_SCHED],
    "Telegram Trigger": [0, ROW_TG],
    "Save LinkedIn Chat ID": [DX, ROW_TG],
    "Classify LinkedIn Message": [DX * 2, ROW_TG],
    "IF LinkedIn Command": [DX * 3, ROW_TG],
    "IF Lihelp": [DX * 4, ROW_TG],
    "Send Lihelp": [DX * 5, ROW_TG - 200],
    "IF Licancel": [DX * 5, ROW_TG],
    "Handle Licancel": [DX * 6, ROW_TG],
    "Send Licancel Reply": [DX * 7, ROW_TG],
    "IF Start": [DX * 5, ROW_TG + 200],
    "Send Start Reply": [DX * 6, ROW_TG + 200],
    "Set Telegram Context": [DX * 6, ROW_CUSTOM],
    "Parse Custom Topic": [DX * 7, ROW_CUSTOM],
    "IF Needs Topic Wait": [DX * 8, ROW_CUSTOM],
    "Wait For Custom Topic": [DX * 9, ROW_CUSTOM - 80],
    "Parse Custom Topic Reply": [DX * 10, ROW_CUSTOM - 80],
    "Merge Selected Topic": [DX * 9, ROW_MAIN],
    "Load S3 Brand Images": [DX * 10, ROW_MAIN],
    "OpenRouter Match Image": [DX * 11, ROW_MAIN],
    "Parse Match Image": [DX * 12, ROW_MAIN],
    "OpenRouter Post Variants": [DX * 13, ROW_MAIN],
    "Parse Post Variants": [DX * 14, ROW_MAIN],
    "Download Post Image": [DX * 15, ROW_MAIN],
    "Attach Image Binary": [DX * 16, ROW_MAIN],
    "Send Image Preview": [DX * 17, ROW_MAIN],
    "Restore Post Context": [DX * 18, ROW_MAIN],
    "Send Post Option 1": [DX * 19, ROW_MAIN],
    "Restore For Post 2": [DX * 20, ROW_MAIN],
    "Send Post Option 2": [DX * 21, ROW_MAIN],
    "Restore For Wait": [DX * 22, ROW_MAIN],
    "Wait For Variant Selection": [DX * 23, ROW_MAIN],
    "Parse Variant Selection": [DX * 24, ROW_MAIN],
    "Prepare LinkedIn Post": [DX * 10, ROW_PUBLISH],
    "LinkedIn Register Upload": [DX * 11, ROW_PUBLISH],
    "Parse Register Upload": [DX * 12, ROW_PUBLISH],
    "Attach Post Image Binary": [DX * 13, ROW_PUBLISH],
    "LinkedIn Upload Image": [DX * 14, ROW_PUBLISH],
    "Set Image Fields": [DX * 15, ROW_PUBLISH],
    "LinkedIn Publish": [DX * 16, ROW_PUBLISH],
    "Set Published Status": [DX * 17, ROW_PUBLISH],
    "Summarize Publish Results": [DX * 18, ROW_PUBLISH],
    "Send Publish Confirmation": [DX * 19, ROW_PUBLISH],
    "Setup Notes": [-280, 80],
}

# Stable webhook IDs (do not regenerate on each build)
WEBHOOK_IDS = {
    "Telegram Trigger": "b1000001-0001-4000-8000-000000000001",
    "Send Lihelp": "b1000001-0001-4000-8000-000000000002",
    "Send Licancel Reply": "b1000001-0001-4000-8000-000000000003",
    "Send Start Reply": "b1000001-0001-4000-8000-000000000004",
    "Wait For Topic Selection": "b1000001-0001-4000-8000-000000000005",
    "Wait For Custom Topic": "b1000001-0001-4000-8000-000000000006",
    "Send Image Preview": "b1000001-0001-4000-8000-000000000007",
    "Wait For Variant Selection": "b1000001-0001-4000-8000-000000000008",
    "Send Publish Confirmation": "b1000001-0001-4000-8000-000000000009",
}


def _pos(name):
    return NODE_POSITIONS[name]


def _restore_context_js(source_node):
    return f"""const ctx = $('{source_node}').first().json;
const bin = $input.first().binary;
if (!ctx.chat_id) throw new Error('Missing chat_id after {source_node}. Message the LinkedIn bot /start first.');
const out = {{ json: {{ ...ctx }} }};
if (bin && Object.keys(bin).length) out.binary = bin;
return [out];"""


def _finalize_workflow():
    """Apply layout, stable webhooks; omit credentials (assign in n8n UI like reels workflow)."""
    for node in b.nodes:
        name = node.get("name")
        if name in NODE_POSITIONS:
            node["position"] = NODE_POSITIONS[name]
        node.pop("credentials", None)
        if name in WEBHOOK_IDS:
            node["webhookId"] = WEBHOOK_IDS[name]


# ── TRIGGERS ──────────────────────────────────────────────
b.add_node("Schedule Trigger", "n8n-nodes-base.scheduleTrigger", {
    "rule": {"interval": [{"field": "cronExpression", "expression": "0 9 * * 1-5"}]},
}, _pos("Schedule Trigger"), 1.2)

b.add_node("Telegram Trigger", "n8n-nodes-base.telegramTrigger", {
    "updates": ["message"],
    "additionalFields": {"download": True},
}, _pos("Telegram Trigger"), 1.2, {"webhookId": WEBHOOK_IDS["Telegram Trigger"]})

# ── TELEGRAM: save chat + route (separate from reels bot) ─
b.add_node("Save LinkedIn Chat ID", "n8n-nodes-base.code", {
    "jsCode": """const staticData = $getWorkflowStaticData('global');
const from = $json.message?.from;
const chat = $json.message?.chat;
if (from?.is_bot) {
  throw new Error('That message came from a bot account. Open Telegram as yourself and message the LinkedIn bot.');
}
if (chat?.type === 'private' && chat.id) {
  staticData.linkedin_telegram_chat_id = String(chat.id);
}
return [{ json: $json, binary: $input.first().binary }];"""
}, _pos("Save LinkedIn Chat ID"), 2)

b.add_node("Classify LinkedIn Message", "n8n-nodes-base.code", {
    "jsCode": """const msg = $json.message || {};
const text = String(msg.text || '').trim();
let li_action = 'ignore';
if (/^\\/start\\b/i.test(text)) li_action = 'start';
else if (/^\\/lihelp\\b/i.test(text)) li_action = 'lihelp';
else if (/^\\/licancel\\b/i.test(text)) li_action = 'licancel';
else if (/^\\/linkedin\\b/i.test(text)) li_action = 'linkedin';
return [{
  json: {
    ...$json,
    li_action,
    li_text: text,
    chat_id: String(msg.chat?.id || ''),
  },
  binary: $input.first().binary,
}];"""
}, _pos("Classify LinkedIn Message"), 2)

b.add_node("IF LinkedIn Command", "n8n-nodes-base.if", {
    "conditions": {
        "options": {"caseSensitive": True, "leftValue": "", "typeValidation": "loose", "version": 2},
        "conditions": [{
            "id": b.nid(),
            "leftValue": "={{ $json.li_action }}",
            "rightValue": "ignore",
            "operator": {"type": "string", "operation": "notEquals"},
        }],
        "combinator": "and",
    },
    "looseTypeValidation": True,
    "options": {},
}, _pos("IF LinkedIn Command"), 2.2)

b.add_node("IF Lihelp", "n8n-nodes-base.if", {
    "conditions": {
        "options": {"caseSensitive": True, "leftValue": "", "typeValidation": "loose", "version": 2},
        "conditions": [{
            "id": b.nid(),
            "leftValue": "={{ $json.li_action }}",
            "rightValue": "lihelp",
            "operator": {"type": "string", "operation": "equals"},
        }],
        "combinator": "and",
    },
    "looseTypeValidation": True,
    "options": {},
}, _pos("IF Lihelp"), 2.2)

b.add_node("Send Lihelp", "n8n-nodes-base.telegram", {
    "chatId": "={{ $json.chat_id }}",
    "text": """LINKEDIN BOT — Commands

/start — register chat for scheduled runs
/linkedin <topic> — generate posts for a custom topic
/linkedin — bot asks for your topic
/licancel — abort stuck run
/lihelp — this message

Scheduled runs (weekdays 9 AM) send 5 news topics; reply 1-5.
After generation, reply 1 or 2 to publish that post.

Uses a SEPARATE bot from reels (/generate, /compose).""",
    "additionalFields": {"appendAttribution": False},
}, _pos("Send Lihelp"), 1.2, {"webhookId": WEBHOOK_IDS["Send Lihelp"]})

b.add_node("IF Licancel", "n8n-nodes-base.if", {
    "conditions": {
        "options": {"caseSensitive": True, "leftValue": "", "typeValidation": "loose", "version": 2},
        "conditions": [{
            "id": b.nid(),
            "leftValue": "={{ $json.li_action }}",
            "rightValue": "licancel",
            "operator": {"type": "string", "operation": "equals"},
        }],
        "combinator": "and",
    },
    "looseTypeValidation": True,
    "options": {},
}, _pos("IF Licancel"), 2.2)

b.add_node("Handle Licancel", "n8n-nodes-base.code", {
    "jsCode": s3_common_js() + s3_linkedin_session_js() + """
const chatId = $json.chat_id;
if (chatId) await deleteLinkedInSession.call(this, chatId);
return [{ json: { chat_id: chatId, reply_text: 'LINKEDIN: session cleared. Send /linkedin to start fresh.' } }];"""
}, _pos("Handle Licancel"), 2)

b.add_node("Send Licancel Reply", "n8n-nodes-base.telegram", {
    "chatId": "={{ $json.chat_id }}",
    "text": "={{ $json.reply_text }}",
    "additionalFields": {"appendAttribution": False},
}, _pos("Send Licancel Reply"), 1.2, {"webhookId": WEBHOOK_IDS["Send Licancel Reply"]})

b.add_node("IF Start", "n8n-nodes-base.if", {
    "conditions": {
        "options": {"caseSensitive": True, "leftValue": "", "typeValidation": "loose", "version": 2},
        "conditions": [{
            "id": b.nid(),
            "leftValue": "={{ $json.li_action }}",
            "rightValue": "start",
            "operator": {"type": "string", "operation": "equals"},
        }],
        "combinator": "and",
    },
    "looseTypeValidation": True,
    "options": {},
}, _pos("IF Start"), 2.2)

b.add_node("Send Start Reply", "n8n-nodes-base.telegram", {
    "chatId": "={{ $json.chat_id }}",
    "text": "LINKEDIN bot ready. Send /linkedin <topic> or wait for weekday scheduled topic picks.",
    "additionalFields": {"appendAttribution": False},
}, _pos("Send Start Reply"), 1.2, {"webhookId": WEBHOOK_IDS["Send Start Reply"]})

# ── SCHEDULED PATH ────────────────────────────────────────
b.add_node("Set Scheduled Context", "n8n-nodes-base.code", {
    "jsCode": f"""const d = new Date();
const p = (n) => String(n).padStart(2, '0');
const run_id = `li-${{d.getFullYear()}}-${{p(d.getMonth() + 1)}}-${{p(d.getDate())}}-${{p(d.getHours())}}${{p(d.getMinutes())}}`;
const staticData = $getWorkflowStaticData('global');
const chat_id = staticData.linkedin_telegram_chat_id || {json.dumps(TELEGRAM_LINKEDIN_CHAT_ID)};
if (!chat_id) {{
  throw new Error('No LinkedIn chat_id saved. Message the LinkedIn bot /start from your personal account.');
}}
return [{{ json: {{
  chat_id,
  trigger_mode: 'scheduled',
  run_id,
  workflow: 'linkedin',
}} }}];"""
}, _pos("Set Scheduled Context"), 2)

b.add_node("Tavily Search", "n8n-nodes-base.httpRequest", {
    "method": "POST",
    "url": "https://api.tavily.com/search",
    "sendHeaders": True,
    "headerParameters": {"parameters": [
        {"name": "Authorization", "value": f"Bearer {TAVILY_KEY}"},
        {"name": "Content-Type", "value": "application/json"},
    ]},
    "sendBody": True,
    "specifyBody": "json",
    "jsonBody": json.dumps({
        "query": LINKEDIN_SEARCH_QUERY,
        "search_depth": "advanced",
        "max_results": 10,
        "include_answer": True,
    }),
    "options": {},
}, _pos("Tavily Search"), 4.2)

b.add_node("Attach Run Context", "n8n-nodes-base.code", {
    "jsCode": """const ctx = $('Set Scheduled Context').first().json;
const tavily = $input.first().json;
const tavily_results = (tavily.results || []).slice(0, 8).map(r => ({
  title: r.title || '',
  url: r.url || '',
  content: String(r.content || '').slice(0, 600),
  score: r.score || 0,
}));
return [{ json: {
  ...ctx,
  tavily_answer: String(tavily.answer || '').slice(0, 1200),
  tavily_results,
} }];"""
}, _pos("Attach Run Context"), 2)

b.call_openrouter(
    "OpenRouter Top 5 Topics",
    'You are a LinkedIn thought-leadership strategist for the vending machine and smart retail industry. Return ONLY valid JSON. Root key MUST be "topics" with exactly 5 objects. Each: rank (1-5), title, angle, why_now, source_hint, best_market (India|Dubai|US|Global).',
    '`Analyze Tavily results and produce 5 ranked LinkedIn post topics for a vending-machine company page.\\n\\nAnswer: ${ctx.tavily_answer}\\n\\nResults: ${JSON.stringify(ctx.tavily_results)}`',
    _pos("OpenRouter Top 5 Topics"),
    model=OPENROUTER_MODEL_FAST,
)

b.add_node("Parse Top 5 Topics", "n8n-nodes-base.code", {
    "jsCode": PARSE_OPENROUTER_JS + """
const item = $input.first().json;
const data = parseOpenRouterJson(item, 'OpenRouter Top 5 Topics');
const topics = extractTopics(data);
if (!topics.length) throw new Error(`No topics returned. Keys: ${Object.keys(data).join(', ')}`);
const lines = topics.map((t, i) => `${t.rank || i+1}. ${t.title}\\n   Angle: ${t.angle || t.hook || ''}\\n   ${t.why_now || t.why_viral || ''} | Market: ${t.best_market || 'Global'}`).join('\\n\\n');
let topic_message = `LINKEDIN TOPIC PICKER\\nRun: ${item.run_id} (SCHEDULED)\\n\\nPick ONE topic (reply 1-5):\\n\\n${lines}\\n\\nReply with a number from 1 to 5.`;
if (topic_message.length > 3900) topic_message = topic_message.slice(0, 3880) + '\\n...(truncated)';
if (!item.chat_id) throw new Error('Missing chat_id. Message the LinkedIn bot /start from your personal account first.');
return [{ json: { ...item, topics, topic_message } }];"""
}, _pos("Parse Top 5 Topics"), 2)

b.add_node("Send Topic Picker", "n8n-nodes-base.telegram", {
    "chatId": "={{ $json.chat_id }}",
    "text": "={{ $json.topic_message }}",
    "additionalFields": {"appendAttribution": False},
}, _pos("Send Topic Picker"), 1.2)

b.add_node("Restore Topic Context", "n8n-nodes-base.code", {
    "jsCode": _restore_context_js("Parse Top 5 Topics"),
}, _pos("Restore Topic Context"), 2)

b.add_node("Wait For Topic Selection", "n8n-nodes-base.telegram", {
    "operation": "sendAndWait",
    "chatId": "={{ $json.chat_id }}",
    "message": "Reply with a number from 1 to 5 for the topic list above.",
    "responseType": "freeText",
    "options": {
        "appendAttribution": False,
        "limitWaitTime": {"values": {"limitWaitTime": 24, "limitWaitTimeUnit": "hours"}},
    },
}, _pos("Wait For Topic Selection"), 1.2, {"webhookId": WEBHOOK_IDS["Wait For Topic Selection"], "onError": "stopWorkflow"})

b.add_node("Parse Topic Selection", "n8n-nodes-base.code", {
    "jsCode": READ_TELEGRAM_REPLY_JS + """
const wait = $input.first().json;
if (wait.error) throw new Error(`Telegram failed: ${wait.error}`);
const prev = $('Parse Top 5 Topics').first().json;
const raw = readTelegramReply($input.first());
if (!raw) throw new Error('No topic selection received. Reply with 1-5.');
const pick = parseInt((raw.match(/[1-5]/) || [])[0], 10);
if (!pick) throw new Error(`Invalid selection "${raw}". Reply 1-5.`);
const selected = prev.topics.find(t => t.rank === pick) || prev.topics[pick - 1];
if (!selected) throw new Error(`Topic #${pick} not found.`);
const slug = (selected.title || 'topic').toLowerCase().replace(/[^a-z0-9]+/g, '-').slice(0, 40);
return [{ json: {
  ...prev,
  selected_topic: selected,
  selected_rank: pick,
  topic_slug: slug,
  topic_source: 'scheduled',
} }];"""
}, _pos("Parse Topic Selection"), 2)

# ── TELEGRAM CUSTOM TOPIC PATH ────────────────────────────
b.add_node("Set Telegram Context", "n8n-nodes-base.code", {
    "jsCode": """const d = new Date();
const p = (n) => String(n).padStart(2, '0');
const run_id = `li-${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}-${p(d.getHours())}${p(d.getMinutes())}`;
const staticData = $getWorkflowStaticData('global');
const chat_id = String($json.chat_id || $json.message?.chat?.id || '');
staticData.linkedin_telegram_chat_id = chat_id;
return [{ json: {
  chat_id,
  trigger_mode: 'manual',
  run_id,
  workflow: 'linkedin',
  li_text: $json.li_text || '',
} }];"""
}, _pos("Set Telegram Context"), 2)

b.add_node("Parse Custom Topic", "n8n-nodes-base.code", {
    "jsCode": """const ctx = $input.first().json;
const text = String(ctx.li_text || '').trim();
const m = text.match(/^\\/linkedin\\s+(.+)/is);
const customTitle = m ? m[1].trim() : '';
if (customTitle) {
  const slug = customTitle.toLowerCase().replace(/[^a-z0-9]+/g, '-').slice(0, 40);
  return [{ json: {
    ...ctx,
    needs_topic_wait: false,
    selected_topic: {
      title: customTitle,
      angle: 'custom',
      why_now: '',
      source_hint: 'user-provided',
      best_market: 'Global',
    },
    topic_slug: slug,
    topic_source: 'telegram_custom',
  } }];
}
return [{ json: { ...ctx, needs_topic_wait: true } }];"""
}, _pos("Parse Custom Topic"), 2)

b.add_node("IF Needs Topic Wait", "n8n-nodes-base.if", {
    "conditions": {
        "options": {"caseSensitive": True, "leftValue": "", "typeValidation": "loose", "version": 2},
        "conditions": [{
            "id": b.nid(),
            "leftValue": "={{ $json.needs_topic_wait }}",
            "rightValue": True,
            "operator": {"type": "boolean", "operation": "true"},
        }],
        "combinator": "and",
    },
    "looseTypeValidation": True,
    "options": {},
}, _pos("IF Needs Topic Wait"), 2.2)

b.add_node("Wait For Custom Topic", "n8n-nodes-base.telegram", {
    "operation": "sendAndWait",
    "chatId": "={{ $json.chat_id }}",
    "message": "LINKEDIN — What topic should I write about?\\n\\nReply with your topic in plain text.",
    "responseType": "freeText",
    "options": {
        "appendAttribution": False,
        "limitWaitTime": {"values": {"limitWaitTime": 24, "limitWaitTimeUnit": "hours"}},
    },
}, _pos("Wait For Custom Topic"), 1.2, {"webhookId": WEBHOOK_IDS["Wait For Custom Topic"]})

b.add_node("Parse Custom Topic Reply", "n8n-nodes-base.code", {
    "jsCode": READ_TELEGRAM_REPLY_JS + """
const prev = $('Parse Custom Topic').first().json;
const raw = readTelegramReply($input.first());
if (!raw) throw new Error('No topic received. Send a topic as plain text.');
const slug = raw.toLowerCase().replace(/[^a-z0-9]+/g, '-').slice(0, 40);
return [{ json: {
  ...prev,
  needs_topic_wait: false,
  selected_topic: {
    title: raw,
    angle: 'custom',
    why_now: '',
    source_hint: 'user-provided',
    best_market: 'Global',
  },
  topic_slug: slug,
  topic_source: 'telegram_custom',
} }];"""
}, _pos("Parse Custom Topic Reply"), 2)

# ── MERGE + SHARED PIPELINE ───────────────────────────────
b.add_node("Merge Selected Topic", "n8n-nodes-base.code", {
    "jsCode": s3_common_js() + s3_linkedin_session_js() + """
const ctx = $input.first().json;
if (!ctx.selected_topic?.title) throw new Error('Missing selected_topic.title');
const session = {
  workflow: 'linkedin',
  run_id: ctx.run_id,
  stage: 'generating',
  selected_topic: ctx.selected_topic,
  chat_id: ctx.chat_id,
  trigger_mode: ctx.trigger_mode,
  topic_source: ctx.topic_source,
  updated_at: new Date().toISOString(),
};
if (ctx.chat_id) await saveLinkedInSession.call(this, ctx.chat_id, session);
return [{ json: { ...ctx, linkedin_session: session } }];"""
}, _pos("Merge Selected Topic"), 2)

LOAD_S3_IMAGES_JS = s3_common_js() + """
const ctx = $input.first().json;
let keys = await listObjects.call(this, IMAGES_PREFIX);
const realImages = keys.filter(k => isImageKey(k) && !k.endsWith('/.keep'));
if (!realImages.length) {
  await putObject.call(this, `${IMAGES_PREFIX}.keep`, new Uint8Array(0), 'application/octet-stream');
  keys = await listObjects.call(this, IMAGES_PREFIX);
}
const imageKeys = keys.filter(k => isImageKey(k));
if (!imageKeys.length) {
  return [{ json: {
    ...ctx,
    brand_files: [],
    brand_file_names: 'none',
    images_folder_note: `Upload images to s3://${BUCKET}/${IMAGES_PREFIX}`,
  } }];
}
const brand_files = imageKeys.map(key => {
  const fileName = key.split('/').pop();
  const name = fileNameToLabel(fileName);
  return { id: key, key, name, file_name: fileName, url: presignGetUrl(key), tags: name };
});
return [{ json: {
  ...ctx,
  brand_files,
  brand_file_names: brand_files.map(f => f.name).join(', '),
  images_count: brand_files.length,
} }];"""

b.add_node("Load S3 Brand Images", "n8n-nodes-base.code", {
    "jsCode": LOAD_S3_IMAGES_JS,
}, _pos("Load S3 Brand Images"), 2)

b.call_openrouter(
    "OpenRouter Match Image",
    """You pick ONE brand image for a LinkedIn post about vending machines / smart retail.
Return ONLY valid JSON with keys: reference_image_name (EXACT from list), reference_image_key, reference_image_url, match_reason.
Use ONLY images from the provided list. Match filename keywords to topic intent (office, breakroom, touchscreen, snack, lobby, etc.).""",
    '`Topic: ${ctx.selected_topic?.title}\\nAngle: ${ctx.selected_topic?.angle || ""}\\nAvailable images: ${JSON.stringify(ctx.brand_files)}`',
    _pos("OpenRouter Match Image"),
    model=OPENROUTER_MODEL_FAST,
)

b.add_node("Parse Match Image", "n8n-nodes-base.code", {
    "jsCode": PARSE_OPENROUTER_JS + """
const item = $input.first().json;
const data = parseOpenRouterJson(item, 'OpenRouter Match Image');
const brandByName = Object.fromEntries((item.brand_files || []).map(f => [f.name.toLowerCase(), f]));
const brandByKey = Object.fromEntries((item.brand_files || []).map(f => [f.key, f]));
const file = brandByName[(data.reference_image_name || '').toLowerCase()]
  || brandByKey[data.reference_image_key]
  || (item.brand_files || [])[0];
if (!file) throw new Error('No brand images in S3 images/ folder.');
return [{ json: {
  ...item,
  matched_image: {
    reference_image_name: file.name,
    reference_image_key: file.key,
    reference_image_url: file.url,
    match_reason: data.match_reason || 'best available match',
  },
} }];"""
}, _pos("Parse Match Image"), 2)

POST_SYSTEM = """You are an expert LinkedIn ghostwriter for a vending-machine / smart retail company page (Wendor).
Return ONLY valid JSON with no markdown fences:
{ "variants": [
  { "id": 1, "style": "professional", "text": "..." },
  { "id": 2, "style": "story", "text": "..." }
] }
Exactly 2 complete, publish-ready posts. 900-1300 chars each. Use \\\\n for line breaks inside JSON strings (never raw newlines).
Post 1 = crisp professional insight (strong hook, 2-4 short paragraphs, clear takeaway).
Post 2 = conversational story angle (human opening, lesson, soft CTA).
Write like a sharp operator — confident, specific, not salesy. Short paragraphs. Minimal emojis (0-2 max).
BANNED: "In today's fast-paced world", game-changer, delve, landscape, leverage, "it's worth noting", "here's the thing", hashtag spam.
On scheduled runs use only facts from provided research — never invent stats. On custom topics use general industry knowledge only."""

b.call_openrouter(
    "OpenRouter Post Variants",
    POST_SYSTEM,
    '`Topic: ${ctx.selected_topic.title}\\nAngle: ${ctx.selected_topic.angle || ""}\\nMarket: ${ctx.selected_topic.best_market || "Global"}\\nSource: ${ctx.topic_source}\\nResearch answer: ${ctx.tavily_answer || "n/a"}\\nResearch results: ${JSON.stringify(ctx.tavily_results || [])}`',
    _pos("OpenRouter Post Variants"),
    model=OPENROUTER_MODEL_HEAVY,
    reasoning={"enabled": True, "effort": "medium"},
    max_tokens=8192,
)

b.add_node("Parse Post Variants", "n8n-nodes-base.code", {
    "jsCode": PARSE_OPENROUTER_JS + s3_common_js() + s3_linkedin_session_js() + """
const item = $input.first().json;
const data = parseOpenRouterJson(item, 'OpenRouter Post Variants');
const raw = data.variants || [];
if (raw.length < 2) throw new Error(`Expected 2 post variants, got ${raw.length}`);
const variants = raw.slice(0, 2).map((v, i) => ({
  id: i + 1,
  style: v.style || (i === 0 ? 'professional' : 'story'),
  text: String(v.text || '').trim(),
}));
if (!variants[0].text || !variants[1].text) throw new Error('Both post variants must have text.');
const session = {
  ...(item.linkedin_session || {}),
  stage: 'awaiting_variant_pick',
  variants,
  matched_image: item.matched_image,
  updated_at: new Date().toISOString(),
};
if (item.chat_id) await saveLinkedInSession.call(this, item.chat_id, session);
return [{ json: { ...item, variants, linkedin_session: session } }];"""
}, _pos("Parse Post Variants"), 2)

b.add_node("Download Post Image", "n8n-nodes-base.httpRequest", {
    "method": "GET",
    "url": "={{ $json.matched_image.reference_image_url }}",
    "options": {
        "response": {
            "response": {
                "responseFormat": "file",
                "outputPropertyName": "post_image",
            }
        },
        "timeout": 120000,
    },
}, _pos("Download Post Image"), 4.2)

b.add_node("Attach Image Binary", "n8n-nodes-base.code", {
    "jsCode": _restore_context_js("Parse Post Variants"),
}, _pos("Attach Image Binary"), 2)

b.add_node("Send Image Preview", "n8n-nodes-base.telegram", {
    "operation": "sendPhoto",
    "chatId": "={{ $json.chat_id }}",
    "binaryData": True,
    "binaryPropertyName": "post_image",
    "additionalFields": {
        "caption": "={{ '📌 ' + $json.selected_topic.title + '\\n\\nTwo post options coming next — reply 1 or 2 to publish.' }}",
        "appendAttribution": False,
    },
}, _pos("Send Image Preview"), 1.2, {"webhookId": WEBHOOK_IDS["Send Image Preview"]})

b.add_node("Restore Post Context", "n8n-nodes-base.code", {
    "jsCode": _restore_context_js("Parse Post Variants"),
}, _pos("Restore Post Context"), 2)

b.add_node("Send Post Option 1", "n8n-nodes-base.telegram", {
    "chatId": "={{ $json.chat_id }}",
    "text": "={{ '━━━ POST 1 (' + ($json.variants[0].style || 'option 1') + ') ━━━\\n\\n' + $json.variants[0].text }}",
    "additionalFields": {"appendAttribution": False},
}, _pos("Send Post Option 1"), 1.2)

b.add_node("Restore For Post 2", "n8n-nodes-base.code", {
    "jsCode": _restore_context_js("Parse Post Variants"),
}, _pos("Restore For Post 2"), 2)

b.add_node("Send Post Option 2", "n8n-nodes-base.telegram", {
    "chatId": "={{ $json.chat_id }}",
    "text": "={{ '━━━ POST 2 (' + ($json.variants[1].style || 'option 2') + ') ━━━\\n\\n' + $json.variants[1].text }}",
    "additionalFields": {"appendAttribution": False},
}, _pos("Send Post Option 2"), 1.2)

b.add_node("Restore For Wait", "n8n-nodes-base.code", {
    "jsCode": _restore_context_js("Parse Post Variants"),
}, _pos("Restore For Wait"), 2)

b.add_node("Wait For Variant Selection", "n8n-nodes-base.telegram", {
    "operation": "sendAndWait",
    "chatId": "={{ $json.chat_id }}",
    "message": "Which post should I publish to LinkedIn? Reply 1 or 2.",
    "responseType": "freeText",
    "options": {
        "appendAttribution": False,
        "limitWaitTime": {"values": {"limitWaitTime": 24, "limitWaitTimeUnit": "hours"}},
    },
}, _pos("Wait For Variant Selection"), 1.2, {"webhookId": WEBHOOK_IDS["Wait For Variant Selection"]})

b.add_node("Parse Variant Selection", "n8n-nodes-base.code", {
    "jsCode": READ_TELEGRAM_REPLY_JS + """
const prev = $('Parse Post Variants').first().json;
const raw = readTelegramReply($input.first()).toLowerCase();
if (!raw) throw new Error('No selection. Reply 1 or 2.');
const pick = parseInt((raw.match(/[12]/) || [])[0], 10);
if (!pick || pick < 1 || pick > 2) throw new Error(`Invalid selection "${raw}". Reply 1 or 2.`);
const v = (prev.variants || [])[pick - 1];
if (!v?.text) throw new Error(`Post ${pick} not found.`);
return [{ json: { ...prev, selected_picks: [pick], selected_variants: [{ ...v, pick }] } }];"""
}, _pos("Parse Variant Selection"), 2)

# ── LINKEDIN PUBLISH (v2 assets + ugcPosts — same as other_linkdien.json) ──
_li_org_urn = f"urn:li:organization:{LINKEDIN_ORG_ID or 'ORG_ID'}"
_li_person_urn = LINKEDIN_PERSON_URN or "urn:li:person:kg3LWhQv94"
_li_publish_as = (LINKEDIN_PUBLISH_AS or "organization").strip().lower()
_li_author_urn = _li_person_urn if _li_publish_as == "person" else _li_org_urn
_li_cred = LINKEDIN_CREDENTIAL_TYPE or "linkedInOAuth2Api"

_register_body = json.dumps({
    "registerUploadRequest": {
        "recipes": ["urn:li:digitalmediaRecipe:feedshare-image"],
        "owner": _li_author_urn,
        "serviceRelationships": [{
            "relationshipType": "OWNER",
            "identifier": "urn:li:userGeneratedContent",
        }],
    },
})

b.add_node("Prepare LinkedIn Post", "n8n-nodes-base.code", {
    "jsCode": """const ctx = $input.first().json;
const pick = (ctx.selected_variants || [])[0];
const linkedin_post = String(pick?.text || '').trim();
if (!linkedin_post) throw new Error('No LinkedIn post selected. Reply 1 or 2.');
return [{ json: {
  ...ctx,
  linkedin_post,
  selected_post_style: pick?.style || '',
  selected_pick: pick?.pick || 1,
  selected_topic_title: ctx.selected_topic?.title || '',
} }];"""
}, _pos("Prepare LinkedIn Post"), 2)

b.add_node("LinkedIn Register Upload", "n8n-nodes-base.httpRequest", {
    "method": "POST",
    "url": "https://api.linkedin.com/v2/assets?action=registerUpload",
    "authentication": "predefinedCredentialType",
    "nodeCredentialType": _li_cred,
    "sendHeaders": True,
    "headerParameters": {"parameters": [
        {"name": "X-Restli-Protocol-Version", "value": "2.0.0"},
        {"name": "Content-Type", "value": "application/json"},
    ]},
    "sendBody": True,
    "specifyBody": "json",
    "jsonBody": _register_body,
    "options": {},
}, _pos("LinkedIn Register Upload"), 4.2)

b.add_node("Parse Register Upload", "n8n-nodes-base.code", {
    "jsCode": """const prep = $('Prepare LinkedIn Post').first().json;
const r = $input.first().json;
const val = r.value || r;
const media_asset = val.asset || val.image || '';
const mech = (val.uploadMechanism || {})['com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest'] || {};
const upload_url = val.uploadUrl || mech.uploadUrl || val.uploadInstructions?.uploadUrl || '';
if (!media_asset || !upload_url) {
  throw new Error('registerUpload missing asset/uploadUrl: ' + JSON.stringify(r).slice(0, 300));
}
return [{ json: { ...prep, media_asset, upload_url } }];"""
}, _pos("Parse Register Upload"), 2)

b.add_node("Attach Post Image Binary", "n8n-nodes-base.code", {
    "jsCode": """const ctx = $('Parse Register Upload').first().json;
const bin = $('Attach Image Binary').first().binary;
if (!bin?.post_image) throw new Error('Missing post_image binary from S3 download.');
return [{ json: ctx, binary: { image: bin.post_image } }];"""
}, _pos("Attach Post Image Binary"), 2)

b.add_node("LinkedIn Upload Image", "n8n-nodes-base.httpRequest", {
    "method": "POST",
    "url": "={{ $json.upload_url }}",
    "authentication": "predefinedCredentialType",
    "nodeCredentialType": _li_cred,
    "sendBody": True,
    "contentType": "binaryData",
    "inputDataFieldName": "image",
    "options": {
        "response": {
            "response": {
                "fullResponse": True,
                "neverError": True,
            }
        },
    },
}, _pos("LinkedIn Upload Image"), 4.2)

b.add_node("Set Image Fields", "n8n-nodes-base.code", {
    "jsCode": """const pru = $('Parse Register Upload').first();
const j = { ...pru.json };
delete j.upload_url;
const prep = $('Prepare LinkedIn Post').first();
const bin = $('Attach Post Image Binary').first().binary;
if (!j.media_asset) throw new Error('No LinkedIn media asset after register upload.');
return [{ json: { ...prep.json, media_asset: j.media_asset }, binary: bin }];"""
}, _pos("Set Image Fields"), 2)

b.add_node("LinkedIn Publish", "n8n-nodes-base.httpRequest", {
    "method": "POST",
    "url": "https://api.linkedin.com/v2/ugcPosts",
    "authentication": "predefinedCredentialType",
    "nodeCredentialType": _li_cred,
    "sendHeaders": True,
    "headerParameters": {"parameters": [
        {"name": "X-Restli-Protocol-Version", "value": "2.0.0"},
        {"name": "Content-Type", "value": "application/json"},
    ]},
    "sendBody": True,
    "specifyBody": "json",
    "jsonBody": (
        f'={{{{ JSON.stringify({{ author: "{_li_author_urn}", lifecycleState: "PUBLISHED", '
        f'specificContent: {{ "com.linkedin.ugc.ShareContent": {{ shareCommentary: {{ text: $json.linkedin_post }}, '
        f'shareMediaCategory: "IMAGE", media: [{{ status: "READY", media: $json.media_asset, '
        f'title: {{ text: ($json.selected_topic_title || $json.selected_topic?.title || "").toString().slice(0,200) }} }}] }} }}, '
        f'visibility: {{ "com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC" }} }}) }}}}'
    ),
    "options": {
        "response": {
            "response": {
                "fullResponse": True,
                "neverError": True,
            }
        },
    },
}, _pos("LinkedIn Publish"), 4.2)

b.add_node("Set Published Status", "n8n-nodes-base.set", {
    "assignments": {
        "assignments": [
            {"name": "publication_status", "value": "published", "type": "string"},
            {
                "name": "linkedin_url",
                "value": "={{ $json.headers && $json.headers['x-restli-id'] ? 'https://www.linkedin.com/feed/update/' + $json.headers['x-restli-id'] : '' }}",
                "type": "string",
            },
            {
                "name": "share_urn",
                "value": "={{ $json.headers && $json.headers['x-restli-id'] ? $json.headers['x-restli-id'] : '' }}",
                "type": "string",
            },
            {"name": "timestamp", "value": "={{$now.toISO()}}", "type": "string"},
        ],
    },
    "options": {},
}, _pos("Set Published Status"), 3.4)

b.add_node("Summarize Publish Results", "n8n-nodes-base.code", {
    "jsCode": s3_common_js() + s3_linkedin_session_js() + """
const pub = $('Set Published Status').first().json;
const prep = $('Prepare LinkedIn Post').first().json;
const chat_id = prep.chat_id;
if (chat_id) await deleteLinkedInSession.call(this, chat_id);
const url = pub.linkedin_url || pub.share_urn || 'posted';
return [{ json: {
  chat_id,
  run_id: prep.run_id,
  linkedin_url: url,
  publication_status: pub.publication_status || 'published',
  reply_text: `LINKEDIN — Posted (option ${prep.selected_pick || 1})\\nRun: ${prep.run_id}\\nTopic: ${prep.selected_topic_title || prep.selected_topic?.title || ''}\\n${url}`,
} }];"""
}, _pos("Summarize Publish Results"), 2)

b.add_node("Send Publish Confirmation", "n8n-nodes-base.telegram", {
    "chatId": "={{ $json.chat_id }}",
    "text": "={{ $json.reply_text }}",
    "additionalFields": {"appendAttribution": False},
}, _pos("Send Publish Confirmation"), 1.2, {"webhookId": WEBHOOK_IDS["Send Publish Confirmation"]})

# ── STICKY NOTE ───────────────────────────────────────────
b.add_sticky(
    "Setup Notes",
    f"""## LinkedIn Post Automation Setup

**Separate from reels** — bot: [@linkdien_wendor_automation_bot](https://t.me/linkdien_wendor_automation_bot). Do NOT reuse the reels bot token.

### Telegram (LinkedIn bot only)
- Bot: `t.me/linkdien_wendor_automation_bot`
- n8n credential name: `Telegram LinkedIn Bot` (paste token from `TELEGRAM_LINKEDIN_BOT_TOKEN` in secrets)
- Commands: `/start`, `/linkedin`, `/lihelp`, `/licancel`
- staticData key: `linkedin_telegram_chat_id` (not reels `telegram_chat_id`)

### LinkedIn publish (v2 — matches other_linkdien.json)
- Publish as: **`{_li_publish_as}`** → author `{_li_author_urn}`
- Credential: `{LINKEDIN_CREDENTIAL_TYPE}` — **`jusmeen<> lakshit LinkedIn account`** works for **person** posts only (scope `w_member_social`)
- **Company page** (`organization`) needs `w_organization_social` → [Community Management App Review](https://learn.microsoft.com/en-us/linkedin/marketing/community-management-app-review) + credential **Organization Support ON** (or Community Management OAuth2)
- Set `LINKEDIN_PUBLISH_AS=organization` in secrets after approval; until then use `person`
- Nodes needing credential: **LinkedIn Register Upload**, **LinkedIn Upload Image**, **LinkedIn Publish**
- Register Upload: POST `v2/assets?action=registerUpload` + `registerUploadRequest` body (NOT rest/images, NOT PUT, NO LinkedIn-Version header)

### S3 brand images
- Folder: `{S3_IMAGES_PREFIX}` in bucket `{RAILWAY_S3_BUCKET}`
- Sessions: `linkedin-sessions/{{chat_id}}.json`
- Run archive: `linkedin-runs/{{run_id}}.json`

### Paths
- **Schedule** (weekdays 9 AM): Tavily → top 5 → pick 1-5 → generate → publish
- **Telegram** `/linkedin <topic>`: custom topic, no Tavily

### OpenRouter
- Fast (`{OPENROUTER_MODEL_FAST}`): topics, image match
- Heavy (`{OPENROUTER_MODEL_HEAVY}`): 2 publish-ready post options (pick 1 or 2)

### Deploy
```
python3 build/build_linkedin_workflow.py
N8N_WORKFLOW_FILE=automations/linkedin_post_automation.json N8N_WORKFLOW_ID=<id> python3 build/deploy_n8n.py
```""",
    [-220, 60],
    height=520,
    width=480,
)

# ── CONNECTIONS ─────────────────────────────────────────
# Schedule path
b.connect("Schedule Trigger", "Set Scheduled Context")
b.connect("Set Scheduled Context", "Tavily Search")
b.connect("Tavily Search", "Attach Run Context")
b.connect("Attach Run Context", "OpenRouter Top 5 Topics")
b.connect("OpenRouter Top 5 Topics", "Parse Top 5 Topics")
b.connect("Parse Top 5 Topics", "Send Topic Picker")
b.connect("Send Topic Picker", "Restore Topic Context")
b.connect("Restore Topic Context", "Wait For Topic Selection")
b.connect("Wait For Topic Selection", "Parse Topic Selection")
b.connect("Parse Topic Selection", "Merge Selected Topic")

# Telegram path
b.connect("Telegram Trigger", "Save LinkedIn Chat ID")
b.connect("Save LinkedIn Chat ID", "Classify LinkedIn Message")
b.connect("Classify LinkedIn Message", "IF LinkedIn Command")
b.connect("IF LinkedIn Command", "IF Lihelp", 0)
b.connect("IF Lihelp", "Send Lihelp", 0)
b.connect("IF Lihelp", "IF Licancel", 1)
b.connect("IF Licancel", "Handle Licancel", 0)
b.connect("Handle Licancel", "Send Licancel Reply")
b.connect("IF Licancel", "IF Start", 1)
b.connect("IF Start", "Send Start Reply", 0)
b.connect("IF Start", "Set Telegram Context", 1)
b.connect("Set Telegram Context", "Parse Custom Topic")
b.connect("Parse Custom Topic", "IF Needs Topic Wait")
b.connect("IF Needs Topic Wait", "Wait For Custom Topic", 0)
b.connect("Wait For Custom Topic", "Parse Custom Topic Reply")
b.connect("Parse Custom Topic Reply", "Merge Selected Topic")
b.connect("IF Needs Topic Wait", "Merge Selected Topic", 1)

# Shared pipeline
b.connect("Merge Selected Topic", "Load S3 Brand Images")
b.connect("Load S3 Brand Images", "OpenRouter Match Image")
b.connect("OpenRouter Match Image", "Parse Match Image")
b.connect("Parse Match Image", "OpenRouter Post Variants")
b.connect("OpenRouter Post Variants", "Parse Post Variants")
b.connect("Parse Post Variants", "Download Post Image")
b.connect("Download Post Image", "Attach Image Binary")
b.connect("Attach Image Binary", "Send Image Preview")
b.connect("Send Image Preview", "Restore Post Context")
b.connect("Restore Post Context", "Send Post Option 1")
b.connect("Send Post Option 1", "Restore For Post 2")
b.connect("Restore For Post 2", "Send Post Option 2")
b.connect("Send Post Option 2", "Restore For Wait")
b.connect("Restore For Wait", "Wait For Variant Selection")
b.connect("Wait For Variant Selection", "Parse Variant Selection")
b.connect("Parse Variant Selection", "Prepare LinkedIn Post")
b.connect("Prepare LinkedIn Post", "LinkedIn Register Upload")
b.connect("LinkedIn Register Upload", "Parse Register Upload")
b.connect("Parse Register Upload", "Attach Post Image Binary")
b.connect("Attach Post Image Binary", "LinkedIn Upload Image")
b.connect("LinkedIn Upload Image", "Set Image Fields")
b.connect("Set Image Fields", "LinkedIn Publish")
b.connect("LinkedIn Publish", "Set Published Status")
b.connect("Set Published Status", "Summarize Publish Results")
b.connect("Summarize Publish Results", "Send Publish Confirmation")

_finalize_workflow()
b.dump(LINKEDIN_WORKFLOW_NAME, LINKEDIN_WORKFLOW_JSON)
print(f"Done: {len(b.nodes)} nodes -> {LINKEDIN_WORKFLOW_JSON}")
