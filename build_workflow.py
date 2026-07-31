#!/usr/bin/env python3
"""Rebuild reelsminiautomation.json — Railway S3 + Telegram."""
import json
import uuid

from build_secrets_placeholder import *
try:
    from build_secrets_local import *  # noqa: F403 — overrides placeholders when present locally
except ImportError:
    pass

OPENROUTER_MODEL_FAST = "openai/gpt-5-mini"
OPENROUTER_MODEL_HEAVY = "anthropic/claude-sonnet-5"

S3_IMAGES_PREFIX = "images/"

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
function toBase64(bytes) {{
  const u8 = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
  let bin = '';
  for (let i = 0; i < u8.length; i += 0x8000) {{
    bin += String.fromCharCode.apply(null, u8.subarray(i, i + 0x8000));
  }}
  return btoa(bin);
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
    return typeof res === 'string' ? res : JSON.stringify(res);
  }} catch (err) {{
    const status = err.statusCode || err.response?.statusCode || '';
    throw new Error(`S3 ${{method}} ${{status}}: ${{err.message || err}}`);
  }}
}}
function signPut(key, body, contentType) {{
  const now = new Date();
  const amzDate = now.toISOString().replace(/[:-]|\\.\\d{{3}}/g, '');
  const dateStamp = amzDate.slice(0, 8);
  const host = hostName();
  const payloadHash = sha256(body);
  const headerMap = {{
    'content-type': contentType,
    host,
    'x-amz-content-sha256': payloadHash,
    'x-amz-date': amzDate,
  }};
  const signedNames = Object.keys(headerMap).sort();
  const canonicalHeaders = signedNames.map((name) => `${{name}}:${{headerMap[name]}}\\n`).join('');
  const signedHeaders = signedNames.join(';');
  const canonicalRequest = ['PUT', '/' + encodePath(key), '', canonicalHeaders, signedHeaders, payloadHash].join('\\n');
  const credentialScope = `${{dateStamp}}/${{REGION}}/s3/aws4_request`;
  const stringToSign = ['AWS4-HMAC-SHA256', amzDate, credentialScope, sha256(canonicalRequest)].join('\\n');
  const signature = toHex(hmacSha256(getSigningKey(dateStamp), stringToSign));
  const authorization = `AWS4-HMAC-SHA256 Credential=${{ACCESS_KEY}}/${{credentialScope}}, SignedHeaders=${{signedHeaders}}, Signature=${{signature}}`;
  return {{ host, authorization, amzDate, payloadHash }};
}}
function describeS3Error(err) {{
  const status = err.statusCode || err.response?.statusCode || err.httpCode || '';
  const body = err.response?.body ?? err.response?.data ?? err.cause?.response?.body;
  if (typeof body === 'string') return `HTTP ${{status}}: ${{body.slice(0, 500)}}`;
  if (body && typeof body === 'object') {{
    if (typeof Buffer !== 'undefined' && Buffer.isBuffer(body)) return `HTTP ${{status}}: ${{body.toString('utf8').slice(0, 500)}}`;
    return `HTTP ${{status}}: ${{JSON.stringify(body).slice(0, 500)}}`;
  }}
  return `HTTP ${{status || 'error'}}: ${{err.message || err}}`;
}}
async function putObject(key, body, contentType = 'application/octet-stream') {{
  const bytes = toBytes(body);
  const {{ host, authorization, amzDate, payloadHash }} = signPut(key, bytes, contentType);
  const path = `/${{encodePath(key)}}`;
  try {{
    await this.helpers.httpRequest({{
      method: 'PUT',
      url: `https://${{host}}${{path}}`,
      headers: {{
        'Content-Type': contentType,
        'x-amz-content-sha256': payloadHash,
        'x-amz-date': amzDate,
        Authorization: authorization,
      }},
      body: typeof Buffer !== 'undefined' ? Buffer.from(bytes) : bytes,
      json: false,
    }});
  }} catch (err) {{
    throw new Error(`S3 PUT ${{describeS3Error(err)}}`);
  }}
}}
function telegramSafeUrl(url) {{
  return String(url).replace(/_/g, '%5F');
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
  return telegramSafeUrl(`https://${{host}}/${{encodePath(key)}}?${{query}}&X-Amz-Signature=${{signature}}`);
}}
function presignPutUrl(key, contentType) {{
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
    'X-Amz-SignedHeaders': 'content-type;host',
  }};
  const query = Object.keys(params).sort().map((k) => `${{encodeURIComponent(k)}}=${{encodeURIComponent(params[k])}}`).join('&');
  const canonicalHeaders = `content-type:${{contentType}}\\nhost:${{host}}\\n`;
  const signedHeaders = 'content-type;host';
  const canonicalRequest = ['PUT', '/' + encodePath(key), query, canonicalHeaders, signedHeaders, 'UNSIGNED-PAYLOAD'].join('\\n');
  const credentialScope = `${{dateStamp}}/${{REGION}}/s3/aws4_request`;
  const stringToSign = ['AWS4-HMAC-SHA256', amzDate, credentialScope, sha256(canonicalRequest)].join('\\n');
  const signature = toHex(hmacSha256(getSigningKey(dateStamp), stringToSign));
  return telegramSafeUrl(`https://${{host}}/${{encodePath(key)}}?${{query}}&X-Amz-Signature=${{signature}}`);
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


