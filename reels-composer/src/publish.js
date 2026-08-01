/**
 * Posting the finished reel to Instagram and YouTube.
 *
 * This lives in the composer rather than in n8n for one reason: YouTube wants
 * the file's *bytes* on a resumable session, and an n8n Code node cannot carry
 * a 20 MB video through the task runner. The service already has the file on
 * S3 and a real HTTP stack, so it does the upload and the workflow polls it —
 * exactly the shape the render already uses.
 *
 * The two platforms are independent. One being unconfigured, rate-limited or
 * rejected never stops the other, and every outcome is reported per platform
 * rather than collapsed into one success flag.
 */
import { createReadStream, promises as fs } from 'node:fs';
import { join } from 'node:path';
import { downloadToFile, presignGetUrl } from './s3.js';

// Read on every call rather than at import. The endpoints are overridable for
// the same reason: the test drives this whole file against a stub Graph and a
// stub YouTube, and there is no other way to prove the three-step Reels publish
// or a resumable upload actually works.
function cfg() {
  return {
    igUserId: process.env.IG_USER_ID || '',
    igToken: process.env.IG_ACCESS_TOKEN || '',
    igGraphBase: process.env.IG_GRAPH_BASE || `https://graph.facebook.com/${process.env.IG_GRAPH_VERSION || 'v21.0'}`,
    igPollAttempts: Number(process.env.IG_POLL_ATTEMPTS) || 30,
    igPollIntervalMs: Number(process.env.IG_POLL_INTERVAL_MS) || 5000,

    ytClientId: process.env.YT_CLIENT_ID || '',
    ytClientSecret: process.env.YT_CLIENT_SECRET || '',
    ytRefreshToken: process.env.YT_REFRESH_TOKEN || '',
    ytTokenUrl: process.env.YT_TOKEN_URL || 'https://oauth2.googleapis.com/token',
    ytUploadUrl: process.env.YT_UPLOAD_URL || 'https://www.googleapis.com/upload/youtube/v3/videos',
    // Shorts are public by default; set this to `private` or `unlisted` while
    // testing so a bad render is not on the channel before anyone has seen it.
    ytPrivacy: process.env.YT_PRIVACY_STATUS || 'public',
    ytCategoryId: process.env.YT_CATEGORY_ID || '22', // People & Blogs
  };
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

export function publishTargets() {
  const c = cfg();
  return {
    instagram: Boolean(c.igUserId && c.igToken),
    youtube: Boolean(c.ytClientId && c.ytClientSecret && c.ytRefreshToken),
  };
}

// Graph and YouTube both answer errors as JSON with a useful message inside,
// and both are worth surfacing verbatim — "an unexpected error occurred" is
// what sends someone to the wrong logs.
async function readError(res) {
  const text = await res.text().catch(() => '');
  try {
    const body = JSON.parse(text);
    const msg = body?.error?.message || body?.error?.error_user_msg || body?.error_description || body?.message;
    if (msg) return `${res.status}: ${msg}`;
  } catch { /* not json */ }
  return `${res.status}: ${text.slice(0, 300) || res.statusText}`;
}

// ── INSTAGRAM ──────────────────────────────────────────────────────────────
//
// Reels are a three-step publish: hand Graph a URL it can fetch, wait for it to
// finish transcoding, then publish the container. The middle step is the one
// that bites — publishing a container that is still IN_PROGRESS fails, and the
// error does not say why.
async function publishToInstagram({ videoUrl, caption, shareToFeed = true, onProgress }) {
  const { igUserId, igToken, igGraphBase: base, igPollAttempts, igPollIntervalMs } = cfg();

  onProgress?.('creating the Instagram container');
  const createRes = await fetch(`${base}/${igUserId}/media`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      media_type: 'REELS',
      video_url: videoUrl,
      caption: String(caption || '').slice(0, 2200),
      share_to_feed: shareToFeed,
      access_token: igToken,
    }),
  });
  if (!createRes.ok) throw new Error(`Instagram container failed — ${await readError(createRes)}`);
  const { id: containerId } = await createRes.json();
  if (!containerId) throw new Error('Instagram accepted the container request but returned no id');

  onProgress?.('Instagram is transcoding the reel');
  let lastStatus = '';
  for (let attempt = 0; attempt < igPollAttempts; attempt++) {
    await sleep(igPollIntervalMs);
    const statusRes = await fetch(
      `${base}/${containerId}?fields=status_code,status&access_token=${encodeURIComponent(igToken)}`
    );
    if (!statusRes.ok) throw new Error(`Instagram status check failed — ${await readError(statusRes)}`);
    const body = await statusRes.json();
    lastStatus = body.status_code || '';
    if (lastStatus === 'FINISHED') break;
    if (lastStatus === 'ERROR' || lastStatus === 'EXPIRED') {
      throw new Error(`Instagram rejected the video (${lastStatus}): ${body.status || 'no detail given'}`);
    }
  }
  if (lastStatus !== 'FINISHED') {
    throw new Error(`Instagram was still "${lastStatus || 'unknown'}" after ${(igPollAttempts * igPollIntervalMs) / 1000}s — the container may still publish, check the app`);
  }

  onProgress?.('publishing to Instagram');
  const publishRes = await fetch(`${base}/${igUserId}/media_publish`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ creation_id: containerId, access_token: igToken }),
  });
  if (!publishRes.ok) throw new Error(`Instagram publish failed — ${await readError(publishRes)}`);
  const { id: mediaId } = await publishRes.json();

  // A permalink is worth one extra call; without it the reply can only say
  // "posted" and leave someone hunting through the app for it.
  let permalink = '';
  try {
    const linkRes = await fetch(`${base}/${mediaId}?fields=permalink&access_token=${encodeURIComponent(igToken)}`);
    if (linkRes.ok) permalink = (await linkRes.json()).permalink || '';
  } catch { /* the post is already live; the link is a nicety */ }

  return { id: mediaId, url: permalink || `https://www.instagram.com/reel/${mediaId}/` };
}

