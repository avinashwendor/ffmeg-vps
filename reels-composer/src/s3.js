import { createHash, createHmac } from 'node:crypto';
import { createWriteStream, promises as fs } from 'node:fs';
import { dirname, join } from 'node:path';
import { pipeline } from 'node:stream/promises';
import { Readable } from 'node:stream';

const ENDPOINT_HOST = process.env.S3_ENDPOINT_HOST || 't3.storageapi.dev';
const BUCKET = process.env.S3_BUCKET || process.env.AWS_S3_BUCKET_NAME || 'lightweight-vault-pew0g4o';
const REGION = process.env.S3_REGION || process.env.AWS_DEFAULT_REGION || 'auto';
// Railway names them AWS_*; fall back to those if S3_* not set.
const ACCESS_KEY = process.env.S3_ACCESS_KEY || process.env.AWS_ACCESS_KEY_ID || '';
const SECRET_KEY = process.env.S3_SECRET_KEY || process.env.AWS_SECRET_ACCESS_KEY || '';
const EXPIRES = Number(process.env.S3_PRESIGN_EXPIRES || 604800);

function encodePath(key) {
  return key.split('/').map((part) => encodeURIComponent(part)).join('/');
}

function hostName() {
  return `${BUCKET}.${ENDPOINT_HOST}`;
}

function hmacSha256(key, msg) {
  return createHmac('sha256', key).update(msg, 'utf8').digest();
}

function getSigningKey(dateStamp) {
  const kDate = hmacSha256(`AWS4${SECRET_KEY}`, dateStamp);
  const kRegion = hmacSha256(kDate, REGION);
  const kService = hmacSha256(kRegion, 's3');
  return hmacSha256(kService, 'aws4_request');
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
  const query = Object.keys(params)
    .sort()
    .map((k) => `${encodeURIComponent(k)}=${encodeURIComponent(params[k])}`)
    .join('&');
  const canonicalRequest = ['GET', `/${encodePath(key)}`, query, `host:${host}\n`, 'host', 'UNSIGNED-PAYLOAD'].join('\n');
  const credentialScope = `${dateStamp}/${REGION}/s3/aws4_request`;
  const stringToSign = ['AWS4-HMAC-SHA256', amzDate, credentialScope, createHash('sha256').update(canonicalRequest).digest('hex')].join('\n');
  const signature = hmacSha256(getSigningKey(dateStamp), stringToSign).toString('hex');
  return `https://${host}/${encodePath(key)}?${query}&X-Amz-Signature=${signature}`;
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
  const query = Object.keys(params)
    .sort()
    .map((k) => `${encodeURIComponent(k)}=${encodeURIComponent(params[k])}`)
    .join('&');
  const canonicalHeaders = `content-type:${contentType}\nhost:${host}\n`;
  const signedHeaders = 'content-type;host';
  const canonicalRequest = ['PUT', `/${encodePath(key)}`, query, canonicalHeaders, signedHeaders, 'UNSIGNED-PAYLOAD'].join('\n');
  const credentialScope = `${dateStamp}/${REGION}/s3/aws4_request`;
  const stringToSign = ['AWS4-HMAC-SHA256', amzDate, credentialScope, createHash('sha256').update(canonicalRequest).digest('hex')].join('\n');
  const signature = hmacSha256(getSigningKey(dateStamp), stringToSign).toString('hex');
  return `https://${host}/${encodePath(key)}?${query}&X-Amz-Signature=${signature}`;
}

const DOWNLOAD_ATTEMPTS = Number(process.env.S3_DOWNLOAD_ATTEMPTS) || 3;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// A render is five clips plus a voiceover, several minutes of work, and a single
// transient 5xx on the last download used to throw all of it away. 4xx is not
// retried — a signature that has expired will not un-expire.
async function downloadToFile(url, destPath) {
  await fs.mkdir(dirname(destPath), { recursive: true });
  let lastErr;
  for (let attempt = 1; attempt <= DOWNLOAD_ATTEMPTS; attempt++) {
    try {
      const res = await fetch(url);
      if (!res.ok) {
        const err = new Error(`Download failed ${res.status}: ${url.split('?')[0]}`);
        if (res.status >= 400 && res.status < 500) throw err;
        throw Object.assign(err, { retryable: true });
      }
      await pipeline(Readable.fromWeb(res.body), createWriteStream(destPath));
      const { size } = await fs.stat(destPath);
      if (!size) throw Object.assign(new Error(`Downloaded 0 bytes: ${url.split('?')[0]}`), { retryable: true });
      return;
    } catch (err) {
      lastErr = err;
      // fetch itself rejects on DNS/socket failures, which are worth another go.
      const retryable = err.retryable || err.name === 'TypeError' || err.cause;
      if (!retryable || attempt === DOWNLOAD_ATTEMPTS) throw lastErr;
      await sleep(500 * 2 ** (attempt - 1));
    }
  }
  throw lastErr;
}

async function uploadFile(key, filePath, contentType) {
  const body = await fs.readFile(filePath);
  const url = presignPutUrl(key, contentType);
  const res = await fetch(url, {
    method: 'PUT',
    headers: { 'Content-Type': contentType },
    body,
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`S3 upload failed ${res.status}: ${text.slice(0, 200)}`);
  }
  return presignGetUrl(key);
}

export { presignGetUrl, presignPutUrl, downloadToFile, uploadFile, BUCKET };
