import express from 'express';
import { spawn } from 'node:child_process';
import { promises as fs } from 'node:fs';
import { join } from 'node:path';
import { v4 as uuidv4 } from 'uuid';
import { renderReel } from './renderJob.js';
import { uploadFile } from './s3.js';

const PORT = Number(process.env.PORT || 3000);
const AUTH_TOKEN = process.env.AUTH_TOKEN || '';
const TMP_ROOT = process.env.TMP_ROOT || '/tmp/reels-composer';

const jobs = new Map();

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
    subtitles_srt: subtitlesSrt,
    recipe,
    callback_url: callbackUrl,
    output_key: outputKey,
  } = req.body || {};

  if (!runId) return res.status(400).json({ error: 'run_id is required' });
  if (!Array.isArray(clips) || clips.length < 1) return res.status(400).json({ error: 'clips array is required' });
  if (!voiceoverUrl) return res.status(400).json({ error: 'voiceover_url is required' });

  const jobId = uuidv4();
  const job = {
    id: jobId,
    run_id: runId,
    status: 'queued',
    created_at: new Date().toISOString(),
    output_url: null,
    duration_sec: null,
    error: null,
  };
  jobs.set(jobId, job);
  res.status(202).json({ job_id: jobId, status: 'queued' });

  setImmediate(async () => {
    const workDir = join(TMP_ROOT, jobId);
    job.status = 'processing';
    try {
      await fs.mkdir(workDir, { recursive: true });
      const { finalPath, duration } = await renderReel({
        workDir,
        clipUrls: clips,
        voiceoverUrl,
        subtitlesSrt,
        recipe,
      });
      const key = outputKey || `reels-final/${runId}.mp4`;
      const outputUrl = await uploadFile(key, finalPath, 'video/mp4');
      job.status = 'done';
      job.output_url = outputUrl;
      job.output_key = key;
      job.duration_sec = duration;

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
            }),
          });
        } catch (cbErr) {
          job.callback_error = cbErr.message;
        }
      }
    } catch (err) {
      job.status = 'failed';
      job.error = err.message || String(err);
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

app.listen(PORT, () => {
  console.log(`reels-composer listening on ${PORT}`);
});
