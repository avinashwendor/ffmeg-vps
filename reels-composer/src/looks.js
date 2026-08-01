/**
 * How the reel *looks*: camera motion on every clip, a different cut at every
 * boundary, and captions that move with the voice.
 *
 * All of it is deliberately separate from renderJob.js, which owns timing. A
 * look can never change how long a clip is on screen — motion is a crop over
 * footage that has already been trimmed to the frame, transition durations come
 * from one number the whole plan was built against, and captions are read off
 * word timings the workflow measured. Nothing here can desync a reel.
 */

const FRAME_W = 1080;
const FRAME_H = 1920;
const FPS = 30;

// ── CAMERA MOTION ──────────────────────────────────────────────────────────
//
// A static clip cut against four other static clips reads as a slideshow. Every
// clip gets a slow move instead, and neighbouring clips get *different* moves so
// the cut has something to cut on.
//
// z is the framing at the start and end of the clip, as a multiple of the final
// 1080x1920 frame; x/y are where the window sits, 0 = left/top, 1 = right/bottom,
// 0.5 = centred. Keep zooms under ~1.14: past that the upscale starts to show on
// footage that is only 1080 wide to begin with.
export const MOTION_PRESETS = {
  hold: { z0: 1.0, z1: 1.0, x0: 0.5, x1: 0.5, y0: 0.5, y1: 0.5 },
  push_in: { z0: 1.0, z1: 1.1, x0: 0.5, x1: 0.5, y0: 0.5, y1: 0.5 },
  pull_out: { z0: 1.1, z1: 1.0, x0: 0.5, x1: 0.5, y0: 0.5, y1: 0.5 },
  pan_left: { z0: 1.08, z1: 1.08, x0: 0.85, x1: 0.15, y0: 0.5, y1: 0.5 },
  pan_right: { z0: 1.08, z1: 1.08, x0: 0.15, x1: 0.85, y0: 0.5, y1: 0.5 },
  tilt_up: { z0: 1.08, z1: 1.08, x0: 0.5, x1: 0.5, y0: 0.8, y1: 0.2 },
  tilt_down: { z0: 1.08, z1: 1.08, x0: 0.5, x1: 0.5, y0: 0.2, y1: 0.8 },
  push_left: { z0: 1.02, z1: 1.12, x0: 0.65, x1: 0.35, y0: 0.5, y1: 0.5 },
  push_right: { z0: 1.02, z1: 1.12, x0: 0.35, x1: 0.65, y0: 0.5, y1: 0.5 },
  rise: { z0: 1.04, z1: 1.12, x0: 0.5, x1: 0.5, y0: 0.62, y1: 0.38 },
  settle: { z0: 1.12, z1: 1.04, x0: 0.5, x1: 0.5, y0: 0.38, y1: 0.52 },
};

export const MOTION_NAMES = Object.keys(MOTION_PRESETS);

// Five moves that read as one camera rather than five. Used when the director
// does not name a motion per clip; the index picks the sequence so two runs of
// the same script do not come out identical.
const MOTION_SEQUENCES = [
  ['push_in', 'pan_right', 'pull_out', 'push_left', 'push_in'],
  ['pan_right', 'push_in', 'tilt_down', 'pan_left', 'rise'],
  ['rise', 'pull_out', 'push_right', 'tilt_up', 'push_in'],
  ['push_left', 'tilt_up', 'pan_right', 'settle', 'push_in'],
];

export function motionSequence(clipCount, seed = 0) {
  const seq = MOTION_SEQUENCES[Math.abs(Math.trunc(seed)) % MOTION_SEQUENCES.length];
  return Array.from({ length: clipCount }, (_, i) => seq[i % seq.length]);
}

function even(n) {
  const v = Math.round(n);
  return v % 2 === 0 ? v : v + 1;
}

function num(v, fallback) {
  const n = Number(v);
  return Number.isFinite(n) ? n : fallback;
}

/**
 * Resolve a motion name plus the director's per-clip zoom into a concrete move.
 * `zoom` multiplies the preset rather than replacing it, so "a gentle push here"
 * stays a push and does not flatten into a static crop.
 */
export function resolveMotion(name, zoom = 1) {
  const preset = MOTION_PRESETS[String(name || '').toLowerCase()] || MOTION_PRESETS.push_in;
  const k = Math.min(1.15, Math.max(1, num(zoom, 1)));
  const clamp = (z) => Math.min(1.2, Math.max(1, z * k));
  return {
    z0: clamp(preset.z0),
    z1: clamp(preset.z1),
    x0: preset.x0,
    x1: preset.x1,
    y0: preset.y0,
    y1: preset.y1,
  };
}

