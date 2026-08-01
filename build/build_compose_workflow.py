#!/usr/bin/env python3
"""Optional: generate legacy standalone compose workflow in automations/archive/."""
import json
import sys
import uuid
from pathlib import Path

BUILD_DIR = Path(__file__).resolve().parent
if str(BUILD_DIR) not in sys.path:
    sys.path.insert(0, str(BUILD_DIR))

from config import *  # noqa: F403
from paths import ARCHIVE_DIR
from workflow_common import resolve_telegram_chat_js

REELS_CHAT_RESOLVE_JS = resolve_telegram_chat_js("telegram_chat_id", TELEGRAM_CHAT_ID)

OPENROUTER_MODEL_HEAVY = "anthropic/claude-sonnet-5"
RENDER_POLL_MAX_ATTEMPTS = 40  # 40 x 15s wait ≈ 10 min
PUBLISH_POLL_MAX_ATTEMPTS = 40  # 40 x 15s wait ≈ 10 min

# The vocabulary the render director is allowed to choose from. These are only
# *prompt* guidance — reels-composer/src/looks.js validates every one of them
# and falls back on anything it does not recognise, so a model inventing a
# transition name can never fail a render. Keep them roughly in step anyway;
# a name the composer has never heard of is a wasted creative choice.
MOTION_NAMES = [
    "hold", "push_in", "pull_out", "pan_left", "pan_right",
    "tilt_up", "tilt_down", "push_left", "push_right", "rise", "settle",
]
TRANSITION_NAMES = [
    "fade", "fadeblack", "fadefast", "dissolve", "smoothleft", "smoothright",
    "smoothup", "smoothdown", "slideleft", "slideright", "slideup", "wipeleft",
    "wiperight", "wipeup", "circleopen", "circleclose", "radial", "coverleft",
    "coverup", "revealright", "zoomin", "squeezev", "hblur",
]
CAPTION_PRESETS = [
    "clean_bold", "soft_fade", "pop_punch", "rise_clean",
    "karaoke_gold", "karaoke_mint", "word_punch", "boxed_news",
]

TELEGRAM_ESCAPE_HTML_JS = """
function escapeHtml(text) {
  return String(text || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}
"""


def nid():
    return str(uuid.uuid4())


def compose_action_if(action_value):
    return {
        "conditions": {
            "options": {"caseSensitive": True, "leftValue": "", "typeValidation": "loose", "version": 2},
            "conditions": [
                {
                    "id": nid(),
                    "leftValue": "={{ $json.compose_action || $json.action }}",
                    "rightValue": action_value,
                    "operator": {"type": "string", "operation": "equals"},
                },
            ],
            "combinator": "and",
        },
        "looseTypeValidation": True,
        "options": {},
    }


def status_cancel_help_if():
    """One IF for the three session-control commands that share a handler."""
    return {
        "conditions": {
            "options": {"caseSensitive": True, "leftValue": "", "typeValidation": "loose", "version": 2},
            "conditions": [
                {
                    "id": nid(),
                    "leftValue": "={{ $json.compose_action || $json.action }}",
                    "rightValue": action,
                    "operator": {"type": "string", "operation": "equals"},
                }
                for action in ("status", "cancel", "help")
            ],
            "combinator": "or",
        },
        "looseTypeValidation": True,
        "options": {},
    }


