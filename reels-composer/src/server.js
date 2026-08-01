import express from 'express';
import { spawn } from 'node:child_process';
import { promises as fs } from 'node:fs';
import { join } from 'node:path';
import { v4 as uuidv4 } from 'uuid';
import { renderReel } from './renderJob.js';
import { publishReel, publishTargets } from './publish.js';
import { uploadFile } from './s3.js';

const PORT = Number(process.env.PORT || 3000);
const AUTH_TOKEN = process.env.AUTH_TOKEN || '';
const TMP_ROOT = process.env.TMP_ROOT || '/tmp/reels-composer';
// Finished jobs are only kept so the workflow can poll for the result. It polls
// for a few minutes at most, so anything this old is never going to be read.
const JOB_TTL_MS = Number(process.env.JOB_TTL_MS) || 6 * 60 * 60 * 1000;

const jobs = new Map();
const publishJobs = new Map();

// One render at a time. ffmpeg is already tuned to sit inside this container's
// memory limit for a single 1080x1920 encode — two at once is how the OOM
// killer comes back. Requests are still accepted immediately and queued.
let renderChain = Promise.resolve();
let queueDepth = 0;

function enqueueRender(task) {
  queueDepth += 1;
  const scheduled = renderChain.then(task, task);
  renderChain = scheduled.then(
    () => { queueDepth -= 1; },
    () => { queueDepth -= 1; },
  );
  return scheduled;
}

const reaper = setInterval(() => {
  const cutoff = Date.now() - JOB_TTL_MS;
  for (const map of [jobs, publishJobs]) {
    for (const [id, job] of map) {
      if (job.status !== 'done' && job.status !== 'failed') continue;
      if (new Date(job.created_at).getTime() < cutoff) map.delete(id);
    }
  }
}, 15 * 60 * 1000);
reaper.unref?.();

const app = express();
app.use(express.json({ limit: '2mb' }));

function auth(req, res, next) {
  if (!AUTH_TOKEN) return next();
  const header = req.headers.authorization || '';
  const token = header.startsWith('Bearer ') ? header.slice(7) : '';
  if (token !== AUTH_TOKEN) {
    return res.status(401).json({ message: 'Unauthorized' });
  }
  return next();
}

app.get('/health', (_req, res) => {
  const p = spawn('ffmpeg', ['-version']);
  let out = '';
  p.stdout.on('data', (d) => { out += d; });
  p.on('close', (code) => {
    res.json({
      ok: code === 0,
      service: 'reels-composer',
      ffmpeg: code === 0 ? out.split('\n')[0] : 'not found',
      queue_depth: queueDepth,
      jobs_tracked: jobs.size,
      // Renders die on the final upload without these, after doing all the work.
      // Railway names them AWS_*; accept either S3_* or AWS_* naming.
      s3_configured: Boolean(
        (process.env.S3_ACCESS_KEY || process.env.AWS_ACCESS_KEY_ID) &&
        (process.env.S3_SECRET_KEY || process.env.AWS_SECRET_ACCESS_KEY)
      ),
      // Which platforms this service could post to right now. Visible here so a
      // missing token is found before someone answers "yes" to the upload
      // prompt and gets told nothing was configured.
      publish_targets: publishTargets(),
    });
  });
});

app.get('/v1/jobs/:id', auth, (req, res) => {
  const job = jobs.get(req.params.id);
  if (!job) return res.status(404).json({ error: 'Job not found' });
  return res.json(job);
});

