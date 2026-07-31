# ffmeg-vps

Vending-machine reels, end to end: research a topic, write a 40-second script,
record the voiceover, hand you five Google Flow prompts, then cut the clips you
get back into a finished 9:16 reel with burned subtitles.

n8n drives it over Telegram; an FFmpeg service on Railway does the render.

## How a reel gets made

```
/generate                    pick a topic (or /generate 3, or /generate <topic>)
   ↓
  script → voiceover → sync map → 5 Flow prompts
   ↓
Telegram package             voiceover link, image links, 5 prompts,
                             and the filename to save each clip as
   ↓
you run the prompts in Google Flow and download 5 clips
   ↓
/compose RUN_ID              send the clips (any order — the filename says which)
   ↓
done                         → finished MP4 back in Telegram
```

The reel is a fixed 5 × 8s grid because that is what Flow returns. Subtitles,
per-clip trims and playback speed are all computed from the *measured* length of
the recorded voiceover, so the picture lands on the words. See `AGENTS.md` for
how that works and why it is not left to a model.

## Layout

```
build/                          # Python → generates n8n JSON
  build_workflow.py             # main builder (validates as it writes)
  build_compose_workflow.py     # /compose handlers, injected into the main workflow
  build_linkedin_workflow.py    # separate LinkedIn workflow
  validate_workflow.py          # parses every Code node
  test_reels_nodes.py           # executes the Code nodes against stubs
  deploy_n8n.py                 # push JSON to the n8n API
  config.py                     # keys from env or secrets_local.py

automations/
  mini_automation_for_reels.json   # import this into n8n
  linkedin_post_automation.json
  archive/                         # superseded exports

reels-composer/                 # FFmpeg API (Railway)
```

## Build

```bash
python3 build/build_workflow.py
python3 build/test_reels_nodes.py
```

Output: `automations/mini_automation_for_reels.json`. The build refuses to write
a workflow whose Code nodes do not parse — n8n would otherwise accept it and
fail only when the broken node runs.

The generated JSON contains your API keys in plain text. Do not commit it.

## Telegram commands

| | |
|---|---|
| `/generate` | research topics, then reply `1`–`5` |
| `/generate 3` | skip the picker, take topic #3 |
| `/generate <topic>` | skip research entirely |
| `/compose RUN_ID` | start collecting Flow clips |
| `done` | render |
| `/status` `/cancel` `/help` | |

## Deploy

n8n: set `N8N_API_KEY` (env or `build/secrets_local.py`), then
`python3 build/deploy_n8n.py`.

Composer: Railway builds the root `Dockerfile` on push to `main`. Check it with
`curl https://ffmeg-vps-production.up.railway.app/health`.

See `AGENTS.md` for full setup.
