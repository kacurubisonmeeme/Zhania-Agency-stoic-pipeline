"""
broll_matcher.py — Module 5 of the stoic shorts pipeline (Multimodal Vision Re-ranking Integrated)

Reads quote.json (for theme) and script.json (for 4-shot beat-mapped visual_shots).
Collects up to 5 HD video candidates per beat across all 4 beats, then sends all 20 candidate
thumbnails + moment descriptions in ONE batched Gemini 3.6 Flash multimodal call.

Uses Gemini's vision selection per beat. If Gemini selects NONE for a beat, falls through
to the multi-tier search fallback chain (simplified → category → broll_keywords.json) and
selects the top fallback candidate.

Logs vision reasoning, selection, fallback status, and telemetry usage into broll_manifest.json and telemetry_run.json.
"""

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

import requests
from PIL import Image
import io

# ── Optional .env support ─────────────────────────────────────────────────────
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
except ImportError:
    pass

# ── Google GenAI SDK support ──────────────────────────────────────────────────
try:
    from google import genai
    from google.genai import types
    HAS_GENAI = True
except ImportError:
    HAS_GENAI = False

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR          = Path(__file__).parent
DEFAULT_QUOTE     = BASE_DIR / "quote.json"
DEFAULT_SCRIPT    = BASE_DIR / "script.json"
DEFAULT_META      = BASE_DIR / "audio_meta.json"
KEYWORDS_FILE     = BASE_DIR / "broll_keywords.json"
BROLL_DIR         = BASE_DIR / "broll"
OUTPUT_MANIFEST   = BASE_DIR / "broll_manifest.json"
TELEMETRY_PATH    = BASE_DIR / "telemetry_run.json"

# ── Clip & Beat settings ──────────────────────────────────────────────────────
CLIP_SLOT_DURATION       = 5.0      # seconds per clip slot in manifest
DEFAULT_TARGET           = 43.0     # seconds — fallback if audio_meta.json missing
MIN_CLIP_DURATION       = 3.0      # ignore source clips shorter than this
MIN_BEAT_DURATION       = 4.0      # minimum duration floor per beat slot (seconds)
CANDIDATES_PER_BEAT      = 5        # candidate thumbnails to collect for vision rerank

# ── API settings ──────────────────────────────────────────────────────────────
PEXELS_SEARCH_URL   = "https://api.pexels.com/videos/search"
PIXABAY_SEARCH_URL  = "https://pixabay.com/api/videos/"
PER_PAGE            = 15       # results to fetch per query
REQUEST_TIMEOUT     = 15       # seconds

HD_MIN_PIXELS        = 1920 * 1080   # 1080p resolution minimum
EXCLUDE_TITLE_TOKENS = {"woman", "women", "girl", "couple", "pair", "family"}

STOP_WORDS = {
    "a", "an", "the", "of", "on", "in", "at", "by", "for", "with", "about",
    "against", "between", "into", "through", "during", "before", "after",
    "above", "below", "to", "from", "up", "down", "over", "under", "again",
    "further", "then", "once", "here", "there", "when", "where", "why", "how",
    "all", "any", "both", "each", "few", "more", "most", "other", "some", "such",
    "macro", "shot", "close", "up", "slow", "motion", "4k", "hd", "video", "footage",
    "cinematic", "single"
}


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


def log_telemetry_bytes(key: str, byte_count: int) -> None:
    data = {"api_calls": [], "thumbnail_bytes": 0, "broll_bytes": 0}
    if TELEMETRY_PATH.exists():
        try:
            data = json.loads(TELEMETRY_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    data[key] = data.get(key, 0) + byte_count
    TELEMETRY_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


# ─────────────────────────────────────────────────────────────────────────────
# Loaders
# ─────────────────────────────────────────────────────────────────────────────

def load_json_optional(path: Path) -> dict | None:
    """Load a JSON file if it exists; return None if missing."""
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"WARN: could not parse {path.name}: {exc}", file=sys.stderr)
        return None


