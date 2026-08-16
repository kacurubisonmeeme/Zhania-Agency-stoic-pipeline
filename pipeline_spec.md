# Pipeline spec — stoic shorts automation (steps 1-4)

Feed this whole doc as the starting specification. It's structured as 5 independent modules connected by simple file-based handoffs (JSON in, JSON/media out) so each one can be built, run, and tested in isolation before wiring them together.

## Overall architecture

```
quote_picker.py  →  quote.json
                          ↓
script_generator.py  →  script.json
                          ↓
tts_generator.py  →  audio.mp3 + audio_meta.json
                          ↓
caption_generator.py  →  captions.srt (or .ass)
                          ↓
broll_matcher.py  →  broll_manifest.json
```

Each module reads a file, writes a file, and exits. No module calls another module directly — that keeps them independently runnable and testable. The orchestrator (built last, after all 5 work standalone) just calls them in sequence.

---

## Module 1: quote_picker

**Purpose:** Select one quote from the CSV database, matched to a requested theme (or random if none given), and mark it as used so it doesn't repeat.

**Input:**
- `stoic_quotes_database.csv` (existing file)
- Optional CLI arg: `--theme fear` (if omitted, pick randomly across all themes)
- `used_quotes.json` (tracks previously picked quotes, created if missing)

**Output:** `quote.json`
```json
{
  "quote": "There are more things, Lucilius, likely to frighten us than there are to crush us; we suffer more often in imagination than in reality.",
  "author": "Seneca",
  "source": "Letters to Lucilius, Letter 13",
  "theme": "fear",
  "length_bucket": "medium"
}
```

**Test criteria:**
- Running with `--theme fear` only ever returns fear-tagged quotes
- Running twice in a row never returns the same quote until the theme is exhausted
- Fails loudly (non-zero exit, clear error) if the theme doesn't exist in the CSV

---

## Module 2: script_generator

**Purpose:** Take `quote.json` + the voice bible, call Gemini, and produce a structured script following the father/son format.

**Input:**
- `quote.json` (from module 1)
- `voice_bible.md` (existing file, passed as part of the system prompt)
- Gemini API key (from environment variable, never hardcoded)

**Output:** `script.json`
```json
{
  "quote_id": "seneca_letter_13_fear",
  "hook": "Son, there are more things likely to frighten us than there are to crush us. We suffer more in imagination than in reality.",
  "context": "I learned that the hard way, lying awake over things that never came...",
  "application": "Next time your chest gets tight over something, ask yourself one question...",
  "cta": "What's one thing you've been carrying that hasn't even happened yet? Tell me.",
  "full_text": "<hook + context + application + cta concatenated with natural pauses>",
  "word_count": 97
}
```

**Test criteria:**
- `word_count` falls in the 95-110 range (flag, don't silently truncate, if it doesn't)
- `full_text` contains no banned phrases from the voice bible (simple string-match check is enough for v1)
- Hook always starts with "Son," and contains the verbatim quote (or its trimmed punchiest clause for `long` quotes)
- Runs standalone against a hand-written sample `quote.json` without needing module 1

---

## Module 3: tts_generator

**Purpose:** Convert `script.json`'s `full_text` into a voiced audio file.

**Input:**
- `script.json` (from module 2)
- TTS engine choice (edge-tts for v1 — free, no API key needed)

**Output:** `audio.mp3` + `audio_meta.json`
```json
{
  "audio_file": "audio.mp3",
  "duration_seconds": 41.2,
  "voice_used": "en-US-GuyNeural"
}
```

**Test criteria:**
- `duration_seconds` falls in the 38-47 second range (flag if it drifts outside your 40-45s target)
- Runs standalone against a hand-written sample `script.json`
- Fails loudly if the TTS engine returns empty audio

---

## Module 4: caption_generator

**Purpose:** Transcribe `audio.mp3` with Whisper to get word-level timestamps, output a caption file synced to speech.

**Input:**
- `audio.mp3` (from module 3)
- Local Whisper model (small or base model — enough accuracy for English, fast enough for short clips)

**Output:** `captions.srt`
```
1
00:00:00,000 --> 00:00:01,200
Son,

2
00:00:01,200 --> 00:00:02,800
there are more things
```

**Test criteria:**
- Word count in the caption file roughly matches `script.json`'s `full_text` word count (±2 words, accounting for Whisper quirks)
- Runs standalone against any sample .mp3 file, doesn't need module 3's exact output
- Flags (doesn't silently pass) if Whisper's confidence on any segment is unusually low — those are the lines likely to be transcribed wrong

---

## Module 5: broll_matcher

**Purpose:** Given the script's theme and content, pull matching stock footage from Pexels/Pixabay and produce a manifest of clips in order.

**Input:**
- `quote.json` (for theme)
- `script.json` (for keyword extraction from hook/context/application)
- Pexels and/or Pixabay API keys (from environment variables)
- A small hardcoded keyword-to-search-term map per theme (e.g. `fear` → ["dark forest", "man alone at night", "storm clouds"]) — this is your manual curation layer, keep it editable as its own config file, not buried in code

**Output:** `broll_manifest.json`
```json
{
  "clips": [
    { "url": "https://...", "local_path": "broll/clip1.mp4", "start_offset": 0, "duration": 5 },
    { "url": "https://...", "local_path": "broll/clip2.mp4", "start_offset": 5, "duration": 5 }
  ],
  "total_duration": 41
}
```

**Test criteria:**
- Total clip duration covers (or slightly exceeds) the audio duration from module 3 — never falls short
- Runs standalone against a hand-written `quote.json` with just a theme, doesn't need script.json to exist
- Fails loudly (not silently) if Pexels/Pixabay returns zero results for a theme's keywords — this is where you'll want to expand the keyword map over time

---

## Build order

Build and test in this order, confirming each works standalone with a hand-written sample input file before moving to the next:

1. quote_picker (no dependencies, fastest to verify)
2. script_generator (test with a hand-written `quote.json`, don't wait on module 1)
3. tts_generator (test with a hand-written `script.json`)
4. caption_generator (test with any sample .mp3, doesn't need module 3's real output)
5. broll_matcher (test with a hand-written `quote.json`, doesn't need script.json)

Only after all 5 pass their individual tests, build a thin `orchestrator.py` that runs them in sequence, passing real output from each into the next. If something breaks in the chained run, you'll already know it isn't a module logic bug — it's a hand-off/format mismatch, which is much faster to fix.

## What's explicitly out of scope for this spec

- Module 6 (render/assembly via FFmpeg or Remotion) — separate spec, comes after these 5 are solid
- Publishing/scheduling — manual for now
- The orchestrator itself — build after all 5 modules pass individually
