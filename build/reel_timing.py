"""The reel's timing grid. Single source of truth for the builder and the tests.

Gemini Omni Flash returns 10-second clips in Google Flow. The older Veo 3.x
models cap at 8. Change CLIP_SEC here and everything follows: the per-scene word
budget, the script and Flow prompts, the sync windows, the render plan and the
setup notes. Nothing downstream hardcodes a clip length.

The renderer does not trust these numbers either — reels-composer fits each clip
to the footage that actually arrives, so a batch mixing 8s and 10s clips still
cuts correctly.
"""

CLIP_COUNT = 5
CLIP_SEC = 10
TOTAL_SEC = CLIP_COUNT * CLIP_SEC

# Crossfades overlap neighbouring clips, so each one costs real screen time:
# five 10s clips joined by four 0.3s fades run 48.8s, not 50s. The last clip
# also carries a short tail because the mux uses -shortest and would otherwise
# clip the final word.
TRANSITION_SEC = 0.3
TAIL_SEC = 0.25

# What the viewer actually gets, and therefore what the script has to fill.
# Budgeting against TOTAL_SEC instead would ask for 1.45s of speech that has
# nowhere to go, forcing slow-motion on every single clip.
USABLE_SEC = TOTAL_SEC - TRANSITION_SEC * (CLIP_COUNT - 1) - TAIL_SEC

# Natural pace for an energetic short. Used to budget words per scene up front
# and to sanity-check the rendered voiceover afterwards.
WORDS_PER_SEC = 2.6
WORDS_PER_CLIP = round(USABLE_SEC / CLIP_COUNT * WORDS_PER_SEC)
WORDS_MIN = WORDS_PER_CLIP - 3
WORDS_MAX = WORDS_PER_CLIP + 1

# ElevenLabs mp3_44100_128 and Cartesia mp3 @ 128000 are both constant bitrate,
# so voiceover duration can be derived from the file size before render.
VOICEOVER_BITRATE = 128000