/**
 * The filter chain that puts a moving 1080x1920 window over a clip.
 *
 * Every move is the same two steps — scale the frame to the zoom the move is at,
 * then crop the final 1080x1920 window out of it at the position the move is at
 * — with the cheapest form of each step that the particular move needs:
 *
 * - Nothing moves: one static scale and one static crop.
 * - The window slides at a fixed zoom: scale once, and let `crop` evaluate x/y
 *   per frame. No resampling happens beyond the initial fit.
 * - The zoom changes: `scale` with `eval=frame`, which recomputes the size each
 *   frame. This is deliberately *not* `zoompan`, the filter usually reached for
 *   here: zoompan is roughly 50% slower for an identical result, and five 10s
 *   1080x1920 clips is exactly where that starts to matter.
 *
 * `durationSec` is the length of the clip *after* any speed change, because
 * that is the timeline the move has to complete over.
 */
export function motionFilter(motion, durationSec) {
  const m = motion && typeof motion === 'object' ? motion : resolveMotion(motion);
  const d = Math.max(0.1, num(durationSec, 1));
  const still = Math.abs(m.z0 - m.z1) < 1e-6;
  const fixed = still && Math.abs(m.x0 - m.x1) < 1e-6 && Math.abs(m.y0 - m.y1) < 1e-6;

  // Progress through the clip, clamped so a frame past the end cannot carry the
  // move beyond where it was supposed to stop.
  const p = `min(1\\,t/${d.toFixed(3)})`;
  const lerp = (a, b) => `(${a.toFixed(4)}+(${(b - a).toFixed(4)})*${p})`;

  if (still) {
    // One fit to the zoom the whole clip sits at, so nothing resamples twice.
    const srcW = even(FRAME_W * m.z0);
    const srcH = even(FRAME_H * m.z0);
    const fit = `scale=${srcW}:${srcH}:force_original_aspect_ratio=increase,crop=${srcW}:${srcH}`;
    if (fixed) {
      const x = Math.round((srcW - FRAME_W) * m.x0);
      const y = Math.round((srcH - FRAME_H) * m.y0);
      return `${fit},crop=${FRAME_W}:${FRAME_H}:${x}:${y}`;
    }
    return `${fit},crop=${FRAME_W}:${FRAME_H}:x='(in_w-out_w)*${lerp(m.x0, m.x1)}':y='(in_h-out_h)*${lerp(m.y0, m.y1)}'`;
  }

  // Square the frame up to 9:16 first, so the zoom is a clean multiple of the
  // final frame whatever aspect the clip arrived in. libx264 needs even
  // dimensions, hence the rounding on each axis.
  const zoom = lerp(m.z0, m.z1);
  return [
    `scale=${FRAME_W}:${FRAME_H}:force_original_aspect_ratio=increase`,
    `crop=${FRAME_W}:${FRAME_H}`,
    `scale=w='ceil(${FRAME_W}*${zoom}/2)*2':h='ceil(${FRAME_H}*${zoom}/2)*2':eval=frame`,
    `crop=${FRAME_W}:${FRAME_H}:x='(in_w-out_w)*${lerp(m.x0, m.x1)}':y='(in_h-out_h)*${lerp(m.y0, m.y1)}'`,
  ].join(',');
}

// ── TRANSITIONS ────────────────────────────────────────────────────────────
//
// A crossfade at every one of the four cuts is the single thing that makes an
// AI reel look like an AI reel. These are the xfade types that read as
// deliberate at 300ms on vertical footage — no page curls, no pixelate.
export const TRANSITION_CATALOGUE = [
  'fade', 'fadeblack', 'fadefast', 'dissolve', 'smoothleft', 'smoothright',
  'smoothup', 'smoothdown', 'slideleft', 'slideright', 'slideup', 'wipeleft',
  'wiperight', 'wipeup', 'circleopen', 'circleclose', 'radial', 'coverleft',
  'coverup', 'revealright', 'zoomin', 'squeezev', 'hblur',
];

const TRANSITION_SETS = [
  ['smoothleft', 'fade', 'smoothright', 'dissolve'],
  ['slideup', 'fade', 'circleopen', 'smoothleft'],
  ['dissolve', 'wipeup', 'fade', 'zoomin'],
  ['fade', 'smoothup', 'slideleft', 'fadeblack'],
];

