#!/usr/bin/env python3
"""Generate automations/mini_automation_for_reels.json."""
import json
import sys
import uuid
from pathlib import Path

BUILD_DIR = Path(__file__).resolve().parent
if str(BUILD_DIR) not in sys.path:
    sys.path.insert(0, str(BUILD_DIR))

from config import *  # noqa: F403
from paths import AUTOMATIONS_DIR, MAIN_WORKFLOW_JSON, MAIN_WORKFLOW_NAME

OPENROUTER_MODEL_FAST = "openai/gpt-5-mini"
OPENROUTER_MODEL_HEAVY = "anthropic/claude-sonnet-5"

S3_IMAGES_PREFIX = "images/"

# ── REEL TIMING ───────────────────────────────────────────
# See build/reel_timing.py — one grid, shared with the tests.
from reel_timing import (  # noqa: E402
    CLIP_COUNT,
    CLIP_SEC,
    TAIL_SEC,
    TOTAL_SEC,
    TRANSITION_SEC,
    USABLE_SEC,
    VOICEOVER_BITRATE,
    WORDS_MAX,
    WORDS_MIN,
    WORDS_PER_SEC,
)

# ── RAILWAY S3 BUCKET ─────────────────────────────────────
RAILWAY_S3_ENDPOINT_HOST = "t3.storageapi.dev"
RAILWAY_S3_REGION = "auto"
RAILWAY_S3_BUCKET = "lightweight-vault-pew0g4o"
RAILWAY_PRESIGN_EXPIRES = 604800  # 7 days


def s3_common_js():
    return f"""const te = new TextEncoder();
const ENDPOINT_HOST = {json.dumps(RAILWAY_S3_ENDPOINT_HOST)};
const BUCKET = {json.dumps(RAILWAY_S3_BUCKET)};
const REGION = {json.dumps(RAILWAY_S3_REGION)};
const ACCESS_KEY = {json.dumps(RAILWAY_S3_ACCESS_KEY)};
const SECRET_KEY = {json.dumps(RAILWAY_S3_SECRET_KEY)};
const EXPIRES = {RAILWAY_PRESIGN_EXPIRES};
const IMAGES_PREFIX = {json.dumps(S3_IMAGES_PREFIX)};

function toHex(bytes) {{
  return Array.from(bytes).map((b) => b.toString(16).padStart(2, '0')).join('');
}}
function toBytes(data) {{
  if (typeof data === 'string') return te.encode(data);
  if (data instanceof Uint8Array) return data;
  if (ArrayBuffer.isView(data)) return new Uint8Array(data.buffer, data.byteOffset, data.byteLength);
  return te.encode(String(data));
}}
function fromBase64(b64) {{
  const bin = atob(b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return bytes;
}}
function rotr(n, x) {{ return (x >>> n) | (x << (32 - n)); }}
const SHA_K = new Uint32Array([
  0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,
  0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,
  0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,
  0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,
  0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,
  0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,
  0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,
  0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2
]);
function sha256Raw(msgBytes) {{
  const l = msgBytes.length;
  const withLen = new Uint8Array(((l + 9 + 63) >> 6) << 6);
  withLen.set(msgBytes);
  withLen[l] = 0x80;
  const bitLen = l * 8;
  const dv = new DataView(withLen.buffer);
  dv.setUint32(withLen.length - 4, bitLen >>> 0, false);
  dv.setUint32(withLen.length - 8, Math.floor(bitLen / 0x100000000), false);
  let h0 = 0x6a09e667, h1 = 0xbb67ae85, h2 = 0x3c6ef372, h3 = 0xa54ff53a;
  let h4 = 0x510e527f, h5 = 0x9b05688c, h6 = 0x1f83d9ab, h7 = 0x5be0cd19;
  const w = new Uint32Array(64);
  for (let off = 0; off < withLen.length; off += 64) {{
    for (let i = 0; i < 16; i++) w[i] = dv.getUint32(off + i * 4, false);
    for (let i = 16; i < 64; i++) {{
      const s0 = rotr(7, w[i - 15]) ^ rotr(18, w[i - 15]) ^ (w[i - 15] >>> 3);
      const s1 = rotr(17, w[i - 2]) ^ rotr(19, w[i - 2]) ^ (w[i - 2] >>> 10);
      w[i] = (w[i - 16] + s0 + w[i - 7] + s1) >>> 0;
    }}
    let a = h0, b = h1, c = h2, d = h3, e = h4, f = h5, g = h6, hh = h7;
    for (let i = 0; i < 64; i++) {{
      const S1 = rotr(6, e) ^ rotr(11, e) ^ rotr(25, e);
      const ch = (e & f) ^ (~e & g);
      const t1 = (hh + S1 + ch + SHA_K[i] + w[i]) >>> 0;
      const S0 = rotr(2, a) ^ rotr(13, a) ^ rotr(22, a);
      const maj = (a & b) ^ (a & c) ^ (b & c);
      const t2 = (S0 + maj) >>> 0;
      hh = g; g = f; f = e; e = (d + t1) >>> 0; d = c; c = b; b = a; a = (t1 + t2) >>> 0;
    }}
    h0 = (h0 + a) >>> 0; h1 = (h1 + b) >>> 0; h2 = (h2 + c) >>> 0; h3 = (h3 + d) >>> 0;
    h4 = (h4 + e) >>> 0; h5 = (h5 + f) >>> 0; h6 = (h6 + g) >>> 0; h7 = (h7 + hh) >>> 0;
  }}
  const out = new Uint8Array(32);
  const outDv = new DataView(out.buffer);
  outDv.setUint32(0, h0, false); outDv.setUint32(4, h1, false); outDv.setUint32(8, h2, false); outDv.setUint32(12, h3, false);
  outDv.setUint32(16, h4, false); outDv.setUint32(20, h5, false); outDv.setUint32(24, h6, false); outDv.setUint32(28, h7, false);
  return out;
}}
function sha256(data) {{
  return toHex(sha256Raw(toBytes(data)));
}}
function hmacSha256(key, data) {{
  const block = 64;
  let k = toBytes(key);
  if (k.length > block) k = sha256Raw(k);
  if (k.length < block) {{
    const padded = new Uint8Array(block);
    padded.set(k);
    k = padded;
  }}
  const o = new Uint8Array(block);
  const i = new Uint8Array(block);
  for (let j = 0; j < block; j++) {{
    o[j] = k[j] ^ 0x5c;
    i[j] = k[j] ^ 0x36;
  }}
  const dataBytes = toBytes(data);
  const inner = new Uint8Array(block + dataBytes.length);
  inner.set(i);
  inner.set(dataBytes, block);
  const outer = new Uint8Array(block + 32);
  outer.set(o);
  outer.set(sha256Raw(inner), block);
  return sha256Raw(outer);
}}
function getSigningKey(dateStamp) {{
  const kDate = hmacSha256('AWS4' + SECRET_KEY, dateStamp);
  const kRegion = hmacSha256(kDate, REGION);
  const kService = hmacSha256(kRegion, 's3');
  return hmacSha256(kService, 'aws4_request');
}}
function encodePath(key) {{
  return key.split('/').map((part) => encodeURIComponent(part)).join('/');
}}
function hostName() {{
  return `${{BUCKET}}.${{ENDPOINT_HOST}}`;
}}
function readHttpText(res) {{
  if (res == null) return '';
  if (typeof res === 'string') return res;
  if (typeof res.body === 'string') return res.body;
  if (typeof res.data === 'string') return res.data;
  if (typeof Buffer !== 'undefined' && res.body && Buffer.isBuffer(res.body)) return res.body.toString('utf8');
  if (typeof Buffer !== 'undefined' && res.data && Buffer.isBuffer(res.data)) return res.data.toString('utf8');
  return '';
}}
async function s3Request(method, host, path, headers, body) {{
  const options = {{
    method,
    url: `https://${{host}}${{path}}`,
    headers: {{ ...headers, Accept: '*/*' }},
    json: false,
    encoding: 'text',
  }};
  const bytes = body && body.length ? toBytes(body) : null;
  if (bytes) options.body = typeof Buffer !== 'undefined' ? Buffer.from(bytes) : bytes;
  try {{
    const res = await this.helpers.httpRequest(options);
    return readHttpText(res);
  }} catch (err) {{
    const status = err.statusCode || err.response?.statusCode || '';
    throw new Error(`S3 ${{method}} ${{status}}: ${{err.message || err}}`);
  }}
}}
function describeS3Error(err) {{
  const status = err.statusCode || err.response?.statusCode || err.httpCode || err.status || '';
  const body = err.response?.body ?? err.response?.data ?? err.cause?.response?.body ?? err.body;
  if (typeof body === 'string' && body.trim()) return `HTTP ${{status}}: ${{body.slice(0, 500)}}`;
  if (body && typeof body === 'object') {{
    if (typeof Buffer !== 'undefined' && Buffer.isBuffer(body)) return `HTTP ${{status}}: ${{body.toString('utf8').slice(0, 500)}}`;
    try {{ return `HTTP ${{status}}: ${{JSON.stringify(body).slice(0, 500)}}`; }} catch {{}}
  }}
  return `HTTP ${{status || 'error'}}: ${{err.message || err}}`;
}}
async function putObject(key, body, contentType = 'application/octet-stream') {{
  const bytes = toBytes(body);
  const uploadUrl = presignPutUrl(key);
  try {{
    await this.helpers.httpRequest({{
      method: 'PUT',
      url: uploadUrl,
      headers: {{
        'Content-Type': contentType,
      }},
      body: typeof Buffer !== 'undefined' ? Buffer.from(bytes) : bytes,
      json: false,
    }});
  }} catch (err) {{
    throw new Error(`S3 PUT ${{describeS3Error(err)}}`);
  }}
}}
function presignGetUrl(key) {{
  const now = new Date();
  const amzDate = now.toISOString().replace(/[:-]|\\.\\d{{3}}/g, '');
  const dateStamp = amzDate.slice(0, 8);
  const host = hostName();
  const credential = `${{ACCESS_KEY}}/${{dateStamp}}/${{REGION}}/s3/aws4_request`;
  const params = {{
    'X-Amz-Algorithm': 'AWS4-HMAC-SHA256',
    'X-Amz-Credential': credential,
    'X-Amz-Date': amzDate,
    'X-Amz-Expires': String(EXPIRES),
    'X-Amz-SignedHeaders': 'host',
  }};
  const query = Object.keys(params).sort().map((k) => `${{encodeURIComponent(k)}}=${{encodeURIComponent(params[k])}}`).join('&');
  const canonicalRequest = ['GET', '/' + encodePath(key), query, `host:${{host}}\\n`, 'host', 'UNSIGNED-PAYLOAD'].join('\\n');
  const credentialScope = `${{dateStamp}}/${{REGION}}/s3/aws4_request`;
  const stringToSign = ['AWS4-HMAC-SHA256', amzDate, credentialScope, sha256(canonicalRequest)].join('\\n');
  const signature = toHex(hmacSha256(getSigningKey(dateStamp), stringToSign));
  return `https://${{host}}/${{encodePath(key)}}?${{query}}&X-Amz-Signature=${{signature}}`;
}}
function presignPutUrl(key) {{
  const now = new Date();
  const amzDate = now.toISOString().replace(/[:-]|\\.\\d{{3}}/g, '');
  const dateStamp = amzDate.slice(0, 8);
  const host = hostName();
  const credential = `${{ACCESS_KEY}}/${{dateStamp}}/${{REGION}}/s3/aws4_request`;
  const params = {{
    'X-Amz-Algorithm': 'AWS4-HMAC-SHA256',
    'X-Amz-Credential': credential,
    'X-Amz-Date': amzDate,
    'X-Amz-Expires': String(EXPIRES),
    'X-Amz-SignedHeaders': 'host',
  }};
  const query = Object.keys(params).sort().map((k) => `${{encodeURIComponent(k)}}=${{encodeURIComponent(params[k])}}`).join('&');
  const canonicalRequest = ['PUT', '/' + encodePath(key), query, `host:${{host}}\\n`, 'host', 'UNSIGNED-PAYLOAD'].join('\\n');
  const credentialScope = `${{dateStamp}}/${{REGION}}/s3/aws4_request`;
  const stringToSign = ['AWS4-HMAC-SHA256', amzDate, credentialScope, sha256(canonicalRequest)].join('\\n');
  const signature = toHex(hmacSha256(getSigningKey(dateStamp), stringToSign));
  return `https://${{host}}/${{encodePath(key)}}?${{query}}&X-Amz-Signature=${{signature}}`;
}}
function signGet(key) {{
  const now = new Date();
  const amzDate = now.toISOString().replace(/[:-]|\\.\\d{{3}}/g, '');
  const dateStamp = amzDate.slice(0, 8);
  const host = hostName();
  const payloadHash = sha256('');
  const headerMap = {{
    host,
    'x-amz-content-sha256': payloadHash,
    'x-amz-date': amzDate,
  }};
  const signedNames = Object.keys(headerMap).sort();
  const canonicalHeaders = signedNames.map((name) => `${{name}}:${{headerMap[name]}}\\n`).join('');
  const signedHeaders = signedNames.join(';');
  const canonicalRequest = ['GET', '/' + encodePath(key), '', canonicalHeaders, signedHeaders, payloadHash].join('\\n');
  const credentialScope = `${{dateStamp}}/${{REGION}}/s3/aws4_request`;
  const stringToSign = ['AWS4-HMAC-SHA256', amzDate, credentialScope, sha256(canonicalRequest)].join('\\n');
  const signature = toHex(hmacSha256(getSigningKey(dateStamp), stringToSign));
  const authorization = `AWS4-HMAC-SHA256 Credential=${{ACCESS_KEY}}/${{credentialScope}}, SignedHeaders=${{signedHeaders}}, Signature=${{signature}}`;
  return {{ host, authorization, amzDate, payloadHash }};
}}
async function getObject(key) {{
  const {{ host, authorization, amzDate, payloadHash }} = signGet(key);
  const path = `/${{encodePath(key)}}`;
  try {{
    return await s3Request.call(this, 'GET', host, path, {{
      'x-amz-content-sha256': payloadHash,
      'x-amz-date': amzDate,
      Authorization: authorization,
    }});
  }} catch (err) {{
    throw new Error(`S3 GET ${{describeS3Error(err)}}`);
  }}
}}
function signList(prefix) {{
  const now = new Date();
  const amzDate = now.toISOString().replace(/[:-]|\\.\\d{{3}}/g, '');
  const dateStamp = amzDate.slice(0, 8);
  const host = hostName();
  const queryParams = {{ 'list-type': '2', prefix }};
  const canonicalQuery = Object.keys(queryParams).sort().map((k) => `${{encodeURIComponent(k)}}=${{encodeURIComponent(queryParams[k])}}`).join('&');
  const payloadHash = sha256('');
  const canonicalHeaders = `host:${{host}}\\nx-amz-content-sha256:${{payloadHash}}\\nx-amz-date:${{amzDate}}\\n`;
  const signedHeaders = 'host;x-amz-content-sha256;x-amz-date';
  const canonicalRequest = ['GET', '/', canonicalQuery, canonicalHeaders, signedHeaders, payloadHash].join('\\n');
  const credentialScope = `${{dateStamp}}/${{REGION}}/s3/aws4_request`;
  const stringToSign = ['AWS4-HMAC-SHA256', amzDate, credentialScope, sha256(canonicalRequest)].join('\\n');
  const signature = toHex(hmacSha256(getSigningKey(dateStamp), stringToSign));
  const authorization = `AWS4-HMAC-SHA256 Credential=${{ACCESS_KEY}}/${{credentialScope}}, SignedHeaders=${{signedHeaders}}, Signature=${{signature}}`;
  return {{ host, authorization, amzDate, payloadHash, canonicalQuery }};
}}
async function listObjects(prefix) {{
  const {{ host, authorization, amzDate, payloadHash, canonicalQuery }} = signList(prefix);
  const xml = await s3Request.call(this, 'GET', host, `/?${{canonicalQuery}}`, {{
    'x-amz-content-sha256': payloadHash,
    'x-amz-date': amzDate,
    Authorization: authorization,
  }});
  return [...xml.matchAll(/<Key>([^<]+)<\\/Key>/g)].map((m) => m[1]);
}}
"""


