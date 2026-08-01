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
npm --prefix reels-composer test   # look engine, publish stubs, real renders
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
3. TTS reads that one string and reports **where every word falls** (see below).
4. **Build Sync Map** cuts each scene at the moment its first word is spoken,
   then generates *both* the SRT and the per-clip trim/speed plan from that one
   timeline. Clips 1-4 carry an extra transition length because xfade overlaps
   neighbours; clip 5 carries a 0.25s tail so `-shortest` cannot clip the last
   word.
5. **Start Render** sends that plan verbatim, along with the `voiceover_sec`,
   `transition_sec` and `tail_sec` it was built against. The model is only asked
   to pick a look — colour, subtitle face, transition length, per-clip zoom. A
   model choosing trim points is how a reel ends up out of sync.
6. **The composer corrects the plan against reality** before it renders. See
   below.

Anything that cannot be made to fit surfaces in `sync_warnings`, which is shown
in the Telegram package. It never silently produces a desynced video.

### TTS runs three deep, and it is about captions as much as audio

| order | endpoint | gives |
| ----- | -------- | ----- |
| 1 | Cartesia `/tts/sse` | PCM **plus per-word timestamps** |
| 2 | Cartesia `/tts/bytes` | plain mp3, no timestamps |
| 3 | ElevenLabs `/with-timestamps` | mp3 plus a *character* alignment |

Each branch labels its own output (`tts_provider`, `voiceover_ext`,
`word_timings`) so nothing downstream has to sniff which node produced the
audio, and each falls through to the next rather than stopping the run.

Two things about the first branch are not obvious:

- `/tts/sse` is the **only** Cartesia endpoint that emits timestamps, and it
  rejects every container but `raw`. So what comes back is bare PCM, and
  `PARSE_CARTESIA_SSE_JS` puts a 44-byte WAV header on it itself. ffprobe reads
  the result exactly, which is strictly better than the bitrate arithmetic the
  mp3 path needed. At `VOICEOVER_SAMPLE_RATE` a 50s reel is a ~4.4 MB WAV —
  drop that constant to 22050 if n8n struggles with the payload.
- Timestamps **arrive in slices**, one event per handful of words, so they must
  be gathered across the whole stream rather than read off the first event that
  has any. A stream that ends without a `done` event is rejected outright: a
  truncated voiceover is worse than falling back to the mp3 endpoint.

### Captions sit on the word, not near it

When the timings line up 1:1 with the script, every scene boundary and every
subtitle cue is cut at the exact moment its first word is spoken, and each cue
holds until the next one starts instead of blinking off in every pause.

Alignment is checked, not assumed: `alignTimings` walks both lists and merges
spans where the engine split one word into several tokens. Anything beyond that
and it returns `null`, because hanging the whole timeline off a bad alignment is
worse than estimating. The fallback estimate weights each scene by `speechUnits`
(syllables + a per-word gap + a pause for punctuation) rather than word count —
"profits stall" and "eighty thousand rupees" are both three words and nowhere
near the same length of speech. Only the ratios matter, so those constants never
need calibrating to real seconds.

A fallback is reported in `sync_warnings` and in `caption_timing_source`, never
silent. Cues also break on a character budget so a run of long words cannot
produce a caption wider than the frame.

### The plan is a prediction; the composer checks it

Two things about the plan can be wrong on arrival, and both used to cut the last
words off the reel:

- `voiceover_sec` is measured before this service ever sees the file — exactly
  when the WAV path ran, but derived from **byte size** on the mp3 fallbacks,
  where an ID3 tag or a provider ignoring the requested bitrate shifts it.
- the render director is allowed to pick a **250-400ms crossfade**, while the
  plan budgeted for whatever `transition_sec` the manifest recorded. A longer
  crossfade eats more of every clip: at 400ms against a 300ms plan the reel
  finishes 0.15s early.