def build_compose_handlers(s3_session_js, prepare_clip_js, finalize_clip_js):
    """s3_session_js must supply the S3 primitives *and* the compose-session
    helpers — every handler here loads or saves a session."""
    s3 = s3_session_js()
    for required in ("loadComposeSession", "saveComposeSession", "deleteComposeSession"):
        if f"function {required}" not in s3:
            raise SystemExit(f"build_compose_handlers: session helper {required}() missing from the S3 bundle")

    handle_compose_start_js = TELEGRAM_ESCAPE_HTML_JS + REELS_CHAT_RESOLVE_JS + s3 + """
const staticData = $getWorkflowStaticData('global');
const chatId = resolveTelegramChatId($json, staticData);
const runId = $json.run_id;
if (!runId) throw new Error('Usage: /compose RUN_ID (example: /compose 2026-07-30-0930)');

const key = `reels-manifests/${runId}.json`;
let manifest;
try {
  const text = await getObject.call(this, key);
  manifest = parseS3JsonText(text);
  if (!manifest) throw new Error('Manifest file is empty');
} catch (err) {
  throw new Error(`Manifest not found for run_id "${runId}". Run the reels generator first, or check the run_id. (${err.message || err})`);
}

const session = {
  state: 'collecting',
  run_id: runId,
  chat_id: chatId,
  manifest,
  clips: [],
  started_at: Date.now(),
  // Generating and downloading five Flow clips is not a two-hour job in practice.
  expires_at: Date.now() + 12 * 60 * 60 * 1000,
};
await saveComposeSession.call(this, chatId, session);

const title = manifest.selected_topic?.title || manifest.topic_slug || runId;
return [{
  json: {
    chat_id: chatId,
    reply_text: [
      `Compose session started`,
      `Topic: ${escapeHtml(title)}`,
      `Run: ${escapeHtml(runId)}`,
      ``,
      `Send me the 5 Flow clips (album is fine, any order).`,
      `Name each file with its clip number — clip1.mp4 … clip5.mp4 — and I place it in the right slot.`,
      `No number in the name? I read the name against the scene briefs and work it`,
      `out. You can also send the clip with caption 1-5 to be certain.`,
      ``,
      `Every clip is checked in storage after it uploads, so "saved" means saved.`,
      `If one does not make it I will name it and you resend only that one.`,
      ``,
      `/status to see progress · done when all 5 are in · /cancel to abort`,
    ].join('\\n'),
  },
}];
"""

    handle_status_cancel_js = TELEGRAM_ESCAPE_HTML_JS + REELS_CHAT_RESOLVE_JS + s3 + """
const staticData = $getWorkflowStaticData('global');
const chatId = resolveTelegramChatId($json, staticData);

const action = $json.compose_action || $json.action;
if (action === 'cancel') {
  await deleteComposeSession.call(this, chatId);
  return [{ json: { chat_id: chatId, reply_text: 'Compose session cancelled.' } }];
}
if (action === 'help') {
  return [{ json: { chat_id: chatId, reply_text: [
    '<b>Reels bot</b>',
    '',
    '<b>Make a video package</b>',
    '/generate — research topics, then reply 1-5 to pick one',
    '/generate 3 — skip the picker, take topic #3',
    '/generate your own topic — skip research entirely',
    '',
    '<b>Turn Flow clips into the final reel</b>',
    '/compose RUN_ID — start collecting (run id is in the package message)',
    'then send the 5 clips named clip1.mp4 … clip5.mp4',
    'done — render · /status — progress · /cancel — abort',
    '',
    '<b>Post it</b>',
    'When the reel comes back I ask whether to upload it.',
    'yes — Instagram Reels and YouTube Shorts · no — stop there',
  ].join('\\n') } }];
}

const session = await loadComposeSession.call(this, chatId);
if (!session) {
  return [{ json: { chat_id: chatId, reply_text: 'No active session. /compose RUN_ID to start.' } }];
}

if (session.state === 'awaiting_publish') {
  return [{ json: { chat_id: chatId, reply_text: [
    `Session: ${escapeHtml(session.run_id)}`,
    'The reel is rendered and waiting on you.',
    '',
    'yes — post it to Instagram and YouTube',
    'no — stop here',
  ].join('\\n') } }];
}
if (session.state === 'publishing') {
  return [{ json: { chat_id: chatId, reply_text: `Session: ${escapeHtml(session.run_id)}\\nUploading now — I will report back as each platform lands.` } }];
}

// Read from the bucket, not from the session. A session write lost to a
// parallel upload used to make a clip that is sitting on S3 look missing, and
// that is what made the bot ask for clips that had already been sent.
const onS3 = await clipsOnS3.call(this, session.run_id);
const byIndex = new Map(onS3.map((c) => [Number(c.index), c]));
const lines = [1, 2, 3, 4, 5]
  .map((i) => {
    const c = byIndex.get(i);
    return c ? `Clip ${i}/5  received  ${(c.size / 1048576).toFixed(1)}MB` : `Clip ${i}/5  waiting`;
  })
  .join('\\n');
const missing = [1, 2, 3, 4, 5].filter((i) => !byIndex.has(i));
const nextStep = missing.length
  ? `Still need: ${missing.map((i) => `clip${i}.mp4`).join(', ')}`
  : 'All 5 in. Send done to render.';
return [{
  json: {
    chat_id: chatId,
    reply_text: [
      `Session: ${escapeHtml(session.run_id)}`,
      `Clips: ${byIndex.size}/5`,
      '',
      lines,
      '',
      nextStep,
    ].join('\\n'),
  },
}];
"""

    openrouter_render_director_js = f"""
{REELS_CHAT_RESOLVE_JS}
{s3}
const staticData = $getWorkflowStaticData('global');
const chatId = resolveTelegramChatId($json, staticData);
let session = await loadComposeSession.call(this, chatId);
if (!session) throw new Error('No active session. /compose RUN_ID first.');

// What is actually in the bucket, with the zero-byte objects already dropped.
// The session is not consulted for this — it never wins an argument with the
// files the render is about to read.
const clips = await clipsOnS3.call(this, session.run_id);
if (clips.length < 5) {{
  const missing = [1, 2, 3, 4, 5].filter((i) => !clips.some((c) => c.index === i));
  throw new Error(`Need 5 clips before done — ${{clips.length}}/5 are in storage. Still missing: ${{missing.map((i) => `clip${{i}}.mp4`).join(', ')}}. Send those and try done again.`);
}}

const manifest = session.manifest;

// Only the creative decisions go to the model. Clip order and per-clip timing
// are computed from the measured voiceover in Start Render — a model guessing
// trim points is exactly how a reel ends up out of sync.
const userContent = JSON.stringify({{
  topic: manifest.selected_topic?.title,
  production_bible: manifest.production_bible,
  voiceover_seconds: manifest.voiceover_sec,
  // Whether the voice engine reported where each word lands. Without it the
  // word-by-word caption styles have nothing to sit on, so the model is told
  // rather than left to pick one that will quietly degrade.
  word_timings_available: Boolean(manifest.caption_words_measured),
  beats: (manifest.sync_windows || []).map((w) => ({{
    clip: w.clip_number,
    beat: w.narrative_beat,
    seconds: w.vo_seconds,
    voiceover: w.spoken_text,
  }})),
}}, null, 2);

const body = {{
  model: {json.dumps(OPENROUTER_MODEL_HEAVY)},
  response_format: {{ type: 'json_object' }},
  messages: [
    {{
      role: 'system',
      content: `You are the editor, colourist and title designer on a 9:16 short. You are given its beats and you decide how it moves and how it reads. Timing, clip order and trims are already fixed by the edit — never attempt to set them.

Return ONE valid JSON object with exactly these keys:

  style_name       short name for the look, e.g. "warm office documentary"

  motion           array of 5 camera moves, one per clip, from:
                   {json.dumps(MOTION_NAMES)}
                   Every clip moves. Never repeat the same move on two clips in
                   a row — the cut between them is what it costs you. Push in on
                   a claim, pull out on a reveal, pan across a room, rise on an
                   aspirational beat, and use "hold" only when the footage is
                   already moving hard on its own.

  per_clip_zoom    array of 5 numbers 1.0-1.1. This is how *far* each move
                   travels, on top of the move itself. 1.0 is the natural
                   amount; go higher only where the beat wants real energy.

  transitions      array of 4 cuts, one per boundary, each {{ type, duration_ms }},
                   type from: {json.dumps(TRANSITION_NAMES)}
                   duration_ms 250-400 and IDENTICAL on all four — only the
                   first is read, because the whole edit was timed against one
                   crossfade length. Vary the type, not the length. A fade
                   everywhere is the single thing that makes a short look
                   auto-generated; a smooth wipe or a slide on a change of
                   place, a plain fade inside one continuous idea.

  subtitles        {{ mode: "burn", preset, ... }} where preset is one of:
                   {json.dumps(CAPTION_PRESETS)}
                   - karaoke_gold / karaoke_mint light each word as it is
                     spoken; word_punch puts one word on screen at a time. All
                     three need word_timings_available to be true in the input.
                     If it is false, do not choose them — pick pop_punch instead.
                   - pop_punch and rise_clean animate per line and always work.
                   - clean_bold and boxed_news are the restrained options.
                   You may override any of font, size, color, outline_color,
                   highlight_color, all_caps. Sizes are 44-64, or up to 96 for
                   word_punch. Hex colours, high contrast, readable over any
                   frame. Leave position alone — every preset already sits in
                   the lower third, which is where a caption belongs; nothing
                   here should ever float mid-frame or near the top.

  color            {{ saturation, contrast, brightness }}
                   saturation 0.9-1.25, contrast 0.95-1.2, brightness -0.05-0.05

  finish           {{ vignette, grain, sharpen }}
                   vignette 0-1, grain 0-6, sharpen 0-0.8. All default to 0.
                   A little vignette pulls the eye in on a vertical frame and a
                   little grain stops flat AI gradients from banding. Overdone
                   they both look cheap.

  audio            {{ voiceover_gain_db, fade_in_ms, fade_out_ms }}
                   gain -2 to 2, fades 150-500ms

Match all of it to the script. A hard-numbers business short wants a neutral
grade, restrained moves and a plain bold caption. A lifestyle or freedom beat
can take warmth, a rise, and captions that punch word by word. Keep it premium
and legible — never neon, never a decorative script font, never a move so big
the frame looks like it is being shoved.`,
    }},
    {{ role: 'user', content: userContent }},
  ],
}};

const res = await this.helpers.httpRequest({{
  method: 'POST',
  url: 'https://openrouter.ai/api/v1/chat/completions',
  headers: {{
    Authorization: 'Bearer {OPENROUTER_KEY}',
    'Content-Type': 'application/json',
    'HTTP-Referer': 'https://n8n.io',
    'X-Title': 'Reels Compose Automation',
  }},
  body,
  json: true,
  timeout: 300000,
}});

// A styling miss should not block a render that is otherwise ready to go. The
// defaults still move and still animate the captions — a fallback that renders
// five static shots with flat subtitles is a worse reel, not a safer one.
const wordTimings = Boolean(manifest.caption_words_measured);
const DEFAULT_STYLE = {{
  style_name: 'clean commercial',
  color: {{ saturation: 1.06, contrast: 1.04, brightness: 0 }},
  motion: ['push_in', 'pan_right', 'pull_out', 'push_left', 'rise'],
  per_clip_zoom: [1, 1, 1, 1, 1],
  transitions: [
    {{ type: 'smoothleft', duration_ms: 300 }},
    {{ type: 'fade', duration_ms: 300 }},
    {{ type: 'smoothright', duration_ms: 300 }},
    {{ type: 'dissolve', duration_ms: 300 }},
  ],
  subtitles: {{ mode: 'burn', preset: wordTimings ? 'karaoke_gold' : 'pop_punch' }},
  finish: {{ vignette: 0.4, grain: 2, sharpen: 0 }},
  audio: {{ voiceover_gain_db: 0, fade_in_ms: 200, fade_out_ms: 400 }},
}};

let style = DEFAULT_STYLE;
let style_source = 'director';
const content = res?.choices?.[0]?.message?.content || '';
try {{
  const parsed = JSON.parse(content.replace(/```json\\n?/gi, '').replace(/```\\n?/g, '').trim());
  style = {{ ...DEFAULT_STYLE, ...parsed }};
  // A caption style that lights up individual words needs timings that only
  // exist when the TTS reported them. The prompt says so; this is what makes it
  // true, because the alternative is captions highlighting the wrong word.
  const preset = String(style.subtitles?.preset || '');
  if (!wordTimings && /karaoke|word_punch/.test(preset)) {{
    style.subtitles = {{ ...style.subtitles, preset: 'pop_punch' }};
    style_source = 'director (word-level captions swapped out — this voiceover has no word timings)';
  }}
}} catch (e) {{
  style_source = `fell back to defaults (${{String(e.message || e).slice(0, 80)}})`;
}}

return [{{
  json: {{
    chat_id: chatId,
    run_id: session.run_id,
    manifest,
    clips,
    style,
    style_source,
    reply_text: `Rendering your reel in a "${{style.style_name}}" look. I will send it here when it is done, usually 2-5 minutes.`,
  }},
}}];
"""

    start_render_js = f"""
{s3}
const ctx = $input.first().json;
const composerUrl = {json.dumps(COMPOSER_URL)};
if (composerUrl.includes('YOUR-COMPOSER-SERVICE')) {{
  throw new Error('Set COMPOSER_URL in build_compose_workflow.py after deploying reels-composer/ to Railway.');
}}

const voiceKey = ctx.manifest?.voiceover_key;
if (!voiceKey) throw new Error('Manifest missing voiceover_key — re-run reels generator for this run_id.');
const voiceover_url = presignGetUrl(voiceKey);

const manifest = ctx.manifest || {{}};
const style = ctx.style || {{}};
const zooms = Array.isArray(style.per_clip_zoom) ? style.per_clip_zoom : [];

// The generator already worked out, from the measured voiceover, how long each
// clip has to be on screen. Use that verbatim; the model only picked the look.
const plan = Array.isArray(manifest.render_plan) && manifest.render_plan.length
  ? manifest.render_plan
  : ctx.clips.map((c) => ({{ index: c.index, trim_start: 0, trim_end: null, speed: 1 }}));

const per_clip = plan.map((p, i) => ({{
  index: Number(p.index ?? i + 1),
  trim_start: Number(p.trim_start || 0),
  trim_end: p.trim_end == null ? null : Number(p.trim_end),
  speed: Number(p.speed || 1),
  zoom: Math.min(1.15, Math.max(1, Number(zooms[i]) || 1)),
}}));

// One length for every cut. The plan budgeted each clip's screen time against a
// single crossfade, so a per-boundary duration would shorten the reel by
// whatever the differences add up to. Only the *type* varies.
const transition_ms = Math.round(
  Number(style.transitions?.[0]?.duration_ms) || (manifest.transition_sec || 0.3) * 1000
);
const transition_types = Array.isArray(style.transitions) ? style.transitions : [];
const transitions = Array.from({{ length: Math.max(1, per_clip.length - 1) }}, (_, i) => ({{
  after_clip: i + 1,
  type: String(transition_types[i]?.type || transition_types[i] || ''),
  duration_ms: transition_ms,
}}));

const recipe = {{
  style_name: style.style_name || 'clean commercial',
  clip_order: per_clip.map((p) => p.index),
  per_clip,
  transitions,
  motion: Array.isArray(style.motion) ? style.motion.map((m) => String(m || '')) : [],
  finish: {{
    vignette: Number(style.finish?.vignette || 0),
    grain: Number(style.finish?.grain || 0),
    sharpen: Number(style.finish?.sharpen || 0),
  }},
  // Rotates the composer's own fallback sequences, so two runs that both fall
  // back to defaults do not come out as the same edit.
  look_seed: (String(ctx.run_id || '').match(/\\d/g) || ['0']).join('').slice(-3) | 0,
  audio: {{
    voiceover_gain_db: Number(style.audio?.voiceover_gain_db || 0),
    clip_audio_gain_db: -60,
    fade_in_ms: Number(style.audio?.fade_in_ms || 200),
    fade_out_ms: Number(style.audio?.fade_out_ms || 400),
  }},
  subtitles: {{ mode: 'burn', ...(style.subtitles || {{}}) }},
  color: {{ saturation: 1.06, contrast: 1.04, brightness: 0, ...(style.color || {{}}) }},
}};

const body = {{
  run_id: ctx.run_id,
  clips: ctx.clips.map((c) => ({{ index: c.index, url: c.url, s3_key: c.s3_key }})),
  voiceover_url,
  // The generator derived this from the mp3's byte size before the file was ever
  // probed. The composer downloads the real thing, measures it, and rescales the
  // plan if the two disagree — so it has to know what the plan assumed.
  voiceover_sec: manifest.voiceover_sec,
  // The director may pick a different crossfade than the plan assumed, and a
  // longer one eats more of every clip. The composer needs both to correct it.
  transition_sec: manifest.transition_sec,
  tail_sec: manifest.tail_sec,
  subtitles_srt: manifest.subtitles_srt || '',
  // Word-level cues drive the animated caption styles. The SRT still travels
  // as the fallback for a manifest generated before these existed.
  caption_cues: manifest.caption_cues || [],
  recipe,
  output_key: `reels-final/${{ctx.run_id}}.mp4`,
}};

const headers = {{ 'Content-Type': 'application/json' }};
const token = {json.dumps(COMPOSER_AUTH_TOKEN)};
if (token) headers.Authorization = `Bearer ${{token}}`;

const res = await this.helpers.httpRequest({{
  method: 'POST',
  url: `${{composerUrl.replace(/\\/$/, '')}}/v1/render`,
  headers,
  body,
  json: true,
  timeout: 120000,
}});

let session = await loadComposeSession.call(this, ctx.chat_id);
if (session) {{
  session.job_id = res.job_id;
  session.render_status = 'processing';
  await saveComposeSession.call(this, ctx.chat_id, session);
}}

return [{{ json: {{ ...ctx, recipe, job_id: res.job_id, render_status: res.status, poll_attempt: 0 }} }}];
"""

    poll_render_js = f"""
{TELEGRAM_ESCAPE_HTML_JS}
{s3}
const ctx = $input.first().json;
const composerUrl = {json.dumps(COMPOSER_URL)};
const jobId = ctx.job_id;
if (!jobId) throw new Error('Missing job_id');

const poll_attempt = (ctx.poll_attempt || 0) + 1;
const MAX_POLL_ATTEMPTS = {RENDER_POLL_MAX_ATTEMPTS};

const headers = {{}};
const token = {json.dumps(COMPOSER_AUTH_TOKEN)};
if (token) headers.Authorization = `Bearer ${{token}}`;

const job = await this.helpers.httpRequest({{
  method: 'GET',
  url: `${{composerUrl.replace(/\\/$/, '')}}/v1/jobs/${{jobId}}`,
  headers,
  json: true,
  timeout: 60000,
}});

if (job.status === 'failed') {{
  const err = String(job.error || 'Render failed');
  const hint = /moov atom not found/i.test(err)
    ? ' One or more clips on S3 are not valid mp4 files — re-send all 5 clips after redeploying the workflow.'
    : '';
  throw new Error(err + hint);
}}
if (job.status !== 'done') {{
  if (poll_attempt >= MAX_POLL_ATTEMPTS) {{
    throw new Error(`Render timed out after ~${{MAX_POLL_ATTEMPTS * 15}}s. Job ${{jobId}} still "${{job.status}}". Check the composer service or retry /compose.`);
  }}
  return [{{ json: {{ ...ctx, poll_again: true, poll_attempt, job_status: job.status }} }}];
}}

// The composer checks the finished file before handing it over: length against
// the voiceover it actually measured, one audio track, a 1080x1920 frame.
const qc = job.qc || {{}};
const qc_ok = qc.ok !== false;
const problems = Array.isArray(qc.problems) ? qc.problems : [];
const look = job.look || {{}};

// The session is loaded first because the manifest is read off it when the
// item coming out of the Wait loop has lost it.
const session = await loadComposeSession.call(this, ctx.chat_id);
const manifest = ctx.manifest || session?.manifest || {{}};
const topic = manifest.selected_topic?.title || manifest.topic_slug || ctx.run_id;
const caps = manifest.captions || {{}};
const script = manifest.script?.full_script || '';
const hashtags = '#vending #smartvending #passiveincome #retailtech #wendor';

// Written now, while the manifest is in hand, and parked on the session — the
// node that actually uploads only has a chat id and a yes to work from.
const publish_copy = {{
  instagram_caption: [topic, '', caps.caption_1 || '', caps.cta || '', '', hashtags]
    .filter((l) => l !== undefined).join('\\n').trim().slice(0, 2200),
  youtube_title: `${{topic}} #Shorts`.slice(0, 100),
  youtube_description: [script, '', caps.cta || '', '', hashtags].join('\\n').trim().slice(0, 4900),
  youtube_tags: ['vending machine', 'smart vending', 'passive income', 'retail tech', 'wendor'],
}};

// The session is *not* dropped here any more. It carries the finished reel
// through the upload question — answering "yes" an hour later still works, and
// answering "no" is what finally closes it.
if (session) {{
  session.state = 'awaiting_publish';
  session.render_status = 'done';
  session.output_url = job.output_url;
  session.output_key = job.output_key;
  session.duration_sec = job.duration_sec;
  session.qc_ok = qc_ok;
  session.publish_copy = publish_copy;
  session.rendered_at = Date.now();
  // Answering the upload question is not something to be timed out of.
  session.expires_at = Math.max(Number(session.expires_at) || 0, Date.now() + 24 * 60 * 60 * 1000);
  await saveComposeSession.call(this, ctx.chat_id, session);
}}

const header = qc_ok
  ? 'Your reel is ready.'
  : 'Your reel rendered, but it did not pass the final check. Watch it before you post it.';

const lines = [
  header,
  `Run: ${{escapeHtml(ctx.run_id)}}`,
  `Look: ${{escapeHtml(ctx.recipe?.style_name || 'default')}}`,
  `Length: ${{(Number(job.duration_sec) || 0).toFixed(1)}}s against a ${{qc.voiceover_sec ?? ctx.manifest?.voiceover_sec ?? '?'}}s voiceover`,
];
// What the edit actually came out as, rather than what the director asked for.
if (Array.isArray(look.motions) && look.motions.length) {{
  lines.push(`Camera: ${{escapeHtml(look.motions.join(' → '))}}`);
}}
if (Array.isArray(look.transitions) && look.transitions.length) {{
  lines.push(`Cuts: ${{escapeHtml(look.transitions.join(' · '))}}`);
}}
if (look.caption_animation) {{
  const measured = look.caption_words_measured ? 'on measured words' : 'per line';
  lines.push(`Captions: ${{escapeHtml(look.caption_preset || '')}} — ${{escapeHtml(look.caption_animation)}} ${{measured}}`);
}}
// Silent when it worked, same as everything else here — the brand mark is
// only worth a line when it did *not* make it onto the reel.
if (look.branding && look.branding.applied === false && look.branding.reason !== 'disabled for this render') {{
  lines.push(`Heads up: brand logo was not applied — ${{escapeHtml(look.branding.reason || 'unknown reason')}}.`);
}}
// Only worth saying when the byte-size estimate turned out to be wrong.
if (job.timing?.applied) lines.push(`Timing: ${{escapeHtml(job.timing.reason || '')}}`);
if (!qc_ok) {{
  lines.push('', 'PROBLEMS');
  for (const p of problems) lines.push(`• ${{escapeHtml(p)}}`);
}}
lines.push('Download:', `<code>${{String(job.output_url || '').replace(/&/g, '&amp;')}}</code>`);
lines.push('');
lines.push('<b>Upload it?</b>');
lines.push('yes — post to Instagram Reels and YouTube Shorts');
lines.push('no — stop here, the link above stays live for 7 days');
if (!qc_ok) lines.push('done — render it again instead');

// Telegram captions cap at 1024 characters, so the video carries a short one
// and the full report follows as its own message.
const video_caption = [header, `Run: ${{ctx.run_id}}`, `${{(Number(job.duration_sec) || 0).toFixed(1)}}s`]
  .join('\\n').slice(0, 1000);

return [{{ json: {{
  ...ctx,
  poll_again: false,
  output_url: job.output_url,
  output_key: job.output_key,
  duration_sec: job.duration_sec,
  look,
  qc,
  qc_ok,
  publish_copy,
  video_caption,
  reply_text: lines.join('\\n'),
}} }}];
"""

    handle_publish_answer_js = TELEGRAM_ESCAPE_HTML_JS + REELS_CHAT_RESOLVE_JS + s3 + f"""
const staticData = $getWorkflowStaticData('global');
const chatId = resolveTelegramChatId($json, staticData);
const answer = $json.compose_action === 'publish_yes' ? 'yes' : 'no';

const session = await loadComposeSession.call(this, chatId);
if (!session || session.state !== 'awaiting_publish' || !session.output_key) {{
  // "yes" and "no" mean nothing on their own, so say what they would have meant.
  return [{{ json: {{
    chat_id: chatId,
    reply_text: 'Nothing is waiting to be uploaded. Finish a reel first: /compose RUN_ID, send the 5 clips, then done.',
  }} }}];
}}

if (answer === 'no') {{
  await deleteComposeSession.call(this, chatId);
  return [{{ json: {{
    chat_id: chatId,
    reply_text: [
      'Not uploading. Session closed.',
      `The download link for ${{escapeHtml(session.run_id)}} stays live for 7 days.`,
    ].join('\\n'),
  }} }}];
}}

const composerUrl = {json.dumps(COMPOSER_URL)};
const headers = {{ 'Content-Type': 'application/json' }};
const token = {json.dumps(COMPOSER_AUTH_TOKEN)};
if (token) headers.Authorization = `Bearer ${{token}}`;

const copy = session.publish_copy || {{}};
const res = await this.helpers.httpRequest({{
  method: 'POST',
  url: `${{composerUrl.replace(/\\/$/, '')}}/v1/publish`,
  headers,
  body: {{
    run_id: session.run_id,
    output_key: session.output_key,
    instagram: {{ caption: copy.instagram_caption || '' }},
    youtube: {{
      title: copy.youtube_title || session.run_id,
      description: copy.youtube_description || '',
      tags: copy.youtube_tags || [],
    }},
  }},
  json: true,
  timeout: 120000,
}});

session.state = 'publishing';
session.publish_job_id = res.publish_job_id;
await saveComposeSession.call(this, chatId, session);

const targets = res.targets || {{}};
const going = Object.entries(targets).filter(([, on]) => on).map(([name]) => name);
const missing = Object.entries(targets).filter(([, on]) => !on).map(([name]) => name);

const lines = ['Uploading now.'];
lines.push(going.length ? `Going to: ${{going.join(' and ')}}` : 'No platform is configured on the composer service yet.');
if (missing.length) {{
  lines.push(`Not configured: ${{missing.join(', ')}} — set its keys on the Railway service and try again.`);
}}
lines.push('This usually takes 1-3 minutes. I will tell you when each one lands.');

return [{{ json: {{
  chat_id: chatId,
  run_id: session.run_id,
  publish_job_id: res.publish_job_id,
  output_url: session.output_url,
  poll_attempt: 0,
  reply_text: lines.join('\\n'),
}} }}];
"""

    poll_publish_js = TELEGRAM_ESCAPE_HTML_JS + s3 + f"""
const ctx = $input.first().json;
const composerUrl = {json.dumps(COMPOSER_URL)};
const jobId = ctx.publish_job_id;
if (!jobId) throw new Error('Missing publish_job_id');

const poll_attempt = (ctx.poll_attempt || 0) + 1;
const MAX_POLL_ATTEMPTS = {PUBLISH_POLL_MAX_ATTEMPTS};

const headers = {{}};
const token = {json.dumps(COMPOSER_AUTH_TOKEN)};
if (token) headers.Authorization = `Bearer ${{token}}`;

const job = await this.helpers.httpRequest({{
  method: 'GET',
  url: `${{composerUrl.replace(/\\/$/, '')}}/v1/publish/${{jobId}}`,
  headers,
  json: true,
  timeout: 60000,
}});

if (job.status !== 'done' && job.status !== 'failed') {{
  if (poll_attempt >= MAX_POLL_ATTEMPTS) {{
    // The uploads may well still be running on the service — say so rather
    // than implying nothing was posted.
    return [{{ json: {{
      ...ctx,
      poll_again: false,
      reply_text: `Still uploading after ~${{Math.round(MAX_POLL_ATTEMPTS * 15 / 60)}} minutes, so I have stopped watching. Check Instagram and YouTube directly — job ${{escapeHtml(jobId)}}.`,
    }} }}];
  }}
  return [{{ json: {{ ...ctx, poll_again: true, poll_attempt }} }}];
}}

// Whatever happened, the reel is rendered and the session has done its job.
await deleteComposeSession.call(this, ctx.chat_id);

if (job.status === 'failed') {{
  return [{{ json: {{
    ...ctx,
    poll_again: false,
    reply_text: [
      'The upload did not run.',
      escapeHtml(job.error || 'no reason given'),
      '',
      'The reel itself is fine — the download link still works.',
    ].join('\\n'),
  }} }}];
}}

const results = job.results || {{}};
const label = {{ instagram: 'Instagram Reels', youtube: 'YouTube Shorts' }};
const lines = [];
const posted = [];
const failed = [];
const skipped = [];

for (const [name, r] of Object.entries(results)) {{
  const title = label[name] || name;
  if (r.ok) {{
    posted.push(title);
    lines.push(`${{title}}: posted`);
    if (r.url) lines.push(`<code>${{String(r.url).replace(/&/g, '&amp;')}}</code>`);
  }} else if (r.skipped) {{
    skipped.push(title);
    lines.push(`${{title}}: skipped — ${{escapeHtml(r.reason || 'not requested')}}`);
  }} else {{
    failed.push(title);
    lines.push(`${{title}}: failed — ${{escapeHtml(r.error || 'no reason given')}}`);
  }}
}}

const header = posted.length && !failed.length
  ? (posted.length > 1 ? 'Posted to both platforms.' : `Posted to ${{posted[0]}}.`)
  : posted.length
    ? `Posted to ${{posted.join(' and ')}} — the rest did not go.`
    : failed.length
      ? 'Nothing was posted.'
      : 'Nothing was posted — no platform is configured yet.';

return [{{ json: {{
  ...ctx,
  poll_again: false,
  publish_results: results,
  reply_text: [
    header,
    `Run: ${{escapeHtml(ctx.run_id || '')}}`,
    '',
    ...lines,
  ].join('\\n'),
}} }}];
"""

    return {
        "HANDLE_COMPOSE_START_JS": handle_compose_start_js,
        "PREPARE_CLIP_UPLOAD_JS": prepare_clip_js(),
        "FINALIZE_CLIP_UPLOAD_JS": finalize_clip_js(),
        "HANDLE_STATUS_CANCEL_JS": handle_status_cancel_js,
        "OPENROUTER_RENDER_DIRECTOR_JS": openrouter_render_director_js,
        "START_RENDER_JS": start_render_js,
        "POLL_RENDER_JS": poll_render_js,
        "HANDLE_PUBLISH_ANSWER_JS": handle_publish_answer_js,
        "POLL_PUBLISH_JS": poll_publish_js,
    }


