/**
 * Publishing the finished reel.
 *
 * Both platforms are driven against stub servers that behave the way the real
 * ones do — Instagram transcodes for a while before it will accept a publish,
 * YouTube hands back a resumable session URL and expects the bytes on it. The
 * failures pinned here are the ones that would otherwise only show up on a live
 * account: publishing a container that is not FINISHED, a refresh token that has
 * been revoked, and one platform's failure taking the other down with it.
 *
 *   node reels-composer/test/publish.test.mjs
 *
 * No network and no credentials.
 */
import { promises as fs } from 'node:fs';
import { createServer } from 'node:http';
import { join } from 'node:path';
import { tmpdir } from 'node:os';

const failures = [];
const check = (label, ok, detail = '') => {
  console.log(`  ${ok ? 'pass' : 'FAIL'}  ${label}${detail ? `  (${detail})` : ''}`);
  if (!ok) failures.push(label);
};

function readBody(req) {
  return new Promise((resolve) => {
    let body = '';
    req.on('data', (d) => { body += d; });
    req.on('end', () => resolve(body));
  });
}

// ── stub Instagram Graph ───────────────────────────────────────────────────
const ig = {
  containers: new Map(),
  // How many status polls before the container reports FINISHED.
  transcodePolls: 2,
  failCreate: false,
  published: [],
  reset() {
    this.containers.clear();
    this.transcodePolls = 2;
    this.failCreate = false;
    this.published = [];
  },
};