So `renderReel` downloads the voiceover **first**, ffprobes it, and rescales the
per-clip windows and the SRT (`voiceoverScale`, `rescalePerClip`, `scaleSrt`).
Each clip's window is a speech share plus a fixed overlap: the share scales, the
overlap is *swapped*, never stretched. Probing first also means a dead link
fails in seconds instead of after five minutes of encoding.

A ratio beyond 0.5-2x is treated as a plan belonging to a different run and left
alone rather than stretched to fit.

### Nothing ships unchecked

`qcReel` runs on the finished file: length against the voiceover that was
actually measured, exactly one audio track, a 1080x1920 frame. The result rides
on the job and into the Telegram reply. A reel that fails is still uploaded —
but the message leads with the problem instead of "your reel is ready", and the
compose session stays open so the five clips do not have to be sent again.

`reels-composer/test/sync_qc.test.mjs` renders these cases for real, including a
manifest that under-estimates the voiceover by 10%.

## Clip naming is the contract

The package message tells the user to save each Flow download as
`RUNID-clip1.mp4` … `RUNID-clip5.mp4`. `Prepare Clip S3 Upload` resolves the
slot in this order: **filename → caption (`1`-`5`) → the fast model reading the
filename against the scene briefs → album position → first free slot**.

The model step exists because Flow names downloads after the prompt, so
`people browsing chips office lobby.mp4` genuinely does say which scene it is.
It only answers with a free slot and only above 0.55 confidence — a wrong guess
reorders the reel, while a null falls through to the next free slot, which is no
worse than never asking. The filename regex was also tightened: a trailing hex
digit in `Whisk_a1b2c3.mp4` is not a clip number, and reading it as one silently
reordered reels.

Brand reference images use the same convention in the other direction:
`part1-…jpg` … `part5-…jpg` in `images/` map straight to clips 1-5 with no model
involved.

### Slot ownership is not in the session

A Telegram album arrives as **five parallel n8n executions**. They all used to
load the one session object, add their clip, and write it back — so whichever
finished last threw away the other four. That is the whole reason clips went
missing and the bot asked for them again, and why `/status` could show clip 2
as waiting when it had already been sent.

Nothing about which clip took which slot lives in the session now. Each
execution writes its own key and the answer is read back by listing:

- `reels-compose-claims/{chat}/{run}/{slot}-{message_id}.json` — the reservation
- `reels-clips/{run}/clip-0N.mp4` — the clip itself

Two executions can no longer overwrite each other because they never write the
same key. The slot is *in* the key name, so one LIST answers both "which slots
are taken" and "by whom" without reading any bodies. When two do claim the same
slot, both see both claims and both apply the same rule — lowest message id
keeps it — so they settle without coordinating.

`/status`, the "still need" line and the `done` gate are all computed from
`clipsOnS3()`, which lists `reels-clips/{run}/` **with sizes** and drops
zero-byte objects. A dead PUT leaves a zero-byte key that otherwise looks
exactly like an arrived clip.

### Getting the bytes at all

`Telegram Download Clip` (a Telegram node, resource *file*, `retryOnFail` ×3)
now runs ahead of the Code node and fetches by `file_id` using the workflow's
own bot credential. The trigger's own download is best-effort and drops files
under an album of five — that is what produced "Could not read the video bytes".
The Code node still falls back to the trigger's binary, then to the Bot API with
`TELEGRAM_BOT_TOKEN`, and retries the whole read three times.

`S3 PUT Clip` retries too, and **`Finalize Clip Upload` reads the object back**
before saying a word. A 200 from the PUT is not proof the clip is there: if it
is missing or short, the reply names that one clip and releases the claim so a
resend can take the slot. "Saved" now means saved.

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
- `reels-compose-claims/{chat_id}/{run_id}/{slot}-{message_id}.json`
- `reels-voiceovers/{slug}-{run_id}.mp3`
- `reels-final/{run_id}.mp4`
- `reels-compose-sessions/{chat_id}.json`
- `images/` — brand reference images

## Composer