def load_json_required(path: Path) -> dict:
    """Load a JSON file; exit with an error if missing or malformed."""
    if not path.exists():
        print(f"ERROR: Required file not found: {path}", file=sys.stderr)
        sys.exit(1)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"ERROR: {path.name} is not valid JSON — {exc}", file=sys.stderr)
        sys.exit(1)


def load_keywords() -> dict:
    """Load broll_keywords.json; exit if missing."""
    data = load_json_required(KEYWORDS_FILE)
    return {k: v for k, v in data.items() if not k.startswith("_")}


def get_target_duration() -> float:
    """
    Return total required audio duration in seconds.
    Uses audio_meta.json if available, otherwise DEFAULT_TARGET.
    """
    meta = load_json_optional(DEFAULT_META)
    if meta and "duration_seconds" in meta:
        dur = float(meta["duration_seconds"])
        print(f"  Target duration from audio_meta.json: {dur:.1f}s")
        return dur
    print(f"  audio_meta.json not found — using default target: {DEFAULT_TARGET:.1f}s")
    return float(DEFAULT_TARGET)


def load_gemini_client() -> genai.Client | None:
    if not HAS_GENAI:
        return None
    api_key = (
        os.environ.get("GEMINI_API_KEY_1")
        or os.environ.get("GEMINI_API_KEY")
        or os.environ.get("GEMINI_API_KEY_2")
    )
    if api_key:
        return genai.Client(api_key=api_key)
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Word count & Beat Duration Calculations
# ─────────────────────────────────────────────────────────────────────────────

def count_words(text: str) -> int:
    """Count words in a text string."""
    if not text:
        return 0
    return len(text.strip().split())


def calculate_beat_durations(script: dict, total_audio_dur: float) -> dict[str, float]:
    """
    Calculate proportional duration for each of the 4 beats (hook, context, application, cta)
    based on word counts from script.json, applied to total_audio_dur.
    Enforces MIN_BEAT_DURATION floor per beat.
    """
    beats = ["hook", "context", "application", "cta"]
    counts = {b: count_words(script.get(b, "")) for b in beats}
    total_words = sum(counts.values()) or script.get("word_count", 100)

    raw_durs = {b: (counts[b] / total_words) * total_audio_dur for b in beats}
    floored_durs = {b: max(MIN_BEAT_DURATION, raw_durs[b]) for b in beats}

    floor_sum = sum(floored_durs.values())
    if floor_sum > 0:
        scaled_durs = {b: round((floored_durs[b] / floor_sum) * max(total_audio_dur, floor_sum), 2) for b in beats}
    else:
        scaled_durs = {b: round(total_audio_dur / 4, 2) for b in beats}

    return scaled_durs


# ─────────────────────────────────────────────────────────────────────────────
# API Search & Probing
# ─────────────────────────────────────────────────────────────────────────────

