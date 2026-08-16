"""
script_generator.py — Module 2 of the stoic shorts pipeline

Reads quote.json (produced by quote_picker.py or any hand-written sample),
calls the Gemini API with voice_bible.md as the system prompt, and writes
script.json.

CTA Rewatch Loop Rule:
- Every script's CTA beat MUST end with "because..." (or "because") to prompt a seamless rewatch loop.

Usage:
    python script_generator.py                              # reads quote.json in this folder
    python script_generator.py --quote path/to/quote.json  # custom input path

Requires:
    GEMINI_API_KEY environment variable (see README or set it in a .env file)
    pip install google-genai python-dotenv
"""

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
except ImportError:
    pass

from google import genai

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
DEFAULT_QUOTE_PATH = BASE_DIR / "quote.json"
VOICE_BIBLE_PATH = BASE_DIR / "voice_bible.md"
OUTPUT_PATH = BASE_DIR / "script.json"
USED_VISUAL_TERMS_PATH = BASE_DIR / "used_visual_terms.json"
TELEMETRY_PATH = BASE_DIR / "telemetry_run.json"
USED_VISUAL_TERMS_CAP  = 50

# ── Gemini model to use ───────────────────────────────────────────────────────
GEMINI_MODEL = "gemini-3.6-flash"

# ── Word-count target from spec ───────────────────────────────────────────────
WORD_COUNT_MIN = 95
WORD_COUNT_MAX = 110


# ─────────────────────────────────────────────────────────────────────────────
# Telemetry Logging
# ─────────────────────────────────────────────────────────────────────────────