LOAD_S3_BRAND_IMAGES_JS = s3_common_js() + """
const ctx = $('Parse Script Package').first().json;
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
    images_folder_note: `Upload context-named images to s3://${BUCKET}/${IMAGES_PREFIX} (e.g. vending-machine-red.jpg, vending-machine-touch.png)`
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

GENERATE_VOICEOVER_JS = s3_common_js() + f"""
const CARTESIA_API_KEY = {json.dumps(CARTESIA_API_KEY)};
const CARTESIA_VOICE_ID = {json.dumps(CARTESIA_VOICE_ID)};
const ELEVENLABS_API_KEY = {json.dumps(ELEVENLABS_KEY)};
const MIN_AUDIO_BYTES = 1000;

const ctx = $input.first().json;
const text = String(ctx.script?.full_script || '').trim();
const elevenVoiceId = ctx.script?.elevenlabs_voice_id;
if (!text) throw new Error('Missing full_script in script package');

function describeBody(body) {{
  if (body == null) return 'empty response';
  if (typeof body === 'string') return body.slice(0, 300);
  if (typeof Buffer !== 'undefined' && Buffer.isBuffer(body)) return body.toString('utf8').slice(0, 300);
  if (body instanceof ArrayBuffer || ArrayBuffer.isView(body)) {{
    try {{
      const u8 = body instanceof ArrayBuffer ? new Uint8Array(body) : new Uint8Array(body.buffer, body.byteOffset, body.byteLength);
      return Buffer.from(u8).toString('utf8').slice(0, 300);
    }} catch {{ return '[binary]'; }}
  }}
  if (body.type === 'Buffer' && Array.isArray(body.data)) {{
    try {{ return Buffer.from(body.data).toString('utf8').slice(0, 300); }} catch {{ return '[serialized buffer]'; }}
  }}
  return JSON.stringify(body).slice(0, 300);
}}

function isSerializedBuffer(data) {{
  return !!(data && typeof data === 'object' && data.type === 'Buffer' && Array.isArray(data.data));
}}

function normalizeAudioBytes(raw, label) {{
  let data = raw;
  for (let i = 0; i < 3; i++) {{
    if (data == null) break;
    if (typeof Buffer !== 'undefined' && Buffer.isBuffer(data)) break;
    if (data instanceof ArrayBuffer || ArrayBuffer.isView(data)) break;
    if (isSerializedBuffer(data)) break;
    if (typeof data === 'string') break;
    if (typeof data === 'object') {{
      if (data.body !== undefined) {{ data = data.body; continue; }}
      if (data.data !== undefined) {{ data = data.data; continue; }}
      if (data.error || data.message || data.detail) {{
        throw new Error(`${{label}} API error: ${{describeBody(data)}}`);
      }}
    }}
    break;
  }}

  let bytes;
  if (isSerializedBuffer(data)) {{
    bytes = new Uint8Array(Buffer.from(data.data));
  }} else if (typeof Buffer !== 'undefined' && Buffer.isBuffer(data)) {{
    bytes = new Uint8Array(data);
  }} else if (data instanceof ArrayBuffer) {{
    bytes = new Uint8Array(data);
  }} else if (ArrayBuffer.isView(data)) {{
    bytes = new Uint8Array(data.buffer, data.byteOffset, data.byteLength);
  }} else if (typeof data === 'string') {{
    bytes = new Uint8Array(Buffer.from(data, 'binary'));
  }} else {{
    throw new Error(`${{label}}: unsupported audio response type ${{typeof data}} (${{describeBody(data)}})`);
  }}

  if (!bytes.length || bytes.length < MIN_AUDIO_BYTES) {{
    throw new Error(`${{label}}: audio too small (${{bytes.length}} bytes) — ${{describeBody(bytes)}}`);
  }}
  return bytes;
}}