def not_empty_if(expression):
    return {
        "conditions": {
            "options": {"caseSensitive": True, "leftValue": "", "typeValidation": "loose", "version": 2},
            "conditions": [
                {
                    "id": nid(),
                    "leftValue": expression,
                    "rightValue": "",
                    "operator": {"type": "string", "operation": "notEmpty"},
                },
            ],
            "combinator": "and",
        },
        "looseTypeValidation": True,
        "options": {},
    }


def poll_again_if():
    return {
        "conditions": {
            "options": {"caseSensitive": True, "leftValue": "", "typeValidation": "loose", "version": 2},
            "conditions": [
                {"id": nid(), "leftValue": "={{ $json.poll_again }}", "rightValue": True, "operator": {"type": "boolean", "operation": "true"}},
            ],
            "combinator": "and",
        },
        "looseTypeValidation": True,
        "options": {},
    }


def publish_answer_if():
    """The two answers to the upload question share a handler."""
    return {
        "conditions": {
            "options": {"caseSensitive": True, "leftValue": "", "typeValidation": "loose", "version": 2},
            "conditions": [
                {
                    "id": nid(),
                    "leftValue": "={{ $json.compose_action || $json.action }}",
                    "rightValue": action,
                    "operator": {"type": "string", "operation": "equals"},
                }
                for action in ("publish_yes", "publish_no")
            ],
            "combinator": "or",
        },
        "looseTypeValidation": True,
        "options": {},
    }