// ── YOUTUBE ────────────────────────────────────────────────────────────────

async function youtubeAccessToken() {
  const { ytClientId, ytClientSecret, ytRefreshToken, ytTokenUrl } = cfg();
  const res = await fetch(ytTokenUrl, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({
      client_id: ytClientId,
      client_secret: ytClientSecret,
      refresh_token: ytRefreshToken,
      grant_type: 'refresh_token',
    }),
  });
  if (!res.ok) {
    throw new Error(`YouTube refresh token rejected — ${await readError(res)}. Re-run the OAuth consent and update YT_REFRESH_TOKEN.`);
  }
  const { access_token: token } = await res.json();
  if (!token) throw new Error('YouTube returned no access token');
  return token;
}

// A Short is just a vertical video under 3 minutes — there is no "shorts" flag
// in the API. The #Shorts tag in the title is what still nudges classification.
async function publishToYouTube({ filePath, title, description, tags, onProgress }) {
  const { ytUploadUrl, ytPrivacy, ytCategoryId } = cfg();
  const token = await youtubeAccessToken();
  const { size } = await fs.stat(filePath);

  onProgress?.('opening the YouTube upload session');
  const initRes = await fetch(
    `${ytUploadUrl}?uploadType=resumable&part=snippet,status`,
    {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${token}`,
        'Content-Type': 'application/json',
        'X-Upload-Content-Length': String(size),
        'X-Upload-Content-Type': 'video/mp4',
      },
      body: JSON.stringify({
        snippet: {
          title: String(title || 'Reel').slice(0, 100),
          description: String(description || '').slice(0, 4900),
          tags: (tags || []).slice(0, 15),
          categoryId: ytCategoryId,
        },
        status: {
          privacyStatus: ytPrivacy,
          selfDeclaredMadeForKids: false,
        },
      }),
    }
  );
  if (!initRes.ok) throw new Error(`YouTube upload session failed — ${await readError(initRes)}`);
  const uploadUrl = initRes.headers.get('location');
  if (!uploadUrl) throw new Error('YouTube opened no resumable session (no Location header)');

  onProgress?.(`uploading ${(size / 1024 / 1024).toFixed(1)} MB to YouTube`);
  const uploadRes = await fetch(uploadUrl, {
    method: 'PUT',
    headers: { 'Content-Type': 'video/mp4', 'Content-Length': String(size) },
    body: createReadStream(filePath),
    duplex: 'half',
  });
  if (!uploadRes.ok) throw new Error(`YouTube upload failed — ${await readError(uploadRes)}`);
  const video = await uploadRes.json();
  if (!video?.id) throw new Error('YouTube accepted the upload but returned no video id');

  return { id: video.id, url: `https://www.youtube.com/shorts/${video.id}` };
}

// ── ORCHESTRATION ──────────────────────────────────────────────────────────

/**
 * Publish one finished reel to whichever platforms are configured.
 *
 * `job` is mutated as it goes so the workflow's poll can narrate progress —
 * "Instagram is transcoding" is a much better wait than a spinner.
 */
export async function publishReel({ workDir, outputKey, videoUrl, instagram = {}, youtube = {}, job = {} }) {
  const targets = publishTargets();
  job.platforms = job.platforms || {};

  const results = {};
  const wanted = {
    instagram: instagram.enabled !== false,
    youtube: youtube.enabled !== false,
  };

  // Both platforms need the file: Instagram fetches it from a URL it can reach,
  // YouTube needs the bytes. One presign and one download covers both.
  const publicUrl = videoUrl || (outputKey ? presignGetUrl(outputKey) : '');
  let localPath = '';
  const needsLocal = wanted.youtube && targets.youtube;
  if (needsLocal) {
    if (!publicUrl) throw new Error('No video URL or output key to publish');
    localPath = join(workDir, 'publish.mp4');
    job.platforms.youtube = { status: 'downloading' };
    await downloadToFile(publicUrl, localPath);
  }

  const track = (name) => (note) => {
    job.platforms[name] = { ...(job.platforms[name] || {}), status: 'uploading', note };
  };

  const run = async (name, enabled, configured, fn) => {
    if (!enabled) {
      results[name] = { ok: false, skipped: true, reason: 'not requested' };
      job.platforms[name] = results[name];
      return;
    }
    if (!configured) {
      results[name] = {
        ok: false,
        skipped: true,
        reason: name === 'instagram'
          ? 'not configured — set IG_USER_ID and IG_ACCESS_TOKEN on the composer service'
          : 'not configured — set YT_CLIENT_ID, YT_CLIENT_SECRET and YT_REFRESH_TOKEN on the composer service',
      };
      job.platforms[name] = results[name];
      return;
    }
    try {
      const out = await fn();
      results[name] = { ok: true, ...out };
    } catch (err) {
      results[name] = { ok: false, error: err.message || String(err) };
    }
    job.platforms[name] = results[name];
  };

  // Sequential, not parallel: a Reels container transcodes for a minute or two
  // while YouTube pushes 20 MB, and a memory-capped container does not need
  // both at once. It also keeps the progress notes readable.
  await run('instagram', wanted.instagram, targets.instagram, () => publishToInstagram({
    videoUrl: publicUrl,
    caption: instagram.caption,
    shareToFeed: instagram.share_to_feed !== false,
    onProgress: track('instagram'),
  }));

  await run('youtube', wanted.youtube, targets.youtube, () => publishToYouTube({
    filePath: localPath,
    title: youtube.title,
    description: youtube.description,
    tags: youtube.tags,
    onProgress: track('youtube'),
  }));

  if (localPath) await fs.rm(localPath, { force: true }).catch(() => {});

  const attempted = Object.values(results).filter((r) => !r.skipped);
  return {
    results,
    // "Nothing was configured" is a different outcome from "both failed", and
    // the Telegram reply says something different for each.
    published: attempted.filter((r) => r.ok).length,
    attempted: attempted.length,
    ok: attempted.length > 0 && attempted.every((r) => r.ok),
  };
}