async function requestAudio(options, label) {{
  const base = {{
    ...options,
    encoding: 'arraybuffer',
    json: false,
    returnFullResponse: false,
  }};
  try {{
    const raw = await this.helpers.httpRequest(base);
    return normalizeAudioBytes(raw, label);
  }} catch (err) {{
    const status = err.statusCode || err.response?.statusCode || err.httpCode || '';
    const body = err.response?.body ?? err.response?.data ?? err.cause?.response?.body;
    throw new Error(`${{label}} HTTP ${{status || 'error'}}: ${{describeBody(body) || err.message || err}}`);
  }}
}}

async function synthesizeCartesia() {{
  return requestAudio.call(this, {{
    method: 'POST',
    url: 'https://api.cartesia.ai/tts/bytes',
    headers: {{
      Authorization: `Bearer ${{CARTESIA_API_KEY}}`,
      'Cartesia-Version': '2024-11-13',
      'Content-Type': 'application/json',
      Accept: 'audio/mpeg',
    }},
    body: {{
      model_id: 'sonic-3.5',
      transcript: text,
      voice: {{ mode: 'id', id: CARTESIA_VOICE_ID }},
      output_format: {{ container: 'mp3', sample_rate: 44100 }},
    }},
  }}, 'Cartesia');
}}

async function synthesizeElevenLabs() {{
  if (!elevenVoiceId) throw new Error('Missing elevenlabs_voice_id for ElevenLabs fallback');
  return requestAudio.call(this, {{
    method: 'POST',
    url: `https://api.elevenlabs.io/v1/text-to-speech/${{elevenVoiceId}}`,
    headers: {{
      'xi-api-key': ELEVENLABS_API_KEY,
      'Content-Type': 'application/json',
      Accept: 'audio/mpeg',
    }},
    body: {{
      text,
      model_id: 'eleven_flash_v2_5',
      voice_settings: {{ stability: 0.5, similarity_boost: 0.75 }},
    }},
  }}, 'ElevenLabs');
}}

let bytes;
let tts_provider = 'cartesia';
try {{
  bytes = await synthesizeCartesia.call(this);
}} catch (cartesiaErr) {{
  try {{
    bytes = await synthesizeElevenLabs.call(this);
    tts_provider = 'elevenlabs';
  }} catch (elevenErr) {{
    throw new Error(`TTS failed. Cartesia: ${{cartesiaErr.message || cartesiaErr}}. ElevenLabs: ${{elevenErr.message || elevenErr}}`);
  }}
}}

const key = `reels-voiceovers/${{ctx.topic_slug}}-${{ctx.run_id}}.mp3`;
const voiceover_url = presignGetUrl(key);
const upload_url = presignPutUrl(key, 'audio/mpeg');
const fileName = `${{ctx.topic_slug}}-${{ctx.run_id}}.mp3`;

return [{{
  json: {{
    ...ctx,
    voiceover_key: key,
    voiceover_url,
    upload_url,
    storage_bucket: BUCKET,
    tts_provider,
    voiceover_bytes: bytes.length,
  }},
  binary: {{
    voiceover: {{
      data: toBase64(bytes),
      mimeType: 'audio/mpeg',
      fileExtension: 'mp3',
      fileName,
    }},
  }},
}}];"""

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


x, y, dx = 0, 300, 300

# TRIGGERS
add_node("Schedule Trigger", "n8n-nodes-base.scheduleTrigger", {
    "rule": {"interval": [{"field": "cronExpression", "expression": "0 9 * * *"}]}
}, [x, y], 1.2)

add_node("Telegram Trigger", "n8n-nodes-base.telegramTrigger", {
    "updates": ["message"], "additionalFields": {},
}, [x, y + 200], 1.2, {"webhookId": nid()})

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
return [{ json: $json }];"""
}, [x + dx, y + 200], 2)