/**
 * Which cut goes where. `available` is what this ffmpeg build actually has —
 * xfade grew most of its catalogue across 5.x, and naming a type that is not
 * compiled in fails the filtergraph at the very last step of a render.
 */
export function pickTransitions(count, { requested = [], available = null, seed = 0 } = {}) {
  const ok = (name) => {
    const n = String(name || '').toLowerCase();
    if (!n) return false;
    if (available && !available.has(n)) return false;
    return TRANSITION_CATALOGUE.includes(n);
  };
  const named = (Array.isArray(requested) ? requested : [])
    .map((t) => String(t?.type ?? t ?? '').toLowerCase());
  const set = TRANSITION_SETS[Math.abs(Math.trunc(seed)) % TRANSITION_SETS.length];
  return Array.from({ length: Math.max(0, count) }, (_, i) => {
    if (ok(named[i])) return named[i];
    const fromSet = set[i % set.length];
    if (ok(fromSet)) return fromSet;
    return 'fade';
  });
}

// ── CAPTIONS ───────────────────────────────────────────────────────────────

// ASS wants &HAABBGGRR — blue and red swapped relative to hex, alpha first.
export function hexToAss(hex, fallback) {
  const m = String(hex || '').trim().match(/^#?([0-9a-f]{6})$/i);
  if (!m) return fallback;
  const [r, g, b] = [0, 2, 4].map((i) => m[1].slice(i, i + 2).toUpperCase());
  return `&H00${b}${g}${r}`;
}

function assTime(sec) {
  const t = Math.max(0, Number(sec) || 0);
  const h = Math.floor(t / 3600);
  const m = Math.floor((t % 3600) / 60);
  const s = Math.floor(t % 60);
  const cs = Math.round((t - Math.floor(t)) * 100);
  // Rounding centiseconds can carry into the next second.
  const carry = cs === 100 ? 1 : 0;
  return `${h}:${String(m).padStart(2, '0')}:${String(s + carry).padStart(2, '0')}.${String(carry ? 0 : cs).padStart(2, '0')}`;
}

// Greedy wrap, then re-wrap to the balanced width so the last line is never a
// single stranded word. libass would wrap an over-long cue on its own, but it
// picks the break point and routinely leaves "the" alone on line two.
export function wrapCue(text, size) {
  const words = String(text || '').trim().split(/\s+/).filter(Boolean);
  if (!words.length) return '';
  // Usable width is PlayResX minus the two 60px margins. Bold Arial averages
  // about 0.55em per glyph, which is what decides how much fits on a line.
  const perLine = Math.max(12, Math.floor(960 / ((Number(size) || 52) * 0.55)));

  const wrap = (width) => {
    const lines = [];
    let line = '';
    for (const w of words) {
      const next = line ? `${line} ${w}` : w;
      if (next.length <= width || !line) { line = next; continue; }
      lines.push(line);
      line = w;
    }
    if (line) lines.push(line);
    return lines;
  };

  const lines = wrap(perLine);
  if (lines.length < 2) return lines.join('\\N');
  // Greedy fills each line to the brim and leaves the remainder stranded — a
  // cue reading "…eleven months" / "flat". Squeeze the width down to the
  // narrowest that still needs the same number of lines, which spreads the
  // words evenly across them.
  const longestWord = words.reduce((n, w) => Math.max(n, w.length), 0);
  let best = lines;
  for (let width = longestWord; width < perLine; width++) {
    const candidate = wrap(width);
    if (candidate.length <= lines.length) { best = candidate; break; }
  }
  return best.join('\\N');
}

// Same wrap, but reported as groups of word indices so per-word karaoke tags
// can be laid out with the line breaks in the right places.
function wrapWords(words, size) {
  const text = words.join(' ');
  const wrapped = wrapCue(text, size);
  if (!wrapped) return [];
  const lines = wrapped.split('\\N').map((l) => l.trim().split(/\s+/).filter(Boolean).length);
  const groups = [];
  let cursor = 0;
  for (const n of lines) {
    groups.push(words.slice(cursor, cursor + n).map((_, i) => cursor + i));
    cursor += n;
  }
  // Defensive: wrapping should never lose or invent a word, but a caption is
  // not worth crashing a finished render over.
  if (cursor !== words.length) return [words.map((_, i) => i)];
  return groups;
}

/** SRT text → cues. Word timings are not recoverable from an SRT. */
export function parseSrtCues(srt) {
  const blocks = String(srt || '').trim().split(/\n\n+/);
  const cues = [];
  for (const block of blocks) {
    const lines = block.split('\n');
    const timeLine = lines.find((l) => l.includes('-->'));
    if (!timeLine) continue;
    const [rawStart, rawEnd] = timeLine.split('-->').map((s) => s.trim());
    const toSec = (t) => {
      const m = t.match(/(\d+):(\d{2}):(\d{2})[,.](\d{1,3})/);
      if (!m) return 0;
      return Number(m[1]) * 3600 + Number(m[2]) * 60 + Number(m[3]) + Number(m[4].padEnd(3, '0')) / 1000;
    };
    const text = lines.slice(lines.indexOf(timeLine) + 1).join(' ').trim();
    if (!text) continue;
    cues.push({ start: toSec(rawStart), end: toSec(rawEnd), text, words: null });
  }
  return cues;
}

/** Accept either the measured cue list or a plain SRT, and normalise. */
export function normalizeCues(cues, srt) {
  const list = Array.isArray(cues) && cues.length
    ? cues.map((c) => {
      const words = Array.isArray(c.words)
        ? c.words
          .map((w) => ({ start: Number(w.start), end: Number(w.end), text: String(w.text || w.word || '') }))
          .filter((w) => w.text && Number.isFinite(w.start) && Number.isFinite(w.end))
        : null;
      return {
        start: Number(c.start) || 0,
        end: Number(c.end) || 0,
        text: String(c.text || (words || []).map((w) => w.text).join(' ')).trim(),
        words: words && words.length ? words : null,
      };
    }).filter((c) => c.text && c.end > c.start)
    : parseSrtCues(srt);
  return list;
}

/** Every cue time scales by the same factor — the timeline is one proportional
 * split of a single voiceover, so a voiceover that came out longer moves all of
 * it by the same ratio. */
export function scaleCues(cues, scale) {
  if (!(scale > 0) || Math.abs(scale - 1) < 1e-6) return cues;
  return cues.map((c) => ({
    ...c,
    start: c.start * scale,
    end: c.end * scale,
    words: c.words ? c.words.map((w) => ({ ...w, start: w.start * scale, end: w.end * scale })) : null,
  }));
}

// Named caption looks. The director picks one by name and may override any
// individual field; everything not overridden comes from here.
export const CAPTION_PRESETS = {
  clean_bold: {
    font: 'Arial', size: 52, color: '#FFFFFF', outline_color: '#000000',
    highlight_color: '#FFD54A', animation: 'none', position: 'lower',
  },
  soft_fade: {
    font: 'Helvetica', size: 50, color: '#FFFFFF', outline_color: '#101010',
    highlight_color: '#FFFFFF', animation: 'fade', position: 'lower',
  },
  pop_punch: {
    font: 'Arial', size: 58, color: '#FFFFFF', outline_color: '#000000',
    highlight_color: '#FFE24A', animation: 'pop', position: 'lower', all_caps: true,
  },
  rise_clean: {
    font: 'Verdana', size: 52, color: '#FFFFFF', outline_color: '#000000',
    highlight_color: '#FFFFFF', animation: 'rise', position: 'lower',
  },
  karaoke_gold: {
    font: 'Arial', size: 56, color: '#FFFFFF', outline_color: '#000000',
    highlight_color: '#FFC53D', animation: 'karaoke', position: 'lower', all_caps: true,
  },
  karaoke_mint: {
    font: 'Helvetica', size: 54, color: '#FFFFFF', outline_color: '#06231C',
    highlight_color: '#3DF5B0', animation: 'karaoke', position: 'lower',
  },
  // The one preset allowed to sit mid-frame: a single word IS the shot, so it
  // reads as a deliberate design rather than a caption that has drifted off
  // its usual place. See the position clamp below — this is the only route in.
  word_punch: {
    font: 'Impact', size: 84, color: '#FFFFFF', outline_color: '#000000',
    highlight_color: '#FFE24A', animation: 'word', position: 'center', all_caps: true,
  },
  boxed_news: {
    font: 'Arial', size: 48, color: '#FFFFFF', outline_color: '#000000',
    highlight_color: '#FFFFFF', animation: 'fade', position: 'lower', box: true,
  },
};

export const CAPTION_PRESET_NAMES = Object.keys(CAPTION_PRESETS);
export const CAPTION_ANIMATIONS = ['none', 'fade', 'pop', 'rise', 'karaoke', 'word'];

// Reels and Shorts overlay the caption, handle and action buttons across the
// bottom of the frame. At 1920 tall that furniture eats roughly the lowest
// 320px, so `bottom` is the closest a cue can sit to the edge without being
// covered on the exact device people watch this on. `lower` is the normal
// caption position — a proper lower-third, not glued to the edge and nowhere
// near the middle of the frame. `center` and `upper` exist only for the
// word-punch style; see the clamp below.
const POSITION_MARGIN_V = { bottom: 340, lower: 420, center: 840, upper: 1180 };

export function resolveCaptionStyle(subtitles = {}) {
  const presetName = String(subtitles.preset || subtitles.style || '').toLowerCase();
  const preset = CAPTION_PRESETS[presetName] || CAPTION_PRESETS.clean_bold;
  const merged = { ...preset };
  for (const [k, v] of Object.entries(subtitles)) {
    if (v !== undefined && v !== null && v !== '') merged[k] = v;
  }
  let animation = String(merged.animation || 'none').toLowerCase();
  if (!CAPTION_ANIMATIONS.includes(animation)) animation = 'none';
  let position = POSITION_MARGIN_V[String(merged.position || 'lower').toLowerCase()]
    ? String(merged.position).toLowerCase()
    : 'lower';
  // A normal multi-word caption floating mid-frame or up near the top reads as
  // broken, not stylistic — that space belongs to word-punch alone, where one
  // big word fills the shot on purpose. Anything else is pulled back to the
  // lower third regardless of what was asked for.
  if (animation !== 'word' && (position === 'center' || position === 'upper')) {
    position = 'lower';
  }
  // For every animation except word-punch, margin_v is *derived*, not taken
  // from the input at all — a clamped ceiling still left room for a caption to
  // read as "floating" rather than "in the lower third". The director's prompt
  // does not ask for margin_v, but nothing stops a model from including it
  // anyway, and a loophole that is merely narrow is still a loophole.
  const margin_v = animation === 'word'
    ? Math.round(num(merged.margin_v, POSITION_MARGIN_V[position] || 340))
    : POSITION_MARGIN_V[position];

  return {
    preset: CAPTION_PRESETS[presetName] ? presetName : 'clean_bold',
    font: String(merged.font || 'Arial'),
    // A caption bigger than this stops fitting two words on a line at 1080 wide.
    size: Math.min(110, Math.max(28, Math.round(num(merged.size, 52)))),
    color: merged.color || '#FFFFFF',
    outline_color: merged.outline_color || '#000000',
    highlight_color: merged.highlight_color || merged.color || '#FFFFFF',
    animation,
    position,
    margin_v,
    all_caps: Boolean(merged.all_caps),
    box: Boolean(merged.box),
  };
}

function styleText(text, style) {
  const t = String(text || '');
  return style.all_caps ? t.toUpperCase() : t;
}

/**
 * Cues → an ASS subtitle file.
 *
 * `karaoke` and `word` need word timings; both fall back to `pop` when the TTS
 * did not return any, rather than emitting flat captions with no motion.
 */
export function buildAss(cues, subtitles = {}) {
  const style = resolveCaptionStyle(subtitles);
  const list = Array.isArray(cues) ? cues.filter((c) => c && c.end > c.start) : [];
  const hasWords = list.some((c) => Array.isArray(c.words) && c.words.length);
  let animation = style.animation;
  if ((animation === 'karaoke' || animation === 'word') && !hasWords) animation = 'pop';

  const primary = hexToAss(style.color, '&H00FFFFFF');
  const highlight = hexToAss(style.highlight_color, primary);
  const outline = hexToAss(style.outline_color, '&H00000000');
  const marginV = style.margin_v;
  // \an2 anchors the text by its bottom-centre, which is the point \move slides.
  const baseY = FRAME_H - marginV;

  // Karaoke fills PrimaryColour over SecondaryColour as each syllable lands, so
  // the two are swapped relative to what they mean everywhere else: the word
  // that has *not* been spoken yet is drawn in Secondary.
  const stylePrimary = animation === 'karaoke' ? highlight : primary;
  const styleSecondary = animation === 'karaoke' ? primary : '&H000000FF';
  const borderStyle = style.box ? 3 : 1;
  const back = style.box ? '&H64000000' : '&H80000000';
  const size = animation === 'word' ? Math.round(style.size) : style.size;

  const events = [];
  for (const cue of list) {
    const start = Math.max(0, cue.start);
    const end = Math.max(start + 0.05, cue.end);

    if (animation === 'word' && cue.words?.length) {
      // One word at a time, each punched in on its own beat. The last word of a
      // cue holds to the cue end so there is never a blank frame before the cut.
      cue.words.forEach((w, i) => {
        const wStart = Math.max(start, w.start);
        const wEnd = i === cue.words.length - 1 ? end : Math.max(wStart + 0.08, Math.min(end, cue.words[i + 1].start));
        if (wEnd <= wStart) return;
        const tag = '{\\fad(50,60)\\fscx72\\fscy72\\t(0,110,\\fscx106\\fscy106)\\t(110,190,\\fscx100\\fscy100)}';
        events.push(`Dialogue: 0,${assTime(wStart)},${assTime(wEnd)},Default,,0,0,0,,${tag}${styleText(w.text, style)}`);
      });
      continue;
    }

    if (animation === 'karaoke' && cue.words?.length) {
      const words = cue.words.map((w) => styleText(w.text, style));
      const groups = wrapWords(words, size);
      // \k durations are centiseconds and run consecutively from the event
      // start, so any silence before the first word has to be spent explicitly.
      const lead = Math.max(0, Math.round((cue.words[0].start - start) * 100));
      const parts = [];
      groups.forEach((group, gi) => {
        if (gi > 0) parts.push('\\N');
        for (const wi of group) {
          const w = cue.words[wi];
          const next = cue.words[wi + 1];
          const until = next ? Math.min(next.start, end) : end;
          const cs = Math.max(6, Math.round((until - w.start) * 100));
          parts.push(`{\\kf${cs}}${words[wi]}`);
          if (wi !== group[group.length - 1]) parts.push(' ');
        }
      });
      const leadTag = lead > 0 ? `{\\k${lead}}` : '';
      events.push(`Dialogue: 0,${assTime(start)},${assTime(end)},Default,,0,0,0,,{\\fad(80,80)}${leadTag}${parts.join('')}`);
      continue;
    }

    const text = wrapCue(styleText(cue.text, style), size);
    if (!text) continue;
    let tag = '';
    if (animation === 'fade') tag = '{\\fad(120,120)}';
    else if (animation === 'pop') tag = '{\\fad(60,80)\\fscx76\\fscy76\\t(0,130,\\fscx104\\fscy104)\\t(130,210,\\fscx100\\fscy100)}';
    else if (animation === 'rise') tag = `{\\fad(90,90)\\move(540,${baseY + 46},540,${baseY},0,200)}`;
    events.push(`Dialogue: 0,${assTime(start)},${assTime(end)},Default,,0,0,0,,${tag}${text}`);
  }

  const alignment = animation === 'word' || style.position === 'center' ? 5 : 2;
  // \an5 positions by the middle of the text, so its vertical margin is measured
  // from the frame centre outward rather than from the bottom.
  const styleMarginV = alignment === 5 ? Math.max(0, Math.round(FRAME_H / 2 - marginV)) : marginV;

  return `[Script Info]
ScriptType: v4.00+
PlayResX: ${FRAME_W}
PlayResY: ${FRAME_H}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,${style.font},${size},${stylePrimary},${styleSecondary},${outline},${back},-1,0,0,0,100,100,0,0,${borderStyle},4,2,${alignment},60,60,${styleMarginV},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
${events.join('\n')}
`;
}

// ── FINISH ─────────────────────────────────────────────────────────────────
//
// The last 5% — a vignette to pull the eye to the middle of a vertical frame,
// and a whisper of grain so flat AI gradients stop banding. Both are cheap and
// both are off unless the director asks.
export function finishFilters(finish = {}) {
  const out = [];
  const vignette = num(finish.vignette, 0);
  if (vignette > 0) out.push(`vignette=angle=PI/${(6 - Math.min(2.5, vignette * 2)).toFixed(2)}`);
  const grain = num(finish.grain, 0);
  if (grain > 0) out.push(`noise=alls=${Math.min(12, Math.round(grain))}:allf=t+u`);
  const sharpen = num(finish.sharpen, 0);
  if (sharpen > 0) out.push(`unsharp=5:5:${Math.min(1.2, sharpen).toFixed(2)}:5:5:0`);
  return out;
}

export const LOOK_FIELDS = {
  motions: MOTION_NAMES,
  transitions: TRANSITION_CATALOGUE,
  caption_presets: CAPTION_PRESET_NAMES,
  caption_animations: CAPTION_ANIMATIONS,
};
