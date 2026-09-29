import shutil
import json
import subprocess
from pathlib import Path

BASE_DIR = Path(r"C:\data-science\Personal Projects\stoic-pipeline")
ART_DIR = Path(r"C:\Users\SmartKid\.gemini\antigravity\brain\18d713e4-a056-4113-a177-38ea55996a47")
DEST_DIR = BASE_DIR / "broll" / "generated_art"
DEST_DIR.mkdir(parents=True, exist_ok=True)

# Find generated shot files
shot_files = {}
for f in ART_DIR.glob("shot_*_*.jpg"):
    prefix = f.name.split("_")[0] + "_" + f.name.split("_")[1] # e.g. shot_01
    shot_files[prefix] = f

print(f"Found {len(shot_files)} generated shots from Antigravity:")
for i in range(1, 11):
    key = f"shot_{i:02d}"
    src = shot_files.get(key)
    dest = DEST_DIR / f"shot_{i:02d}.jpg"
    if src:
        shutil.copy2(src, dest)
        print(f"  Copied {src.name} -> {dest.name}")

# Create ai_images_manifest.json
manifest = []
zoom_dirs = ["zoom_in", "zoom_out", "pan_up", "pan_down"]
labels = [
    "Hook 1 - The Awakening",
    "Hook 2 - The Choice",
    "Context 1 - The Tempest",
    "Context 2 - Solitary Horizon",
    "Context 3 - The Unfinished Hero",
    "Application 1 - Morning Sun",
    "Application 2 - Writing Journal",
    "Application 3 - Classical Arch",
    "CTA 1 - The Illuminated Path",
    "CTA 2 - Marcus Aurelius Dawn"
]

for i in range(1, 11):
    dest = DEST_DIR / f"shot_{i:02d}.jpg"
    manifest.append({
        "shot": i,
        "label": labels[i-1],
        "prompt": f"Antigravity Caravaggio Oil Painting Shot {i:02d}",
        "file": str(dest.resolve()),
        "duration": 3.8,
        "zoom_dir": zoom_dirs[(i-1) % 4]
    })

manifest_path = BASE_DIR / "ai_images_manifest.json"
manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
print(f"Manifest saved with {len(manifest)} shots.")

# Run TTS
print("\n--- Running tts_generator.py ---")
res_tts = subprocess.run(["python", "tts_generator.py"], cwd=BASE_DIR, capture_output=True, text=True)
print(res_tts.stdout)
if res_tts.stderr:
    print(res_tts.stderr)

# Run Caption Generator
print("\n--- Running caption_generator.py ---")
res_cap = subprocess.run(["python", "caption_generator.py"], cwd=BASE_DIR, capture_output=True, text=True)
print(res_cap.stdout)
if res_cap.stderr:
    print(res_cap.stderr)

# Run Video Renderer
output_mp4 = BASE_DIR / "outputs" / "marcus_aurelius_master_your_mind_9x16.mp4"
print(f"\n--- Running davinci_video_renderer.py -> {output_mp4.name} ---")
res_vid = subprocess.run(["python", "davinci_video_renderer.py", "--output", str(output_mp4)], cwd=BASE_DIR, capture_output=True, text=True)
print(res_vid.stdout)
if res_vid.stderr:
    print(res_vid.stderr)
