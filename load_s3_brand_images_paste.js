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
} }];