add_node("IF Manual Command", "n8n-nodes-base.if", {
    "conditions": {
        "options": {"caseSensitive": False, "leftValue": "", "typeValidation": "loose", "version": 2},
        "conditions": [
            {"id": nid(), "leftValue": "={{ $json.message.text }}", "rightValue": "/generate", "operator": {"type": "string", "operation": "equals"}},
            {"id": nid(), "leftValue": "={{ $json.message.text }}", "rightValue": "/topics", "operator": {"type": "string", "operation": "equals"}},
            {"id": nid(), "leftValue": "={{ $json.message.text }}", "rightValue": "generate", "operator": {"type": "string", "operation": "equals"}},
        ],
        "combinator": "or",
    },
    "looseTypeValidation": True, "options": {},
}, [x + dx, y + 200], 2.2)

RUN_ID_JS = """const d = new Date();
const p = (n) => String(n).padStart(2, '0');
const run_id = `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}-${p(d.getHours())}${p(d.getMinutes())}`;"""

add_node("Set Manual Context", "n8n-nodes-base.code", {
    "jsCode": RUN_ID_JS + """
const staticData = $getWorkflowStaticData('global');
const chat_id = String($json.message.chat.id);
staticData.telegram_chat_id = chat_id;
return [{ json: {
  chat_id,
  trigger_mode: 'manual',
  run_id,
} }];"""
}, [x + 2 * dx, y + 120], 2)

add_node("Set Scheduled Context", "n8n-nodes-base.code", {
    "jsCode": RUN_ID_JS + f"""
const staticData = $getWorkflowStaticData('global');
const chat_id = staticData.telegram_chat_id || {json.dumps(TELEGRAM_CHAT_ID)};
if (!chat_id) {{
  throw new Error('No Telegram chat_id saved. Message your bot /start from your personal account. Get your user ID from @userinfobot — never use the bot\\'s own ID.');
}}
return [{{ json: {{
  chat_id,
  trigger_mode: 'scheduled',
  run_id,
}} }}];"""
}, [x + dx, y], 2)

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
}, [x + 3 * dx, y + 100], 4.2)

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
}
function extractTopics(data) {
  if (Array.isArray(data)) return data;
  return data.topics || data.key_topics || data.video_topics || data.top5_topics || [];
}"""


def call_openrouter(name, system_prompt, user_content_js, position, model=OPENROUTER_MODEL_FAST, reasoning=None, timeout_ms=300000):
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
    'X-Title': 'Reels Mini Automation',
  }},
  body,
  json: true,
  timeout: {timeout_ms},
}});
return [{{ json: {{ ...ctx, ...res }} }}];"""
    add_node(name, "n8n-nodes-base.code", {"jsCode": code}, position, 2)
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
}, [x + 3 * dx + 140, y + 100], 2)

# TOPICS — light model: summarize search results into 5 ranked topic cards
call_openrouter(
    "OpenRouter Top 5 Topics",
    'You are a viral short-form content strategist for the vending machine industry. Return ONLY valid JSON. The root object MUST use the exact key "topics" (not key_topics) containing an array of exactly 5 objects. Each object: rank (1-5), title, hook, why_viral, best_market (India|Dubai|US|Global).',
    '`Analyze Tavily results and produce 5 ranked vending-machine marketing video topics for Shorts/Reels.\\n\\nAnswer: ${ctx.tavily_answer}\\n\\nResults: ${JSON.stringify(ctx.tavily_results)}`',
    [x + 4 * dx, y + 100],
    model=OPENROUTER_MODEL_FAST,
)

add_node("Parse Top 5 Topics", "n8n-nodes-base.code", {
    "jsCode": PARSE_OPENROUTER_JS + """
const item = $input.first().json;
const data = parseOpenRouterJson(item, 'OpenRouter Top 5 Topics');
const topics = extractTopics(data);
if (!topics.length) throw new Error(`No topics returned. Keys: ${Object.keys(data).join(', ')}`);
const lines = topics.map((t, i) => `${t.rank || i+1}. ${t.title}\\n   Hook: ${t.hook}\\n   ${t.why_viral} | Market: ${t.best_market || 'Global'}`).join('\\n\\n');
const modeLabel = item.trigger_mode === 'scheduled' ? 'SCHEDULED' : 'MANUAL';
let topic_message = `VENDING MACHINE TOPIC PICKER\\nRun: ${item.run_id} (${modeLabel})\\n\\nPick ONE topic (reply 1-5):\\n\\n${lines}\\n\\nReply with a number from 1 to 5.`;
if (topic_message.length > 3900) topic_message = topic_message.slice(0, 3880) + '\\n...(truncated)';
return [{ json: { ...item, topics, topic_message } }];"""
}, [x + 5 * dx, y + 100], 2)

