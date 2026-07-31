const te = new TextEncoder();
const ENDPOINT_HOST = "t3.storageapi.dev";
const BUCKET = "lightweight-vault-pew0g4o";
const REGION = "auto";
const ACCESS_KEY = "YOUR_S3_ACCESS_KEY";
const SECRET_KEY = "YOUR_S3_SECRET_KEY";
const EXPIRES = 604800;
const IMAGES_PREFIX = "images/";

function toHex(bytes) {
  return Array.from(bytes).map((b) => b.toString(16).padStart(2, '0')).join('');
}
function toBytes(data) {
  if (typeof data === 'string') return te.encode(data);
  if (data instanceof Uint8Array) return data;
  if (ArrayBuffer.isView(data)) return new Uint8Array(data.buffer, data.byteOffset, data.byteLength);
  return te.encode(String(data));
}
function toBase64(bytes) {
  const u8 = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
  let bin = '';
  for (let i = 0; i < u8.length; i += 0x8000) {
    bin += String.fromCharCode.apply(null, u8.subarray(i, i + 0x8000));
  }
  return btoa(bin);
}
function fromBase64(b64) {
  const bin = atob(b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return bytes;
}
function rotr(n, x) { return (x >>> n) | (x << (32 - n)); }
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
function sha256Raw(msgBytes) {
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
  for (let off = 0; off < withLen.length; off += 64) {
    for (let i = 0; i < 16; i++) w[i] = dv.getUint32(off + i * 4, false);
    for (let i = 16; i < 64; i++) {
      const s0 = rotr(7, w[i - 15]) ^ rotr(18, w[i - 15]) ^ (w[i - 15] >>> 3);
      const s1 = rotr(17, w[i - 2]) ^ rotr(19, w[i - 2]) ^ (w[i - 2] >>> 10);
      w[i] = (w[i - 16] + s0 + w[i - 7] + s1) >>> 0;
    }
    let a = h0, b = h1, c = h2, d = h3, e = h4, f = h5, g = h6, hh = h7;
    for (let i = 0; i < 64; i++) {
      const S1 = rotr(6, e) ^ rotr(11, e) ^ rotr(25, e);
      const ch = (e & f) ^ (~e & g);
      const t1 = (hh + S1 + ch + SHA_K[i] + w[i]) >>> 0;
      const S0 = rotr(2, a) ^ rotr(13, a) ^ rotr(22, a);
      const maj = (a & b) ^ (a & c) ^ (b & c);
      const t2 = (S0 + maj) >>> 0;
      hh = g; g = f; f = e; e = (d + t1) >>> 0; d = c; c = b; b = a; a = (t1 + t2) >>> 0;
    }
    h0 = (h0 + a) >>> 0; h1 = (h1 + b) >>> 0; h2 = (h2 + c) >>> 0; h3 = (h3 + d) >>> 0;
    h4 = (h4 + e) >>> 0; h5 = (h5 + f) >>> 0; h6 = (h6 + g) >>> 0; h7 = (h7 + hh) >>> 0;
  }
  const out = new Uint8Array(32);
  const outDv = new DataView(out.buffer);
  outDv.setUint32(0, h0, false); outDv.setUint32(4, h1, false); outDv.setUint32(8, h2, false); outDv.setUint32(12, h3, false);
  outDv.setUint32(16, h4, false); outDv.setUint32(20, h5, false); outDv.setUint32(24, h6, false); outDv.setUint32(28, h7, false);
  return out;
}
function sha256(data) {
  return toHex(sha256Raw(toBytes(data)));
}
function hmacSha256(key, data) {
  const block = 64;
  let k = toBytes(key);
  if (k.length > block) k = sha256Raw(k);
  if (k.length < block) {
    const padded = new Uint8Array(block);
    padded.set(k);
    k = padded;
  }
  const o = new Uint8Array(block);
  const i = new Uint8Array(block);
  for (let j = 0; j < block; j++) {
    o[j] = k[j] ^ 0x5c;
    i[j] = k[j] ^ 0x36;
  }
  const dataBytes = toBytes(data);
  const inner = new Uint8Array(block + dataBytes.length);
  inner.set(i);
  inner.set(dataBytes, block);
  const outer = new Uint8Array(block + 32);
  outer.set(o);
  outer.set(sha256Raw(inner), block);
  return sha256Raw(outer);
}
function getSigningKey(dateStamp) {
  const kDate = hmacSha256('AWS4' + SECRET_KEY, dateStamp);
  const kRegion = hmacSha256(kDate, REGION);
  const kService = hmacSha256(kRegion, 's3');
  return hmacSha256(kService, 'aws4_request');
}
function encodePath(key) {
  return key.split('/').map((part) => encodeURIComponent(part)).join('/');
}
function hostName() {
  return `${BUCKET}.${ENDPOINT_HOST}`;
}
async function s3Request(method, host, path, headers, body) {
  const options = {
    method,
    url: `https://${host}${path}`,
    headers: { ...headers, Accept: '*/*' },
    json: false,
    encoding: 'text',
  };
  const bytes = body && body.length ? toBytes(body) : null;
  if (bytes) options.body = typeof Buffer !== 'undefined' ? Buffer.from(bytes) : bytes;
  try {
    const res = await this.helpers.httpRequest(options);
    return typeof res === 'string' ? res : JSON.stringify(res);
  } catch (err) {
    const status = err.statusCode || err.response?.statusCode || '';
    throw new Error(`S3 ${method} ${status}: ${err.message || err}`);
  }
}
function signPut(key, body, contentType) {
  const now = new Date();
  const amzDate = now.toISOString().replace(/[:-]|\.\d{3}/g, '');
  const dateStamp = amzDate.slice(0, 8);
  const host = hostName();
  const payloadHash = sha256(body);
  const headerMap = {
    'content-type': contentType,
    host,
    'x-amz-content-sha256': payloadHash,
    'x-amz-date': amzDate,
  };
  const signedNames = Object.keys(headerMap).sort();
  const canonicalHeaders = signedNames.map((name) => `${name}:${headerMap[name]}\n`).join('');
  const signedHeaders = signedNames.join(';');
  const canonicalRequest = ['PUT', '/' + encodePath(key), '', canonicalHeaders, signedHeaders, payloadHash].join('\n');
  const credentialScope = `${dateStamp}/${REGION}/s3/aws4_request`;
  const stringToSign = ['AWS4-HMAC-SHA256', amzDate, credentialScope, sha256(canonicalRequest)].join('\n');
  const signature = toHex(hmacSha256(getSigningKey(dateStamp), stringToSign));
  const authorization = `AWS4-HMAC-SHA256 Credential=${ACCESS_KEY}/${credentialScope}, SignedHeaders=${signedHeaders}, Signature=${signature}`;
  return { host, authorization, amzDate, payloadHash };
}
function describeS3Error(err) {
  const status = err.statusCode || err.response?.statusCode || err.httpCode || '';
  const body = err.response?.body ?? err.response?.data ?? err.cause?.response?.body;
  if (typeof body === 'string') return `HTTP ${status}: ${body.slice(0, 500)}`;
  if (body && typeof body === 'object') {
    if (typeof Buffer !== 'undefined' && Buffer.isBuffer(body)) return `HTTP ${status}: ${body.toString('utf8').slice(0, 500)}`;
    return `HTTP ${status}: ${JSON.stringify(body).slice(0, 500)}`;
  }
  return `HTTP ${status || 'error'}: ${err.message || err}`;
}
async function putObject(key, body, contentType = 'application/octet-stream') {
  const bytes = toBytes(body);
  const { host, authorization, amzDate, payloadHash } = signPut(key, bytes, contentType);
  const path = `/${encodePath(key)}`;
  try {
    await this.helpers.httpRequest({
      method: 'PUT',
      url: `https://${host}${path}`,
      headers: {
        'Content-Type': contentType,
        'x-amz-content-sha256': payloadHash,
        'x-amz-date': amzDate,
        Authorization: authorization,
      },
      body: typeof Buffer !== 'undefined' ? Buffer.from(bytes) : bytes,
      json: false,
    });
  } catch (err) {
    throw new Error(`S3 PUT ${describeS3Error(err)}`);
  }
}
function telegramSafeUrl(url) {
  return String(url).replace(/_/g, '%5F');
}
function presignGetUrl(key) {
  const now = new Date();
  const amzDate = now.toISOString().replace(/[:-]|\.\d{3}/g, '');
  const dateStamp = amzDate.slice(0, 8);
  const host = hostName();
  const credential = `${ACCESS_KEY}/${dateStamp}/${REGION}/s3/aws4_request`;
  const params = {
    'X-Amz-Algorithm': 'AWS4-HMAC-SHA256',
    'X-Amz-Credential': credential,
    'X-Amz-Date': amzDate,
    'X-Amz-Expires': String(EXPIRES),
    'X-Amz-SignedHeaders': 'host',
  };
  const query = Object.keys(params).sort().map((k) => `${encodeURIComponent(k)}=${encodeURIComponent(params[k])}`).join('&');
  const canonicalRequest = ['GET', '/' + encodePath(key), query, `host:${host}\n`, 'host', 'UNSIGNED-PAYLOAD'].join('\n');
  const credentialScope = `${dateStamp}/${REGION}/s3/aws4_request`;
  const stringToSign = ['AWS4-HMAC-SHA256', amzDate, credentialScope, sha256(canonicalRequest)].join('\n');
  const signature = toHex(hmacSha256(getSigningKey(dateStamp), stringToSign));
  return telegramSafeUrl(`https://${host}/${encodePath(key)}?${query}&X-Amz-Signature=${signature}`);
}
function presignPutUrl(key, contentType) {
  const now = new Date();
  const amzDate = now.toISOString().replace(/[:-]|\.\d{3}/g, '');
  const dateStamp = amzDate.slice(0, 8);
  const host = hostName();
  const credential = `${ACCESS_KEY}/${dateStamp}/${REGION}/s3/aws4_request`;
  const params = {
    'X-Amz-Algorithm': 'AWS4-HMAC-SHA256',
    'X-Amz-Credential': credential,
    'X-Amz-Date': amzDate,
    'X-Amz-Expires': String(EXPIRES),
    'X-Amz-SignedHeaders': 'content-type;host',
  };
  const query = Object.keys(params).sort().map((k) => `${encodeURIComponent(k)}=${encodeURIComponent(params[k])}`).join('&');
  const canonicalHeaders = `content-type:${contentType}\nhost:${host}\n`;
  const signedHeaders = 'content-type;host';
  const canonicalRequest = ['PUT', '/' + encodePath(key), query, canonicalHeaders, signedHeaders, 'UNSIGNED-PAYLOAD'].join('\n');
  const credentialScope = `${dateStamp}/${REGION}/s3/aws4_request`;
  const stringToSign = ['AWS4-HMAC-SHA256', amzDate, credentialScope, sha256(canonicalRequest)].join('\n');
  const signature = toHex(hmacSha256(getSigningKey(dateStamp), stringToSign));
  return telegramSafeUrl(`https://${host}/${encodePath(key)}?${query}&X-Amz-Signature=${signature}`);
}
function signList(prefix) {
  const now = new Date();
  const amzDate = now.toISOString().replace(/[:-]|\.\d{3}/g, '');
  const dateStamp = amzDate.slice(0, 8);
  const host = hostName();
  const queryParams = { 'list-type': '2', prefix };
  const canonicalQuery = Object.keys(queryParams).sort().map((k) => `${encodeURIComponent(k)}=${encodeURIComponent(queryParams[k])}`).join('&');
  const payloadHash = sha256('');
  const canonicalHeaders = `host:${host}\nx-amz-content-sha256:${payloadHash}\nx-amz-date:${amzDate}\n`;
  const signedHeaders = 'host;x-amz-content-sha256;x-amz-date';
  const canonicalRequest = ['GET', '/', canonicalQuery, canonicalHeaders, signedHeaders, payloadHash].join('\n');
  const credentialScope = `${dateStamp}/${REGION}/s3/aws4_request`;
  const stringToSign = ['AWS4-HMAC-SHA256', amzDate, credentialScope, sha256(canonicalRequest)].join('\n');
  const signature = toHex(hmacSha256(getSigningKey(dateStamp), stringToSign));
  const authorization = `AWS4-HMAC-SHA256 Credential=${ACCESS_KEY}/${credentialScope}, SignedHeaders=${signedHeaders}, Signature=${signature}`;
  return { host, authorization, amzDate, payloadHash, canonicalQuery };
}
async function listObjects(prefix) {
  const { host, authorization, amzDate, payloadHash, canonicalQuery } = signList(prefix);
  const xml = await s3Request.call(this, 'GET', host, `/?${canonicalQuery}`, {
    'x-amz-content-sha256': payloadHash,
    'x-amz-date': amzDate,
    Authorization: authorization,
  });
  return [...xml.matchAll(/<Key>([^<]+)<\/Key>/g)].map((m) => m[1]);
}
function fileNameToLabel(fileName) {
  const base = fileName.replace(/\.[^.]+$/, '');
  return base.replace(/[-_]+/g, ' ').replace(/\s+/g, ' ').trim();
}
function isImageKey(key) {
  return /\.(jpe?g|png|webp|gif)$/i.test(key);
}
const CARTESIA_API_KEY = "YOUR_CARTESIA_API_KEY";
const CARTESIA_VOICE_ID = "db6b0ed5-d5d3-463d-ae85-518a07d3c2b4";
const ELEVENLABS_API_KEY = "YOUR_ELEVENLABS_KEY";
const MIN_AUDIO_BYTES = 1000;

const ctx = $input.first().json;
const text = String(ctx.script?.full_script || '').trim();
const elevenVoiceId = ctx.script?.elevenlabs_voice_id;
if (!text) throw new Error('Missing full_script in script package');

function describeBody(body) {
  if (body == null) return 'empty response';
  if (typeof body === 'string') return body.slice(0, 300);
  if (typeof Buffer !== 'undefined' && Buffer.isBuffer(body)) return body.toString('utf8').slice(0, 300);
  if (body instanceof ArrayBuffer || ArrayBuffer.isView(body)) {
    try {
      const u8 = body instanceof ArrayBuffer ? new Uint8Array(body) : new Uint8Array(body.buffer, body.byteOffset, body.byteLength);
      return Buffer.from(u8).toString('utf8').slice(0, 300);
    } catch { return '[binary]'; }
  }
  if (body.type === 'Buffer' && Array.isArray(body.data)) {
    try { return Buffer.from(body.data).toString('utf8').slice(0, 300); } catch { return '[serialized buffer]'; }
  }
  return JSON.stringify(body).slice(0, 300);
}

function isSerializedBuffer(data) {
  return !!(data && typeof data === 'object' && data.type === 'Buffer' && Array.isArray(data.data));
}

function normalizeAudioBytes(raw, label) {
  let data = raw;
  for (let i = 0; i < 3; i++) {
    if (data == null) break;
    if (typeof Buffer !== 'undefined' && Buffer.isBuffer(data)) break;
    if (data instanceof ArrayBuffer || ArrayBuffer.isView(data)) break;
    if (isSerializedBuffer(data)) break;
    if (typeof data === 'string') break;
    if (typeof data === 'object') {
      if (data.body !== undefined) { data = data.body; continue; }
      if (data.data !== undefined) { data = data.data; continue; }
      if (data.error || data.message || data.detail) {
        throw new Error(`${label} API error: ${describeBody(data)}`);
      }
    }
    break;
  }

  let bytes;
  if (isSerializedBuffer(data)) {
    bytes = new Uint8Array(Buffer.from(data.data));
  } else if (typeof Buffer !== 'undefined' && Buffer.isBuffer(data)) {
    bytes = new Uint8Array(data);
  } else if (data instanceof ArrayBuffer) {
    bytes = new Uint8Array(data);
  } else if (ArrayBuffer.isView(data)) {
    bytes = new Uint8Array(data.buffer, data.byteOffset, data.byteLength);
  } else if (typeof data === 'string') {
    bytes = new Uint8Array(Buffer.from(data, 'binary'));
  } else {
    throw new Error(`${label}: unsupported audio response type ${typeof data} (${describeBody(data)})`);
  }

  if (!bytes.length || bytes.length < MIN_AUDIO_BYTES) {
    throw new Error(`${label}: audio too small (${bytes.length} bytes) — ${describeBody(bytes)}`);
  }
  return bytes;
}

async function requestAudio(options, label) {
  const base = {
    ...options,
    encoding: 'arraybuffer',
    json: false,
    returnFullResponse: false,
  };
  try {
    const raw = await this.helpers.httpRequest(base);
    return normalizeAudioBytes(raw, label);
  } catch (err) {
    const status = err.statusCode || err.response?.statusCode || err.httpCode || '';
    const body = err.response?.body ?? err.response?.data ?? err.cause?.response?.body;
    throw new Error(`${label} HTTP ${status || 'error'}: ${describeBody(body) || err.message || err}`);
  }
}

async function synthesizeCartesia() {
  return requestAudio.call(this, {
    method: 'POST',
    url: 'https://api.cartesia.ai/tts/bytes',
    headers: {
      Authorization: `Bearer ${CARTESIA_API_KEY}`,
      'Cartesia-Version': '2024-11-13',
      'Content-Type': 'application/json',
      Accept: 'audio/mpeg',
    },
    body: {
      model_id: 'sonic-3.5',
      transcript: text,
      voice: { mode: 'id', id: CARTESIA_VOICE_ID },
      output_format: { container: 'mp3', sample_rate: 44100 },
    },
  }, 'Cartesia');
}

async function synthesizeElevenLabs() {
  if (!elevenVoiceId) throw new Error('Missing elevenlabs_voice_id for ElevenLabs fallback');
  return requestAudio.call(this, {
    method: 'POST',
    url: `https://api.elevenlabs.io/v1/text-to-speech/${elevenVoiceId}`,
    headers: {
      'xi-api-key': ELEVENLABS_API_KEY,
      'Content-Type': 'application/json',
      Accept: 'audio/mpeg',
    },
    body: {
      text,
      model_id: 'eleven_flash_v2_5',
      voice_settings: { stability: 0.5, similarity_boost: 0.75 },
    },
  }, 'ElevenLabs');
}

let bytes;
let tts_provider = 'cartesia';
try {
  bytes = await synthesizeCartesia.call(this);
} catch (cartesiaErr) {
  try {
    bytes = await synthesizeElevenLabs.call(this);
    tts_provider = 'elevenlabs';
  } catch (elevenErr) {
    throw new Error(`TTS failed. Cartesia: ${cartesiaErr.message || cartesiaErr}. ElevenLabs: ${elevenErr.message || elevenErr}`);
  }
}

const key = `reels-voiceovers/${ctx.topic_slug}-${ctx.run_id}.mp3`;
const voiceover_url = presignGetUrl(key);
const upload_url = presignPutUrl(key, 'audio/mpeg');
const fileName = `${ctx.topic_slug}-${ctx.run_id}.mp3`;

return [{
  json: {
    ...ctx,
    voiceover_key: key,
    voiceover_url,
    upload_url,
    storage_bucket: BUCKET,
    tts_provider,
    voiceover_bytes: bytes.length,
  },
  binary: {
    voiceover: {
      data: toBase64(bytes),
      mimeType: 'audio/mpeg',
      fileExtension: 'mp3',
      fileName,
    },
  },
}];