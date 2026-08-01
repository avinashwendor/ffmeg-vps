"""Shared helpers for n8n workflow JSON generators."""
import json
import uuid

from config import (  # noqa: F401
    OPENROUTER_KEY,
    RAILWAY_S3_ACCESS_KEY,
    RAILWAY_S3_SECRET_KEY,
)

OPENROUTER_MODEL_FAST = "openai/gpt-5-mini"
OPENROUTER_MODEL_HEAVY = "anthropic/claude-sonnet-5"

S3_IMAGES_PREFIX = "images/"

RAILWAY_S3_ENDPOINT_HOST = "t3.storageapi.dev"
RAILWAY_S3_REGION = "auto"
RAILWAY_S3_BUCKET = "lightweight-vault-pew0g4o"
RAILWAY_PRESIGN_EXPIRES = 604800


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
function toBase64(bytes) {{
  const u8 = toBytes(bytes);
  if (typeof Buffer !== 'undefined') return Buffer.from(u8).toString('base64');
  let bin = '';
  for (let i = 0; i < u8.length; i++) bin += String.fromCharCode(u8[i]);
  return btoa(bin);
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
function decodeBufferJson(value) {{
  if (value && typeof value === 'object' && value.type === 'Buffer' && Array.isArray(value.data)) {{
    return new TextDecoder().decode(Uint8Array.from(value.data));
  }}
  return null;
}}
function readHttpText(res) {{
  if (res == null) return '';
  if (typeof res === 'string') return res;
  const direct = decodeBufferJson(res);
  if (direct != null) return direct;
  if (typeof res.body === 'string') return res.body;
  if (typeof res.data === 'string') return res.data;
  const bodyBuf = decodeBufferJson(res.body);
  if (bodyBuf != null) return bodyBuf;
  const dataBuf = decodeBufferJson(res.data);
  if (dataBuf != null) return dataBuf;
  if (typeof Buffer !== 'undefined' && res.body && Buffer.isBuffer(res.body)) return res.body.toString('utf8');
  if (typeof Buffer !== 'undefined' && res.data && Buffer.isBuffer(res.data)) return res.data.toString('utf8');
  return '';
}}
function parseS3JsonText(text) {{
  const trimmed = String(text || '').trim();
  if (!trimmed) return null;
  const outer = JSON.parse(trimmed);
  if (outer && outer.type === 'Buffer' && Array.isArray(outer.data)) {{
    const inner = new TextDecoder().decode(Uint8Array.from(outer.data));
    return JSON.parse(inner);
  }}
  return outer;
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
  const uploadUrl = presignPutUrl(key);
  const requestBody = typeof body === 'string'
    ? body
    : (() => {{
      const bytes = toBytes(body);
      return typeof Buffer !== 'undefined' ? Buffer.from(bytes) : bytes;
    }})();
  try {{
    await this.helpers.httpRequest({{
      method: 'PUT',
      url: uploadUrl,
      headers: {{ 'Content-Type': contentType }},
      body: requestBody,
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
function fileNameToLabel(fileName) {{
  const base = fileName.replace(/\\.[^.]+$/, '');
  return base.replace(/[-_]+/g, ' ').replace(/\\s+/g, ' ').trim();
}}
function isImageKey(key) {{
  return /\\.(jpe?g|png|webp|gif)$/i.test(key);
}}"""


def s3_linkedin_session_js():
    return """
function linkedinSessionKey(chatId) {
  return `linkedin-sessions/${chatId}.json`;
}
async function loadLinkedInSession(chatId) {
  const url = presignGetUrl(linkedinSessionKey(chatId));
  try {
    const raw = await this.helpers.httpRequest({ method: 'GET', url, json: false, timeout: 30000 });
    const text = readHttpText(raw);
    if (!text || !text.trim()) return null;
    const session = parseS3JsonText(text);
    if (!session?.run_id || session.deleted) return null;
    return session;
  } catch {
    return null;
  }
}
async function saveLinkedInSession(chatId, session) {
  await putObject.call(this, linkedinSessionKey(chatId), JSON.stringify(session), 'application/json');
}
async function deleteLinkedInSession(chatId) {
  await saveLinkedInSession(chatId, { deleted: true, deleted_at: Date.now() });
}"""


PARSE_OPENROUTER_JS = """function stripMarkdownFences(raw) {
  return String(raw || '')
    .replace(/^```(?:json)?\\s*/i, '')
    .replace(/\\s*```\\s*$/g, '')
    .trim();
}
function extractJsonObject(text) {
  const start = text.indexOf('{');
  if (start < 0) return '';
  let depth = 0;
  let inString = false;
  let escaped = false;
  for (let i = start; i < text.length; i++) {
    const ch = text[i];
    if (escaped) { escaped = false; continue; }
    if (ch === '\\\\' && inString) { escaped = true; continue; }
    if (ch === '"') { inString = !inString; continue; }
    if (inString) continue;
    if (ch === '{') depth++;
    if (ch === '}') {
      depth--;
      if (depth === 0) return text.slice(start, i + 1);
    }
  }
  const end = text.lastIndexOf('}');
  return end > start ? text.slice(start, end + 1) : text.slice(start);
}
function repairJsonStringNewlines(text) {
  let out = '';
  let inString = false;
  let escaped = false;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (escaped) {
      out += ch;
      escaped = false;
      continue;
    }
    if (ch === '\\\\') {
      out += ch;
      escaped = true;
      continue;
    }
    if (ch === '"') {
      inString = !inString;
      out += ch;
      continue;
    }
    if (inString && (ch === '\\n' || ch === '\\r')) {
      out += '\\\\n';
      continue;
    }
    out += ch;
  }
  return out;
}
function sanitizeJsonText(raw) {
  let content = stripMarkdownFences(raw);
  content = extractJsonObject(content);
  return content
    .replace(/[\\u201c\\u201d]/g, '"')
    .replace(/[\\u2018\\u2019]/g, "'")
    .replace(/^\\{\\s*\\[/, '{\"variants\":[')
    .replace(/,\\s*([}\\]])/g, '$1');
}
function tryParseJson(text) {
  return JSON.parse(text);
}
function parseOpenRouterJson(res, label) {
  if (res?.error) throw new Error(`${label}: ${res.error.message || JSON.stringify(res.error)}`);
  let content = res?.choices?.[0]?.message?.content || '';
  if (!content) throw new Error(`${label}: empty response`);
  const finish = res?.choices?.[0]?.finish_reason || '';
  if (finish === 'length') {
    throw new Error(`${label}: output truncated by token limit — retry or shorten post length.`);
  }
  const attempts = [
    () => tryParseJson(stripMarkdownFences(content)),
    () => tryParseJson(sanitizeJsonText(content)),
    () => tryParseJson(repairJsonStringNewlines(sanitizeJsonText(content))),
    () => tryParseJson(repairJsonStringNewlines(extractJsonObject(stripMarkdownFences(content)))),
  ];
  let lastErr;
  for (const attempt of attempts) {
    try {
      return attempt();
    } catch (e) {
      lastErr = e;
    }
  }
  throw new Error(`${label}: invalid JSON - ${String(content).slice(0, 300)} (${lastErr?.message || 'parse failed'})`);
}
function extractTopics(data) {
  if (Array.isArray(data)) return data;
  return data.topics || data.key_topics || data.video_topics || data.top5_topics || [];
}"""


READ_TELEGRAM_REPLY_JS = """function readTelegramReply(input) {
  const j = input?.json || {};
  return String(j.data?.text || j.message?.text || j.result?.text || j.text || '').trim();
}"""


def telegram_compose_js(bot_token: str = "") -> str:
    """Telegram media detection + binary download for compose clip uploads.

    n8n Cloud stores trigger downloads in filesystem mode — Code nodes must call
    getBinaryDataBuffer(), not read item.binary.data directly. When that fails,
    fall back to Telegram getFile + direct download using the bot token.
    """
    return f"""function detectTelegramVideo(msg) {{
  const m = msg || {{}};
  if (m.video?.file_id) {{
    return {{
      kind: 'video',
      file_id: m.video.file_id,
      file_name: m.video.file_name || '',
      mime_type: m.video.mime_type || 'video/mp4',
    }};
  }}
  if (m.document?.file_id && /^video\\//i.test(String(m.document.mime_type || ''))) {{
    return {{
      kind: 'document',
      file_id: m.document.file_id,
      file_name: m.document.file_name || '',
      mime_type: m.document.mime_type || 'video/mp4',
    }};
  }}
  if (m.animation?.file_id) {{
    return {{
      kind: 'animation',
      file_id: m.animation.file_id,
      file_name: m.animation.file_name || 'animation.mp4',
      mime_type: m.animation.mime_type || 'video/mp4',
    }};
  }}
  return null;
}}

async function readInputBinaryBytes(itemIndex, keys) {{
  const item = $input.first();
  const names = (keys && keys.length) ? keys : ['data'];
  for (const name of names) {{
    try {{
      const buf = await this.helpers.getBinaryDataBuffer(itemIndex ?? 0, name);
      if (buf && buf.length) {{
        return {{
          bytes: buf instanceof Uint8Array ? buf : new Uint8Array(buf),
          binaryKey: name,
          fileName: item.binary?.[name]?.fileName || '',
        }};
      }}
    }} catch (_) {{}}
  }}
  const binary = item.binary || {{}};
  for (const name of names) {{
    const raw = binary[name];
    if (!raw) continue;
    if (typeof raw.data === 'string') {{
      try {{
        return {{ bytes: fromBase64(raw.data), binaryKey: name, fileName: raw.fileName || '' }};
      }} catch (_) {{}}
    }}
    if (raw.data?.type === 'Buffer' && Array.isArray(raw.data.data)) {{
      return {{ bytes: Uint8Array.from(raw.data.data), binaryKey: name, fileName: raw.fileName || '' }};
    }}
    if (raw.data instanceof Uint8Array) {{
      return {{ bytes: raw.data, binaryKey: name, fileName: raw.fileName || '' }};
    }}
  }}
  return null;
}}

async function downloadTelegramFileById(fileId) {{
  const token = {json.dumps(bot_token or "")};
  if (!token) {{
    // Only reached once the Telegram Download Clip node and the trigger's own
    // download have both come back empty, so name those first — a bot token is
    // the last resort here, not the fix.
    throw new Error(
      'neither the Telegram Download Clip node nor the trigger returned the file. ' +
      'Check that the Telegram credential is set on the Telegram Download Clip node and that ' +
      'Download is ON in the Telegram Trigger. (A TELEGRAM_BOT_TOKEN in build/secrets_local.py ' +
      'adds one more fallback.)'
    );
  }}
  const meta = await this.helpers.httpRequest({{
    method: 'GET',
    url: `https://api.telegram.org/bot${{token}}/getFile?file_id=${{encodeURIComponent(fileId)}}`,
    json: true,
    timeout: 60000,
  }});
  const filePath = meta?.result?.file_path;
  if (!filePath) throw new Error(`Telegram getFile failed: ${{JSON.stringify(meta).slice(0, 200)}}`);
  const body = await this.helpers.httpRequest({{
    method: 'GET',
    url: `https://api.telegram.org/file/bot${{token}}/${{filePath}}`,
    json: false,
    encoding: 'arraybuffer',
    timeout: 120000,
  }});
  if (body instanceof ArrayBuffer) return new Uint8Array(body);
  if (typeof Buffer !== 'undefined' && Buffer.isBuffer(body)) return new Uint8Array(body);
  if (body && typeof body === 'object' && body.type === 'Buffer' && Array.isArray(body.data)) {{
    return Uint8Array.from(body.data);
  }}
  throw new Error('Telegram file download returned an unexpected body type');
}}

async function loadTelegramVideoBytes(itemIndex, msg) {{
  const media = detectTelegramVideo(msg);
  const fromInput = await readInputBinaryBytes.call(this, itemIndex, ['data', 'video', 'document', 'animation']);
  if (fromInput?.bytes?.length) {{
    return {{ ...fromInput, source: 'trigger', media }};
  }}
  if (media?.file_id) {{
    const bytes = await downloadTelegramFileById.call(this, media.file_id);
    return {{
      bytes,
      binaryKey: 'data',
      fileName: media.file_name || '',
      source: 'telegram_api',
      media,
    }};
  }}
  throw new Error(
    'No video on this message. Send an mp4 as a video or file (albums and forwards are fine). ' +
    'Photos, links, and voice notes are not clips.'
  );
}}"""


def resolve_telegram_chat_js(static_key: str, fallback_chat_id: str = "") -> str:
    """Resolve Telegram chat_id: message → workflow staticData → build-time fallback."""
    return f"""function resolveTelegramChatId(json, staticData) {{
  const direct = String(json?.chat_id || json?.message?.chat?.id || '').trim();
  if (direct && direct !== 'undefined') {{
    staticData[{json.dumps(static_key)}] = direct;
    return direct;
  }}
  const saved = String(staticData?.[{json.dumps(static_key)}] || '').trim();
  if (saved && saved !== 'undefined') return saved;
  const fallback = {json.dumps(fallback_chat_id or "")};
  if (fallback) return fallback;
  throw new Error(
    'No Telegram chat_id. Message this bot with /start from YOUR personal Telegram account ' +
    '(get your numeric ID from @userinfobot — never the bot\\'s own ID). ' +
    'Or set TELEGRAM_CHAT_ID in build/secrets_local.py and rebuild the workflow.'
  );
}}"""


class WorkflowBuilder:
    def __init__(self, x=0, y=300, dx=300):
        self.nodes = []
        self.connections = {}
        self.x = x
        self.y = y
        self.dx = dx
        self.lanes = {
            "main": y + 100,
            "sched": y,
            "tg": y + 200,
            "branch": y + 50,
            "publish": y + 250,
        }

    def nid(self):
        return str(uuid.uuid4())

    def P(self, col, lane="main"):
        return [self.x + col * self.dx, self.lanes[lane]]

    def add_node(self, name, node_type, params, position, type_version=1, extra=None):
        node = {
            "parameters": params,
            "type": node_type,
            "typeVersion": type_version,
            "position": position,
            "id": self.nid(),
            "name": name,
        }
        if extra:
            node.update(extra)
        self.nodes.append(node)
        return name

    def connect(self, src, dst, out_index=0, in_index=0):
        self.connections.setdefault(src, {}).setdefault("main", [])
        while len(self.connections[src]["main"]) <= out_index:
            self.connections[src]["main"].append([])
        self.connections[src]["main"][out_index].append(
            {"node": dst, "type": "main", "index": in_index}
        )

    def add_sticky(self, name, content, position, height=400, width=460):
        self.nodes.append({
            "parameters": {"content": content, "height": height, "width": width},
            "type": "n8n-nodes-base.stickyNote",
            "typeVersion": 1,
            "position": position,
            "id": self.nid(),
            "name": name,
        })

    def call_openrouter(
        self,
        name,
        system_prompt,
        user_content_js,
        position,
        model=OPENROUTER_MODEL_FAST,
        reasoning=None,
        timeout_ms=300000,
        title="LinkedIn Post Automation",
        max_tokens=None,
    ):
        reasoning_js = f"\nbody.reasoning = {json.dumps(reasoning)};" if reasoning else ""
        max_tokens_js = f"\nbody.max_tokens = {max_tokens};" if max_tokens else ""
        code = f"""const ctx = $input.first().json;
const userContent = {user_content_js};
const body = {{
  model: {json.dumps(model)},
  response_format: {{ type: 'json_object' }},
  messages: [
    {{ role: 'system', content: {json.dumps(system_prompt)} }},
    {{ role: 'user', content: userContent }}
  ],
}};{reasoning_js}{max_tokens_js}
const res = await this.helpers.httpRequest({{
  method: 'POST',
  url: 'https://openrouter.ai/api/v1/chat/completions',
  headers: {{
    Authorization: 'Bearer {OPENROUTER_KEY}',
    'Content-Type': 'application/json',
    'HTTP-Referer': 'https://n8n.io',
    'X-Title': {json.dumps(title)},
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
        self.add_node(name, "n8n-nodes-base.code", {"jsCode": code}, position, 2)
        return name

    def telegram_cred(self):
        return {
            "telegramApi": {
                "id": self.nid(),
                "name": "Telegram LinkedIn Bot",
            }
        }

    def linkedin_cred(self):
        return {
            "linkedInCommunityManagementOAuth2Api": {
                "id": self.nid(),
                "name": "LinkedIn Community Management",
            }
        }

    def dump(self, name, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({
                "name": name,
                "nodes": self.nodes,
                "connections": self.connections,
                "pinData": {},
                "settings": {"executionOrder": "v1"},
                "meta": {"templateCredsSetupCompleted": False, "instanceId": self.nid()},
            }, f, indent=2, ensure_ascii=False)