add_node("Wait For Topic Selection", "n8n-nodes-base.telegram", {
    "operation": "sendAndWait", "chatId": "={{ $json.chat_id }}",
    "message": "={{ $json.topic_message }}",
    "responseType": "freeText",
    "options": {
        "appendAttribution": False,
        "limitWaitTime": {"values": {"limitWaitTime": 24, "limitWaitTimeUnit": "hours"}},
    },
}, [x + 6 * dx, y + 100], 1.2, {"webhookId": nid(), "onError": "stopWorkflow"})

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
const pick = parseInt((raw.match(/[1-5]/) || [])[0], 10);
if (!pick) throw new Error(`Invalid topic selection "${raw}". Reply with a number from 1 to 5.`);
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
}, [x + 7 * dx, y + 100], 2)

# SCRIPT — Sonnet 5: full creative package (script, scenes, bible, SRT)
call_openrouter(
    "OpenRouter Script Package",
    """You are a viral YouTube Shorts scriptwriter for vending machine marketing.
Return ONLY valid JSON: hook, caption_1-4, cta, full_script (max 35 sec), elevenlabs_voice_id, elevenlabs_voice_name, voice_reason, subtitles_srt,
production_bible (story_arc, protagonist_pov, primary_location, time_of_day, color_grade, hero_subject, continuity_locks),
scenes (exactly 5 objects with scene_index, clip_number, timeline_start/end, narrative_beat, what_happened_before, what_happens_in_this_clip, what_happens_next, on_screen_text, subtitle_in_at/out, voiceover_segment, visual_brief, end_frame_state, transition_out).
Voices: Rachel 21m00Tcm4TlvDq8ikWAM | Adam pNInz6obpgDQGcFmaJgB | Josh TxGEqnHWrfWFTfGW9XjX | Bella EXAVITQu4vr4xnSDxMaL | Antoni ErXwobaYiN019PkySvjV
5 scenes x 8 sec. Arc: HOOK, SETUP, PROOF, EMOTION, CTA.""",
    '`Topic: ${ctx.selected_topic.title}\\nHook: ${ctx.selected_topic.hook}\\nMarket: ${ctx.selected_topic.best_market}\\nWhy viral: ${ctx.selected_topic.why_viral}`',
    [x + 8 * dx, y + 100],
    model=OPENROUTER_MODEL_HEAVY,
    reasoning={"enabled": True, "effort": "medium"},
)

add_node("Parse Script Package", "n8n-nodes-base.code", {
    "jsCode": PARSE_OPENROUTER_JS + """
const item = $input.first().json;
const script = parseOpenRouterJson(item, 'OpenRouter Script Package');
if (!script.scenes?.length) throw new Error('Script package missing scenes array');
if (!script.elevenlabs_voice_id) throw new Error('Script package missing elevenlabs_voice_id');
if (!script.full_script) throw new Error('Script package missing full_script');
return [{ json: { ...item, script } }];"""
}, [x + 9 * dx, y + 100], 2)

# S3 BRAND IMAGES
add_node("Load S3 Brand Images", "n8n-nodes-base.code", {
    "jsCode": LOAD_S3_BRAND_IMAGES_JS,
}, [x + 10 * dx, y + 100], 2)

# MATCH IMAGES — light model: pick best image per scene from a fixed list
call_openrouter(
    "OpenRouter Match Images",
    """You match context-named brand reference images to a 5-scene vending machine Short.
Image names describe visual context (examples: 'vending machine red', 'vending machine touch', 'vending machine night').
Return ONLY valid JSON. The root object MUST use the exact key "matched_scenes" containing an array of exactly 5 objects.
Each object: scene_index (0-4), clip_number (1/5..5/5), reference_image_name (EXACT name from list), reference_image_key, reference_image_url, match_reason.
Rules: use ONLY images from the provided list; pick the best visual match per scene; reuse an image only if no better option exists; reference_image_name must match list exactly.""",
    '`Topic: ${ctx.selected_topic?.title}\\nScenes: ${JSON.stringify(ctx.script.scenes)}\\nProduction bible: ${JSON.stringify(ctx.script.production_bible)}\\nAvailable images: ${JSON.stringify(ctx.brand_files)}`',
    [x + 11 * dx, y + 100],
    model=OPENROUTER_MODEL_FAST,
)