# Only the image-listing node needs these; keeping them out of every other node
# keeps the Code panels readable in the n8n editor.
S3_IMAGES_JS = """
function fileNameToLabel(fileName) {
  const base = fileName.replace(/\\.[^.]+$/, '');
  return base.replace(/[-_]+/g, ' ').replace(/\\s+/g, ' ').trim();
}
function isImageKey(key) {
  return /\\.(jpe?g|png|webp|gif)$/i.test(key);
}"""


# Compose sessions live in S3 so they survive across separate n8n executions
# (each Telegram message is its own execution).
S3_SESSION_JS = """
function composeSessionKey(chatId) {
  return `reels-compose-sessions/${chatId}.json`;
}
async function loadComposeSession(chatId) {
  try {
    const text = await getObject.call(this, composeSessionKey(chatId));
    if (!text || !text.trim()) return null;
    const session = JSON.parse(text);
    if (!session?.run_id || session.deleted) return null;
    return session;
  } catch {
    return null;
  }
}
async function saveComposeSession(chatId, session) {
  await putObject.call(this, composeSessionKey(chatId), JSON.stringify(session), 'application/json');
}
async function deleteComposeSession(chatId) {
  await saveComposeSession.call(this, chatId, { deleted: true, deleted_at: Date.now() });
}
// Late-arriving uploads from a Telegram album run as parallel executions, so a
// plain overwrite loses clips. Re-read and merge by index right before saving.
async function mergeClipIntoSession(chatId, fallback, clip) {
  const session = (await loadComposeSession.call(this, chatId)) || fallback;
  session.clips = (session.clips || []).filter((c) => Number(c.index) !== Number(clip.index));
  session.clips.push(clip);
  session.clips.sort((a, b) => a.index - b.index);
  await saveComposeSession.call(this, chatId, session);
  return session;
}"""


def s3_session_js():
    """S3 primitives + compose-session helpers."""
    return s3_common_js() + S3_SESSION_JS


# One naming convention, used in both directions: brand reference images are
# read as partN/clipN, and Flow clips come back named clipN. Returns 1-5 or 0.
CLIP_INDEX_FROM_NAME_JS = """
function clipIndexFromName(name) {
  const s = String(name || '').toLowerCase();
  const tagged = s.match(/(?:^|[^a-z])(?:part|clip|scene|shot)[-_ ]?([1-5])(?![0-9])/);
  if (tagged) return Number(tagged[1]);
  const trailing = s.replace(/\\.[a-z0-9]+$/, '').match(/([1-5])$/);
  if (trailing) return Number(trailing[1]);
  return 0;
}"""


def compose_clip_upload_js():
    return s3_session_js() + CLIP_INDEX_FROM_NAME_JS + """
const chatId = $json.chat_id || String($json.message?.chat?.id || '');
if (!chatId) throw new Error('Missing chat_id on clip upload.');

let session = await loadComposeSession.call(this, chatId);
if (!session || session.state !== 'collecting') {
  return [{ json: { chat_id: chatId, reply_text: 'No active compose session. Send /compose RUN_ID first.' } }];
}
if (Date.now() > session.expires_at) {
  await deleteComposeSession.call(this, chatId);
  return [{ json: { chat_id: chatId, reply_text: 'That compose session expired. Send /compose RUN_ID again — your clips are still on S3.' } }];
}

const msg = $json.message || {};
const messageId = String(msg.message_id || $json.file_id || Date.now());
session.processed_messages = session.processed_messages || {};
if (session.processed_messages[messageId]) {
  const existing = session.processed_messages[messageId];
  return [{ json: { chat_id: chatId, reply_text: `Clip ${existing}/5 already saved for this message.` } }];
}

const binary = $input.first().binary || {};
const binKey = Object.keys(binary).find((k) => /video/i.test(String(binary[k]?.mimeType || '')))
  || Object.keys(binary)[0];
if (!binKey) {
  throw new Error('No video binary on message. Turn Download ON in the Telegram Trigger node.');
}

const raw = binary[binKey];
let bytes;
if (typeof raw.data === 'string') bytes = fromBase64(raw.data);
else if (raw.data?.type === 'Buffer') bytes = Uint8Array.from(raw.data.data);
else if (raw.data instanceof Uint8Array) bytes = raw.data;
else throw new Error('Unexpected binary format from Telegram');

// Order source #1 — the filename. Deterministic and race-free, which is why the
// package message asks for clip1.mp4 … clip5.mp4.
const fileName = String($json.clip_file_name || raw.fileName || '');
let index = clipIndexFromName(fileName);
let index_source = index ? 'filename' : '';

// #2 — an explicit "3" or "clip 3" caption on the upload.
if (!index && $json.caption_index) {
  index = Number($json.caption_index);
  index_source = 'caption';
}

// #3 — position within a Telegram album. Albums arrive as parallel executions,
// so agree on an order via the shared session rather than arrival time.
const mediaGroupId = msg.media_group_id ? String(msg.media_group_id) : null;
if (!index && mediaGroupId) {
  session.media_groups = session.media_groups || {};
  let group = session.media_groups[mediaGroupId] || { message_ids: [] };
  if (!group.message_ids.includes(messageId)) {
    group.message_ids.push(messageId);
    group.message_ids.sort((a, b) => Number(a) - Number(b));
  }
  session.media_groups[mediaGroupId] = group;
  await saveComposeSession.call(this, chatId, session);
  await new Promise((r) => setTimeout(r, 1500));
  session = (await loadComposeSession.call(this, chatId)) || session;
  group = session.media_groups?.[mediaGroupId] || group;
  const groupIndex = group.message_ids.indexOf(messageId) + 1;
  if (groupIndex >= 1 && groupIndex <= 5) {
    index = groupIndex;
    index_source = 'album order';
  }
}

// #4 — first free slot.
const reserved = new Set(Object.values(session.processed_messages || {}).map(Number));
for (const c of session.clips || []) reserved.add(Number(c.index));

if (!index || index < 1 || index > 5 || reserved.has(index)) {
  const wanted = index;
  index = 0;
  for (let i = 1; i <= 5; i++) {
    if (!reserved.has(i)) { index = i; break; }
  }
  index_source = wanted ? `slot ${wanted} taken, used next free` : 'next free slot';
}
if (!index) {
  return [{ json: { chat_id: chatId, reply_text: 'All 5 clip slots are filled. Send done to render, or /cancel to start over.' } }];
}

session.processed_messages[messageId] = index;
session.clips = (session.clips || []).filter((c) => Number(c.index) !== index);
session.clips.push({ index, pending: true, message_id: messageId, reserved_at: Date.now() });
session.clips.sort((a, b) => a.index - b.index);
await saveComposeSession.call(this, chatId, session);

const runId = session.run_id;
const s3Key = `reels-clips/${runId}/clip-${String(index).padStart(2, '0')}.mp4`;
await putObject.call(this, s3Key, bytes, 'video/mp4');
const url = presignGetUrl(s3Key);

session = await mergeClipIntoSession.call(this, chatId, session, {
  index,
  s3_key: s3Key,
  url,
  file_name: fileName || null,
  index_source,
  message_id: messageId,
  uploaded_at: Date.now(),
});

const have = new Set((session.clips || []).filter((c) => c.url).map((c) => Number(c.index)));
const missing = [1, 2, 3, 4, 5].filter((i) => !have.has(i));
const tail = missing.length
  ? `Still need: ${missing.map((i) => `clip${i}.mp4`).join(', ')}`
  : 'All 5 in — send done to render.';
return [{
  json: {
    chat_id: chatId,
    reply_text: `Clip ${index}/5 saved from ${index_source} (${have.size}/5).\\n${tail}`,
  },
}];
"""


LOAD_S3_BRAND_IMAGES_JS = s3_common_js() + S3_IMAGES_JS + """
const ctx = $('Normalize Script Timing').first().json;
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
    images_folder_ready: true,
    images_folder_note: `Upload context-named images to s3://${BUCKET}/${IMAGES_PREFIX} (e.g. part1-hook-breakroom-wide.jpg, part2-setup-restock.jpg, part3-proof-touchscreen.jpg, part4-emotion-lobby.jpg, part5-cta-customer-selecting.jpg)`
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
  images_folder_ready: true,
  images_count: brand_files.length
} }];"""

TTS_FILE_RESPONSE_OPTS = {
    "response": {
        "response": {
            "responseFormat": "file",
            "outputPropertyName": "voiceover",
        }
    },
    "timeout": 120000,
}

S3_PUT_RESPONSE_OPTS = {
    "response": {
        "response": {
            "responseFormat": "text",
            "fullResponse": False,
        },
    },
}

