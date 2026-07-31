# Social Media Reels Automation — Agent Handoff

## Layout

```
build/
  build_workflow.py          → automations/mini_automation_for_reels.json   (MAIN)
  build_compose_workflow.py  → compose handlers, injected into the main workflow
  build_linkedin_workflow.py → automations/linkedin_post_automation.json
  validate_workflow.py       → parses every Code node; run before importing
  test_reels_nodes.py        → runs the Code nodes against stubbed S3/OpenRouter
  deploy_n8n.py              → push main JSON to the n8n API
  config.py                  → keys from env or build/secrets_local.py (gitignored)

automations/
  mini_automation_for_reels.json   # import this into n8n
  linkedin_post_automation.json
  archive/                         # superseded exports, not imported

reels-composer/           # FFmpeg render API on Railway
```

## Build

```bash
python3 build/build_workflow.py    # writes the JSON and validates it
python3 build/test_reels_nodes.py  # executes the Code nodes
```

`build_workflow.py` fails the build if any Code node does not parse. **Do not
skip this.** The workflow JSON is generated from Python, so a plain string that
should have been an f-string emits `${{expr}}` into JavaScript — a syntax error
n8n does not surface until that node happens to run. That is precisely how
`/compose` sat silently broken. `validate_workflow.py` greps for `${{` and
parses every node with `node --check`.

`test_reels_nodes.py` goes further and actually executes the nodes against an
in-memory bucket. Parsing is not enough: splitting a helper out of the shared
S3 bundle produced a node that parsed fine and threw `saveComposeSession is not
defined` at runtime. Run both.

## The reel is a fixed 5 × 8s grid

Google Flow returns 8-second clips, so the reel is 40 seconds and everything
derives from `CLIP_COUNT`, `CLIP_SEC` and `WORDS_PER_SEC` at the top of
`build_workflow.py`. Do not hardcode 8 or 40 anywhere else.

How sync is held together — the important part:

1. **OpenRouter Script Package** writes 5 scenes, each with a
   `voiceover_segment` of 18-22 spoken words.
2. **Normalize Script Timing** strips anything a speech engine would read aloud
   (stage directions, speaker labels, markdown) and builds `full_script` by
   concatenating the segments. The audio and the scenes are then *the same
   thing*, not two independent guesses at the same thing. This is the single
   change that makes sync work.
3. TTS reads that one string. Cartesia is pinned to 128 kbps so
   **Finalize Voiceover** can derive the true duration from the file size.
4. **Build Sync Map** splits the measured audio across the 5 scenes by word
   share, then generates *both* the SRT and the per-clip trim/speed plan from
   that one timeline. Clips 1-4 carry an extra transition length because xfade
   overlaps neighbours; clip 5 carries a 0.25s tail so `-shortest` cannot clip
   the last word.
5. **Start Render** sends that plan verbatim. The model is only asked to pick a
   look — colour, subtitle face, transition length, per-clip zoom. A model
   choosing trim points is how a reel ends up out of sync.

Anything that cannot be made to fit surfaces in `sync_warnings`, which is shown
in the Telegram package. It never silently produces a desynced video.

## Clip naming is the contract

The package message tells the user to save each Flow download as
`RUNID-clip1.mp4` … `RUNID-clip5.mp4`. `Handle Clip Upload WF1` resolves the
slot in this order: **filename → caption (`1`-`5`) → album position → first free
slot**. Filename first makes ordering deterministic and race-free, which matters
because a Telegram album arrives as several parallel n8n executions that all
read and write the same session object.

Brand reference images use the same convention in the other direction:
`part1-…jpg` … `part5-…jpg` in `images/` map straight to clips 1-5 with no model
involved.

## Secrets

Environment variables (`OPENROUTER_KEY`, `RAILWAY_S3_ACCESS_KEY`, …) or
`build/secrets_local.py` (gitignored):

```python
OPENROUTER_KEY = "sk-or-..."
RAILWAY_S3_ACCESS_KEY = "tid_..."
RAILWAY_S3_SECRET_KEY = "tsec_..."
```

Note that the generated workflow JSON embeds these keys in plain text — treat
`automations/*.json` as secret.

## S3 keys

- `reels-manifests/{run_id}.json`
- `reels-clips/{run_id}/clip-01.mp4` … `clip-05.mp4`
- `reels-voiceovers/{slug}-{run_id}.mp3`
- `reels-final/{run_id}.mp4`
- `reels-compose-sessions/{chat_id}.json`
- `images/` — brand reference images

## Composer

`https://ffmeg-vps-production.up.railway.app`, deployed from the GitHub repo
`avinashwendor/ffmeg-vps` (Railway builds the root `Dockerfile` on push to
`main`). `GET /health` reports ffmpeg's version.

Two bugs fixed in `reels-composer/src/renderJob.js` that both failed silently:

- `downloadToFile` was used without being imported, so **every** render failed
  with `downloadToFile is not defined`.
- `setpts` was passed as `-filter:v` while the rest of the chain was passed as
  `-vf`. Those are aliases, so the later flag won and per-clip `speed` was
  quietly discarded — sync correction never actually applied.

Also: subtitle colours are now converted to ASS `&HBBGGRR` instead of a
find-and-replace that never matched, and trims use `-t` rather than `-to`.

## n8n notes

- Telegram Trigger needs **Download ON** or clip uploads arrive with no binary.
- Use HTTP Request nodes for binary S3 PUT. A Code node cannot carry the MP3
  through the task runner.
- `getObject()` uses a signed GET; presigned GET often 403s inside the Code
  sandbox.
- Telegram chat ID must be the user's own ID from @userinfobot, never the
  bot's. Any `/start` saves it to workflow static data.
- Code nodes cannot import, so the SigV4 signing helpers are inlined into every
  node that touches S3. That duplication is deliberate; the helpers are split
  into `s3_common_js()` / `S3_SESSION_JS` / `S3_IMAGES_JS` so a node only
  carries what it uses.

## Deploy

```bash
python3 build/deploy_n8n.py   # needs N8N_API_KEY
```