add_node("Parse Match Images", "n8n-nodes-base.code", {
    "jsCode": PARSE_OPENROUTER_JS + """
const item = $input.first().json;
const data = parseOpenRouterJson(item, 'OpenRouter Match Images');
if (!data.matched_scenes?.length) throw new Error(`No matched_scenes returned. Keys: ${Object.keys(data).join(', ')}`);
const brandByName = Object.fromEntries((item.brand_files || []).map(f => [f.name.toLowerCase(), f]));
const brandByKey = Object.fromEntries((item.brand_files || []).map(f => [f.key, f]));
const matched_scenes = (data.matched_scenes || []).map(m => {
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
const image_links_text = matched_scenes.map(m =>
  `Clip ${m.clip_number || (Number(m.scene_index || 0) + 1) + '/5'}: ${m.reference_image_name}\\n${m.reference_image_url || 'no-url'}`
).join('\\n\\n');
const unique_images = [...new Map(matched_scenes.filter(m => m.reference_image_url).map(m => [m.reference_image_url, m])).values()];
const unique_images_text = unique_images.map((m, i) => `${i + 1}. ${m.reference_image_name}\\n${m.reference_image_url}`).join('\\n\\n');
return [{ json: { ...item, matched_scenes, image_links_text, unique_images_text, unique_images } }];"""
}, [x + 12 * dx, y + 100], 2)

# ELEVENLABS — code node avoids expression syntax issues in HTTP jsonBody
add_node("Generate Voiceover", "n8n-nodes-base.code", {
    "jsCode": GENERATE_VOICEOVER_JS,
}, [x + 13 * dx, y + 100], 2)

add_node("Upload Voiceover to S3", "n8n-nodes-base.httpRequest", {
    "method": "PUT",
    "url": "={{ $json.upload_url }}",
    "sendHeaders": True,
    "headerParameters": {"parameters": [
        {"name": "Content-Type", "value": "audio/mpeg"},
    ]},
    "sendBody": True,
    "contentType": "binaryData",
    "inputDataFieldName": "voiceover",
    "options": {
        "response": {
            "response": {
                "neverError": True,
                "responseFormat": "text",
            }
        }
    },
}, [x + 13.5 * dx, y + 100], 4.2)

add_node("Restore Voiceover Context", "n8n-nodes-base.code", {
    "jsCode": """const ctx = $('Generate Voiceover').first().json;
if (!ctx.voiceover_url) throw new Error('Voiceover context missing after S3 upload');
return [{ json: ctx }];"""
}, [x + 14 * dx, y + 100], 2)

# SYNC MAP
add_node("Build Sync Map", "n8n-nodes-base.code", {
    "jsCode": """const ctx = $input.first().json;
const srt = ctx.script?.subtitles_srt || '';
const scenes = ctx.script?.scenes || [];
function parseSrtTime(t) {
  const [h, m, rest] = t.trim().split(':');
  const [s, ms] = rest.split(',');
  return (+h)*3600+(+m)*60+(+s)+(+ms)/1000;
}
const cues = [];
for (const block of srt.trim().split(/\\n\\n+/)) {
  const lines = block.split('\\n');
  const times = lines.find(l => l.includes('-->'));
  if (!times) continue;
  const [start, end] = times.split('-->').map(s => s.trim());
  cues.push({ start: parseSrtTime(start), end: parseSrtTime(end), text: lines.slice(lines.indexOf(times)+1).join(' ').trim() });
}
const sync_windows = [0,8,16,24,32].map((start,i) => {
  const end = start+8;
  const matched = (ctx.matched_scenes||[]).find(m => m.scene_index===i)||{};
  return {
    clip_number: `${i+1}/5`,
    timeline_label: `00:${String(start).padStart(2,'0')}–00:${String(end).padStart(2,'0')}`,
    spoken_text: cues.filter(c=>c.start<end&&c.end>start).map(c=>c.text).join(' ') || (scenes[i]?.voiceover_segment||''),
    scene: scenes[i]||{}, reference_image_name: matched.reference_image_name||'none', reference_image_url: matched.reference_image_url||''
  };
});
return [{ json: { ...ctx, sync_windows } }];"""
}, [x + 14 * dx, y + 100], 2)