`https://ffmeg-vps-production.up.railway.app`, deployed from the GitHub repo
`avinashwendor/ffmeg-vps` (Railway builds the root `Dockerfile` on push to
`main`). `GET /health` reports ffmpeg's version.

### Required Railway service variables

`S3_ACCESS_KEY` and `S3_SECRET_KEY` **must** be set on the Railway service, to
the same values as `RAILWAY_S3_ACCESS_KEY` / `RAILWAY_S3_SECRET_KEY` in
`build/secrets_local.py`. `src/s3.js` defaults them to `''`, so without them
every render finishes the whole ffmpeg pipeline and then dies on the final
upload with `InvalidAccessKeyId`. The other S3 variables have working defaults.

Optional: `AUTH_TOKEN` (pair with `COMPOSER_AUTH_TOKEN` in
`build/secrets_local.py`), `FFMPEG_THREADS`, `FFMPEG_PRESET`, `FFMPEG_CRF`,
`QC_TOLERANCE_SEC`, `JOB_TTL_MS`, `S3_DOWNLOAD_ATTEMPTS`.

`GET /health` reports `s3_configured`, `queue_depth` and `jobs_tracked`, so a
service missing its S3 keys is visible without waiting for a render to die on
the final upload.

Renders are **serialised** — one at a time, whatever arrives. ffmpeg is tuned to
sit inside the container's memory limit for a single 1080x1920 encode; two
concurrent renders is how the OOM killer comes back. Requests are still accepted
immediately and queued.

Burning subtitles needs an ffmpeg built with **libass**. Debian's `ffmpeg`
package has it, which is what the Dockerfile installs; many static builds do
not, and the filter is simply absent. `renderReel` checks for it before encoding
anything, because the failure otherwise lands at the very last step as an
unhelpful filtergraph parse error.

Bugs fixed in `reels-composer/src/renderJob.js` that all failed silently:

- `downloadToFile` was used without being imported, so **every** render failed
  with `downloadToFile is not defined`.
- `setpts` was passed as `-filter:v` while the rest of the chain was passed as
  `-vf`. Those are aliases, so the later flag won and per-clip `speed` was
  quietly discarded — sync correction never actually applied.

- a crossfade longer than the plan assumed shortened the reel by 0.15s, which
  is under any tolerance worth failing on and still clips the last word.

Also: subtitle colours are now converted to ASS `&HBBGGRR` instead of a
find-and-replace that never matched, and trims use `-t` rather than `-to`.
Captions are wrapped deliberately (`wrapCue`) rather than left to libass, which
picks its own break point and strands single words on a second line.

A third failure was environmental. Any render of two or more clips died with a
null exit code — the container OOM killer. ffmpeg sizes its thread pools from
the host's core count, not the container's memory limit, so x264 held
(threads + lookahead) 1080x1920 frames in flight during the xfade step, where
two streams decode at once. One clip fit, two did not. Threads and lookahead
are now capped; a null exit reports the OOM plainly instead of dumping raw
progress output.

## The look — motion, cuts and captions

`reels-composer/src/looks.js` owns everything about how the reel *looks*. It is
deliberately separate from `renderJob.js`, which owns timing, and it cannot
desync a reel: motion is a crop over footage that has already been trimmed to
the frame, every cut shares one duration the plan was built against, and
captions are read off word timings the workflow measured.

**Motion.** Every clip gets a slow move, and neighbouring clips get different
ones so the cut has something to cut on. Eleven presets (`push_in`, `pan_right`,
`tilt_up`, `rise`, …), each expressed as a start and end framing. Two
implementations, picked by whether the zoom actually changes:

- fixed zoom → one `scale` and a `crop` with per-frame x/y. Nothing resamples.
- changing zoom → `scale` with `eval=frame`, then a crop.

That second one is deliberately **not** `zoompan`, which is the filter usually
reached for here. Measured on a 10s 1080x1920 clip: zoompan 16s, `eval=frame`
11s. Five clips a render is where that starts to matter.