def search_pexels(query: str, api_key: str) -> list[dict]:
    """Search Pexels Videos API. Returns normalized clip dicts."""
    try:
        resp = requests.get(
            PEXELS_SEARCH_URL,
            headers={"Authorization": api_key},
            params={"query": query, "per_page": PER_PAGE},
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        print(f"  WARN: Pexels request failed for '{query}': {exc}", file=sys.stderr)
        return []

    clips = []
    for video in resp.json().get("videos", []):
        files = video.get("video_files", [])
        if not files:
            continue
        best = max(files, key=lambda f: f.get("width", 0) * f.get("height", 0))
        dur = float(video.get("duration", 0))
        if dur < MIN_CLIP_DURATION:
            continue
        clips.append({
            "id":         str(video.get("id", "")),
            "url":        best["link"],
            "poster_url": video.get("image", ""),
            "source":     "pexels",
            "duration":   dur,
            "width":      best.get("width", 0),
            "height":     best.get("height", 0),
            "title":      video.get("url", "").rstrip("/").split("/")[-1],
        })
    return clips


def search_pixabay(query: str, api_key: str) -> list[dict]:
    """Search Pixabay Videos API. Returns normalized clip dicts."""
    try:
        resp = requests.get(
            PIXABAY_SEARCH_URL,
            params={
                "key":          api_key,
                "q":            query,
                "per_page":     PER_PAGE,
                "video_type":   "film",
            },
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        print(f"  WARN: Pixabay request failed for '{query}': {exc}", file=sys.stderr)
        return []

    clips = []
    for hit in resp.json().get("hits", []):
        videos = hit.get("videos", {})
        file_info = (videos.get("large") or videos.get("medium")
                     or videos.get("small") or videos.get("tiny"))
        if not file_info:
            continue
        dur = float(hit.get("duration", 0))
        if dur < MIN_CLIP_DURATION:
            continue
        clips.append({
            "id":         str(hit.get("id", "")),
            "url":        file_info["url"],
            "poster_url": hit.get("userImageURL", ""),
            "source":     "pixabay",
            "duration":   dur,
            "width":      file_info.get("width", 0),
            "height":     file_info.get("height", 0),
            "title":      hit.get("tags", ""),
        })
    return clips


def search_all(query: str, pexels_key: str | None, pixabay_key: str | None) -> list[dict]:
    """Search both APIs for query; return combined clip results."""
    results = []
    if pexels_key:
        results.extend(search_pexels(query, pexels_key))
    if pixabay_key:
        results.extend(search_pixabay(query, pixabay_key))
    return results


def _title_is_excluded(title: str) -> bool:
    """Return True if title contains female/group exclusion tokens."""
    t_lower = title.lower()
    return any(tok in t_lower for tok in EXCLUDE_TITLE_TOKENS)


def filter_hd_clips(raw_clips: list[dict]) -> list[dict]:
    """Filter raw search results to HD resolution and non-excluded titles."""
    hd = [c for c in raw_clips if c.get("width", 0) * c.get("height", 0) >= HD_MIN_PIXELS]
    return [c for c in hd if not _title_is_excluded(c.get("title", ""))]


def simplify_search_phrase(search_phrase: str, category: str = "") -> list[str]:
    """Generate simplified 2-3 word queries from a detailed search phrase."""
    raw_words = [w.strip(".,!?\"'()").lower() for w in search_phrase.split()]
    content = [w for w in raw_words if w and w not in STOP_WORDS]

    queries = []
    if len(content) >= 3:
        queries.append(" ".join(content[:3]))
        queries.append(" ".join(content[:2]))
    elif len(content) == 2:
        queries.append(" ".join(content[:2]))
    elif content:
        queries.append(f"{content[0]} {category.replace('/', ' ')}".strip())

    cat_clean = category.replace("/", " ").strip()
    if cat_clean and cat_clean not in queries:
        queries.append(cat_clean)

    seen = set()
    result = []
    for q in queries:
        if q and q not in seen:
            seen.add(q)
            result.append(q)

    return result


def collect_beat_candidates(
    beat_name: str,
    shot_info: dict,
    theme: str,
    theme_keywords: list[str],
    pexels_key: str | None,
    pixabay_key: str | None,
    target_count: int = CANDIDATES_PER_BEAT,
) -> tuple[list[dict], str, str]:
    """
    Collect up to `target_count` HD candidate clips for a beat by checking search tiers.
    """
    search_phrase = shot_info.get("search_phrase", "").strip()
    category      = shot_info.get("category", "").strip()

    print(f"  [Probing Candidates] Beat '{beat_name.upper()}' (Category: '{category}')")

    candidates = []
    tier_used = "Tier 1: Direct"
    query_used = search_phrase

    # Tier 1: Direct search_phrase
    if search_phrase:
        raw = search_all(search_phrase, pexels_key, pixabay_key)
        hd = filter_hd_clips(raw)
        for clip in hd:
            if clip["url"] not in [c["url"] for c in candidates]:
                candidates.append(clip)
        if len(candidates) >= target_count:
            return candidates[:target_count], tier_used, query_used

    # Tier 2: Simplified queries
    simplified = simplify_search_phrase(search_phrase, category)
    for simp_q in simplified:
        if simp_q.lower() == search_phrase.lower():
            continue
        raw = search_all(simp_q, pexels_key, pixabay_key)
        hd = filter_hd_clips(raw)
        for clip in hd:
            if clip["url"] not in [c["url"] for c in candidates]:
                candidates.append(clip)
        if len(candidates) >= target_count:
            if len(candidates) > 0 and len(candidates) < target_count:
                tier_used = "Tier 2: Simplified"
                query_used = simp_q
            return candidates[:target_count], "Tier 2: Simplified", simp_q

    # Tier 3: Category search term
    cat_query = category.replace("/", " ").strip()
    if cat_query:
        raw = search_all(cat_query, pexels_key, pixabay_key)
        hd = filter_hd_clips(raw)
        for clip in hd:
            if clip["url"] not in [c["url"] for c in candidates]:
                candidates.append(clip)
        if len(candidates) >= target_count:
            return candidates[:target_count], "Tier 3: Category", cat_query

    # Tier 4: Keywords fallback
    for kw in theme_keywords:
        raw = search_all(kw, pexels_key, pixabay_key)
        hd = filter_hd_clips(raw)
        for clip in hd:
            if clip["url"] not in [c["url"] for c in candidates]:
                candidates.append(clip)
        if len(candidates) >= target_count:
            return candidates[:target_count], "Tier 4: Keywords Fallback", kw

    best_q = search_phrase or cat_query or (theme_keywords[0] if theme_keywords else "stoic nature")
    return candidates[:target_count], tier_used, best_q


# ─────────────────────────────────────────────────────────────────────────────
# Batched Multimodal Vision Re-ranking Engine
# ─────────────────────────────────────────────────────────────────────────────

def run_batched_vision_rerank(
    beats_candidates: dict[str, list[dict]],  # beat_name -> list of candidate clip dicts
    shots_by_beat: dict[str, dict],            # beat_name -> shot info dict
    gemini_client: genai.Client,
) -> dict[str, dict]:
    """
    Batches all 4 beats' candidate thumbnails + moment descriptions into a SINGLE
    Gemini 3.6 Flash multimodal API call.

    Returns dict mapping beat_name -> {
        "selection_index": int | None,  # 0-indexed candidate index or None if NONE
        "selection_label": str,         # e.g. "Candidate #5" or "NONE"
        "reasoning": str,               # Gemini's visual reasoning for this beat
    }
    """
    beats = ["hook", "context", "application", "cta"]
    contents = [
        "You are an expert film director and visual editor evaluating stock footage candidate thumbnails for a 4-beat video script.\n\n"
        "Below are 4 distinct beats. Each beat has a specific TARGET MOMENT DESCRIPTION followed by 5 candidate thumbnail images (#1 to #5).\n\n"
        "CRITICAL INSTRUCTION: Evaluate each beat's candidate images ONLY against that beat's target moment description. Do NOT cross-match candidates between beats.\n\n"
    ]

    total_images = 0

    for idx, b_name in enumerate(beats, 1):
        shot_info = shots_by_beat.get(b_name, {})
        moment = shot_info.get("moment", "")
        cand_list = beats_candidates.get(b_name, [])

        contents.append(f"\n==================== BEAT {idx}: {b_name.upper()} ====================")
        contents.append(f"TARGET MOMENT DESCRIPTION:\n\"{moment}\"\n\nCANDIDATE THUMBNAIL IMAGES:")

        for cand_idx, clip in enumerate(cand_list, 1):
            poster_url = clip.get("poster_url", "")
            if not poster_url:
                continue
            try:
                resp = requests.get(poster_url, timeout=10)
                if resp.status_code == 200:
                    raw_bytes = resp.content
                    log_telemetry_bytes("thumbnail_bytes", len(raw_bytes))
                    Image.open(io.BytesIO(raw_bytes)).verify()
                    img_part = types.Part.from_bytes(data=raw_bytes, mime_type="image/jpeg")
                    contents.append(f"\n[BEAT {idx} - Candidate #{cand_idx}]")
                    contents.append(img_part)
                    total_images += 1
            except Exception as exc:
                print(f"  WARN: Failed to download thumbnail for beat '{b_name}' candidate #{cand_idx}: {exc}", file=sys.stderr)

    contents.append(
        "\nINSTRUCTIONS FOR OUTPUT:\n"
        "For EACH of the 4 beats (BEAT 1, BEAT 2, BEAT 3, BEAT 4), structure your response clearly with exact headers:\n\n"
        "=== BEAT 1: HOOK ===\n"
        "EVALUATIONS:\n[Concise visual evaluations for candidates #1 to #5 based strictly on thumbnail images]\n"
        "RANKING:\n[Rank candidates from best to worst match]\n"
        "SELECTION: Candidate #X (OR 'SELECTION: NONE' if no candidate genuinely matches the moment details)\n\n"
        "=== BEAT 2: CONTEXT ===\n"
        "EVALUATIONS:\n...\nRANKING:\n...\nSELECTION: Candidate #X (OR 'SELECTION: NONE')\n\n"
        "=== BEAT 3: APPLICATION ===\n"
        "EVALUATIONS:\n...\nRANKING:\n...\nSELECTION: Candidate #X (OR 'SELECTION: NONE')\n\n"
        "=== BEAT 4: CTA ===\n"
        "EVALUATIONS:\n...\nRANKING:\n...\nSELECTION: Candidate #X (OR 'SELECTION: NONE')\n"
    )

    print(f"\n-> [Batched Vision Rerank] Sending {total_images} candidate thumbnails across 4 beats to Gemini 3.6 Flash...")
    
    try:
        response = gemini_client.models.generate_content(
            model="gemini-3.6-flash",
            contents=contents
        )
        log_telemetry_call("broll_matcher (vision rerank)", "gemini-3.6-flash", getattr(response, "usage_metadata", None))
        full_text = response.text
    except Exception as exc:
        print(f"ERROR: Gemini vision rerank API call failed: {exc}", file=sys.stderr)
        return {b: {"selection_index": None, "selection_label": "NONE", "reasoning": f"Gemini API error: {exc}"} for b in beats}

    # ── Parse per-beat selections and reasoning ──────────────────────────────
    results = {}
    beat_names = ["hook", "context", "application", "cta"]
    
    for idx, b_name in enumerate(beat_names, 1):
        pattern = re.compile(rf"===\s*BEAT\s*{idx}:?\s*{b_name.upper()}\s*===(.*?)(?=(===\s*BEAT|\Z))", re.DOTALL | re.IGNORECASE)
        match = pattern.search(full_text)
        
        if not match:
            pattern = re.compile(rf"BEAT\s*{idx}:?\s*(.*?)(?=(BEAT\s*{idx+1}|\Z))", re.DOTALL | re.IGNORECASE)
            match = pattern.search(full_text)

        beat_text = match.group(1).strip() if match else full_text

        sel_match = re.search(r"SELECTION:\s*(Candidate\s*#?(\d+)|NONE)", beat_text, re.IGNORECASE)
        if not sel_match:
            sel_match = re.search(r"FINAL SELECTION:\s*(Candidate\s*#?(\d+)|NONE)", beat_text, re.IGNORECASE)

        selection_index = None
        selection_label = "NONE"

        if sel_match:
            raw_sel = sel_match.group(1).upper()
            if "NONE" in raw_sel:
                selection_label = "NONE"
                selection_index = None
            elif sel_match.group(2):
                cand_num = int(sel_match.group(2))
                selection_index = cand_num - 1
                selection_label = f"Candidate #{cand_num}"

        results[b_name] = {
            "selection_index": selection_index,
            "selection_label": selection_label,
            "reasoning":       beat_text
        }

    return results


# ─────────────────────────────────────────────────────────────────────────────
# Clip Selection & Download
# ─────────────────────────────────────────────────────────────────────────────

def select_clips_for_beat(
    candidates: list[dict],
    beat_name: str,
    target_dur: float,
    start_offset: float,
    start_clip_index: int,
    tier_name: str,
    query_used: str,
    vision_info: dict | None = None,
) -> tuple[list[dict], float]:
    """Select clips to cover target_dur for beat_name."""
    if not candidates:
        return [], start_offset

    selected = []
    accum = 0.0
    curr_offset = start_offset
    idx = 0

    vis_reasoning = vision_info.get("reasoning", "") if vision_info else ""
    vis_label     = vision_info.get("selection_label", "NONE") if vision_info else "N/A"
    fallback_trig = vision_info.get("fallback_triggered", False) if vision_info else False

    while accum < target_dur:
        clip = candidates[idx % len(candidates)]
        slot = min(CLIP_SLOT_DURATION, clip["duration"])
        clip_num = start_clip_index + len(selected)
        selected.append({
            "beat":               beat_name,
            "url":                clip["url"],
            "source":             clip["source"],
            "local_path":         f"broll/clip{clip_num}.mp4",
            "start_offset":       round(curr_offset, 2),
            "duration":           round(slot, 2),
            "resolution":         f"{clip.get('width', 0)}x{clip.get('height', 0)}",
            "fallback_tier":      tier_name,
            "search_phrase_used": query_used,
            "vision_selection":   vis_label,
            "vision_reasoning":   vis_reasoning,
            "fallback_triggered": fallback_trig,
        })
        accum += slot
        curr_offset += slot
        idx += 1
        if len(selected) >= 20:
            break

    return selected, curr_offset


def download_clip(url: str, local_path: Path, retries: int = 3) -> tuple[bool, str]:
    """Download a video clip to local_path. Overwrites existing files."""
    local_path.parent.mkdir(parents=True, exist_ok=True)

    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(url, timeout=60, stream=True)
            resp.raise_for_status()

            expected_size = int(resp.headers.get("Content-Length", 0))
            bytes_written  = 0

            with open(local_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=1024 * 64):
                    f.write(chunk)
                    bytes_written += len(chunk)

            log_telemetry_bytes("broll_bytes", bytes_written)

        except requests.RequestException as exc:
            if attempt < retries:
                print(f"  WARN: clip download attempt {attempt}/{retries} failed ({exc}) — retrying...", file=sys.stderr)
                time.sleep(2 ** attempt)
                continue
            return False, f"HTTP error after {retries} attempts: {exc}"

        if not local_path.exists():
            return False, "file missing after write"
        actual_size = local_path.stat().st_size
        if actual_size == 0 or bytes_written == 0:
            return False, "file is 0 bytes after write"

        if expected_size > 0 and actual_size < expected_size * 0.95:
            if attempt < retries:
                print(f"  WARN: incomplete download ({actual_size} of {expected_size} bytes, attempt {attempt}/{retries}) — retrying...", file=sys.stderr)
                time.sleep(2 ** attempt)
                continue
            return False, f"incomplete download: got {actual_size//1024}KB of {expected_size//1024}KB"

        size_kb = actual_size // 1024
        return True, f"{size_kb} KB"

    return False, f"download failed after {retries} attempts"


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Find and download b-roll footage matched to script visual shots with Vision Re-ranking."
    )
    parser.add_argument(
        "--quote",
        type=Path,
        default=DEFAULT_QUOTE,
        help="Path to quote.json (default: quote.json)",
    )
    parser.add_argument(
        "--script",
        type=Path,
        default=DEFAULT_SCRIPT,
        help="Path to script.json (default: script.json)",
    )
    parser.add_argument(
        "--no-download",
        action="store_true",
        help="Build manifest without downloading clips (dry run)",
    )
    args = parser.parse_args()

    pexels_key  = os.environ.get("PEXELS_API_KEY")
    pixabay_key = os.environ.get("PIXABAY_API_KEY")

    if not pexels_key and not pixabay_key:
        print("ERROR: No API keys found. Set PEXELS_API_KEY or PIXABAY_API_KEY.", file=sys.stderr)
        sys.exit(1)

    gemini_client = load_gemini_client()
    if not gemini_client:
        print("  WARN: Gemini API key missing or SDK unavailable — Vision Re-ranking disabled.", file=sys.stderr)

    quote  = load_json_required(args.quote)
    script = load_json_optional(args.script)

    theme = quote.get("theme", "").strip()
    if not theme:
        print("ERROR: quote.json has no 'theme' field.", file=sys.stderr)
        sys.exit(1)

    keywords_map = load_keywords()
    if theme not in keywords_map:
        print(f"ERROR: Theme '{theme}' not found in broll_keywords.json.", file=sys.stderr)
        sys.exit(1)

    theme_keywords = keywords_map[theme]
    target_dur = get_target_duration()

    all_selected = []
    beat_summary = {}
    current_timeline = 0.0

    if script and "visual_shots" in script and "shots" in script["visual_shots"]:
        shots_data = script["visual_shots"]["shots"]
        beat_durations = calculate_beat_durations(script, target_dur)

        print(f"\n-> Processing 4 beat-mapped visual shots for theme '{theme}'...")
        print(f"  Target video duration: {target_dur:.1f}s")
        print(f"  Calculated beat durations (min floor {MIN_BEAT_DURATION}s):")
        for b_name, b_dur in beat_durations.items():
            print(f"    - {b_name:11s}: {b_dur:.1f}s")

        shots_by_beat = {s.get("beat"): s for s in shots_data if "beat" in s}

        # ── Step 1: Collect up to 5 HD Candidates per beat ────────────────────
        beats_candidates = {}
        beats_tier_used  = {}
        beats_query_used = {}

        for beat_name in ["hook", "context", "application", "cta"]:
            shot_info = shots_by_beat.get(beat_name, {})
            cands, tier_u, q_u = collect_beat_candidates(
                beat_name=beat_name,
                shot_info=shot_info,
                theme=theme,
                theme_keywords=theme_keywords,
                pexels_key=pexels_key,
                pixabay_key=pixabay_key,
                target_count=CANDIDATES_PER_BEAT,
            )
            beats_candidates[beat_name] = cands
            beats_tier_used[beat_name]  = tier_u
            beats_query_used[beat_name] = q_u

        # ── Step 2: Run Batched Vision Re-ranking (1 Gemini Call) ─────────────
        vision_results = {}
        if gemini_client:
            vision_results = run_batched_vision_rerank(
                beats_candidates=beats_candidates,
                shots_by_beat=shots_by_beat,
                gemini_client=gemini_client,
            )

        # ── Step 3: Apply Selections & Fallback Chain per Beat ─────────────────
        for beat_name in ["hook", "context", "application", "cta"]:
            shot_info = shots_by_beat.get(beat_name, {})
            b_target  = beat_durations.get(beat_name, MIN_BEAT_DURATION)
            cands     = beats_candidates.get(beat_name, [])

            vis_res   = vision_results.get(beat_name, {})
            sel_idx   = vis_res.get("selection_index")
            sel_lbl   = vis_res.get("selection_label", "NONE")
            reasoning = vis_res.get("reasoning", "")

            chosen_candidates = []
            tier_used  = beats_tier_used.get(beat_name, "Tier 1: Direct")
            query_used = beats_query_used.get(beat_name, "")
            fallback_triggered = False

            if sel_idx is not None and 0 <= sel_idx < len(cands):
                winning_clip = cands[sel_idx]
                chosen_candidates = [winning_clip] + [c for i, c in enumerate(cands) if i != sel_idx]
                print(f"  [Vision Match] Beat '{beat_name.upper()}': {sel_lbl} selected! (ID: {winning_clip.get('id')})")
            else:
                fallback_triggered = True
                print(f"  [Vision Fallback] Beat '{beat_name.upper()}': Vision returned {sel_lbl}. Triggering Fallback Chain...")

                fallback_cands, fb_tier, fb_query = collect_beat_candidates(
                    beat_name=beat_name,
                    shot_info=shot_info,
                    theme=theme,
                    theme_keywords=theme_keywords,
                    pexels_key=pexels_key,
                    pixabay_key=pixabay_key,
                    target_count=CANDIDATES_PER_BEAT,
                )
                if fallback_cands:
                    chosen_candidates = fallback_cands
                    tier_used  = f"{fb_tier} (Fallback)"
                    query_used = fb_query
                else:
                    chosen_candidates = cands
                    tier_used  = "Tier 4: Keywords Fallback"

            vis_info = {
                "selection_label":    sel_lbl,
                "reasoning":          reasoning,
                "fallback_triggered": fallback_triggered,
            }

            beat_clips, next_timeline = select_clips_for_beat(
                candidates=chosen_candidates,
                beat_name=beat_name,
                target_dur=b_target,
                start_offset=current_timeline,
                start_clip_index=len(all_selected) + 1,
                tier_name=tier_used,
                query_used=query_used,
                vision_info=vis_info,
            )

            all_selected.extend(beat_clips)
            current_timeline = next_timeline
            beat_summary[beat_name] = {
                "duration":           b_target,
                "tier":               tier_used,
                "query_used":         query_used,
                "vision_selection":   sel_lbl,
                "fallback_triggered": fallback_triggered,
                "vision_reasoning":   reasoning,
                "clips":              len(beat_clips),
            }

    else:
        print(f"\n-> Legacy Mode: probing search terms for theme '{theme}'...")
        script_terms = script.get("visual_search_terms", []) if script else []
        candidates, tier_used, query_used = collect_beat_candidates(
            beat_name="main",
            shot_info={"search_phrase": script_terms[0] if script_terms else ""},
            theme=theme,
            theme_keywords=theme_keywords,
            pexels_key=pexels_key,
            pixabay_key=pixabay_key,
            target_count=CANDIDATES_PER_BEAT,
        )
        beat_clips, _ = select_clips_for_beat(
            candidates=candidates,
            beat_name="main",
            target_dur=target_dur,
            start_offset=0.0,
            start_clip_index=1,
            tier_name=tier_used,
            query_used=query_used,
        )
        all_selected = beat_clips

    if not all_selected:
        print(f"ERROR: Zero HD clips found for theme '{theme}'. Check API keys.", file=sys.stderr)
        sys.exit(1)

    total_duration = sum(c["duration"] for c in all_selected)

    print(f"\n" + "-" * 75)
    print(f"  B-ROLL MATCHING SUMMARY ({len(all_selected)} clips, {total_duration:.1f}s total)")
    print(f"---------------------------------------------------------------------------")
    if beat_summary:
        for b_name, b_info in beat_summary.items():
            vis_status = f"Vision: {b_info['vision_selection']}"
            if b_info['fallback_triggered']:
                vis_status += " [FALLBACK]"
            print(f"  {b_name.upper():12s} | {b_info['duration']:5.1f}s | {vis_status:24s} | Query: \"{b_info['query_used']}\"")
    print(f"---------------------------------------------------------------------------")

    if args.no_download:
        print("\n  [--no-download] Skipping clip downloads.")
    else:
        if BROLL_DIR.exists():
            stale = [f for f in BROLL_DIR.iterdir() if f.is_file() and f.suffix == ".mp4"]
            if stale:
                print(f"\n  Clearing {len(stale)} stale clip(s) from broll/ before download...")
                for f in stale:
                    try:
                        f.unlink()
                    except Exception:
                        pass

        print(f"\n-> Downloading {len(all_selected)} clips to broll/...")
        any_failed = False
        for i, clip in enumerate(all_selected, 1):
            local_file = BASE_DIR / clip["local_path"]
            ok, detail = download_clip(clip["url"], local_file)
            if ok:
                print(f"  [OK]   clip{i}.mp4  [{clip['beat']:11s}]  {detail}  ({clip['duration']}s  {clip['source']})")
            else:
                print(f"  [FAIL] clip{i}.mp4  [{clip['beat']:11s}]  {detail}", file=sys.stderr)
                any_failed = True
        if any_failed:
            print("WARN: one or more clip downloads failed.", file=sys.stderr)

    manifest = {
        "theme":          theme,
        "quote_id":       quote.get("quote_id", script.get("quote_id", "unknown") if script else "unknown"),
        "total_duration": round(total_duration, 2),
        "beats_summary":  beat_summary,
        "clips":          all_selected,
    }
    with open(OUTPUT_MANIFEST, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    print(f"\n[OK] broll_manifest.json written ({len(all_selected)} clips, {total_duration:.1f}s total)")


if __name__ == "__main__":
    main()