# FLOW PROMPTS — Sonnet 5: director-level multi-clip continuity prompts
call_openrouter(
    "OpenRouter Flow Prompts",
    """Film director cutting a 40-sec vending Short into 5 seamless 8-sec Google Flow clips.
Return ONLY one valid JSON object. No markdown, no commentary, no reasoning text.
Root object keys: clip_prompts (array of exactly 5 objects) and production_bible_summary (string).
Each clip_prompts item: clip_number (string like 1/5), prompt_text (string, max 900 chars, escape quotes as backslash-quote, use \\n for line breaks).
Each prompt_text MUST include: STORY CONTINUITY, VOICEOVER SYNC, SUBTITLE SYNC, CONTINUITY LOCKS, REFERENCE IMAGE (name + URL), VISUAL, MOTION (3 shots), TRANSITION OUT.
9:16, premium cinematic, external voiceover only. Clip roles: 1=HOOK, 2=SETUP, 3=PROOF, 4=EMOTION, 5=CTA.""",
    '`Topic: ${ctx.selected_topic.title}\\nScript: ${ctx.script.full_script}\\nVoice URL: ${ctx.voiceover_url}\\nBible: ${JSON.stringify(ctx.script.production_bible)}\\nSync: ${JSON.stringify(ctx.sync_windows)}\\nImages: ${JSON.stringify(ctx.matched_scenes)}`',
    [x + 15 * dx, y + 100],
    model=OPENROUTER_MODEL_HEAVY,
    reasoning={"enabled": True, "effort": "medium"},
)

add_node("Parse Flow Prompts", "n8n-nodes-base.code", {
    "jsCode": PARSE_OPENROUTER_JS + """
const item = $input.first().json;
const flow = parseFlowPayload(item);
const prompts = flow.clip_prompts || flow.clipPrompts || [];
if (!prompts.length) throw new Error(`No clip_prompts returned. Keys: ${Object.keys(flow).join(', ')}`);
const flowText = prompts.map((p,i) => `${'='.repeat(40)}\\nCLIP ${p.clip_number||(i+1)+'/5'}\\n${'='.repeat(40)}\\n${p.prompt_text}`).join('\\n\\n');
const bible = flow.production_bible_summary || JSON.stringify(item.script?.production_bible);
const script_json = JSON.stringify({ selected_topic: item.selected_topic, script: item.script, matched_scenes: item.matched_scenes, run_id: item.run_id }, null, 2);
return [{ json: {
  ...item, clip_prompts: prompts, production_bible_summary: bible,
  flow_prompts_text: flowText, script_json,
  subtitles_srt: item.script?.subtitles_srt || ''
}}];"""
}, [x + 16 * dx, y + 100], 2)

UPLOAD_MANIFEST_JS = s3_common_js() + """
const ctx = $input.first().json;
const manifest = {
  run_id: ctx.run_id,
  topic_slug: ctx.topic_slug,
  chat_id: ctx.chat_id,
  selected_topic: ctx.selected_topic,
  voiceover_url: ctx.voiceover_url,
  voiceover_key: ctx.voiceover_key,
  subtitles_srt: ctx.script?.subtitles_srt || ctx.subtitles_srt || '',
  sync_windows: ctx.sync_windows || [],
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
    subtitles_srt: ctx.script?.subtitles_srt,
    production_bible: ctx.script?.production_bible,
  },
  created_at: new Date().toISOString(),
};
const key = `reels-manifests/${ctx.run_id}.json`;
const bytes = new TextEncoder().encode(JSON.stringify(manifest, null, 2));
await putObject.call(this, key, bytes, 'application/json');
const manifest_url = presignGetUrl(key);
return [{ json: { ...ctx, manifest_key: key, manifest_url } }];"""

add_node("Upload Manifest to S3", "n8n-nodes-base.code", {
    "jsCode": UPLOAD_MANIFEST_JS,
}, [x + 17 * dx, y + 100], 2)

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

const sections = [
  `VIDEO PACKAGE READY\\nTopic: ${ctx.selected_topic?.title}\\nRun: ${ctx.run_id}\\nVoice: ${ctx.script?.elevenlabs_voice_name}`,
  `VOICEOVER (7-day link)\\n${ctx.voiceover_url}`,
  imageSection,
  perClipImages,
  flowText ? `FLOW PROMPTS (copy to Google Flow)\\n${flowText}` : '',
  `COMPOSE FINAL REEL\\nAfter Google Flow clips are ready:\\n1) /compose ${ctx.run_id}\\n2) Upload 5 clips\\n3) Send done`,
];

const telegram_chunks = packSections(sections);
return telegram_chunks.map((telegram_message, i) => ({
  json: {
    ...ctx,
    telegram_message,
    telegram_chunk: i + 1,
    telegram_chunk_total: telegram_chunks.length,
  },
}));"""
}, [x + 18 * dx, y + 100], 2)

add_node("Send Final Package", "n8n-nodes-base.telegram", {
    "chatId": "={{ $json.chat_id }}", "text": "={{ $json.telegram_message }}",
    "additionalFields": {"appendAttribution": False},
}, [x + 19 * dx, y + 100], 1.2, {"webhookId": nid()})

nodes.append({
    "parameters": {
        "content": f"""## Railway S3 + Telegram Setup

