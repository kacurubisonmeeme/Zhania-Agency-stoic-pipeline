"""
ai_image_generator.py — Dynamic 9:16 AI Artwork Generator for Stoic Shorts.

Generates unique 9:16 Renaissance oil painting master artworks for each video:
1. Loads GEMINI_API_KEY automatically from .env
2. Generates dynamic prompts from script.json (Hook, Context, Application, CTA)
3. Calls Google GenAI Imagen 3 API for native 9:16 vertical art generation
4. Provides dynamic theme-specific canvas art fallback so images NEVER repeat across quotes!

Usage:
    python ai_image_generator.py
"""

import json
import os
import sys
import io
import time
import hashlib
from pathlib import Path

BASE_DIR = Path(__file__).parent.resolve()
SCRIPT_PATH = BASE_DIR / "script.json"
QUOTE_PATH = BASE_DIR / "quote.json"
MANIFEST_PATH = BASE_DIR / "ai_images_manifest.json"
OUTPUT_DIR = BASE_DIR / "broll" / "generated_art"

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def load_env():
    """Load environment variables from .env file into os.environ."""
    env_file = BASE_DIR / ".env"
    if env_file.exists():
        try:
            for line in env_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    k_str = k.strip()
                    v_str = v.strip().strip("'\"")
                    if k_str and not os.environ.get(k_str):
                        os.environ[k_str] = v_str
        except Exception as e:
            print(f"Notice loading .env: {e}")


load_env()

STYLE_PROMPT = (
    "Masterpiece Renaissance oil painting, dramatic chiaroscuro lighting by Caravaggio and Rembrandt, "
    "deep golden hour tones, rich canvas texture, cinematic 9:16 vertical composition, highly detailed 8k"
)

# Theme color palettes for procedural unique artwork fallback
THEME_PALETTES = {
    "adversity":        {"bg1": (25, 18, 12),  "bg2": (70, 45, 25),  "accent": (212, 175, 55), "name": "Deep Obsidian & Amber Gold"},
    "fear":             {"bg1": (12, 18, 28),  "bg2": (35, 55, 80),  "accent": (180, 210, 245),"name": "Stormy Navy & Celestial Steel"},
    "control":          {"bg1": (18, 25, 20),  "bg2": (45, 75, 55),  "accent": (220, 200, 140),"name": "Bronze Olive & Emerald Dusk"},
    "anger":            {"bg1": (35, 12, 12),  "bg2": (85, 30, 20),  "accent": (245, 180, 100),"name": "Caravaggio Crimson & Flame"},
    "discipline":       {"bg1": (20, 20, 25),  "bg2": (55, 50, 70),  "accent": (230, 190, 90), "name": "Imperial Violet & Sunburst Gold"},
    "time_management":  {"bg1": (28, 22, 16),  "bg2": (75, 58, 38),  "accent": (240, 205, 110),"name": "Hourglass Sepia & Radiant Ocher"},
    "custom":           {"bg1": (22, 18, 26),  "bg2": (60, 45, 75),  "accent": (215, 185, 120),"name": "Philosopher Royal & Gold"}
}