PREPARE_VOICEOVER_JS = """
const item = $input.first().json;
const text = String(item.script?.full_script || '').trim();
if (!text) throw new Error('Missing full_script in script package');
const ELEVEN_VOICE_MAP = {
  rachel: '21m00Tcm4TlvDq8ikWAM',
  adam: 'pNInz6obpgDQGcFmaJgB',
  josh: 'TxGEqnHWrfWFTfGW9XjX',
  bella: 'EXAVITQu4vr4xnSDxMaL',
  antoni: 'ErXwobaYiN019PkySvjV',
};
const DEFAULT_ELEVEN_VOICE_ID = '21m00Tcm4TlvDq8ikWAM';
function resolveElevenVoiceId(raw) {
  const v = String(raw || '').trim();
  if (!v) return DEFAULT_ELEVEN_VOICE_ID;
  if (/^[A-Za-z0-9]{20,}$/.test(v)) return v;
  const nameKey = v.toLowerCase().replace(/[^a-z]/g, '');
  for (const [name, id] of Object.entries(ELEVEN_VOICE_MAP)) {
    if (nameKey.includes(name)) return id;
  }
  return DEFAULT_ELEVEN_VOICE_ID;
}
return [{
  json: {
    ...item,
    _eleven_voice_id: resolveElevenVoiceId(item.script?.elevenlabs_voice_id),
    _voiceover_text: text,
  },
}];
"""

# Task runner cannot PUT binary via Code node (getBinaryDataBuffer / httpRequest → "Unknown error").
PREPARE_S3_UPLOAD_JS = s3_common_js() + """
const ctx = $('Prepare Voiceover').first().json;
const bin = $input.first().binary?.voiceover;
if (!bin?.fileName) {
  throw new Error('Voiceover MP3 missing. Check Cartesia/ElevenLabs HTTP nodes and API keys.');
}

let tts_provider = 'cartesia';
try {
  const cartesiaBin = $('Cartesia TTS').first()?.binary?.voiceover;
  if (!cartesiaBin?.fileName) {
    tts_provider = 'elevenlabs';
  }
} catch {
  tts_provider = 'elevenlabs';
}

const key = `reels-voiceovers/${ctx.topic_slug}-${ctx.run_id}.mp3`;
const upload_url = presignPutUrl(key);

return [{
  json: {
    ...ctx,
    voiceover_key: key,
    upload_url,
    storage_bucket: BUCKET,
    tts_provider,
  },
  binary: $input.first().binary,
}];
"""

FINALIZE_VOICEOVER_JS = s3_common_js() + """
const prep = $('Prepare S3 Upload').first().json;
const voiceover_url = presignGetUrl(prep.voiceover_key);
const bin = $('Prepare S3 Upload').first().binary?.voiceover;

// Byte count is what tells Build Sync Map how long the voiceover actually runs,
// so read it from the buffer when it is in memory and fall back to n8n's
// human-readable size only when it is not.
function parseFileSize(s) {
  const m = String(s || '').match(/([\\d.]+)\\s*(GB|MB|kB|B)/i);
  if (!m) return 0;
  const n = parseFloat(m[1]);
  const unit = m[2].toLowerCase();
  if (unit === 'gb') return Math.round(n * 1024 * 1024 * 1024);
  if (unit === 'mb') return Math.round(n * 1024 * 1024);
  if (unit === 'kb') return Math.round(n * 1024);
  return Math.round(n);
}

let voiceover_bytes = 0;
const data = bin?.data;
if (typeof data === 'string') voiceover_bytes = Math.floor((data.length * 3) / 4);
else if (data?.type === 'Buffer' && Array.isArray(data.data)) voiceover_bytes = data.data.length;
if (!voiceover_bytes) voiceover_bytes = parseFileSize(bin?.fileSize);

return [{
  json: {
    ...prep,
    voiceover_url,
    voiceover_bytes,
  },
}];
"""

nodes = []
connections = {}


def nid():
    return str(uuid.uuid4())


DX = 360

NODE_POSITIONS = {
    "Setup Notes": [-300, 40],
    # Schedule entry
    "Schedule Trigger": [0, 120],
    "Set Scheduled Context": [DX, 120],
    # Telegram entry
    "Telegram Trigger": [0, 360],
    "Save Telegram Chat ID": [DX, 360],
    "Route Compose vs Generate": [DX * 2, 360],
    "IF Compose Route": [DX * 3, 360],
    "IF Delegate Compose": [DX * 4, 360],
    # Manual /generate path
    "Parse Generate Command": [DX * 4, 600],
    "IF Is Generate Command": [DX * 5, 600],
    "Set Manual Context": [DX * 6, 600],
    "IF Custom Topic": [DX * 7, 600],
    "Set Custom Topic": [DX * 8, 500],
    # Compose — clip upload
    "Classify Compose Message": [DX * 5, 180],
    "IF Clip Upload": [DX * 6, 180],
    "Handle Clip Upload WF1": [DX * 7, 180],
    "Reply Compose": [DX * 8, 180],
    # Compose — session control
    "IF Compose Start": [DX * 5, 0],
    "Handle Compose Start": [DX * 6, 0],
    "IF Status Cancel": [DX * 5, -180],
    "Handle Status Cancel": [DX * 6, -180],
    # Compose — render pipeline
    "IF Done": [DX * 5, 540],
    "OpenRouter Render Director": [DX * 6, 540],
    "Start Render": [DX * 7, 540],
    "Wait For Render": [DX * 8, 540],
    "Poll Render Job": [DX * 9, 540],
    "IF Poll Again": [DX * 10, 540],
    # Research + topic pick
    "Tavily Search": [DX, 840],
    "Attach Run Context": [DX * 2, 840],
    "OpenRouter Top 5 Topics": [DX * 3, 840],
    "Parse Top 5 Topics": [DX * 4, 840],
    "IF Preselected Rank": [DX * 5, 840],
    "Select Topic By Rank": [DX * 6, 740],
    "Wait For Topic Selection": [DX * 6, 940],
    "Parse Topic Selection": [DX * 7, 940],
    # Main generate pipeline
    "OpenRouter Script Package": [DX * 8, 840],
    "Parse Script Package": [DX * 9, 840],
    "Normalize Script Timing": [DX * 10, 840],
    "Load S3 Brand Images": [DX * 11, 840],
    "OpenRouter Match Images": [DX * 12, 840],
    "Parse Match Images": [DX * 13, 840],
    "Prepare Voiceover": [DX * 14, 840],
    "Cartesia TTS": [DX * 15, 840],
    "IF Cartesia OK": [DX * 16, 840],
    "ElevenLabs TTS": [DX * 16, 1040],
    "Prepare S3 Upload": [DX * 17, 840],
    "S3 PUT Voiceover": [DX * 18, 840],
    "S3 PUT Voiceover OK": [DX * 19, 840],
    "Finalize Voiceover": [DX * 20, 840],
    "Build Sync Map": [DX * 21, 840],
    "OpenRouter Flow Prompts": [DX * 22, 840],
    "Parse Flow Prompts": [DX * 23, 840],
    "Upload Manifest to S3": [DX * 24, 840],
    "Format Final Package": [DX * 25, 840],
    "Send Final Package": [DX * 26, 840],
}


def _pos(name):
    if name not in NODE_POSITIONS:
        raise KeyError(f"Missing NODE_POSITIONS entry for {name!r}")
    return NODE_POSITIONS[name]