**Configured:** Railway bucket `{RAILWAY_S3_BUCKET}`

**Still configure:**
- Telegram bot credential on Trigger + ALL Telegram nodes (same bot token)
- First-time setup: open bot → send `/start` (any message saves your chat_id for scheduled runs)

### Telegram chat ID
- Must be YOUR personal user ID from @userinfobot
- Do NOT use the bot's own ID (causes "bot can't send messages to the bot")
- Any /start message to your bot saves the correct chat_id automatically

### OpenRouter model tiers
- **Fast** (`{OPENROUTER_MODEL_FAST}`): Top 5 Topics, Match Images
- **Heavy** (`{OPENROUTER_MODEL_HEAVY}`): Script Package (medium reasoning), Flow Prompts (high reasoning)

### Brand images (Railway S3)
Upload to folder: `{S3_IMAGES_PREFIX}`
- Auto-creates `images/.keep` if folder is empty
- Name files by context, e.g. `vending-machine-red.jpg`, `vending-machine-touch.png`
- AI reads names + matches best image per scene
- 7-day presigned download links sent in Telegram

### Voiceovers (Railway S3)
- Path: `reels-voiceovers/{{slug}}-{{run_id}}.mp3`

### Topic selection (ALL triggers)
- Scheduled + manual runs ALWAYS send top-5 topics to Telegram and wait for reply 1-5
- Workflow does NOT continue until you pick a topic

### Voiceover TTS
- Primary: Cartesia sonic-3.5 (`CARTESIA_VOICE_ID` in build_workflow.py)
- Fallback: ElevenLabs if Cartesia fails

### Final Telegram order
1. Flow prompts
2. Voiceover link
3. Reference image links (per clip + unique list)

### Compose (separate workflow)
- Manifest saved: `reels-manifests/{{run_id}}.json`
- Use Reels Compose Automation: `/compose {{run_id}}`""",
        "height": 440, "width": 460,
    },
    "type": "n8n-nodes-base.stickyNote", "typeVersion": 1,
    "position": [-220, 60], "id": nid(), "name": "Setup Notes",
})

# CONNECTIONS
connect("Schedule Trigger", "Set Scheduled Context")
connect("Telegram Trigger", "Save Telegram Chat ID")
connect("Save Telegram Chat ID", "IF Manual Command")
connect("IF Manual Command", "Set Manual Context")
connect("Set Manual Context", "Tavily Search")
connect("Set Scheduled Context", "Tavily Search")
connect("Tavily Search", "Attach Run Context")
connect("Attach Run Context", "OpenRouter Top 5 Topics")
connect("OpenRouter Top 5 Topics", "Parse Top 5 Topics")
connect("Parse Top 5 Topics", "Wait For Topic Selection")
connect("Wait For Topic Selection", "Parse Topic Selection")
connect("Parse Topic Selection", "OpenRouter Script Package")
connect("OpenRouter Script Package", "Parse Script Package")
connect("Parse Script Package", "Load S3 Brand Images")
connect("Load S3 Brand Images", "OpenRouter Match Images")
connect("OpenRouter Match Images", "Parse Match Images")
connect("Parse Match Images", "Generate Voiceover")
connect("Generate Voiceover", "Upload Voiceover to S3")
connect("Upload Voiceover to S3", "Restore Voiceover Context")
connect("Restore Voiceover Context", "Build Sync Map")
connect("Build Sync Map", "OpenRouter Flow Prompts")
connect("OpenRouter Flow Prompts", "Parse Flow Prompts")
connect("Parse Flow Prompts", "Upload Manifest to S3")
connect("Upload Manifest to S3", "Format Final Package")
connect("Format Final Package", "Send Final Package")

with open("reelsminiautomation.json", "w", encoding="utf-8") as f:
    json.dump({
        "name": "Reels Mini Automation",
        "nodes": nodes,
        "connections": connections,
        "pinData": {},
        "settings": {"executionOrder": "v1"},
        "meta": {"templateCredsSetupCompleted": False, "instanceId": nid()},
    }, f, indent=2, ensure_ascii=False)

print(f"Done: {len(nodes)} nodes")