def log_telemetry_call(module_name: str, model_name: str, usage_meta) -> None:
    data = {"api_calls": [], "thumbnail_bytes": 0, "broll_bytes": 0}
    if TELEMETRY_PATH.exists():
        try:
            data = json.loads(TELEMETRY_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass

    p_tokens = getattr(usage_meta, "prompt_token_count", 0) or 0
    c_tokens = getattr(usage_meta, "candidates_token_count", 0) or 0
    t_tokens = getattr(usage_meta, "total_token_count", 0) or (p_tokens + c_tokens)

    data["api_calls"].append({
        "module": module_name,
        "model": model_name,
        "prompt_tokens": p_tokens,
        "candidates_tokens": c_tokens,
        "total_tokens": t_tokens,
    })
    TELEMETRY_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def load_json(path: Path) -> dict:
    if not path.exists():
        print(f"ERROR: File not found: {path}", file=sys.stderr)
        sys.exit(1)
    with open(path, encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError as exc:
            print(f"ERROR: {path} is not valid JSON — {exc}", file=sys.stderr)
            sys.exit(1)


def load_text(path: Path) -> str:
    if not path.exists():
        print(f"ERROR: File not found: {path}", file=sys.stderr)
        sys.exit(1)
    return path.read_text(encoding="utf-8")


def count_words(text: str) -> int:
    return len(text.split())


def make_quote_id(quote: dict) -> str:
    parts = [quote.get("author", ""), quote.get("source", ""), quote.get("theme", "")]
    combined = "_".join(parts)
    slug = re.sub(r"[^a-z0-9]+", "_", combined.lower()).strip("_")
    return slug


def build_prompt(quote: dict, voice_bible: str) -> str:
    length_bucket = quote.get("length_bucket", "medium")
    hook_instruction = (
        "The hook MUST start with \"Son,\" followed IMMEDIATELY by the seed quote "
        "spoken word for word — this is NOT optional and NOT up to your judgement. "
        "ONE exception only: if the quote contains an embedded addressee name or "
        "direct-address term in the middle of the sentence (e.g. \"Lucilius\", "
        "\"my dear Lucilius\", \"my friend\") that would sound wrong in a "
        "father-to-son context, silently drop that term and close the gap — "
        "but every other word must remain exactly as written in the seed quote. "
        "Do NOT rephrase, reorder, summarise, or trim the quote to a single clause. "
        "The full quote (minus any addressee name) must appear in the hook verbatim."
        if length_bucket != "long"
        else
        "This is a LONG quote. For the hook, trim to the single punchiest clause "
        "(under ~12 words) that carries the full weight on its own, then speak that "
        "verbatim after \"Son,\". Do NOT paraphrase the hook clause — it must be a "
        "cut from the original wording, not a rewrite. Cover the rest of the quote's "
        "meaning in Context/Application in the father's own words."
    )

    return f"""Generate a script following the voice bible instructions exactly.

SEED QUOTE: {quote['quote']}
AUTHOR: {quote['author']}
SOURCE: {quote['source']}
THEME: {quote['theme']}
LENGTH BUCKET: {length_bucket}

HOOK RULE: {hook_instruction}

TARGET: 95-110 words total for full_text (all four beats combined).

CRITICAL WORD USAGE RULE: The word "son" MUST appear EXACTLY ONCE in the entire script, right at the very beginning of the hook ("Son,"). Do NOT use the word "son" or "son," anywhere in the context, application, or cta sections.

CRITICAL CTA REWATCH LOOP RULE: The CTA beat MUST end with the word "because..." (or "because") to create an addictive rewatch loop that naturally flows directly back into the opening hook ("Son,"). Example: "What's standing in your way right now that might actually be the way, because..."

Return ONLY valid JSON in exactly this format — no markdown fences, no extra keys:
{{
  "hook": "<Son, + verbatim quote (or trimmed clause for long)>",
  "context": "<father grounds the idea in his own experience/observation>",
  "application": "<concrete instruction from father to son, doable today>",
  "cta": "<follow prompt or question ending with 'because...'>"
}}"""


def _load_gemini_keys() -> list[str]:
    keys: list[str] = []
    seen: set[str]  = set()

    i = 1
    while True:
        k = os.environ.get(f"GEMINI_API_KEY_{i}")
        if not k:
            break
        if k not in seen:
            keys.append(k)
            seen.add(k)
        i += 1

    plain = os.environ.get("GEMINI_API_KEY")
    if plain and plain not in seen:
        keys.append(plain)

    if not keys:
        print(
            "ERROR: No Gemini API key found.\n"
            "       Set GEMINI_API_KEY or GEMINI_API_KEY_1, GEMINI_API_KEY_2, ... in .env",
            file=sys.stderr,
        )
        sys.exit(1)

    return keys


def _is_quota_error(exc: Exception) -> bool:
    s = str(exc).lower()
    return "429" in s and "quota" in s


def _gemini_call(prompt: str, *, label: str = "Gemini") -> str:
    keys          = _load_gemini_keys()
    n_keys        = len(keys)
    max_transient = 4

    for key_idx, api_key in enumerate(keys):
        client = genai.Client(api_key=api_key)
        if n_keys > 1:
            print(f"  [{label}] Using API key {key_idx + 1}/{n_keys}", file=sys.stderr)

        for attempt in range(max_transient):
            try:
                response = client.models.generate_content(
                    model=GEMINI_MODEL,
                    contents=prompt
                )
                log_telemetry_call(label, GEMINI_MODEL, getattr(response, "usage_metadata", None))
                text = (response.text or "").strip()
                if not text:
                    print(f"ERROR: {label} returned an empty response.", file=sys.stderr)
                    sys.exit(1)
                return text

            except Exception as exc:
                if _is_quota_error(exc):
                    print(
                        f"  WARN: API key {key_idx + 1}/{n_keys} has hit its daily quota.",
                        file=sys.stderr,
                    )
                    break

                err_str = str(exc)
                is_transient = (
                    "500" in err_str
                    or "503" in err_str
                    or "network" in err_str.lower()
                    or "timeout" in err_str.lower()
                )
                if is_transient and attempt < max_transient - 1:
                    m = re.search(r"retry in (\d+(?:\.\d+)?)s", err_str, re.IGNORECASE)
                    wait = float(m.group(1)) + 2.0 if m else 30.0 * (2 ** attempt)
                    print(
                        f"  WARN: {label} transient error — retrying in {wait:.1f}s "
                        f"(attempt {attempt + 1}/{max_transient}): {exc}",
                        file=sys.stderr,
                    )
                    time.sleep(wait)
                else:
                    raise

    print(
        f"ERROR: All {n_keys} Gemini API key(s) have hit their daily quota.",
        file=sys.stderr,
    )
    sys.exit(1)


def call_gemini(system_prompt: str, user_prompt: str) -> str:
    combined_input = (
        "VOICE BIBLE — follow every rule in this document exactly:\n\n"
        f"{system_prompt}\n\n"
        "---\n\n"
        f"{user_prompt}"
    )
    return _gemini_call(combined_input, label="script_generator")


def parse_gemini_response(raw: str) -> dict:
    cleaned = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.MULTILINE)
    cleaned = re.sub(r"```\s*$", "", cleaned, flags=re.MULTILINE).strip()

    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not match:
        print(
            f"ERROR: Could not find a JSON object in Gemini's response.\n"
            f"Raw response:\n{raw}",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        return json.loads(match.group())
    except json.JSONDecodeError as exc:
        print(
            f"ERROR: Gemini's JSON response could not be parsed — {exc}\n"
            f"Raw response:\n{raw}",
            file=sys.stderr,
        )
        sys.exit(1)


def enforce_single_son_and_cta_loop(beats: dict) -> dict:
    hook = beats.get("hook", "").strip()
    if not hook.lower().startswith("son"):
        beats["hook"] = f"Son, {hook}"

    for key in ("context", "application", "cta"):
        if key in beats and beats[key]:
            text = beats[key]
            text = re.sub(r",\s*\bson\b([.,!?])", r"\1", text, flags=re.IGNORECASE)
            text = re.sub(r"\bson,\s*", "", text, flags=re.IGNORECASE)
            text = re.sub(r"\s+\bson\b", "", text, flags=re.IGNORECASE)
            beats[key] = text.strip()

    # Enforce CTA rewatch loop ending with "because..."
    cta = beats.get("cta", "").strip()
    if cta:
        words = cta.split()
        last_word_clean = re.sub(r"[^\w']+", "", words[-1]).lower() if words else ""
        if last_word_clean not in {"because", "since", "for"}:
            if cta.endswith((".", "!", "?")):
                cta = cta.rstrip(".!?") + ", because..."
            else:
                cta = cta + " because..."
            beats["cta"] = cta

    return beats


def _words(text: str) -> list[str]:
    return re.sub(r"[^\w\s]", "", text.lower()).split()


def _hook_words_are_subsequence_of_quote(hook: str, quote_text: str) -> bool:
    hook_words  = _words(hook)
    if hook_words and hook_words[0] == "son":
        hook_words = hook_words[1:]

    quote_words = _words(quote_text)

    it = iter(quote_words)
    if not all(word in it for word in hook_words):
        return False

    if len(quote_words) > 0:
        coverage = len(hook_words) / len(quote_words)
        if coverage < 0.80:
            return False

    return True


def validate_beats(beats: dict, quote: dict) -> list[str]:
    warnings = []

    hook = beats.get("hook", "")
    if not hook.lower().startswith("son,"):
        warnings.append(f'WARN: hook does not start with "Son," — got: {hook[:60]}')

    if quote.get("length_bucket") != "long":
        quote_text = quote.get("quote", "")
        if not _hook_words_are_subsequence_of_quote(hook, quote_text):
            warnings.append(
                "WARN: hook wording does not match the seed quote\n"
                f"      Seed quote: {quote_text[:80]}\n"
                f"      Hook was:   {hook[:80]}"
            )

    for beat in ("hook", "context", "application", "cta"):
        if not beats.get(beat, "").strip():
            warnings.append(f"WARN: beat '{beat}' is empty.")

    full_text_lower = " ".join(beats.values()).lower()
    son_count = len(re.findall(r"\bson\b", full_text_lower))
    if son_count != 1:
        warnings.append(f"WARN: 'son' count is {son_count} (expected exactly 1 at the start of the hook).")

    cta = beats.get("cta", "").strip().lower()
    if not any(w in cta for w in ("because", "since", "for")):
        warnings.append("WARN: CTA does not end with 'because...' for rewatch loop.")

    return warnings


def _load_used_visual_terms() -> list[str]:
    if not USED_VISUAL_TERMS_PATH.exists():
        return []
    try:
        data = json.loads(USED_VISUAL_TERMS_PATH.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
    except (json.JSONDecodeError, OSError):
        pass
    return []


def _save_used_visual_terms(new_phrases: list[str]) -> None:
    existing = _load_used_visual_terms()
    updated  = existing + [p for p in new_phrases if p not in existing]
    updated  = updated[-USED_VISUAL_TERMS_CAP:]
    USED_VISUAL_TERMS_PATH.write_text(
        json.dumps(updated, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def generate_visual_shot_list(script_beats: dict, theme: str) -> dict | None:
    recent = _load_used_visual_terms()
    recent_terms_str = (
        "\n".join(f"  - {t}" for t in recent[-10:])
        if recent else "  (none yet)"
    )

    hook        = script_beats.get("hook", "")
    context     = script_beats.get("context", "")
    application = script_beats.get("application", "")
    cta         = script_beats.get("cta", "")

    prompt = f"""You are directing the visuals for a short film. You are not a stock footage tagger — you are choosing what the audience sees at each moment, and why.

THE SCRIPT:
Hook: {hook}
Context: {context}
Application: {application}
CTA: {cta}

RECENTLY USED VISUAL CONCEPTS (avoid repeating these — find something genuinely different):
{recent_terms_str}

YOUR PROCESS — think through these in order:

1. NAME THE EMOTIONAL ARC. In one line each, what is happening emotionally
   in the hook, context, application, and cta? Not what's being said — what
   the listener is meant to FEEL at that moment.

2. FOR EACH BEAT, choose ONE specific, concrete visual moment — not a mood,
   a MOMENT. Not "solitude" but "a man setting down a heavy bag he's been
   carrying." Be as specific as if you were describing a single frame you
   can picture. Avoid the most obvious/generic choice for this theme — if
   your first instinct is "man walking alone in fog," push past it to
   something more particular and less overused.

3. CONSIDER SEQUENCE, NOT JUST FIT. Does the shot for beat 2 create a
   meaningful contrast or continuation with beat 1? A held, still shot
   after a sharp opening can hit harder than four quick cuts. You don't
   need constant movement or variety for its own sake — sometimes the
   right choice is restraint.

4. NAME WHICH CATEGORY EACH SHOT BELONGS TO, choosing from: solitary
   figure, hands/craft, weather/elements, still object/symbolism, animal.
   Do not use the same category for more than 2 of the 4 beats.

CRITICAL — subject rules for any search_phrase that depicts a person:
- Always specify "man" explicitly (e.g. "man tying boots dawn", not "tying boots dawn")
- The figure must be solitary — never a couple, group, or mixed-gender scene
- If a phrase would naturally show mixed results, make it person-free instead

Return ONLY valid JSON, no markdown fences:
{{
  "emotional_arc": {{
    "hook": "<one line: what the viewer feels here>",
    "context": "<one line>",
    "application": "<one line>",
    "cta": "<one line>"
  }},
  "shots": [
    {{"beat": "hook", "moment": "...", "search_phrase": "...", "category": "..."}},
    {{"beat": "context", "moment": "...", "search_phrase": "...", "category": "..."}},
    {{"beat": "application", "moment": "...", "search_phrase": "...", "category": "..."}},
    {{"beat": "cta", "moment": "...", "search_phrase": "...", "category": "..."}}
  ]
}}"""

    try:
        raw = _gemini_call(prompt, label="visual_shot_list")
        raw = re.sub(r"^```(?:json)?\s*", "", raw.strip(), flags=re.MULTILINE)
        raw = re.sub(r"```\s*$", "", raw, flags=re.MULTILINE).strip()

        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            raise ValueError("No JSON object found in response")
        data = json.loads(match.group())

        shots = data.get("shots", [])
        expected_beats = ["hook", "context", "application", "cta"]

        if len(shots) != 4:
            raise ValueError(f"Expected 4 shots, got {len(shots)}")

        for i, (shot, beat) in enumerate(zip(shots, expected_beats)):
            if shot.get("beat") != beat:
                raise ValueError(
                    f"Shot {i} has beat '{shot.get('beat')}', expected '{beat}'"
                )
            for field in ("moment", "search_phrase", "category"):
                if not shot.get(field, "").strip():
                    raise ValueError(f"Shot {i} ('{beat}') missing field '{field}'")

        from collections import Counter
        cat_counts = Counter(s["category"] for s in shots)
        for cat, count in cat_counts.items():
            if count > 2:
                print(
                    f"  WARN: visual shot category '{cat}' used {count}/4 times "
                    "(should be ≤2). Consider regenerating for more visual variety.",
                    file=sys.stderr,
                )

        new_phrases = [s["search_phrase"] for s in shots if s.get("search_phrase")]
        _save_used_visual_terms(new_phrases)

        return data

    except Exception as exc:
        print(
            f"  WARN: visual shot list generation failed ({exc}) — "
            "falling back to generic search phrases.",
            file=sys.stderr,
        )
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a father-son script from a stoic quote using Gemini."
    )
    parser.add_argument(
        "--quote",
        type=Path,
        default=DEFAULT_QUOTE_PATH,
        help="Path to quote.json (default: quote.json)",
    )
    args = parser.parse_args()

    quote = load_json(args.quote)
    voice_bible = load_text(VOICE_BIBLE_PATH)

    required_fields = {"quote", "author", "source", "theme", "length_bucket"}
    missing = required_fields - quote.keys()
    if missing:
        print(f"ERROR: quote.json is missing fields: {', '.join(sorted(missing))}", file=sys.stderr)
        sys.exit(1)

    print(f"-> Generating script for: {quote['quote'][:70]}...")
    print(f"  Theme: {quote['theme']}  |  Bucket: {quote['length_bucket']}")

    user_prompt = build_prompt(quote, voice_bible)
    raw_response = call_gemini(system_prompt=voice_bible, user_prompt=user_prompt)

    beats = parse_gemini_response(raw_response)
    beats = enforce_single_son_and_cta_loop(beats)

    full_text = " ".join([
        beats.get("hook", ""),
        beats.get("context", ""),
        beats.get("application", ""),
        beats.get("cta", ""),
    ]).strip()
    full_text = re.sub(r"  +", " ", full_text)

    word_count = count_words(full_text)

    warnings = validate_beats(beats, quote)

    if word_count < WORD_COUNT_MIN or word_count > WORD_COUNT_MAX:
        warnings.append(
            f"WARN: word_count {word_count} is outside the 95-110 target range."
        )

    for w in warnings:
        print(w, file=sys.stderr)

    print("-> Generating visual shot list for b-roll...")
    visual_shots = generate_visual_shot_list(beats, quote["theme"])

    if visual_shots:
        print(f"  visual shot list: {len(visual_shots.get('shots', []))} beats mapped")
        for s in visual_shots.get("shots", []):
            print(f"    [{s['beat']:11s}] {s['category']:22s} | {s['search_phrase']}")
        visual_field_name  = "visual_shots"
        visual_field_value = visual_shots
    else:
        print("  WARN: shot list failed", file=sys.stderr)
        visual_field_name  = "visual_search_terms"
        visual_field_value = []

    output = {
        "quote_id": make_quote_id(quote),
        "hook": beats["hook"],
        "context": beats["context"],
        "application": beats["application"],
        "cta": beats["cta"],
        "full_text": full_text,
        "word_count": word_count,
        visual_field_name: visual_field_value,
    }

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    status = "[OK]" if not warnings else "[WARN]"
    print(f"\n{status} script.json written ({word_count} words)")
    print(f"  quote_id : {output['quote_id']}")
    print(f"  cta      : {output['cta']}")


if __name__ == "__main__":
    main()