def add_node(name, node_type, params, type_version=1, extra=None):
    node = {
        "parameters": params,
        "type": node_type,
        "typeVersion": type_version,
        "position": _pos(name),
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


def connect_in(src, dst, merge_in_index=0, out_index=0):
    """Connect src → dst on merge input 0 or 1."""
    connect(src, dst, out_index, merge_in_index)


# TRIGGERS
add_node("Schedule Trigger", "n8n-nodes-base.scheduleTrigger", {
    "rule": {"interval": [{"field": "cronExpression", "expression": "0 9 * * *"}]}
}, 1.2)

add_node("Telegram Trigger", "n8n-nodes-base.telegramTrigger", {
    "updates": ["message"],
    "additionalFields": {"download": True},
}, 1.2, {"webhookId": nid()})

add_node("Save Telegram Chat ID", "n8n-nodes-base.code", {
    "jsCode": """const staticData = $getWorkflowStaticData('global');
const from = $json.message?.from;
const chat = $json.message?.chat;
if (from?.is_bot) {
  throw new Error('That message came from a bot account. Open Telegram as yourself and message your bot with /start.');
}
if (chat?.type === 'private' && chat.id) {
  staticData.telegram_chat_id = String(chat.id);
}
return [{ json: $json, binary: $input.first().binary }];"""
}, 2)

# Single source of truth for "what did the user just send?", shared by the
# router and the classifier so the two can never disagree about a message.
COMPOSE_ACTION_JS = """
function classifyComposeMessage(rawMessage) {
  const msg = rawMessage || {};
  const text = String(msg.text || msg.caption || '').trim();
  const video = msg.video;
  const doc = msg.document;
  const isVideoDoc = doc && /^video\\//i.test(String(doc.mime_type || ''));
  const isClip = !!(video || isVideoDoc);

  let compose_action = 'ignore';
  if (/^\\/compose\\b/i.test(text)) compose_action = 'compose_start';
  else if (/^done$/i.test(text)) compose_action = 'done';
  else if (/^\\/cancel$/i.test(text)) compose_action = 'cancel';
  else if (/^\\/status$/i.test(text)) compose_action = 'status';
  else if (/^\\/help$/i.test(text)) compose_action = 'help';
  else if (isClip) compose_action = 'clip_upload';

  const runIdMatch = text.match(/^\\/compose\\s+(\\S+)/i);
  const captionIndex = text.match(/^(?:clip\\s*)?([1-5])\\s*$/i) || text.match(/^([1-5])\\s*\\/\\s*5$/);

  return {
    compose_action,
    is_compose_route: compose_action !== 'ignore',
    chat_id: String(msg.chat?.id || ''),
    text,
    run_id: runIdMatch ? runIdMatch[1].trim() : null,
    caption_index: captionIndex ? Number(captionIndex[1]) : null,
    clip_file_name: String(doc?.file_name || video?.file_name || ''),
    message: msg,
  };
}"""

ROUTE_COMPOSE_JS = COMPOSE_ACTION_JS + """
const { is_compose_route } = classifyComposeMessage($json.message);

return [{
  json: { ...$json, is_compose_route },
  binary: $input.first().binary,
}];
"""

add_node("Route Compose vs Generate", "n8n-nodes-base.code", {
    "jsCode": ROUTE_COMPOSE_JS,
}, 2)

add_node("IF Compose Route", "n8n-nodes-base.if", {
    "conditions": {
        "options": {"caseSensitive": True, "leftValue": "", "typeValidation": "loose", "version": 2},
        "conditions": [
            {"id": nid(), "leftValue": "={{ $json.is_compose_route }}", "rightValue": True, "operator": {"type": "boolean", "operation": "true"}},
        ],
        "combinator": "and",
    },
    "looseTypeValidation": True, "options": {},
}, 2.2)

CLASSIFY_COMPOSE_JS = COMPOSE_ACTION_JS + """
const parsed = classifyComposeMessage($json.message);

return [{
  json: {
    ...$json,
    compose_action: parsed.compose_action,
    chat_id: parsed.chat_id,
    run_id: parsed.run_id,
    caption_index: parsed.caption_index,
    clip_file_name: parsed.clip_file_name,
    message: parsed.message,
  },
  binary: $input.first().binary,
}];
"""

add_node("Classify Compose Message", "n8n-nodes-base.code", {
    "jsCode": CLASSIFY_COMPOSE_JS,
}, 2)

add_node("IF Clip Upload", "n8n-nodes-base.if", {
    "conditions": {
        "options": {"caseSensitive": True, "leftValue": "", "typeValidation": "loose", "version": 2},
        "conditions": [
            {"id": nid(), "leftValue": "={{ $json.compose_action }}", "rightValue": "clip_upload", "operator": {"type": "string", "operation": "equals"}},
        ],
        "combinator": "and",
    },
    "looseTypeValidation": True, "options": {},
}, 2.2)

add_node("Handle Clip Upload WF1", "n8n-nodes-base.code", {
    "jsCode": compose_clip_upload_js(),
}, 2)

add_node("Reply Compose", "n8n-nodes-base.telegram", {
    "chatId": "={{ $json.chat_id }}",
    "text": "={{ $json.reply_text }}",
    "additionalFields": {"appendAttribution": False, "parse_mode": "HTML"},
}, 1.2, {"webhookId": nid()})

add_node("IF Delegate Compose", "n8n-nodes-base.if", {
    "conditions": {
        "options": {"caseSensitive": True, "leftValue": "", "typeValidation": "loose", "version": 2},
        "conditions": [
            {"id": nid(), "leftValue": "={{ $json.compose_action }}", "rightValue": action, "operator": {"type": "string", "operation": "equals"}}
            for action in ("compose_start", "done", "status", "cancel", "help")
        ],
        "combinator": "or",
    },
    "looseTypeValidation": True, "options": {},
}, 2.2)

add_node("Parse Generate Command", "n8n-nodes-base.code", {
    "jsCode": """const text = String($json.message?.text || '').trim();
const is_generate_command = /^\\/generate\\b/i.test(text)
  || /^\\/topics\\b/i.test(text)
  || /^generate\\b/i.test(text);
const topicMatch = text.match(/^\\/(?:generate|topics)\\s+(.+)/is);
const topicArg = topicMatch ? topicMatch[1].trim() : '';
let topic_mode = 'picker';
let custom_topic = '';
let topic_rank = null;
if (/^[1-5]$/.test(topicArg)) {
  topic_mode = 'rank';
  topic_rank = parseInt(topicArg, 10);
} else if (topicArg) {
  topic_mode = 'custom';
  custom_topic = topicArg;
}
return [{
  json: {
    ...$json,
    is_generate_command,
    topic_mode,
    custom_topic,
    topic_rank,
    skip_topic_picker: topic_mode !== 'picker',
  },
}];"""
}, 2)

add_node("IF Is Generate Command", "n8n-nodes-base.if", {
    "conditions": {
        "options": {"caseSensitive": True, "leftValue": "", "typeValidation": "loose", "version": 2},
        "conditions": [
            {"id": nid(), "leftValue": "={{ $json.is_generate_command }}", "rightValue": True, "operator": {"type": "boolean", "operation": "true"}},
        ],
        "combinator": "and",
    },
    "looseTypeValidation": True, "options": {},
}, 2.2)

RUN_ID_JS = """const d = new Date();
const p = (n) => String(n).padStart(2, '0');
const run_id = `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}-${p(d.getHours())}${p(d.getMinutes())}`;"""

add_node("Set Manual Context", "n8n-nodes-base.code", {
    "jsCode": RUN_ID_JS + """
const staticData = $getWorkflowStaticData('global');
const chat_id = String($json.message.chat.id);
staticData.telegram_chat_id = chat_id;
const topic_mode = $json.topic_mode || 'picker';
const custom_topic = String($json.custom_topic || '').trim();
const topic_rank = $json.topic_rank || null;
return [{ json: {
  chat_id,
  trigger_mode: 'manual',
  run_id,
  topic_mode,
  custom_topic,
  topic_rank,
  skip_topic_picker: topic_mode !== 'picker',
  topic_source: topic_mode === 'custom' ? 'telegram_custom' : (topic_mode === 'rank' ? 'telegram_rank' : 'tavily_picker'),
} }];"""
}, 2)

add_node("IF Custom Topic", "n8n-nodes-base.if", {
    "conditions": {
        "options": {"caseSensitive": True, "leftValue": "", "typeValidation": "loose", "version": 2},
        "conditions": [
            {"id": nid(), "leftValue": "={{ $json.topic_mode }}", "rightValue": "custom", "operator": {"type": "string", "operation": "equals"}},
        ],
        "combinator": "and",
    },
    "looseTypeValidation": True, "options": {},
}, 2.2)

add_node("Set Custom Topic", "n8n-nodes-base.code", {
    "jsCode": """const ctx = $input.first().json;
const title = String(ctx.custom_topic || '').trim();
if (!title) throw new Error('Missing custom topic after /generate.');
const slug = title.toLowerCase().replace(/[^a-z0-9]+/g, '-').slice(0, 40);
return [{ json: {
  ...ctx,
  selected_topic: {
    title,
    hook: title.slice(0, 120),
    why_viral: 'user-provided custom topic',
    best_market: 'Global',
  },
  topic_slug: slug,
  selection_source: 'custom_command',
} }];"""
}, 2)

add_node("Set Scheduled Context", "n8n-nodes-base.code", {
    "jsCode": RUN_ID_JS + """
const staticData = $getWorkflowStaticData('global');
const chat_id = staticData.telegram_chat_id;
if (!chat_id) {
  throw new Error('No Telegram chat_id saved. Message your reels bot /start from your personal account first.');
}
return [{ json: {
  chat_id,
  trigger_mode: 'scheduled',
  run_id,
} }];"""
}, 2)

# TAVILY
add_node("Tavily Search", "n8n-nodes-base.httpRequest", {
    "method": "POST", "url": "https://api.tavily.com/search",
    "sendHeaders": True,
    "headerParameters": {"parameters": [
        {"name": "Authorization", "value": f"Bearer {TAVILY_KEY}"},
        {"name": "Content-Type", "value": "application/json"},
    ]},
    "sendBody": True, "specifyBody": "json",
    "jsonBody": json.dumps({
        "query": "vending machine business marketing trends 2026 passive income smart vending UPI India Dubai US YouTube Shorts Instagram Reels viral topics",
        "search_depth": "advanced", "max_results": 10, "include_answer": True,
    }),
    "options": {},
}, 4.2)

PARSE_OPENROUTER_JS = """function sanitizeJsonText(raw) {
  let content = String(raw || '').replace(/```json\\n?/gi, '').replace(/```\\n?/g, '').trim();
  const start = content.indexOf('{');
  const end = content.lastIndexOf('}');
  if (start > 0) content = content.slice(start);
  if (end >= 0) content = content.slice(0, end + 1);
  return content
    .replace(/^\\{\\s*\\[/, '{\"clip_prompts\":[')
    .replace(/,\\s*([}\\]])/g, '$1');
}
function parseOpenRouterJson(res, label) {
  if (res?.error) throw new Error(`${label}: ${res.error.message || JSON.stringify(res.error)}`);
  let content = res?.choices?.[0]?.message?.content || '';
  if (!content) throw new Error(`${label}: empty response`);
  const attempts = [
    content.replace(/```json\\n?/gi, '').replace(/```\\n?/g, '').trim(),
    sanitizeJsonText(content),
  ];
  let lastErr;
  for (const attempt of attempts) {
    try {
      return JSON.parse(attempt);
    } catch (e) {
      lastErr = e;
    }
  }
  throw new Error(`${label}: invalid JSON - ${String(content).slice(0, 300)}`);
}
"""

# Long director prompts are the one place the model reliably breaks JSON, so
# this node gets a regex salvage pass the other parsers do not need.
PARSE_FLOW_PAYLOAD_JS = """
function parseFlowPayload(item) {
  try {
    return parseOpenRouterJson(item, 'OpenRouter Flow Prompts');
  } catch (err) {
    const raw = String(item?.choices?.[0]?.message?.content || '');
    const prompts = [];
    const re = /\"clip_number\"\\s*:\\s*\"([^\"]*)\"[\\s\\S]*?\"prompt_text\"\\s*:\\s*\"((?:\\\\.|[^\"\\\\])*)\"/g;
    let m;
    while ((m = re.exec(raw)) !== null) {
      prompts.push({
        clip_number: m[1],
        prompt_text: m[2].replace(/\\\\n/g, '\\n').replace(/\\\\\"/g, '\"').replace(/\\\\t/g, '\\t'),
      });
    }
    if (prompts.length) {
      const bibleMatch = raw.match(/\"production_bible_summary\"\\s*:\\s*\"((?:\\\\.|[^\"\\\\])*)\"/);
      return {
        clip_prompts: prompts,
        production_bible_summary: bibleMatch ? bibleMatch[1].replace(/\\\\n/g, '\\n').replace(/\\\\\"/g, '\"') : '',
      };
    }
    throw err;
  }
}"""

EXTRACT_TOPICS_JS = """
function extractTopics(data) {
  if (Array.isArray(data)) return data;
  return data.topics || data.key_topics || data.video_topics || data.top5_topics || [];
}"""


def call_openrouter(name, system_prompt, user_content_js, model=OPENROUTER_MODEL_FAST, reasoning=None, timeout_ms=300000):
    reasoning_js = f"\nbody.reasoning = {json.dumps(reasoning)};" if reasoning else ""
    code = f"""const ctx = $input.first().json;
const userContent = {user_content_js};
const body = {{
  model: {json.dumps(model)},
  response_format: {{ type: 'json_object' }},
  messages: [
    {{ role: 'system', content: {json.dumps(system_prompt)} }},
    {{ role: 'user', content: userContent }}
  ],
}};{reasoning_js}
const res = await this.helpers.httpRequest({{
  method: 'POST',
  url: 'https://openrouter.ai/api/v1/chat/completions',
  headers: {{
    Authorization: 'Bearer {OPENROUTER_KEY}',
    'Content-Type': 'application/json',
    'HTTP-Referer': 'https://n8n.io',
    'X-Title': 'Mini Automation for Reels',
  }},
  body,
  json: true,
  timeout: {timeout_ms},
}});
return [{{ json: {{
  ...ctx,
  id: res.id,
  model: res.model,
  choices: res.choices,
  usage: res.usage,
}} }}];"""
    add_node(name, "n8n-nodes-base.code", {"jsCode": code}, 2)
    return name

add_node("Attach Run Context", "n8n-nodes-base.code", {
    "jsCode": """let ctx;
try { ctx = $('Set Manual Context').first().json; }
catch (e) { ctx = $('Set Scheduled Context').first().json; }
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
}, 2)

# TOPICS — light model: summarize search results into 5 ranked topic cards
call_openrouter(
    "OpenRouter Top 5 Topics",
    'You are a viral short-form content strategist for the vending machine industry. Return ONLY valid JSON. The root object MUST use the exact key "topics" (not key_topics) containing an array of exactly 5 objects. Each object: rank (1-5), title, hook, why_viral, best_market (India|Dubai|US|Global).',
    '`Analyze Tavily results and produce 5 ranked vending-machine marketing video topics for Shorts/Reels.\\n\\nAnswer: ${ctx.tavily_answer}\\n\\nResults: ${JSON.stringify(ctx.tavily_results)}`',
    model=OPENROUTER_MODEL_FAST,
)

add_node("Parse Top 5 Topics", "n8n-nodes-base.code", {
    "jsCode": PARSE_OPENROUTER_JS + EXTRACT_TOPICS_JS + """
const item = $input.first().json;
const data = parseOpenRouterJson(item, 'OpenRouter Top 5 Topics');
const topics = extractTopics(data);
if (!topics.length) throw new Error(`No topics returned. Keys: ${Object.keys(data).join(', ')}`);
const lines = topics.map((t, i) => `${t.rank || i+1}. ${t.title}\\n   Hook: ${t.hook}\\n   ${t.why_viral} | Market: ${t.best_market || 'Global'}`).join('\\n\\n');
const modeLabel = item.trigger_mode === 'scheduled' ? 'SCHEDULED' : 'MANUAL';
let topic_message = `VENDING MACHINE TOPIC PICKER\\nRun: ${item.run_id} (${modeLabel})\\n\\nPick ONE topic (reply 1-5):\\n\\n${lines}\\n\\nReply with a number from 1 to 5.`;
if (topic_message.length > 3900) topic_message = topic_message.slice(0, 3880) + '\\n...(truncated)';
return [{ json: { ...item, topics, topic_message } }];"""
}, 2)

add_node("IF Preselected Rank", "n8n-nodes-base.if", {
    "conditions": {
        "options": {"caseSensitive": True, "leftValue": "", "typeValidation": "loose", "version": 2},
        "conditions": [
            {"id": nid(), "leftValue": "={{ $json.topic_mode }}", "rightValue": "rank", "operator": {"type": "string", "operation": "equals"}},
        ],
        "combinator": "and",
    },
    "looseTypeValidation": True, "options": {},
}, 2.2)

add_node("Select Topic By Rank", "n8n-nodes-base.code", {
    "jsCode": """const item = $input.first().json;
const pick = Number(item.topic_rank);
if (!pick || pick < 1 || pick > 5) throw new Error(`Invalid topic rank ${item.topic_rank}. Use /generate 1 through /generate 5.`);
const selected = item.topics.find(t => t.rank === pick) || item.topics[pick - 1];
if (!selected) throw new Error(`Topic #${pick} not found in top-5 list.`);
const slug = (selected.title || 'topic').toLowerCase().replace(/[^a-z0-9]+/g, '-').slice(0, 40);
return [{ json: {
  ...item,
  selected_topic: selected,
  selected_rank: pick,
  topic_slug: slug,
  selection_source: 'command_rank',
} }];"""
}, 2)

add_node("Wait For Topic Selection", "n8n-nodes-base.telegram", {
    "operation": "sendAndWait", "chatId": "={{ $json.chat_id }}",
    "message": "={{ $json.topic_message }}",
    "responseType": "freeText",
    "options": {
        "appendAttribution": False,
        "limitWaitTime": {"values": {"limitWaitTime": 24, "limitWaitTimeUnit": "hours"}},
    },
}, 1.2, {"webhookId": nid(), "onError": "stopWorkflow"})

add_node("Parse Topic Selection", "n8n-nodes-base.code", {
    "jsCode": """function readTelegramReply(input) {
  const j = input?.json || {};
  return String(j.data?.text || j.message?.text || j.result?.text || j.text || '').trim();
}
const wait = $input.first().json;
if (wait.error) {
  throw new Error(`Telegram failed: ${wait.error}. If it says "bot can't send messages to the bot", your chat_id is the BOT id — use your personal user ID from @userinfobot instead. Also send /start to your bot from your own account.`);
}
const prev = $('Parse Top 5 Topics').first().json;
const raw = readTelegramReply($input.first());
if (!raw) throw new Error('No topic selection received from Telegram. Reply with a number from 1 to 5.');
if (!/^[1-5]$/.test(raw)) throw new Error(`Invalid topic selection "${raw}". Reply with only a number from 1 to 5.`);
const pick = parseInt(raw, 10);
const selected = prev.topics.find(t => t.rank === pick) || prev.topics[pick - 1];
if (!selected) throw new Error(`Topic #${pick} not found in top-5 list. Reply with a number from 1 to 5.`);
const slug = (selected.title || 'topic').toLowerCase().replace(/[^a-z0-9]+/g, '-').slice(0, 40);
return [{ json: {
  ...prev,
  selected_topic: selected,
  selected_rank: pick,
  topic_slug: slug,
  selection_source: 'telegram',
} }];"""
}, 2)

# SCRIPT — Sonnet 5: the creative core. Everything downstream (voiceover,
# subtitles, clip timing, Flow prompts) is derived from these 5 scenes, so the
# prompt's whole job is to make the scenes precise and self-consistent.
SCRIPT_PACKAGE_PROMPT = f"""You write {TOTAL_SEC}-second vertical video scripts for a smart vending machine brand selling to businesses in India, the Gulf and the US.

Your output drives a fully automated pipeline. One text-to-speech pass reads your five voiceover segments back to back as a single continuous take, and five separate {CLIP_SEC}-second AI video clips are generated to sit under them. Nothing downstream can rewrite you, so precision beats flourish.

Return ONE JSON object. No markdown fences, no commentary.

TOP-LEVEL KEYS
  hook                  the scroll-stopper, max 12 words, the same words that open scene 1
  caption_1 … caption_4 four post-caption options, max 120 characters each
  cta                   the closing ask, max 10 words
  elevenlabs_voice_id   one id from the voice list below
  elevenlabs_voice_name matching name
  voice_reason          one sentence on why that voice suits this script
  production_bible      {{ story_arc, protagonist_pov, primary_location, time_of_day,
                          color_grade, hero_subject, continuity_locks }}
  scenes                exactly {CLIP_COUNT} objects, in order

EACH SCENE OBJECT
  scene_index           0,1,2,3,4
  clip_number           "1/{CLIP_COUNT}" … "{CLIP_COUNT}/{CLIP_COUNT}"
  narrative_beat        HOOK, SETUP, PROOF, EMOTION, CTA — in that order
  voiceover_segment     the exact spoken words for this {CLIP_SEC} seconds
  on_screen_text        max 5 words, or "" when the shot reads better clean
  visual_brief          what the camera sees, 1-2 sentences, present tense
  what_happened_before  one clause of continuity from the previous beat
  what_happens_next     one clause pointing at the next beat
  end_frame_state       where subject, camera and light sit on the final frame
  transition_out        how this beat hands off to the next

THE {CLIP_SEC}-SECOND BUDGET — nothing downstream can correct a miss here
- Every voiceover_segment is {WORDS_MIN}-{WORDS_MAX} words. Count them. Not {WORDS_MIN - 5}, not {WORDS_MAX + 5}.
- The five segments together total {WORDS_MIN * CLIP_COUNT}-{WORDS_MAX * CLIP_COUNT} words. That is {USABLE_SEC:.0f} seconds at natural pace, which is what {CLIP_COUNT} clips of {CLIP_SEC} seconds come to once the crossfades between them are taken out.
- They are read with no pause inserted between them, so the last word of one segment must flow straight into the first word of the next. Each segment is still a complete thought.
- voiceover_segment is spoken aloud character for character. No stage directions, no speaker labels, no emoji, no bracketed notes, no ellipses.
- Spell out anything a speech engine would mangle: "twenty-four seven" not "24/7", "eighty thousand rupees" not "Rs 80,000", "U P I" not "UPI", "two point five times" not "2.5x".

THE BEATS
  1 HOOK     Open on the sharpest specific claim, number or contradiction you have. Never "imagine this", "in today's world" or a question the viewer does not already care about. Earn the next three seconds.
  2 SETUP    Ground it. Who, where, what the old way costs them.
  3 PROOF    One concrete number, timeframe or mechanism. This is the beat that decides whether anyone shares the video.
  4 EMOTION  Why it lands for one specific person — relief, control, pride, time back.
  5 CTA      One clear next step, said with confidence rather than urgency.

VISUAL DISCIPLINE
- Every visual_brief is a real vending machine in a real place: office breakroom, building lobby, campus corridor, factory floor, gym, clinic waiting room.
- One protagonist, one wardrobe, one time of day, one colour grade across all five scenes. continuity_locks names exactly what must not change.
- Never invent hardware. No coin slots, no cash boxes, no levers, no features you have not been shown.
- The voiceover carries the argument; the visuals carry the feeling. Do not narrate the picture.

VOICES
  Rachel 21m00Tcm4TlvDq8ikWAM — warm, credible, trusted-advisor
  Adam pNInz6obpgDQGcFmaJgB — confident male, business authority
  Josh TxGEqnHWrfWFTfGW9XjX — young, high energy, fast-paced hooks
  Bella EXAVITQu4vr4xnSDxMaL — bright and friendly, consumer-facing
  Antoni ErXwobaYiN019PkySvjV — smooth and premium, aspirational"""

SCRIPT_PACKAGE_USER_JS = """`Topic: ${ctx.selected_topic.title}
Hook angle: ${ctx.selected_topic.hook}
Primary market: ${ctx.selected_topic.best_market}
Why this travels: ${ctx.selected_topic.why_viral}

Write the """ + str(CLIP_COUNT) + """-scene package for this topic. Speak to the person who would buy or host the machine, not to a general audience.`"""

call_openrouter(
    "OpenRouter Script Package",
    SCRIPT_PACKAGE_PROMPT,
    SCRIPT_PACKAGE_USER_JS,
    model=OPENROUTER_MODEL_HEAVY,
    reasoning={"enabled": True, "effort": "medium"},
)

add_node("Parse Script Package", "n8n-nodes-base.code", {
    "jsCode": PARSE_OPENROUTER_JS + f"""
const item = $input.first().json;
const script = parseOpenRouterJson(item, 'OpenRouter Script Package');
if (!Array.isArray(script.scenes) || !script.scenes.length) {{
  throw new Error('Script package missing scenes array');
}}
if (script.scenes.length !== {CLIP_COUNT}) {{
  throw new Error(`Script package returned ${{script.scenes.length}} scenes, need exactly {CLIP_COUNT}.`);
}}
const emptyScene = script.scenes.findIndex((s) => !String(s?.voiceover_segment || '').trim());
if (emptyScene >= 0) {{
  throw new Error(`Scene ${{emptyScene + 1}} has an empty voiceover_segment — nothing to speak over that clip.`);
}}
if (!script.elevenlabs_voice_id) throw new Error('Script package missing elevenlabs_voice_id');
return [{{ json: {{ ...item, script }} }}];"""
}, 2)

# The whole sync story lives here: the voiceover the TTS reads is built by
# concatenating the scene segments, so audio and scenes cannot drift apart.
# Anything the model got wrong about length is measured and reported now
# rather than discovered in the finished render.
add_node("Normalize Script Timing", "n8n-nodes-base.code", {
    "jsCode": f"""const item = $input.first().json;
const script = {{ ...(item.script || {{}}) }};

const CLIP_COUNT = {CLIP_COUNT};
const CLIP_SEC = {CLIP_SEC};
const WORDS_PER_SEC = {WORDS_PER_SEC};
const BEATS = ['HOOK', 'SETUP', 'PROOF', 'EMOTION', 'CTA'];

function countWords(text) {{
  const words = String(text || '').trim().split(/\\s+/).filter(Boolean);
  return words.length;
}}

// Strip anything the model may have slipped in that a speech engine would read
// out loud: bracketed directions, speaker labels, stray markdown.
function cleanSpoken(text) {{
  return String(text || '')
    .replace(/\\[[^\\]]*\\]/g, ' ')
    .replace(/\\([^)]*\\)/g, ' ')
    .replace(/^\\s*(?:VO|VOICEOVER|NARRATOR|SPEAKER)\\s*:\\s*/i, '')
    .replace(/[*_`#]/g, '')
    .replace(/\\s+/g, ' ')
    .trim();
}}

const scenes = [];
const sync_warnings = [];

for (let i = 0; i < CLIP_COUNT; i++) {{
  const raw = (script.scenes || [])[i] || {{}};
  const spoken = cleanSpoken(raw.voiceover_segment);
  const words = countWords(spoken);
  const estimated_sec = Number((words / WORDS_PER_SEC).toFixed(2));

  if (!spoken) {{
    sync_warnings.push(`Clip ${{i + 1}}/${{CLIP_COUNT}} has no voiceover after cleanup.`);
  }} else if (estimated_sec > CLIP_SEC + 1.5) {{
    sync_warnings.push(`Clip ${{i + 1}}/${{CLIP_COUNT}} runs long: ${{words}} words ≈ ${{estimated_sec}}s over a ${{CLIP_SEC}}s clip. The clip is slowed to fit.`);
  }} else if (estimated_sec < CLIP_SEC - 2.5) {{
    sync_warnings.push(`Clip ${{i + 1}}/${{CLIP_COUNT}} runs short: ${{words}} words ≈ ${{estimated_sec}}s over a ${{CLIP_SEC}}s clip. The clip is trimmed to fit.`);
  }}

  scenes.push({{
    ...raw,
    scene_index: i,
    clip_number: `${{i + 1}}/${{CLIP_COUNT}}`,
    narrative_beat: raw.narrative_beat || BEATS[i],
    voiceover_segment: spoken,
    on_screen_text: String(raw.on_screen_text || '').trim(),
    word_count: words,
    estimated_sec,
  }});
}}

// One TTS pass over the concatenation — this is what makes the segments and the
// audio the same thing rather than two guesses at the same thing.
const full_script = scenes.map((s) => s.voiceover_segment).filter(Boolean).join(' ');
if (!full_script) throw new Error('Every scene lost its voiceover during cleanup — rerun the script step.');

const total_words = scenes.reduce((n, s) => n + s.word_count, 0);
const estimated_total_sec = Number((total_words / WORDS_PER_SEC).toFixed(2));

return [{{ json: {{
  ...item,
  script: {{ ...script, scenes, full_script }},
  script_word_count: total_words,
  script_estimated_sec: estimated_total_sec,
  sync_warnings,
}} }}];"""
}, 2)

# S3 BRAND IMAGES
add_node("Load S3 Brand Images", "n8n-nodes-base.code", {
    "jsCode": LOAD_S3_BRAND_IMAGES_JS,
}, 2)

# MATCH IMAGES — light model: pick best image per scene from a fixed list
call_openrouter(
    "OpenRouter Match Images",
    """You assign one brand reference image per clip for a 5-scene vending-machine YouTube Short.
Return ONLY valid JSON. Root key MUST be "matched_scenes" (array of exactly 5 objects).
Each object: scene_index (0-4), clip_number ("1/5".."5/5"), reference_image_name (EXACT from list), reference_image_key, reference_image_url, match_reason.

MATCHING RULES (strict):
0. FILENAME PART TAGS (highest priority): if a filename contains part1, part2, part3, part4, part5 (also clip1..5 or scene1..5), assign that file to clip N/5 automatically — part1 → 1/5, part2 → 2/5, etc. Only use semantic matching for files without part tags.
1. Use ONLY images from the provided list — never invent names.
2. Read each scene's narrative_beat, visual_brief, and voiceover_segment — match filename keywords to scene intent.
3. General snack/drink/profit topics: prefer snack, drink, office, breakroom, lobby, touchscreen, black/red machine images.
4. NEVER assign sanitary-pad, NGO, feminine-hygiene, or specialty-niche machines unless the script explicitly discusses that product.
5. Clip 1 (HOOK): dramatic close-up or hero machine shot that fits the hook — not a random unrelated category.
6. Clip 2 (SETUP): location/context wide shot (breakroom, lobby, office) when script establishes setting.
7. Clip 3 (PROOF): touchscreen, QR, payment, dashboard-friendly machine if script mentions sales/data.
8. Clip 4 (EMOTION): people + machine lifestyle shot when script is personal/freedom beat.
9. Clip 5 (CTA): customer selecting product or direct-friendly machine shot.
10. Prefer 5 different images; reuse only if list has fewer than 5 relevant options.
11. match_reason must cite overlapping keywords between scene text and filename, or state "partN filename → clip N/5" when part tag used.""",
    '`Topic: ${ctx.selected_topic?.title}\\nScenes: ${JSON.stringify(ctx.script.scenes)}\\nProduction bible: ${JSON.stringify(ctx.script.production_bible)}\\n\\nNaming tip: files with part1..part5 (or clip1..5) in the filename are pre-tagged for clips 1..5.\\nAvailable images: ${JSON.stringify(ctx.brand_files)}`',
    model=OPENROUTER_MODEL_FAST,
)

add_node("Parse Match Images", "n8n-nodes-base.code", {
    "jsCode": PARSE_OPENROUTER_JS + CLIP_INDEX_FROM_NAME_JS + f"""
const item = $input.first().json;
const CLIP_COUNT = {CLIP_COUNT};

// If every clip already has a partN/clipN image, the naming is the answer and
// there is nothing for a model to decide.
function buildPartMappedScenes(brandFiles) {{
  const slots = [];
  for (const f of brandFiles || []) {{
    const n = clipIndexFromName(f.file_name || f.name || f.key);
    const idx = n - 1;
    if (n < 1 || n > CLIP_COUNT || slots[idx]) continue;
    slots[idx] = {{
      scene_index: idx,
      clip_number: `${{n}}/${{CLIP_COUNT}}`,
      reference_image_name: f.name,
      reference_image_key: f.key,
      reference_image_url: f.url,
      match_reason: `Filename tag ${{n}} → clip ${{n}}/${{CLIP_COUNT}}`,
    }};
  }}
  return slots.length === CLIP_COUNT && slots.every(Boolean) ? slots : null;
}}
""" + """
const partMapped = buildPartMappedScenes(item.brand_files);
let picked;
if (partMapped) {
  picked = partMapped;
} else {
  const data = parseOpenRouterJson(item, 'OpenRouter Match Images');
  if (!data.matched_scenes?.length) throw new Error(`No matched_scenes returned. Keys: ${Object.keys(data).join(', ')}`);
  const brandByName = Object.fromEntries((item.brand_files || []).map(f => [f.name.toLowerCase(), f]));
  const brandByKey = Object.fromEntries((item.brand_files || []).map(f => [f.key, f]));
  picked = (data.matched_scenes || []).map(m => {
    const file = brandByName[(m.reference_image_name || '').toLowerCase()]
      || brandByKey[m.reference_image_key]
      || (item.brand_files || []).find(f => f.file_name === m.reference_image_name);
    return {
      ...m,
      reference_image_name: file?.name || m.reference_image_name || 'none',
      reference_image_key: file?.key || m.reference_image_key || '',
      reference_image_url: file?.url || m.reference_image_url || '',
      match_reason: m.match_reason || ''
    };
  });
}

// Downstream nodes index straight into matched_scenes by scene_index, so pin it
// to exactly one entry per clip whatever the model returned.
const fallbackImage = (item.brand_files || [])[0] || {};
const matched_scenes = Array.from({ length: CLIP_COUNT }, (_, i) => {
  const m = picked.find((s) => Number(s.scene_index) === i) || picked[i] || {};
  return {
    scene_index: i,
    clip_number: `${i + 1}/${CLIP_COUNT}`,
    reference_image_name: m.reference_image_name || fallbackImage.name || 'none',
    reference_image_key: m.reference_image_key || fallbackImage.key || '',
    reference_image_url: m.reference_image_url || fallbackImage.url || '',
    match_reason: m.match_reason || 'no match returned — fell back to first available image',
  };
});

const image_links_text = matched_scenes.map(m =>
  `Clip ${m.clip_number}: ${m.reference_image_name}\\n${m.reference_image_url || 'no-url'}`
).join('\\n\\n');
const unique_images = [...new Map(matched_scenes.filter(m => m.reference_image_url).map(m => [m.reference_image_url, m])).values()];
const unique_images_text = unique_images.map((m, i) => `${i + 1}. ${m.reference_image_name}\\n${m.reference_image_url}`).join('\\n\\n');
return [{ json: { ...item, matched_scenes, image_links_text, unique_images_text, unique_images } }];"""
}, 2)

# Voiceover: HTTP Request nodes (Response Format: File) — Code node httpRequest cannot read binary in task runner
add_node("Prepare Voiceover", "n8n-nodes-base.code", {
    "jsCode": PREPARE_VOICEOVER_JS,
}, 2)

add_node("Cartesia TTS", "n8n-nodes-base.httpRequest", {
    "method": "POST",
    "url": "https://api.cartesia.ai/tts/bytes",
    "sendHeaders": True,
    "headerParameters": {"parameters": [
        {"name": "Authorization", "value": f"Bearer {CARTESIA_API_KEY}"},
        {"name": "Cartesia-Version", "value": "2024-11-13"},
        {"name": "Content-Type", "value": "application/json"},
        {"name": "Accept", "value": "audio/mpeg"},
    ]},
    "sendBody": True,
    "specifyBody": "json",
    # bit_rate is pinned so Build Sync Map can derive duration from file size.
    "jsonBody": (
        '={{ JSON.stringify({ model_id: "sonic-3.5", transcript: $json._voiceover_text, '
        f'voice: {{ mode: "id", id: "{CARTESIA_VOICE_ID}" }}, '
        f'output_format: {{ container: "mp3", sample_rate: 44100, bit_rate: {VOICEOVER_BITRATE} }} }}) }}}}'
    ),
    "options": TTS_FILE_RESPONSE_OPTS,
}, 4.2, {"onError": "continueRegularOutput"})

add_node("IF Cartesia OK", "n8n-nodes-base.if", {
    "conditions": {
        "options": {"caseSensitive": True, "leftValue": "", "typeValidation": "loose", "version": 2},
        "conditions": [
            {
                "id": nid(),
                "leftValue": "={{ $binary.voiceover?.fileName || '' }}",
                "rightValue": "",
                "operator": {"type": "string", "operation": "notEmpty"},
            },
        ],
        "combinator": "and",
    },
    "looseTypeValidation": True, "options": {},
}, 2.2)

add_node("ElevenLabs TTS", "n8n-nodes-base.httpRequest", {
    "method": "POST",
    "url": "={{ 'https://api.elevenlabs.io/v1/text-to-speech/' + $json._eleven_voice_id + '?output_format=mp3_44100_128' }}",
    "sendHeaders": True,
    "headerParameters": {"parameters": [
        {"name": "xi-api-key", "value": ELEVENLABS_KEY},
        {"name": "Content-Type", "value": "application/json"},
        {"name": "Accept", "value": "audio/mpeg"},
    ]},
    "sendBody": True,
    "specifyBody": "json",
    "jsonBody": '={{ JSON.stringify({ text: $json._voiceover_text, model_id: "eleven_flash_v2_5", voice_settings: { stability: 0.5, similarity_boost: 0.75 } }) }}',
    "options": TTS_FILE_RESPONSE_OPTS,
}, 4.2)

add_node("Prepare S3 Upload", "n8n-nodes-base.code", {
    "jsCode": PREPARE_S3_UPLOAD_JS,
}, 2)

add_node("S3 PUT Voiceover", "n8n-nodes-base.httpRequest", {
    "method": "PUT",
    "url": "={{ $json.upload_url }}",
    "sendBody": True,
    "contentType": "binaryData",
    "inputDataFieldName": "voiceover",
    "options": S3_PUT_RESPONSE_OPTS,
}, 4.2)

add_node("S3 PUT Voiceover OK", "n8n-nodes-base.code", {
    "jsCode": "return [{ json: { s3_voiceover_ok: true } }];",
}, 2)

add_node("Finalize Voiceover", "n8n-nodes-base.code", {
    "jsCode": FINALIZE_VOICEOVER_JS,
}, 2)

# Sync is computed, not guessed. The rendered voiceover is measured, split
# across the five scenes by word share, and the subtitles plus the per-clip
# render timing are both generated from that one timeline — so subtitles,
# audio and picture cannot disagree.
add_node("Build Sync Map", "n8n-nodes-base.code", {
    "jsCode": f"""const ctx = $input.first().json;
const scenes = ctx.script?.scenes || [];

const CLIP_COUNT = {CLIP_COUNT};
const CLIP_SEC = {CLIP_SEC};
const TOTAL_SEC = {TOTAL_SEC};
const WORDS_PER_SEC = {WORDS_PER_SEC};
const BITRATE = {VOICEOVER_BITRATE};
const TRANSITION_SEC = {TRANSITION_SEC};
// Slowing a clip below this looks like a glitch rather than a choice.
const MIN_SPEED = 0.8;
// The render muxes with -shortest, so the picture has to outlast the audio by a
// hair or the last word gets clipped off the end.
const TAIL_SEC = {TAIL_SEC};

function round2(n) {{ return Number(Number(n).toFixed(2)); }}

function timecode(sec) {{
  const total = Math.max(0, sec);
  const m = Math.floor(total / 60);
  const s = Math.floor(total % 60);
  const ms = Math.round((total - Math.floor(total)) * 1000);
  return `${{String(m).padStart(2, '0')}}:${{String(s).padStart(2, '0')}},${{String(ms).padStart(3, '0')}}`;
}}
function srtStamp(sec) {{ return `00:${{timecode(sec)}}`; }}

// Both TTS providers return constant-bitrate mp3, so bytes give a reliable
// duration without downloading and probing the file.
const bytes = Number(ctx.voiceover_bytes || 0);
const measured_sec = bytes > 0 ? (bytes * 8) / BITRATE : 0;
const words = scenes.reduce((n, s) => n + (Number(s.word_count) || 0), 0);
const fallback_sec = words ? words / WORDS_PER_SEC : TOTAL_SEC;
// Guard against a truncated or padded file throwing the whole timeline off.
const plausible = measured_sec > TOTAL_SEC * 0.5 && measured_sec < TOTAL_SEC * 2;
const voiceover_sec = round2(plausible ? measured_sec : fallback_sec);
const duration_source = plausible ? 'measured from mp3 size' : 'estimated from word count';

// Share the real audio out by word count — a 25-word scene genuinely takes
// longer to say than a 15-word one.
const weights = scenes.map((s) => Math.max(1, Number(s.word_count) || 1));
const weightTotal = weights.reduce((a, b) => a + b, 0);

let cursor = 0;
const sync_windows = [];
const srtBlocks = [];
let cueNumber = 0;

for (let i = 0; i < CLIP_COUNT; i++) {{
  const scene = scenes[i] || {{}};
  const matched = (ctx.matched_scenes || []).find((m) => Number(m.scene_index) === i)
    || (ctx.matched_scenes || [])[i]
    || {{}};

  const vo_start = round2(cursor);
  const share = (weights[i] / weightTotal) * voiceover_sec;
  const vo_end = round2(i === CLIP_COUNT - 1 ? voiceover_sec : cursor + share);
  const vo_len = round2(Math.max(0.5, vo_end - vo_start));
  cursor = vo_end;

  // An xfade overlaps neighbours, so every clip but the last has to carry the
  // transition on top of its own voiceover or the reel ends up short and the
  // final words get cut off. The last clip carries the safety tail instead.
  const target_len = round2(vo_len + (i === CLIP_COUNT - 1 ? TAIL_SEC : TRANSITION_SEC));
  let trim_start = 0;
  let trim_end = round2(Math.min(CLIP_SEC, target_len));
  let speed = 1;
  if (target_len > CLIP_SEC) {{
    // Not enough footage: stretch it, down to the point where it still reads.
    speed = round2(Math.max(MIN_SPEED, CLIP_SEC / target_len));
    trim_end = CLIP_SEC;
  }}
  const rendered_len = round2(trim_end / speed);

  // Subtitles are cut from the same words at the same times as the audio.
  const cueWords = String(scene.voiceover_segment || '').split(/\\s+/).filter(Boolean);
  const perCue = 6;
  const cueCount = Math.max(1, Math.ceil(cueWords.length / perCue));
  for (let c = 0; c < cueCount && cueWords.length; c++) {{
    const slice = cueWords.slice(c * perCue, (c + 1) * perCue);
    if (!slice.length) continue;
    const cueStart = vo_start + (vo_len * (c * perCue)) / cueWords.length;
    const cueEnd = vo_start + (vo_len * Math.min(cueWords.length, (c + 1) * perCue)) / cueWords.length;
    cueNumber += 1;
    srtBlocks.push(`${{cueNumber}}\\n${{srtStamp(cueStart)}} --> ${{srtStamp(cueEnd)}}\\n${{slice.join(' ')}}`);
  }}

  sync_windows.push({{
    clip_number: `${{i + 1}}/${{CLIP_COUNT}}`,
    scene_index: i,
    narrative_beat: scene.narrative_beat || '',
    vo_start,
    vo_end,
    vo_seconds: vo_len,
    timeline_label: `${{timecode(vo_start).slice(0, 5)}}–${{timecode(vo_end).slice(0, 5)}}`,
    spoken_text: scene.voiceover_segment || '',
    on_screen_text: scene.on_screen_text || '',
    word_count: Number(scene.word_count) || 0,
    render: {{ index: i + 1, trim_start, trim_end, speed, rendered_len }},
    scene,
    reference_image_name: matched.reference_image_name || 'none',
    reference_image_url: matched.reference_image_url || '',
  }});
}}

const subtitles_srt = srtBlocks.join('\\n\\n');
const rendered_total = round2(
  sync_windows.reduce((n, w) => n + w.render.rendered_len, 0) - TRANSITION_SEC * (CLIP_COUNT - 1)
);
const drift = round2(rendered_total - voiceover_sec);

const sync_warnings = [...(ctx.sync_warnings || [])];
// drift should sit at about +TAIL_SEC. Negative means the picture runs out
// before the voiceover does, which is the only case that damages the reel.
if (drift < -0.1) {{
  sync_warnings.push(`Video ends ${{Math.abs(drift)}}s before the voiceover — a clip hit the ${{MIN_SPEED}}x slow-motion limit, so the last words would be cut. Regenerate with a shorter script.`);
}}

return [{{ json: {{
  ...ctx,
  sync_windows,
  subtitles_srt,
  voiceover_sec,
  voiceover_duration_source: duration_source,
  render_total_sec: rendered_total,
  render_drift_sec: drift,
  transition_sec: TRANSITION_SEC,
  sync_warnings,
}} }}];"""
}, 2)

# FLOW PROMPTS — Sonnet 5 directs five clips that have to cut together as one
# film. Each clip is pinned to its reference image by name only; the presigned
# links go out in their own Telegram message so the prompt stays clean enough
# to paste straight into Flow.
FLOW_PROMPTS_USER_JS = """`Topic: ${ctx.selected_topic.title}
Full voiceover as recorded: ${ctx.script.full_script}
Production bible: ${JSON.stringify(ctx.script.production_bible)}
Measured voiceover length: ${ctx.voiceover_sec}s across """ + str(CLIP_COUNT) + """ clips.

Per-clip briefs. The reference image is already chosen and locked — use its name exactly as written, never swap it, and never describe a machine or setting that contradicts it.
${(ctx.sync_windows || []).map((w) => {
  const scene = w.scene || {};
  return [
    '--- CLIP ' + w.clip_number + ' | ' + w.timeline_label + ' | ' + w.narrative_beat + ' ---',
    'LOCKED REFERENCE IMAGE: ' + (w.reference_image_name || 'none'),
    'Voiceover over this clip (' + w.vo_seconds + 's, external audio, nobody speaks on camera):',
    '  "' + (w.spoken_text || '') + '"',
    'Burned subtitle: same words, ' + w.vo_start + 's to ' + w.vo_end + 's',
    'On-screen text: ' + (w.on_screen_text || 'none'),
    'Visual brief: ' + (scene.visual_brief || ''),
    'Coming from: ' + (scene.what_happened_before || 'opening frame'),
    'Leading into: ' + (scene.what_happens_next || 'end of film'),
    'End frame must be: ' + (scene.end_frame_state || ''),
    'Hand off by: ' + (scene.transition_out || 'straight cut'),
  ].join('\\n');
}).join('\\n\\n')}`"""

FLOW_PROMPTS_PROMPT = f"""You are a commercial director writing {CLIP_COUNT} image-to-video prompts for Google Flow. Together they form one continuous {TOTAL_SEC}-second vertical film about a smart vending machine. Each prompt generates one {CLIP_SEC}-second 9:16 clip from the reference image named in its brief.

Return ONE valid JSON object. No markdown fences, no commentary.
Root keys: clip_prompts (array of exactly {CLIP_COUNT}) and production_bible_summary (string, max 400 characters).
Each clip_prompts item: clip_number ("1/{CLIP_COUNT}" … "{CLIP_COUNT}/{CLIP_COUNT}") and prompt_text (string, max 1100 characters).

prompt_text must be these labelled lines, in this order, separated by newlines:

REFERENCE IMAGE: the locked image name, copied exactly from the brief
SHOT: framing and lens feel in one line, e.g. "medium close-up, 35mm, shallow depth"
SUBJECT: who or what is on screen and what they physically do across the {CLIP_SEC} seconds
SETTING: the room, its depth, what fills the background
CAMERA: one continuous move — push in, slow dolly left, rack focus, static on a gimbal. One move per clip, no cutting inside the clip.
LIGHT AND GRADE: source, direction, colour temperature, the grade named in the bible
CONTINUITY: what carries over from the previous clip and must not change — wardrobe, machine model, time of day, grade
END FRAME: the exact state of subject, camera and light on the last frame, so the next clip can pick it up
AUDIO: silent or ambient room tone only. No dialogue, no narration, no music, no sound effects. Nobody speaks. The generated audio track is discarded and replaced by a separate voiceover, so any speech here is wasted and any on-camera talking will not match it.

HOW TO WRITE THEM WELL
- Describe motion that fills exactly {CLIP_SEC} seconds. One intention per clip. A clip that tries to show three things reads as none of them.
- Write what the camera sees, in present tense, concrete nouns. No adjectives doing the work of a shot: "fluorescent light catching the glass door" beats "a beautiful scene".
- Nobody talks to camera. No lip movement, no mouthing words, no piece to camera, no interview framing. The model you are writing for generates speech and lip-sync by default, and the reel carries a separate recorded voiceover — a mouth moving to different words is the one thing that makes the finished video look broken. If a person is in frame they are doing something with their hands, their body or their attention.
- The five clips share one protagonist, one wardrobe, one location logic, one grade. CONTINUITY and END FRAME are how the cut survives.
- The voiceover in the brief is the argument being made over the picture. Do not have the picture repeat it literally — support it.

HARD RULES
- Clip N uses only the reference image named in clip N's brief. Never substitute, never merge two references.
- Never contradict what that image shows. If the reference is a lobby drinks machine, do not write a factory snack wall. If it is a touchscreen, do not invent a coin slot, a cash box or a lever.
- Never describe a product category the script does not discuss.
- No text overlays, captions, watermarks or logos in the generated video. Subtitles are burned in afterwards.
- Vertical 9:16 throughout, premium commercial polish, real-world lighting.
- Beats are fixed: 1 HOOK, 2 SETUP, 3 PROOF, 4 EMOTION, 5 CTA."""

call_openrouter(
    "OpenRouter Flow Prompts",
    FLOW_PROMPTS_PROMPT,
    FLOW_PROMPTS_USER_JS,
    model=OPENROUTER_MODEL_HEAVY,
    reasoning={"enabled": True, "effort": "medium"},
)

add_node("Parse Flow Prompts", "n8n-nodes-base.code", {
    "jsCode": PARSE_OPENROUTER_JS + PARSE_FLOW_PAYLOAD_JS + f"""
const item = $input.first().json;
const flow = parseFlowPayload(item);
const windows = item.sync_windows || [];
const rawPrompts = flow.clip_prompts || flow.clipPrompts || [];
if (!rawPrompts.length) throw new Error(`No clip_prompts returned. Keys: ${{Object.keys(flow).join(', ')}}`);

const CLIP_COUNT = {CLIP_COUNT};

function clipIndex(p, i) {{
  const m = String(p.clip_number || '').match(/(\\d+)/);
  return m ? Number(m[1]) - 1 : i;
}}

// The model is told to copy the image name verbatim; this makes sure of it.
// Name only — the presigned links go out in their own message, and pasting a
// 600-character signed URL into Flow only wastes prompt budget.
function enforceReferenceLine(text, name) {{
  const refLine = `REFERENCE IMAGE: ${{name || 'none'}}`;
  let out = String(text || '').trim();
  if (/^\\s*REFERENCE IMAGE:/im.test(out)) {{
    return out.replace(/^\\s*REFERENCE IMAGE:[^\\n]*/im, refLine);
  }}
  return `${{refLine}}\\n${{out}}`;
}}

const prompts = [];
for (let i = 0; i < CLIP_COUNT; i++) {{
  const w = windows[i] || {{}};
  const p = rawPrompts.find((c, ci) => clipIndex(c, ci) === i) || rawPrompts[i] || {{}};
  if (!String(p.prompt_text || '').trim()) {{
    throw new Error(`Flow prompt for clip ${{i + 1}}/${{CLIP_COUNT}} came back empty — rerun the generate step.`);
  }}
  prompts.push({{
    clip_number: `${{i + 1}}/${{CLIP_COUNT}}`,
    narrative_beat: w.narrative_beat || '',
    timeline_label: w.timeline_label || '',
    reference_image_name: w.reference_image_name || 'none',
    save_as: `${{item.run_id}}-clip${{i + 1}}.mp4`,
    prompt_text: enforceReferenceLine(p.prompt_text, w.reference_image_name),
  }});
}}

const flowText = prompts.map((p) => [
  '─'.repeat(34),
  `CLIP ${{p.clip_number}} · ${{p.timeline_label}} · ${{p.narrative_beat}}`,
  `Reference image: ${{p.reference_image_name}}`,
  `Save the download as: ${{p.save_as}}`,
  '─'.repeat(34),
  'Paste everything below into Flow:',
  '',
  p.prompt_text,
].join('\\n')).join('\\n\\n');

const bible = flow.production_bible_summary || JSON.stringify(item.script?.production_bible);
const script_json = JSON.stringify({{
  selected_topic: item.selected_topic,
  script: item.script,
  matched_scenes: item.matched_scenes,
  sync_windows: item.sync_windows,
  run_id: item.run_id,
}}, null, 2);

return [{{ json: {{
  ...item,
  clip_prompts: prompts,
  production_bible_summary: bible,
  flow_prompts_text: flowText,
  script_json,
}}}}];"""
}, 2)

UPLOAD_MANIFEST_JS = s3_common_js() + """
const ctx = $input.first().json;
if (!ctx?.run_id) throw new Error('Missing run_id on input — run Parse Flow Prompts first.');
const manifest = {
  run_id: ctx.run_id,
  topic_slug: ctx.topic_slug,
  chat_id: ctx.chat_id,
  selected_topic: ctx.selected_topic,
  voiceover_url: ctx.voiceover_url,
  voiceover_key: ctx.voiceover_key,
  subtitles_srt: ctx.subtitles_srt || '',
  sync_windows: ctx.sync_windows || [],
  // Timing the render needs so the picture lands on the voiceover.
  voiceover_sec: ctx.voiceover_sec,
  transition_sec: ctx.transition_sec,
  render_plan: (ctx.sync_windows || []).map((w) => w.render),
  sync_warnings: ctx.sync_warnings || [],
  production_bible: ctx.script?.production_bible || {},
  captions: {
    caption_1: ctx.script?.caption_1,
    caption_2: ctx.script?.caption_2,
    caption_3: ctx.script?.caption_3,
    caption_4: ctx.script?.caption_4,
    cta: ctx.script?.cta,
  },
  matched_scenes: ctx.matched_scenes || [],
  script: {
    full_script: ctx.script?.full_script,
    scenes: ctx.script?.scenes || [],
    production_bible: ctx.script?.production_bible,
  },
  created_at: new Date().toISOString(),
};
const manifest_key = `reels-manifests/${ctx.run_id}.json`;
const manifest_body = JSON.stringify(manifest, null, 2);
await putObject.call(this, manifest_key, manifest_body, 'application/json');
const manifest_url = presignGetUrl(manifest_key);
return [{
  json: {
    ...ctx,
    manifest_key,
    manifest_url,
    manifest_uploaded: true,
  },
}];
"""

add_node("Upload Manifest to S3", "n8n-nodes-base.code", {
    "jsCode": UPLOAD_MANIFEST_JS,
}, 2)

add_node("Format Final Package", "n8n-nodes-base.code", {
    "jsCode": """const ctx = $input.first().json;
const flowText = ctx.flow_prompts_text || '';
const imageSection = ctx.unique_images_text
  ? `REFERENCE IMAGES (7-day links)\\n${ctx.unique_images_text}`
  : (ctx.images_folder_note || 'No images found in Railway images/ folder yet. Upload context-named images and re-run.');
const perClipImages = ctx.image_links_text ? `PER-CLIP IMAGE MAP\\n${ctx.image_links_text}` : '';
const MAX = 3900;

function splitText(text, max = MAX) {
  const chunks = [];
  let rest = String(text || '').trim();
  while (rest.length > max) {
    let cut = rest.lastIndexOf('\\n', max);
    if (cut < Math.floor(max * 0.5)) cut = max;
    chunks.push(rest.slice(0, cut).trim());
    rest = rest.slice(cut).trim();
  }
  if (rest) chunks.push(rest);
  return chunks;
}

function packSections(sections, max = MAX) {
  const chunks = [];
  let current = '';
  for (const section of sections.filter(Boolean)) {
    const next = current ? `${current}\\n\\n${section}` : section;
    if (next.length <= max) {
      current = next;
      continue;
    }
    if (current) chunks.push(current);
    if (section.length <= max) {
      current = section;
    } else {
      chunks.push(...splitText(section, max));
      current = '';
    }
  }
  if (current) chunks.push(current);
  return chunks;
}

function protectUrlsForTelegram(text) {
  return String(text || '').split('\\n').map((line) => {
    const trimmed = line.trim();
    if (trimmed.startsWith('http://') || trimmed.startsWith('https://')) {
      const safe = trimmed.replace(/&/g, '&amp;');
      return line.replace(trimmed, `<code>${safe}</code>`);
    }
    return line
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');
  }).join('\\n');
}

const clipNames = (ctx.clip_prompts || []).map((p) => p.save_as);
const warnings = (ctx.sync_warnings || []).length
  ? `HEADS UP\\n${(ctx.sync_warnings || []).map((w) => `• ${w}`).join('\\n')}`
  : '';

const sections = [
  [
    `VIDEO PACKAGE READY`,
    `Topic: ${ctx.selected_topic?.title}`,
    `Run: ${ctx.run_id}`,
    `Voice: ${ctx.script?.elevenlabs_voice_name}`,
    `Voiceover: ${ctx.voiceover_sec}s (${ctx.voiceover_duration_source})`,
    `Timeline: ${ctx.sync_windows?.length || 0} clips × ${ctx.transition_sec}s crossfade → ${ctx.render_total_sec}s`,
  ].join('\\n'),
  warnings,
  `VOICEOVER (7-day link)\\n${ctx.voiceover_url}`,
  imageSection,
  perClipImages,
  // The naming rule is the contract between Flow and /compose: the clip number
  // is read straight off the filename, so order of sending stops mattering.
  [
    `NAME YOUR CLIPS BEFORE SENDING THEM BACK`,
    `Flow downloads come out with generic names. Rename each one to the name`,
    `printed above its prompt below:`,
    ``,
    clipNames.map((n) => `  ${n}`).join('\\n'),
    ``,
    `I read the clip number out of the filename, so you can send them in any`,
    `order, all at once, as an album. If a name has no number I fall back to`,
    `the caption — send the clip with just "1", "2" and so on.`,
  ].join('\\n'),
  flowText ? `FLOW PROMPTS (one clip per block, paste into Google Flow)\\n${flowText}` : '',
  [
    `COMPOSE THE FINAL REEL`,
    `Once all 5 clips are downloaded and renamed:`,
    `1) /compose ${ctx.run_id}`,
    `2) send the 5 clips`,
    `3) send done`,
  ].join('\\n'),
  ctx.manifest_url ? `MANIFEST (7-day link)\\n${ctx.manifest_url}` : '',
];

const telegram_chunks = packSections(sections);
return telegram_chunks.map((telegram_message, i) => ({
  json: {
    ...ctx,
    telegram_message: protectUrlsForTelegram(telegram_message),
    telegram_chunk: i + 1,
    telegram_chunk_total: telegram_chunks.length,
  },
}));"""
}, 2)

add_node("Send Final Package", "n8n-nodes-base.telegram", {
    "chatId": "={{ $json.chat_id }}", "text": "={{ $json.telegram_message }}",
    "additionalFields": {"appendAttribution": False, "parse_mode": "HTML"},
}, 1.2, {"webhookId": nid()})

nodes.append({
    "parameters": {
        "content": f"""## Reels pipeline — setup and how it fits together

Bucket `{RAILWAY_S3_BUCKET}` is already wired. **You still need to** put your
Telegram bot credential on the Trigger and on every Telegram node, then send
`/start` once so scheduled runs know where to post.

### Telegram chat ID
Your personal user ID from @userinfobot — never the bot's own ID, which
produces "bot can't send messages to the bot". Any `/start` saves it for you.

### Commands
- `/generate` — research, then reply `1`–`5` to pick a topic
- `/generate 3` — skip the picker, take topic #3
- `/generate <your topic>` — skip research entirely
- `/compose RUN_ID` → send 5 clips → `done`
- `/status`, `/cancel`, `/help`

### The {TOTAL_SEC}-second grid
Flow returns {CLIP_SEC}s clips, so the reel is a fixed {CLIP_COUNT} × {CLIP_SEC}s = {TOTAL_SEC}s.
Everything derives from that:
1. **Script Package** writes {CLIP_COUNT} scenes of {WORDS_MIN}-{WORDS_MAX} spoken words each
2. **Normalize Script Timing** strips anything unspeakable and builds the
   voiceover text by concatenating the scene segments — so the audio and the
   scenes are the same thing, not two guesses
3. **Build Sync Map** measures the rendered mp3, splits it across the {CLIP_COUNT} scenes
   by word share, then generates the SRT *and* the per-clip trim/speed plan
   from that one timeline
4. **Start Render** sends that plan verbatim; the model only picks the look

Anything that cannot be made to fit shows up as a warning in the Telegram
package rather than as a silently out-of-sync video.

### Brand images — `{S3_IMAGES_PREFIX}`
Name them `part1-hook-breakroom-wide.jpg` … `part5-cta-customer.jpg` and
part1..part{CLIP_COUNT} maps straight to clips 1..{CLIP_COUNT} with no model involved. Without
part tags the fast model matches them semantically. 7-day links go out in
their own Telegram message; the Flow prompts reference images by name only.

### Naming the clips you get back from Flow
The package tells you to save each download as `RUNID-clip1.mp4` …
`RUNID-clip5.mp4`. `/compose` reads the number out of the filename, so you
can send all five at once in any order. Fallbacks, in order: filename →
caption (`1`–`5`) → album position → first free slot.

### Models
- Fast (`{OPENROUTER_MODEL_FAST}`): topics, image matching
- Heavy (`{OPENROUTER_MODEL_HEAVY}`): script package, Flow prompts, render look

### Voiceover
Cartesia (pinned to {VOICEOVER_BITRATE // 1000}kbps so duration is derivable from file size)
with ElevenLabs as fallback. Response Format **File** → binary `voiceover`;
a Code node cannot carry the MP3 through the task runner. Stored at
`reels-voiceovers/{{slug}}-{{run_id}}.mp3`.

### Composer
Manifest at `reels-manifests/{{run_id}}.json`, clips at
`reels-clips/{{run_id}}/clip-0N.mp4`, output at `reels-final/{{run_id}}.mp4`.
Set `AUTH_TOKEN` on the Railway service and `COMPOSER_AUTH_TOKEN` in
`build/secrets_local.py` to lock the render endpoint down. Polling gives up
after 40 tries (~10 min) with a clear message.

### Before importing a rebuild
`python3 build/validate_workflow.py` parses every Code node — a JS syntax
error otherwise stays invisible until that node happens to run.""",
        "height": 640, "width": 520,
    },
    "type": "n8n-nodes-base.stickyNote", "typeVersion": 1,
    "position": _pos("Setup Notes"), "id": nid(), "name": "Setup Notes",
})

# CONNECTIONS
connect("Schedule Trigger", "Set Scheduled Context")
connect("Telegram Trigger", "Save Telegram Chat ID")
connect("Save Telegram Chat ID", "Route Compose vs Generate")
connect("Route Compose vs Generate", "IF Compose Route")
connect("IF Compose Route", "Classify Compose Message", 0)
connect("Classify Compose Message", "IF Clip Upload")
connect("Classify Compose Message", "IF Delegate Compose")
connect("IF Clip Upload", "Handle Clip Upload WF1", 0)
connect("Handle Clip Upload WF1", "Reply Compose")

import build_compose_workflow as compose_builder
compose_builder.inject_compose_delegate_into_wf1(
    s3_session_js,
    compose_clip_upload_js,
    add_node,
    connect,
    delegate_if_name="IF Delegate Compose",
    reply_node_name="Reply Compose",
)

connect("IF Compose Route", "Parse Generate Command", 1)
connect("Parse Generate Command", "IF Is Generate Command")
connect("IF Is Generate Command", "Set Manual Context")
connect("Set Manual Context", "IF Custom Topic")
connect("IF Custom Topic", "Set Custom Topic", 0)
connect("IF Custom Topic", "Tavily Search", 1)
connect("Set Custom Topic", "OpenRouter Script Package")
connect("Set Scheduled Context", "Tavily Search")
connect("Tavily Search", "Attach Run Context")
connect("Attach Run Context", "OpenRouter Top 5 Topics")
connect("OpenRouter Top 5 Topics", "Parse Top 5 Topics")
connect("Parse Top 5 Topics", "IF Preselected Rank")
connect("IF Preselected Rank", "Select Topic By Rank", 0)
connect("IF Preselected Rank", "Wait For Topic Selection", 1)
connect("Select Topic By Rank", "OpenRouter Script Package")
connect("Wait For Topic Selection", "Parse Topic Selection")
connect("Parse Topic Selection", "OpenRouter Script Package")
connect("OpenRouter Script Package", "Parse Script Package")
connect("Parse Script Package", "Normalize Script Timing")
connect("Normalize Script Timing", "Load S3 Brand Images")
connect("Load S3 Brand Images", "OpenRouter Match Images")
connect("OpenRouter Match Images", "Parse Match Images")
connect("Parse Match Images", "Prepare Voiceover")
connect("Prepare Voiceover", "Cartesia TTS")
connect("Cartesia TTS", "IF Cartesia OK")
connect("IF Cartesia OK", "Prepare S3 Upload", 0)
connect("IF Cartesia OK", "ElevenLabs TTS", 1)
connect("ElevenLabs TTS", "Prepare S3 Upload")
connect("Prepare S3 Upload", "S3 PUT Voiceover")
connect("S3 PUT Voiceover", "S3 PUT Voiceover OK")
connect("S3 PUT Voiceover OK", "Finalize Voiceover")
connect("Finalize Voiceover", "Build Sync Map")
connect("Build Sync Map", "OpenRouter Flow Prompts")
connect("OpenRouter Flow Prompts", "Parse Flow Prompts")
connect("Parse Flow Prompts", "Upload Manifest to S3")
connect("Upload Manifest to S3", "Format Final Package")
connect("Format Final Package", "Send Final Package")

pos_groups = {}
for node in nodes:
    pos_groups.setdefault(tuple(node["position"]), []).append(node["name"])
dupes = {p: names for p, names in pos_groups.items() if len(names) > 1}
if dupes:
    for p, names in dupes.items():
        print(f"ERROR: overlapping position {p}: {names}", file=sys.stderr)
    raise SystemExit(1)

AUTOMATIONS_DIR.mkdir(parents=True, exist_ok=True)
with open(MAIN_WORKFLOW_JSON, "w", encoding="utf-8") as f:
    json.dump({
        "name": MAIN_WORKFLOW_NAME,
        "nodes": nodes,
        "connections": connections,
        "pinData": {},
        "settings": {"executionOrder": "v1"},
        "meta": {"templateCredsSetupCompleted": False, "instanceId": nid()},
    }, f, indent=2, ensure_ascii=False)

print(f"Done: {len(nodes)} nodes -> {MAIN_WORKFLOW_JSON}")

# Parse every Code node before this JSON can reach n8n. A syntax error here is
# otherwise invisible until the node happens to execute — which is how
# /compose sat broken behind a Python format-string slip.
from validate_workflow import validate  # noqa: E402

if not validate(MAIN_WORKFLOW_JSON):
    raise SystemExit(1)
