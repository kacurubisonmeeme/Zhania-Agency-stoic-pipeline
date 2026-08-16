"""
test_vision_rerank.py — Batched Multimodal Vision Re-ranking Test

Batches all 4 beats of a real video script into a SINGLE Gemini 3.6 Flash multimodal API call.
Sends 20 candidate thumbnail image parts (5 per beat) live from Pexels API and gets a complete
evaluations, ranking, and final selection for all 4 beats in a single response.
"""

import os
import sys
import json
import requests
from pathlib import Path
from PIL import Image
import io

from google import genai
from google.genai import types

# ── Load Environment (.env) ──────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
ENV_PATH = BASE_DIR / ".env"

if ENV_PATH.exists():
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ[k.strip()] = v.strip()


def load_gemini_client() -> genai.Client:
    api_key = (
        os.environ.get("GEMINI_API_KEY_1")
        or os.environ.get("GEMINI_API_KEY")
        or os.environ.get("GEMINI_API_KEY_2")
    )
    if not api_key:
        print("ERROR: No Gemini API key found in environment / .env", file=sys.stderr)
        sys.exit(1)
    return genai.Client(api_key=api_key)


def fetch_pexels_candidates(search_query: str, count: int = 5) -> list[dict]:
    """Fetch candidate video thumbnail URLs directly from Pexels API."""
    api_key = os.environ.get("PEXELS_API_KEY")
    if not api_key:
        print("ERROR: PEXELS_API_KEY missing from environment", file=sys.stderr)
        sys.exit(1)

    headers = {"Authorization": api_key}
    url = "https://api.pexels.com/videos/search"
    params = {"query": search_query, "per_page": count}

    resp = requests.get(url, headers=headers, params=params, timeout=15)
    resp.raise_for_status()

    videos = resp.json().get("videos", [])
    candidates = []
    for idx, v in enumerate(videos[:count], 1):
        candidates.append({
            "cand_num": idx,
            "id": str(v["id"]),
            "image_url": v["image"],
            "video_url": v.get("url", "")
        })
    return candidates


def run_batched_4beat_vision_rerank(script_json_path: Path):
    if not script_json_path.exists():
        print(f"ERROR: Script JSON file not found at {script_json_path}", file=sys.stderr)
        sys.exit(1)

    with open(script_json_path, "r", encoding="utf-8") as f:
        script_data = json.load(f)

    shots = script_data.get("visual_shots", {}).get("shots", [])
    if len(shots) != 4:
        print(f"ERROR: Expected 4 visual shots in script, found {len(shots)}", file=sys.stderr)
        sys.exit(1)

    print("=========================================================================")
    print(f"BATCHED MULTIMODAL VISION RE-RANKING: 4 BEATS (SINGLE GEMINI CALL)")
    print(f"SCRIPT: {script_data.get('quote_id', 'unknown')}")
    print("=========================================================================\n")

    contents = [
        "You are an expert film director and visual editor evaluating stock footage candidate thumbnails for a 4-beat video script.\n\n"
        "Below are 4 distinct beats. Each beat has a specific TARGET MOMENT DESCRIPTION followed by 5 candidate thumbnail images (#1 to #5).\n\n"
        "CRITICAL INSTRUCTION: Evaluate each beat's candidate images ONLY against that beat's target moment description. Do NOT cross-match candidates between beats.\n\n"
    ]

    total_images = 0

    for idx, shot in enumerate(shots, 1):
        beat_name = shot.get("beat", f"beat_{idx}").upper()
        moment = shot.get("moment", "")
        query = shot.get("search_phrase", "")

        print(f"--- BEAT {idx} ({beat_name}) ---")
        print(f"  MOMENT: \"{moment}\"")
        print(f"  PEXELS QUERY: \"{query}\"")

        # Fetch 5 candidates from live Pexels API
        candidates = fetch_pexels_candidates(query, count=5)
        print(f"  Pexels Candidates Returned: {len(candidates)}")

        contents.append(f"\n==================== BEAT {idx}: {beat_name} ====================")
        contents.append(f"TARGET MOMENT DESCRIPTION:\n\"{moment}\"\n\nCANDIDATE THUMBNAIL IMAGES:")

        for c in candidates:
            img_url = c["image_url"]
            print(f"    Candidate #{c['cand_num']} (Pexels ID {c['id']}): {img_url}")

            resp = requests.get(img_url, timeout=15)
            resp.raise_for_status()
            raw_bytes = resp.content
            
            # Verify image
            Image.open(io.BytesIO(raw_bytes)).verify()
            
            print(f"       -> Downloaded {len(raw_bytes):,} raw JPEG bytes.")
            img_part = types.Part.from_bytes(data=raw_bytes, mime_type="image/jpeg")
            
            contents.append(f"\n[BEAT {idx} - Candidate #{c['cand_num']}]")
            contents.append(img_part)
            total_images += 1

        print()

    contents.append(
        "\nINSTRUCTIONS FOR OUTPUT:\n"
        "For EACH of the 4 beats (Beat 1, Beat 2, Beat 3, Beat 4), structure your response clearly:\n\n"
        "### BEAT [N]: [NAME]\n"
        "1. Visual Evaluations: Evaluate Candidate #1 through #5 based strictly on what is visually visible in their thumbnail images.\n"
        "2. Candidate Ranking: Rank Candidate #1 through #5 from best match to worst match.\n"
        "3. Final Selection: Conclude with 'FINAL SELECTION: Candidate #X' OR 'FINAL SELECTION: NONE (no match)' if no candidate genuinely matches that beat's specific moment details.\n"
    )

    print(f"Total candidate images prepared: {total_images} across 4 beats.")
    print("Sending SINGLE batched multimodal API request to Gemini 3.6 Flash...")

    client = load_gemini_client()
    response = client.models.generate_content(
        model="gemini-3.6-flash",
        contents=contents
    )

    print("\n------------------- GEMINI 3.6 FLASH BATCHED VISION RESPONSE -------------------")
    print(response.text)
    print("=========================================================================\n")


if __name__ == "__main__":
    script_path = BASE_DIR / "scratch" / "script_control.json"
    if not script_path.exists():
        # Fallback to local artifacts path if needed
        script_path = Path(r"C:\Users\SmartKid\.gemini\antigravity\brain\cde61320-2c82-416b-84e0-12b77abfee39\scratch\script_control.json")
    
    run_batched_4beat_vision_rerank(script_path)