def inject_compose_delegate_into_wf1(s3_session_js, prepare_clip_js, finalize_clip_js, wf_add_node, wf_connect, delegate_if_name, reply_node_name):
    """Inline compose_start / done / status / cancel / help into WF1 (no sub-workflow)."""
    h = build_compose_handlers(s3_session_js, prepare_clip_js, finalize_clip_js)

    wf_add_node("IF Compose Start", "n8n-nodes-base.if", compose_action_if("compose_start"), 2.2)
    wf_add_node("IF Done", "n8n-nodes-base.if", compose_action_if("done"), 2.2)
    wf_add_node("IF Status Cancel", "n8n-nodes-base.if", status_cancel_help_if(), 2.2)

    wf_add_node("Handle Compose Start", "n8n-nodes-base.code", {"jsCode": h["HANDLE_COMPOSE_START_JS"]}, 2)
    wf_add_node("Handle Status Cancel", "n8n-nodes-base.code", {"jsCode": h["HANDLE_STATUS_CANCEL_JS"]}, 2)
    wf_add_node("OpenRouter Render Director", "n8n-nodes-base.code", {"jsCode": h["OPENROUTER_RENDER_DIRECTOR_JS"]}, 2)
    wf_add_node("Start Render", "n8n-nodes-base.code", {"jsCode": h["START_RENDER_JS"]}, 2)
    wf_add_node("Wait For Render", "n8n-nodes-base.wait", {"amount": 15, "unit": "seconds"}, 1.1)
    wf_add_node("Poll Render Job", "n8n-nodes-base.code", {"jsCode": h["POLL_RENDER_JS"]}, 2)
    wf_add_node("IF Poll Again", "n8n-nodes-base.if", poll_again_if(), 2.2)

    # The finished reel goes back as a *video*, not a link. Telegram will only
    # fetch a URL itself up to 20MB and a 50s 1080x1920 encode goes past that,
    # so n8n downloads it and uploads the bytes. Both steps continue on error —
    # a reel that is too big to send is still a reel, and the message that
    # follows carries the download link either way.
    wf_add_node("Download Reel", "n8n-nodes-base.httpRequest", {
        "url": "={{ $('Poll Render Job').first().json.output_url }}",
        "options": {
            "response": {"response": {"responseFormat": "file", "outputPropertyName": "data"}},
            "timeout": 180000,
        },
    }, 4.2, {"onError": "continueRegularOutput", "retryOnFail": True, "maxTries": 3, "waitBetweenTries": 3000})

    wf_add_node("Send Reel Video", "n8n-nodes-base.telegram", {
        "operation": "sendVideo",
        "chatId": "={{ $('Poll Render Job').first().json.chat_id }}",
        "binaryData": True,
        "binaryPropertyName": "data",
        "additionalFields": {
            "caption": "={{ $('Poll Render Job').first().json.video_caption }}",
            "appendAttribution": False,
        },
    }, 1.2, {"webhookId": nid(), "onError": "continueRegularOutput", "retryOnFail": True, "maxTries": 2, "waitBetweenTries": 3000})

    wf_add_node("Ask To Publish", "n8n-nodes-base.telegram", {
        "chatId": "={{ $('Poll Render Job').first().json.chat_id }}",
        "text": "={{ $('Poll Render Job').first().json.reply_text }}",
        "additionalFields": {"appendAttribution": False, "parse_mode": "HTML"},
    }, 1.2, {"webhookId": nid()})

    # yes / no on a finished reel.
    wf_add_node("IF Publish Answer", "n8n-nodes-base.if", publish_answer_if(), 2.2)
    wf_add_node("Handle Publish Answer", "n8n-nodes-base.code", {"jsCode": h["HANDLE_PUBLISH_ANSWER_JS"]}, 2)
    wf_add_node("IF Publish Started", "n8n-nodes-base.if", not_empty_if("={{ $json.publish_job_id }}"), 2.2)
    wf_add_node("Wait For Publish", "n8n-nodes-base.wait", {"amount": 15, "unit": "seconds"}, 1.1)
    wf_add_node("Poll Publish Job", "n8n-nodes-base.code", {"jsCode": h["POLL_PUBLISH_JS"]}, 2)
    wf_add_node("IF Publish Poll Again", "n8n-nodes-base.if", poll_again_if(), 2.2)

    wf_connect(delegate_if_name, "IF Compose Start", 0)
    wf_connect(delegate_if_name, "IF Done", 0)
    wf_connect(delegate_if_name, "IF Status Cancel", 0)
    wf_connect(delegate_if_name, "IF Publish Answer", 0)

    wf_connect("IF Compose Start", "Handle Compose Start", 0)
    wf_connect("Handle Compose Start", reply_node_name)

    wf_connect("IF Status Cancel", "Handle Status Cancel", 0)
    wf_connect("Handle Status Cancel", reply_node_name)

    wf_connect("IF Done", "OpenRouter Render Director", 0)
    wf_connect("OpenRouter Render Director", "Start Render")
    wf_connect("Start Render", reply_node_name)
    wf_connect("Start Render", "Wait For Render")
    wf_connect("Wait For Render", "Poll Render Job")
    wf_connect("Poll Render Job", "IF Poll Again")
    wf_connect("IF Poll Again", "Wait For Render", 0)
    wf_connect("IF Poll Again", "Download Reel", 1)
    wf_connect("Download Reel", "Send Reel Video")
    wf_connect("Send Reel Video", "Ask To Publish")

    wf_connect("IF Publish Answer", "Handle Publish Answer", 0)
    wf_connect("Handle Publish Answer", reply_node_name)
    wf_connect("Handle Publish Answer", "IF Publish Started")
    wf_connect("IF Publish Started", "Wait For Publish", 0)
    wf_connect("Wait For Publish", "Poll Publish Job")
    wf_connect("Poll Publish Job", "IF Publish Poll Again")
    wf_connect("IF Publish Poll Again", "Wait For Publish", 0)
    wf_connect("IF Publish Poll Again", reply_node_name, 1)