def load_context():
    script_data = {}
    quote_data = {}
    if SCRIPT_PATH.exists():
        try:
            script_data = json.loads(SCRIPT_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    if QUOTE_PATH.exists():
        try:
            quote_data = json.loads(QUOTE_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return script_data, quote_data


def build_dynamic_beats(script_data: dict, quote_data: dict) -> list[dict]:
    author = quote_data.get("author", "Stoic Philosopher")
    theme = quote_data.get("theme", "discipline").lower()
    quote = quote_data.get("quote", "Focus on what you can control.")
    
    hook = script_data.get("hook", quote[:50])
    context = script_data.get("context", quote)
    application = script_data.get("application", "Apply wisdom to your life.")
    cta = script_data.get("cta", "What will you focus on today?")

    return [
        {"shot": 1,  "label": "Hook 1 - The Awakening",           "prompt": f"Elder Stoic philosopher {author} contemplating {hook[:40]}, quiet marble study"},
        {"shot": 2,  "label": "Hook 2 - The Choice",              "prompt": f"Dramatic hourglass with sand slipping through fingers, representing {hook[:40]}"},
        {"shot": 3,  "label": "Context 1 - The Tempest",         "prompt": f"Classical Roman marketplace under stormy sky, shadows of marble columns, {context[:40]}"},
        {"shot": 4,  "label": "Context 2 - Solitary Horizon",     "prompt": f"Solitary Stoic scholar standing on rocky cliff overlooking stormy ocean at twilight"},
        {"shot": 5,  "label": "Context 3 - The Unfinished Hero", "prompt": f"Unfinished marble hero statue bathed in single candle flame light"},
        {"shot": 6,  "label": "Application 1 - Morning Sun",      "prompt": f"Philosopher stepping onto Roman balcony bathed in golden morning sunlight, {application[:40]}"},
        {"shot": 7,  "label": "Application 2 - Writing Journal",  "prompt": f"Hands of Stoic scholar writing reflective thoughts with quill in leather journal"},
        {"shot": 8,  "label": "Application 3 - Classical Arch",   "prompt": f"Serene classical garden with cypress trees and marble archways opening to horizon"},
        {"shot": 9,  "label": "CTA 1 - The Illuminated Path",    "prompt": f"Courageous wanderer stepping over broken sundial towards illuminated golden path, {cta[:40]}"},
        {"shot": 10, "label": "CTA 2 - Marcus Aurelius Dawn",    "prompt": f"Monumental marble statue of Marcus Aurelius under starry night sky with golden dawn breaking"}
    ]


def generate_procedural_fallback_art(out_path: Path, shot_num: int, label: str, quote_text: str, theme: str, author: str):
    """Generates a unique dynamic 9:16 artwork frame when API is offline, guaranteeing no repetition across videos."""
    from PIL import Image, ImageDraw, ImageFilter, ImageFont

    palette = THEME_PALETTES.get(theme.lower(), THEME_PALETTES["custom"])
    
    # Hash quote + shot_num for unique deterministic visual variation
    seed_str = f"{quote_text}_{shot_num}_{theme}"
    hash_num = int(hashlib.md5(seed_str.encode("utf-8")).hexdigest()[:8], 16)

    w, h = 1080, 1920
    img = Image.new("RGB", (w, h), color=palette["bg1"])
    draw = ImageDraw.Draw(img)

    # 1. Generate radial chiaroscuro gradient background
    c1 = palette["bg1"]
    c2 = palette["bg2"]
    
    # Focal light position varies per shot
    fx = int(w * (0.3 + (hash_num % 40) / 100.0))
    fy = int(h * (0.2 + (shot_num * 7 % 50) / 100.0))

    for r in range(w, 0, -8):
        factor = r / w
        ir = int(c1[0] * factor + c2[0] * (1 - factor))
        ig = int(c1[1] * factor + c2[1] * (1 - factor))
        ib = int(c1[2] * factor + c2[2] * (1 - factor))
        draw.ellipse([fx - r, fy - r, fx + r, fy + r], fill=(ir, ig, ib))

    # Blur gradient for smooth Rembrandt effect
    img = img.filter(ImageFilter.GaussianBlur(radius=15))
    draw = ImageDraw.Draw(img)

    # 2. Draw classical architectural frame & borders
    accent = palette["accent"]
    margin = 70
    draw.rectangle([margin, margin, w - margin, h - margin], outline=accent, width=3)
    draw.rectangle([margin + 12, margin + 12, w - margin - 12, h - margin - 12], outline=(accent[0]//2, accent[1]//2, accent[2]//2), width=1)

    # Corner Classical Ornaments
    ornament_size = 40
    for cx, cy in [(margin, margin), (w - margin, margin), (margin, h - margin), (w - margin, h - margin)]:
        draw.rectangle([cx - 10, cy - 10, cx + 10, cy + 10], fill=accent)

    # 3. Add Classical Text & Symbolism Overlay
    try:
        font_title = ImageFont.truetype("arial.ttf", 44)
        font_sub   = ImageFont.truetype("arial.ttf", 30)
        font_author= ImageFont.truetype("arial.ttf", 36)
    except Exception:
        font_title = font_sub = font_author = ImageFont.load_default()

    # Draw Header & Shot Title
    draw.text((w // 2, 220), "RENAISSANCE MASTERPIECE", fill=accent, font=font_sub, anchor="mm")
    draw.text((w // 2, 280), f"BEAT {shot_num:02d} • {label.upper()}", fill=(240, 240, 240), font=font_title, anchor="mm")

    # Center Quote Fragment Emblem
    draw.ellipse([w//2 - 180, h//2 - 180, w//2 + 180, h//2 + 180], outline=accent, width=4)
    draw.text((w // 2, h // 2 - 20), f"PROMPT {shot_num}", fill=accent, font=font_title, anchor="mm")
    draw.text((w // 2, h // 2 + 40), f"{theme.upper()} STOIC ART", fill=(200, 200, 200), font=font_sub, anchor="mm")

    # Draw Author & Footer Signature
    draw.text((w // 2, h - 280), f"— {author.upper()} —", fill=accent, font=font_author, anchor="mm")
    draw.text((w // 2, h - 220), f"Palette: {palette['name']}", fill=(160, 160, 160), font=font_sub, anchor="mm")

    img.save(str(out_path), quality=95)
    print(f"  -> Generated dynamic unique canvas frame: {out_path.name}")


def get_api_keys():
    """Retrieve all available Gemini API keys from environment variables."""
    keys = []
    for key_name in ["GEMINI_API_KEY_1", "GEMINI_API_KEY_2", "GEMINI_API_KEY_3", "GEMINI_API_KEY", "GOOGLE_API_KEY"]:
        val = os.environ.get(key_name)
        if val and val not in keys:
            keys.append(val)
    return keys


def generate_artworks():
    script_data, quote_data = load_context()
    quote_text = script_data.get("full_text") or quote_data.get("quote", "Stoic wisdom for daily focus.")
    author = quote_data.get("author", "Stoic Philosopher")
    theme = quote_data.get("theme", "discipline")

    beats = build_dynamic_beats(script_data, quote_data)
    
    print("=" * 60)
    print("  [ai_image_generator] AI Artwork Generation (9:16 Renaissance)")
    print("=" * 60)
    print(f"Target Quote : {quote_text[:60]}...")
    print(f"Author       : {author}")
    print(f"Theme        : {theme}")
    
    api_keys = get_api_keys()
    print(f"Found {len(api_keys)} API keys for round-robin rotation.")

    clients = []
    for k in api_keys:
        try:
            from google import genai
            c = genai.Client(api_key=k)
            clients.append((k, c))
        except Exception as e:
            print(f"GenAI SDK notice for key: {e}.")

    generated_manifest = []

    for idx, beat in enumerate(beats, start=1):
        out_filename = f"shot_{idx:02d}.jpg"
        out_path = OUTPUT_DIR / out_filename
        
        full_prompt = f"{beat['prompt']}, {STYLE_PROMPT}"
        success = False

        if clients:
            # Try clients starting at round-robin offset: (idx - 1) % len(clients)
            start_offset = (idx - 1) % len(clients)
            for attempt_idx in range(len(clients)):
                k_str, client = clients[(start_offset + attempt_idx) % len(clients)]
                try:
                    from google.genai import types
                    print(f"Generating Shot {idx}/10 with Imagen 3 using API Key {(start_offset + attempt_idx) % len(clients) + 1}...")
                    result = client.models.generate_images(
                        model="imagen-3.0-generate-002",
                        prompt=full_prompt,
                        config=types.GenerateImagesConfig(
                            number_of_images=1,
                            output_mime_type="image/jpeg",
                            aspect_ratio="9:16",
                            person_generation="ALLOW_ADULT"
                        )
                    )
                    if result.generated_images:
                        from PIL import Image
                        gen_img = result.generated_images[0]
                        img = Image.open(io.BytesIO(gen_img.image.image_bytes))
                        img.save(str(out_path), quality=95)
                        print(f"  -> Saved 9:16 AI Artwork: {out_path.name}")
                        success = True
                        break
                except Exception as exc:
                    print(f"  -> API key {(start_offset + attempt_idx) % len(clients) + 1} note for shot {idx}: {exc}")

        if not success:
            # Generate dynamic procedural Renaissance artwork frame tailored to THIS quote & theme
            generate_procedural_fallback_art(
                out_path,
                shot_num=idx,
                label=beat["label"],
                quote_text=quote_text,
                theme=theme,
                author=author
            )

        generated_manifest.append({
            "shot": idx,
            "label": beat["label"],
            "prompt": full_prompt,
            "file": str(out_path.resolve()),
            "duration": 3.0,
            "zoom_dir": ["zoom_in", "zoom_out", "pan_up", "pan_down"][idx % 4]
        })

    MANIFEST_PATH.write_text(json.dumps(generated_manifest, indent=2), encoding="utf-8")
    print(f"\nCompleted AI Artwork generation! Manifest written to: {MANIFEST_PATH.name}")


if __name__ == "__main__":
    generate_artworks()
