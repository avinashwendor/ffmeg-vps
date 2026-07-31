# Social Media Reels Automation — Agent Handoff

Read this first in a new session. This repo automates short-form reel production: research → script → TTS → Flow prompts → Telegram → clip upload → FFmpeg final render.

## Architecture (two n8n workflows + one render service)

```
Workflow 1: reelsminiautomation.json
  Schedule or Telegram /generate → Tavily → Top 5 topics → user picks 1–5
  → OpenRouter script + image match → Cartesia/ElevenLabs TTS → S3 voice
  → Flow prompts → Upload manifest to S3 → Telegram package

Workflow 2: reels_compose_automation.json
  Telegram only: /compose RUN_ID → upload 5 clips → done
  → load manifest from S3 → OpenRouter render recipe → POST reels-composer /v1/render
  → poll /v1/jobs/:id → Telegram final MP4 link

Render service: reels-composer/ (Node + FFmpeg from git.ffmpeg.org release/8.1)
```

Linked only by **S3** and **`run_id`**. Same Telegram bot for both workflows.

## Infra decisions (confirmed with user)

| Resource | Action |
|----------|--------|
| Railway S3 bucket `lightweight-vault-pew0g4o` | **KEEP** |
| Old `ffmpeg-rest` Railway service | **REMOVE** (basic convert only; no concat/subtitles) |
| Redis on Railway | **REMOVE for v1** (not wired in code yet) |
| `reels-composer` Railway service | **DEPLOY** (4 vCPU / 4 GB recommended) |

## Repo layout

| Path | Purpose |
|------|---------|
| `build_workflow.py` | Generates `reelsminiautomation.json` |
| `build_compose_workflow.py` | Generates `reels_compose_automation.json` |
| `reelsminiautomation.json` | Import into n8n — workflow 1 |
| `reels_compose_automation.json` | Import into n8n — workflow 2 |
| `reels-composer/` | FFmpeg render API (deploy to Railway) |
| `reels-composer/Dockerfile` | Multi-stage: clone `release/8.1` from git.ffmpeg.org, compile, Node app |
| `reels-composer/src/server.js` | `GET /health`, `POST /v1/render`, `GET /v1/jobs/:id` |
| `reels-composer/src/renderJob.js` | Normalize clips, xfade, voice mux, burn ASS subtitles |
| `reels-composer/src/s3.js` | SigV4 presign download/upload (same pattern as n8n) |
| `generate_voiceover_paste.js` | Reference paste for n8n Code node (voiceover) |
| `load_s3_brand_images_paste.js` | Reference paste for S3 image listing |
| `test_railway_s3_http.py` | Local S3 presign test script |

## S3 key conventions

- `images/` — brand reference images (context-named filenames)
- `reels-voiceovers/{slug}-{run_id}.mp3` — TTS output
- `reels-manifests/{run_id}.json` — compose manifest (workflow 1 uploads this)
- `reels-clips/{run_id}/clip-01.mp4` … `clip-05.mp4` — Telegram uploads (workflow 2)
- `reels-final/{run_id}.mp4` — finished reel

## Config to set before go-live

### `build_compose_workflow.py` (lines 13–15)

```python
COMPOSER_URL = "https://YOUR-COMPOSER-SERVICE.up.railway.app"  # ← user must set after deploy
COMPOSER_AUTH_TOKEN = ""  # optional; match Railway AUTH_TOKEN
```

### `build_workflow.py`

- API keys, S3 creds, Telegram chat ID, OpenRouter models
- Regenerate after edits: `python3 build_workflow.py`

### Railway env for `reels-composer`

```
S3_ENDPOINT_HOST=t3.storageapi.dev
S3_BUCKET=lightweight-vault-pew0g4o
S3_REGION=auto
S3_ACCESS_KEY=<from Railway bucket>
S3_SECRET_KEY=<from Railway bucket>
AUTH_TOKEN=<optional bearer secret>
PORT=<set by Railway>
```

## Commands

```bash
# Regenerate n8n JSON after Python changes
python3 build_workflow.py
python3 build_compose_workflow.py

# Local composer dev (requires brew ffmpeg or Docker)
cd reels-composer && npm install && PORT=3847 node src/server.js
curl http://127.0.0.1:3847/health

# Docker build (slow first time ~15–25 min — compiles FFmpeg)
cd reels-composer && docker build -t reels-composer .
```

## n8n setup

1. Import both JSON workflows.
2. Attach **same Telegram bot credential** to all Telegram Trigger + Telegram send nodes.
3. **Activate both workflows** (static data / webhooks require active workflows).
4. Workflow 1: Schedule Trigger (9am cron) + Telegram `/generate` or `/topics`.
5. Workflow 2: Telegram Trigger with **Download Images/Files enabled**.

## User flow (E2E test)

1. Run workflow 1 → pick topic `1`–`5` in Telegram.
2. Note `run_id` in the package (e.g. `2026-07-31-0930`).
3. Generate 5 clips in Google Flow using prompts from Telegram.
4. In Telegram: `/compose {run_id}`
5. Upload 5 videos (optional caption `1`–`5`).
6. Send `done`.
7. Wait for render (n8n polls every 15s) → final MP4 link in Telegram.

Compose commands: `/compose RUN_ID`, `done`, `/status`, `/cancel`.

## Current blockers / next session tasks

- [ ] User deploys `reels-composer/` to Railway (root dir `reels-composer`)
- [ ] User removes old ffmpeg-rest + Redis services
- [ ] Set `COMPOSER_URL` (+ `COMPOSER_AUTH_TOKEN` if used) in `build_compose_workflow.py`
- [ ] Run `python3 build_compose_workflow.py` and re-import JSON in n8n
- [ ] Re-import `reelsminiautomation.json` if manifest node not in n8n yet
- [ ] Full E2E test with real Flow clips
- [ ] Optional: `docker build` locally to verify Dockerfile before Railway deploy

## reels-composer API

```
GET  /health
POST /v1/render
  Body: { run_id, clips: [{index, url, s3_key}], voiceover_url, subtitles_srt, recipe, output_key? }
  Returns: { job_id, status: "queued" }
GET  /v1/jobs/:id
  Returns: { status: queued|processing|done|failed, output_url?, error? }
```

Auth: `Authorization: Bearer ${AUTH_TOKEN}` when `AUTH_TOKEN` env is set.

Jobs are **in-memory** (`Map` in `server.js`) — fine for single-user / ~50 reels/month. Survives neither restart nor horizontal scale.

## Phase 2 (not built — do not claim in code until implemented)

- Redis + BullMQ job queue (replace in-memory `jobs` Map)
- Webhook callback to n8n instead of poll loop
- Move API keys from `build_workflow.py` inline strings to n8n credentials / env refs
- Telegram Send Video binary for finals under 50 MB

## Code conventions

- n8n workflows are **generated** from Python — edit `build_workflow.py` / `build_compose_workflow.py`, not JSON by hand (unless hotfix).
- S3 SigV4 helpers are duplicated in Python-generated JS and `reels-composer/src/s3.js` — keep in sync if bucket/creds change.
- User rule: React Query hooks for APIs — **N/A here** (n8n + Node worker, no React app).
- Do not create extra `.md` files unless user asks.

## Secrets warning

`build_workflow.py` contains inline API keys. Do not commit new secrets to JSON exports. Prefer n8n credentials for production.

## FFmpeg source note

Official clone verified: `git clone --depth 1 --branch release/8.1 https://git.ffmpeg.org/ffmpeg.git`
Dockerfile uses this (not `master`). Local dev can use `brew install ffmpeg` instead of compiling.