def build_standalone_compose_workflow():
    from build_workflow import finalize_clip_upload_js, prepare_clip_s3_upload_js, s3_session_js
    from build_workflow import S3_PUT_RESPONSE_OPTS

    handlers = build_compose_handlers(s3_session_js, prepare_clip_s3_upload_js, finalize_clip_upload_js)
    nodes = []
    connections = {}

    def add_node(name, node_type, params, position, type_version=1, extra=None):
        node = {
            "parameters": params,
            "type": node_type,
            "typeVersion": type_version,
            "position": position,
            "id": nid(),
            "name": name,
        }
        if extra:
            node.update(extra)
        nodes.append(node)
        return name

    def connect(src, dst, out_index=0, in_index=0):
        connections.setdefault(src, {}).setdefault("main", [])
        while len(connections[src]["main"]) <= out_index:
            connections[src]["main"].append([])
        connections[src]["main"][out_index].append({"node": dst, "type": "main", "index": in_index})

    parse_incoming_js = """
const msg = $json.message || {};
const chatId = String(msg.chat?.id || '');
const text = String(msg.text || msg.caption || '').trim();
const from = msg.from || {};

if (from.is_bot) {
  return [{ json: { action: 'reply', chat_id: chatId, reply_text: 'Use your personal Telegram account, not a bot.' } }];
}
if (!chatId) return [];

const video = msg.video;
const doc = msg.document;
const animation = msg.animation;
const isVideoDoc = doc && /^video\\//i.test(String(doc.mime_type || ''));
const isClip = !!(video || isVideoDoc || animation?.file_id);

let action = 'ignore';
if (/^\\/compose\\b/i.test(text)) action = 'compose_start';
else if (/^done$/i.test(text)) action = 'done';
else if (/^\\/cancel$/i.test(text)) action = 'cancel';
else if (/^\\/status$/i.test(text)) action = 'status';
else if (isClip) action = 'clip_upload';

const runIdMatch = text.match(/^\\/compose\\s+(\\S+)/i);
const captionIndex = text.match(/^(?:clip\\s*)?(\\d)\\s*$/i) || text.match(/^(\\d)\\s*\\/\\s*5$/);

return [{
  json: {
    action,
    chat_id: chatId,
    text,
    run_id: runIdMatch ? runIdMatch[1].trim() : null,
    caption_index: captionIndex ? Number(captionIndex[1]) : null,
    file_id: video?.file_id || doc?.file_id || animation?.file_id || null,
    file_name: doc?.file_name || video?.file_name || animation?.file_name || `clip-${Date.now()}.mp4`,
    message: msg,
  },
  binary: $input.first().binary,
}];
"""

    x, y, dx = 0, 300, 280

    add_node("When Called by WF1", "n8n-nodes-base.executeWorkflowTrigger", {"inputSource": "passthrough"}, [x, y], 1.1)
    add_node("Parse Incoming", "n8n-nodes-base.code", {"jsCode": parse_incoming_js}, [x + dx, y], 2)
    add_node("IF Compose Start", "n8n-nodes-base.if", compose_action_if("compose_start"), [x + 2 * dx, y], 2.2)
    add_node("IF Clip Upload", "n8n-nodes-base.if", compose_action_if("clip_upload"), [x + 2 * dx, y + 120], 2.2)
    add_node("IF Done", "n8n-nodes-base.if", compose_action_if("done"), [x + 2 * dx, y + 240], 2.2)
    add_node("IF Status Cancel", "n8n-nodes-base.if", status_cancel_help_if(), [x + 2 * dx, y + 360], 2.2)

    add_node("Handle Compose Start", "n8n-nodes-base.code", {"jsCode": handlers["HANDLE_COMPOSE_START_JS"]}, [x + 3 * dx, y - 60], 2)
    add_node("Prepare Clip S3 Upload", "n8n-nodes-base.code", {"jsCode": handlers["PREPARE_CLIP_UPLOAD_JS"]}, [x + 3 * dx, y + 120], 2)
    add_node("IF Clip Needs S3 PUT", "n8n-nodes-base.if", {
        "conditions": {
            "options": {"caseSensitive": True, "leftValue": "", "typeValidation": "loose", "version": 2},
            "conditions": [
                {"id": nid(), "leftValue": "={{ $json.upload_url }}", "rightValue": "", "operator": {"type": "string", "operation": "notEmpty"}},
            ],
            "combinator": "and",
        },
        "looseTypeValidation": True,
        "options": {},
    }, [x + 4 * dx, y + 120], 2.2)
    add_node("S3 PUT Clip", "n8n-nodes-base.httpRequest", {
        "method": "PUT",
        "url": "={{ $json.upload_url }}",
        "sendBody": True,
        "contentType": "binaryData",
        "inputDataFieldName": "clip",
        "options": S3_PUT_RESPONSE_OPTS,
    }, [x + 5 * dx, y + 120], 4.2)
    add_node("Finalize Clip Upload", "n8n-nodes-base.code", {"jsCode": handlers["FINALIZE_CLIP_UPLOAD_JS"]}, [x + 6 * dx, y + 120], 2)
    add_node("Handle Status Cancel", "n8n-nodes-base.code", {"jsCode": handlers["HANDLE_STATUS_CANCEL_JS"]}, [x + 3 * dx, y + 360], 2)
    add_node("OpenRouter Render Director", "n8n-nodes-base.code", {"jsCode": handlers["OPENROUTER_RENDER_DIRECTOR_JS"]}, [x + 4 * dx, y + 240], 2)
    add_node("Start Render", "n8n-nodes-base.code", {"jsCode": handlers["START_RENDER_JS"]}, [x + 5 * dx, y + 240], 2)
    add_node("Wait For Render", "n8n-nodes-base.wait", {"amount": 15, "unit": "seconds"}, [x + 6 * dx, y + 240], 1.1)
    add_node("Poll Render Job", "n8n-nodes-base.code", {"jsCode": handlers["POLL_RENDER_JS"]}, [x + 7 * dx, y + 240], 2)
    add_node("IF Poll Again", "n8n-nodes-base.if", {
        "conditions": {
            "options": {"caseSensitive": True, "leftValue": "", "typeValidation": "loose", "version": 2},
            "conditions": [
                {"id": nid(), "leftValue": "={{ $json.poll_again }}", "rightValue": True, "operator": {"type": "boolean", "operation": "true"}},
            ],
            "combinator": "and",
        },
        "looseTypeValidation": True,
        "options": {},
    }, [x + 8 * dx, y + 240], 2.2)

    add_node("Reply Processing", "n8n-nodes-base.telegram", {
        "chatId": "={{ $json.chat_id }}",
        "text": "={{ $json.reply_text }}",
        "additionalFields": {"appendAttribution": False, "parse_mode": "HTML"},
    }, [x + 5 * dx, y + 80], 1.2, {"webhookId": nid(), "onError": "continueRegularOutput"})

    add_node("Reply Final", "n8n-nodes-base.telegram", {
        "chatId": "={{ $json.chat_id }}",
        "text": "={{ $json.reply_text }}",
        "additionalFields": {"appendAttribution": False, "parse_mode": "HTML"},
    }, [x + 9 * dx, y + 320], 1.2, {"webhookId": nid()})

    connect("When Called by WF1", "Parse Incoming")
    connect("Parse Incoming", "IF Compose Start")
    connect("Parse Incoming", "IF Clip Upload")
    connect("Parse Incoming", "IF Done")
    connect("Parse Incoming", "IF Status Cancel")
    connect("IF Compose Start", "Handle Compose Start", 0)
    connect("Handle Compose Start", "Reply Processing")
    connect("IF Clip Upload", "Prepare Clip S3 Upload", 0)
    connect("Prepare Clip S3 Upload", "IF Clip Needs S3 PUT")
    connect("IF Clip Needs S3 PUT", "S3 PUT Clip", 0)
    connect("S3 PUT Clip", "Finalize Clip Upload")
    connect("Finalize Clip Upload", "Reply Processing")
    connect("IF Clip Needs S3 PUT", "Reply Processing", 1)
    connect("IF Status Cancel", "Handle Status Cancel", 0)
    connect("Handle Status Cancel", "Reply Processing")
    connect("IF Done", "OpenRouter Render Director", 0)
    connect("OpenRouter Render Director", "Start Render")
    connect("Start Render", "Reply Processing")
    connect("Start Render", "Wait For Render")
    connect("Wait For Render", "Poll Render Job")
    connect("Poll Render Job", "IF Poll Again")
    connect("IF Poll Again", "Wait For Render", 0)
    connect("IF Poll Again", "Reply Final", 1)

    return nodes, connections


if __name__ == "__main__":
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    nodes, connections = build_standalone_compose_workflow()
    out = ARCHIVE_DIR / "reels_compose_automation.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump({
            "name": "Reels Compose Automation",
            "nodes": nodes,
            "connections": connections,
            "pinData": {},
            "settings": {"executionOrder": "v1"},
            "meta": {"templateCredsSetupCompleted": False, "instanceId": nid()},
        }, f, indent=2, ensure_ascii=False)
    print(f"Done: {len(nodes)} nodes -> {out}")