**Cuts.** One xfade type per boundary, from a catalogue of 23. A fade at all
four cuts is the single thing that makes a short look auto-generated. Durations
stay identical across all four — the plan gave each clip its screen time against
one crossfade length, so varying it would shorten the reel. `xfadeTransitions()`
reads what this ffmpeg build actually has, because xfade grew most of its
catalogue across 5.x and naming a missing type fails the filtergraph at the very
last step, after every clip has already encoded.

**Captions.** Eight presets over six animations: `none`, `fade`, `pop`, `rise`,
`karaoke` (per-word `\kf` sweep) and `word` (one word at a time). The last two
need per-word timings, which is why `Build Sync Map` now emits `caption_cues`
carrying every word's start and end alongside the SRT. Without them both degrade
to `pop` rather than disappearing — and `OpenRouter Render Director` is told
whether timings exist and swaps the preset itself if the model picks one anyway.
Estimated timings are never good enough to light up individual words; a caption
highlighting the wrong word is worse than one that does not move.

The director now chooses `motion`, `transitions`, `subtitles.preset`, `finish`
(vignette/grain/sharpen) and `color`. Everything it returns is validated by the
composer and falls back on anything unrecognised, so a model inventing a
transition name can never fail a render. The defaults still move and still
animate — a fallback that renders five static shots with flat subtitles is a
worse reel, not a safer one.

`reels-composer/test/looks.test.mjs` runs every motion through real ffmpeg and
checks the frame comes out 1080x1920. Burning captions needs libass, which many
developer machines lack; the ASS *files* are still validated by having ffprobe
read each preset back (the ass demuxer is separate from the libass-backed
`subtitles` filter).

## Posting the reel

The finished reel goes back to Telegram as a **video**, not a link — n8n
downloads it and uploads the bytes, because Telegram will only fetch a URL
itself up to 20 MB and a 50s 1080x1920 encode goes past that. Then the bot asks.
`yes` publishes, `no` closes the session. The session is no longer dropped when
the render finishes; it carries the reel and its captions through that question,
so answering an hour later still works.

The upload runs on the composer (`POST /v1/publish`, polled at
`/v1/publish/{id}`) rather than in n8n, because YouTube wants the file's bytes
on a resumable session and a Code node cannot carry a 20 MB video through the
task runner.

- **Instagram** is a three-step publish: create a REELS container from a URL
  Graph can fetch, poll until `status_code` is `FINISHED`, then publish.
  Publishing a container that is still `IN_PROGRESS` fails with an error that
  does not say why, which is the mistake worth knowing about.
- **YouTube** refreshes an OAuth token, opens a resumable session, and streams
  the file to the `Location` header it returns.

The two are independent: one being unconfigured, rate-limited or rejected never
stops the other, and every outcome is reported per platform. "Nothing was
configured" is reported differently from "both failed" — the first names the
variables to set.

Railway service variables: `IG_USER_ID`, `IG_ACCESS_TOKEN`,
`YT_CLIENT_ID`, `YT_CLIENT_SECRET`, `YT_REFRESH_TOKEN`, and optionally
`YT_PRIVACY_STATUS` (`unlisted` while testing). `GET /health` reports
`publish_targets` so a missing key is visible before anyone answers `yes`.
`reels-composer/test/publish.test.mjs` drives both against stub servers.

## Only the voiceover is ever heard

Gemini Omni generates speech, effects and lip movement with every clip. None of
it reaches the reel, guarded twice: `-an` on `normalizeClip` strips each clip's
audio on the first pass, and `muxVoiceover` maps `0:v:0` and `1:a:0` explicitly
so audio can only come from the voiceover file. `reels-composer/test/audio_isolation.test.mjs`
renders clips with a loud tone baked in and asserts none of it survives — run it
if you touch either.

The picture side is prompt-only and cannot be enforced in code: the Flow prompt
forbids talking to camera, because a mouth moving to words the voiceover is not
saying is what makes a reel look broken. If clips come back with people
speaking, that instruction is what needs tightening.

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