const igServer = createServer(async (req, res) => {
  const url = new URL(req.url, 'http://x');
  const json = (code, body) => {
    res.statusCode = code;
    res.setHeader('content-type', 'application/json');
    res.end(JSON.stringify(body));
  };

  if (req.method === 'POST' && url.pathname.endsWith('/media')) {
    if (ig.failCreate) return json(400, { error: { message: 'The video file is invalid' } });
    const body = JSON.parse(await readBody(req));
    const id = `container-${ig.containers.size + 1}`;
    ig.containers.set(id, { polls: 0, caption: body.caption, videoUrl: body.video_url });
    return json(200, { id });
  }
  if (req.method === 'POST' && url.pathname.endsWith('/media_publish')) {
    const body = JSON.parse(await readBody(req));
    const container = ig.containers.get(body.creation_id);
    // The real Graph refuses a container that is still transcoding, and this is
    // the mistake that makes a publish silently never appear.
    if (!container || container.polls < ig.transcodePolls) {
      return json(400, { error: { message: 'Media ID is not available' } });
    }
    ig.published.push(body.creation_id);
    return json(200, { id: 'media-9001' });
  }
  const id = url.pathname.replace(/^\//, '');
  if (ig.containers.has(id)) {
    const container = ig.containers.get(id);
    container.polls += 1;
    return json(200, {
      status_code: container.polls >= ig.transcodePolls ? 'FINISHED' : 'IN_PROGRESS',
    });
  }
  if (id === 'media-9001') return json(200, { permalink: 'https://www.instagram.com/reel/ABC123/' });
  return json(404, { error: { message: `no stub route for ${req.method} ${url.pathname}` } });
});

// ── stub YouTube ───────────────────────────────────────────────────────────
const yt = {
  tokenValid: true,
  uploaded: null,
  metadata: null,
  reset() {
    this.tokenValid = true;
    this.uploaded = null;
    this.metadata = null;
  },
};

const ytServer = createServer(async (req, res) => {
  const url = new URL(req.url, 'http://x');
  const json = (code, body) => {
    res.statusCode = code;
    res.setHeader('content-type', 'application/json');
    res.end(JSON.stringify(body));
  };

  if (url.pathname === '/token') {
    if (!yt.tokenValid) return json(400, { error: 'invalid_grant', error_description: 'Token has been expired or revoked.' });
    return json(200, { access_token: 'ya29.stub', expires_in: 3600 });
  }
  if (url.pathname === '/upload' && req.method === 'POST') {
    yt.metadata = JSON.parse(await readBody(req));
    res.statusCode = 200;
    res.setHeader('location', `http://127.0.0.1:${ytServer.address().port}/session/abc`);
    return res.end('');
  }
  if (url.pathname === '/session/abc' && req.method === 'PUT') {
    const chunks = [];
    for await (const chunk of req) chunks.push(chunk);
    yt.uploaded = Buffer.concat(chunks);
    return json(200, { id: 'yt-video-1', kind: 'youtube#video' });
  }
  return json(404, { error: { message: `no stub route for ${req.method} ${url.pathname}` } });
});

// ── stub S3 (serves the rendered reel over http) ───────────────────────────
const dir = join(tmpdir(), `publish-test-${Date.now()}`);
await fs.mkdir(dir, { recursive: true });
const REEL_BYTES = Buffer.alloc(64 * 1024, 7);
await fs.writeFile(join(dir, 'reel.mp4'), REEL_BYTES);

const s3Server = createServer(async (req, res) => {
  try {
    res.end(await fs.readFile(join(dir, req.url.replace(/^\//, '').split('?')[0])));
  } catch {
    res.statusCode = 404;
    res.end();
  }
});

for (const s of [igServer, ytServer, s3Server]) {
  await new Promise((r) => s.listen(0, '127.0.0.1', r));
}

const IG_BASE = `http://127.0.0.1:${igServer.address().port}`;
const YT_BASE = `http://127.0.0.1:${ytServer.address().port}`;
const REEL_URL = `http://127.0.0.1:${s3Server.address().port}/reel.mp4`;

// Set before the module is imported so `cfg()` sees it either way.
process.env.IG_GRAPH_BASE = IG_BASE;
process.env.IG_POLL_INTERVAL_MS = '10';
process.env.IG_POLL_ATTEMPTS = '8';
process.env.YT_TOKEN_URL = `${YT_BASE}/token`;
process.env.YT_UPLOAD_URL = `${YT_BASE}/upload`;
process.env.YT_PRIVACY_STATUS = 'unlisted';

const { publishReel, publishTargets } = await import('../src/publish.js');

function configure({ instagram = true, youtube = true } = {}) {
  process.env.IG_USER_ID = instagram ? '17841400000000000' : '';
  process.env.IG_ACCESS_TOKEN = instagram ? 'EAAstub' : '';
  process.env.YT_CLIENT_ID = youtube ? 'client.apps.googleusercontent.com' : '';
  process.env.YT_CLIENT_SECRET = youtube ? 'secret' : '';
  process.env.YT_REFRESH_TOKEN = youtube ? '1//refresh' : '';
}

async function publish(opts = {}) {
  const workDir = join(dir, `work-${Math.random().toString(36).slice(2)}`);
  await fs.mkdir(workDir, { recursive: true });
  const job = {};
  const summary = await publishReel({
    workDir,
    videoUrl: REEL_URL,
    instagram: { caption: 'vending pays for itself #reels' },
    youtube: { title: 'Vending pays for itself #Shorts', description: 'the whole story', tags: ['vending'] },
    job,
    ...opts,
  });
  return { summary, job };
}

try {
  console.log('\nnothing configured');
  {
    configure({ instagram: false, youtube: false });
    check('health reports both platforms off', publishTargets().instagram === false && publishTargets().youtube === false);
    const { summary } = await publish();
    check('nothing is attempted', summary.attempted === 0 && summary.published === 0);
    // "Nothing was set up" must not read as "both uploads failed".
    check('and that is not reported as a failure', summary.ok === false && summary.results.instagram.skipped === true);
    check('the reason names the variables to set', /IG_USER_ID/.test(summary.results.instagram.reason), summary.results.instagram.reason);
    check('and the same for YouTube', /YT_REFRESH_TOKEN/.test(summary.results.youtube.reason), summary.results.youtube.reason);
  }

  console.log('\nboth platforms');
  {
    configure();
    ig.reset();
    yt.reset();
    const { summary, job } = await publish();
    check('both report success', summary.ok && summary.published === 2, JSON.stringify(summary.results));
    check('the Instagram permalink comes back', summary.results.instagram.url === 'https://www.instagram.com/reel/ABC123/', summary.results.instagram.url);
    check('the reel was only published once it had finished transcoding', ig.published.length === 1);
    check('the caption reached Instagram', [...ig.containers.values()][0].caption === 'vending pays for itself #reels');
    check('the YouTube link is a Shorts link', summary.results.youtube.url === 'https://www.youtube.com/shorts/yt-video-1', summary.results.youtube.url);
    check('every byte of the reel was uploaded', yt.uploaded?.length === REEL_BYTES.length, `${yt.uploaded?.length} of ${REEL_BYTES.length}`);
    check('the privacy setting is honoured', yt.metadata?.status?.privacyStatus === 'unlisted');
    check('the title and tags are set', yt.metadata?.snippet?.title.includes('#Shorts') && yt.metadata?.snippet?.tags[0] === 'vending');
    check('progress is visible while it runs', Boolean(job.platforms.instagram) && Boolean(job.platforms.youtube));
  }

  console.log('\none platform fails');
  {
    configure();
    ig.reset();
    yt.reset();
    ig.failCreate = true;
    const { summary } = await publish();
    check('Instagram reports the reason it rejected the video', /video file is invalid/.test(summary.results.instagram.error || ''), summary.results.instagram.error);
    // The whole point of running them independently.
    check('YouTube still goes up', summary.results.youtube.ok === true);
    check('the run is not "ok", but it did publish one', summary.ok === false && summary.published === 1);
  }

  console.log('\na revoked YouTube token');
  {
    configure();
    ig.reset();
    yt.reset();
    yt.tokenValid = false;
    const { summary } = await publish();
    check('the error says the token was revoked', /revoked/i.test(summary.results.youtube.error || ''), summary.results.youtube.error);
    check('and says how to fix it', /YT_REFRESH_TOKEN/.test(summary.results.youtube.error || ''));
    check('Instagram is unaffected', summary.results.instagram.ok === true);
  }

  console.log('\nInstagram never finishes transcoding');
  {
    configure({ instagram: true, youtube: false });
    ig.reset();
    ig.transcodePolls = 99;
    const { summary } = await publish();
    check('it gives up rather than publishing a half-transcoded container', summary.results.instagram.ok === false);
    check('and says the container may still land', /may still publish/.test(summary.results.instagram.error || ''), summary.results.instagram.error);
    check('nothing was published', ig.published.length === 0);
  }

  console.log('\nopting out of one platform');
  {
    configure();
    ig.reset();
    yt.reset();
    const { summary } = await publish({ instagram: { enabled: false } });
    check('a disabled platform is skipped, not failed', summary.results.instagram.skipped === true && summary.results.instagram.reason === 'not requested');
    check('the other still runs and the result is ok', summary.ok === true && summary.attempted === 1);
  }
} finally {
  igServer.close();
  ytServer.close();
  s3Server.close();
  await fs.rm(dir, { recursive: true, force: true });
}

if (failures.length) {
  console.log(`\n${failures.length} failure(s)`);
  process.exit(1);
}
console.log('\nboth platforms publish, and neither can take the other down');