app.post('/v1/render', auth, async (req, res) => {
  const {
    run_id: runId,
    clips,
    voiceover_url: voiceoverUrl,
    voiceover_sec: voiceoverSec,
    transition_sec: transitionSec,
    tail_sec: tailSec,
    subtitles_srt: subtitlesSrt,
    // Word-level cues when the TTS measured them. The animated caption styles
    // need these; without them they degrade rather than fail.
    caption_cues: captionCues,
    recipe,
    callback_url: callbackUrl,
    output_key: outputKey,
  } = req.body || {};

  if (!runId) return res.status(400).json({ error: 'run_id is required' });
  if (!Array.isArray(clips) || clips.length < 1) return res.status(400).json({ error: 'clips array is required' });
  if (!voiceoverUrl) return res.status(400).json({ error: 'voiceover_url is required' });
  const missingUrl = clips.findIndex((c) => !(c && (c.url || typeof c === 'string')));
  if (missingUrl >= 0) return res.status(400).json({ error: `clips[${missingUrl}] has no url` });

  const jobId = uuidv4();
  const job = {
    id: jobId,
    run_id: runId,
    status: 'queued',
    queue_position: queueDepth,
    created_at: new Date().toISOString(),
    output_url: null,
    duration_sec: null,
    qc: null,
    error: null,
  };
  jobs.set(jobId, job);
  res.status(202).json({ job_id: jobId, status: 'queued', queue_position: job.queue_position });

  enqueueRender(async () => {
    const workDir = join(TMP_ROOT, jobId);
    job.status = 'processing';
    job.queue_position = 0;
    job.started_at = new Date().toISOString();
    try {
      await fs.mkdir(workDir, { recursive: true });
      const { finalPath, duration, qc, timing, look } = await renderReel({
        workDir,
        clipUrls: clips,
        voiceoverUrl,
        voiceoverSec,
        transitionSec,
        tailSec: tailSec == null ? undefined : Number(tailSec),
        subtitlesSrt,
        captionCues,
        recipe,
      });
      const key = outputKey || `reels-final/${runId}.mp4`;
      const outputUrl = await uploadFile(key, finalPath, 'video/mp4');
      job.status = 'done';
      job.output_url = outputUrl;
      job.output_key = key;
      job.duration_sec = duration;
      // The reel is uploaded either way — a QC failure is something to look at,
      // not a reason to throw away a finished render. It travels with the job so
      // the workflow leads with the warning instead of announcing success.
      job.qc = qc;
      job.timing = timing;
      // What the edit actually came out as — the moves and cuts chosen, and
      // whether the captions ended up animated off measured words.
      job.look = look;
      job.finished_at = new Date().toISOString();

      if (callbackUrl) {
        try {
          await fetch(callbackUrl, {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              ...(AUTH_TOKEN ? { Authorization: `Bearer ${AUTH_TOKEN}` } : {}),
            },
            body: JSON.stringify({
              job_id: jobId,
              run_id: runId,
              status: 'done',
              output_url: outputUrl,
              output_key: key,
              duration_sec: duration,
              qc,
            }),
          });
        } catch (cbErr) {
          job.callback_error = cbErr.message;
        }
      }
    } catch (err) {
      job.status = 'failed';
      job.error = err.message || String(err);
      job.finished_at = new Date().toISOString();
      if (callbackUrl) {
        try {
          await fetch(callbackUrl, {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              ...(AUTH_TOKEN ? { Authorization: `Bearer ${AUTH_TOKEN}` } : {}),
            },
            body: JSON.stringify({
              job_id: jobId,
              run_id: runId,
              status: 'failed',
              error: job.error,
            }),
          });
        } catch {
          // ignore callback failure
        }
      }
    } finally {
      await fs.rm(workDir, { recursive: true, force: true }).catch(() => {});
    }
  });
});

// ── PUBLISH ────────────────────────────────────────────────────────────────
//
// Same shape as a render: accepted immediately, polled for a result. Uploading
// a reel to two platforms takes a couple of minutes, which is far longer than
// any sensible HTTP timeout.

app.get('/v1/publish/:id', auth, (req, res) => {
  const job = publishJobs.get(req.params.id);
  if (!job) return res.status(404).json({ error: 'Publish job not found' });
  return res.json(job);
});

app.post('/v1/publish', auth, async (req, res) => {
  const {
    run_id: runId,
    output_key: outputKey,
    video_url: videoUrl,
    instagram = {},
    youtube = {},
  } = req.body || {};

  if (!outputKey && !videoUrl) {
    return res.status(400).json({ error: 'output_key or video_url is required' });
  }

  const targets = publishTargets();
  const jobId = uuidv4();
  const job = {
    id: jobId,
    run_id: runId || null,
    status: 'queued',
    created_at: new Date().toISOString(),
    targets,
    platforms: {},
    results: null,
    error: null,
  };
  publishJobs.set(jobId, job);
  res.status(202).json({ publish_job_id: jobId, status: 'queued', targets });

  // Publishing shares the render queue. Both are long, network-heavy and
  // memory-hungry, and running one while the other encodes is how the OOM
  // killer came back the first time.
  enqueueRender(async () => {
    const workDir = join(TMP_ROOT, `publish-${jobId}`);
    job.status = 'processing';
    job.started_at = new Date().toISOString();
    try {
      await fs.mkdir(workDir, { recursive: true });
      const summary = await publishReel({ workDir, outputKey, videoUrl, instagram, youtube, job });
      job.status = 'done';
      job.results = summary.results;
      job.published = summary.published;
      job.attempted = summary.attempted;
      job.ok = summary.ok;
    } catch (err) {
      job.status = 'failed';
      job.error = err.message || String(err);
    } finally {
      job.finished_at = new Date().toISOString();
      await fs.rm(workDir, { recursive: true, force: true }).catch(() => {});
    }
  });
});

app.listen(PORT, () => {
  console.log(`reels-composer listening on ${PORT}`);
});
