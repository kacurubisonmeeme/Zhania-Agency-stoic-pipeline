import shutil
import json
import subprocess
from pathlib import Path

BASE_DIR = Path(r"C:\data-science\Personal Projects\stoic-pipeline")
ART_DIR = Path(r"C:\Users\SmartKid\.gemini\antigravity\brain\18d713e4-a056-4113-a177-38ea55996a47")
DEST_DIR = BASE_DIR / "broll" / "generated_art"
DEST_DIR.mkdir(parents=True, exist_ok=True)

def assemble_video(v_prefix: str, output_name: str):
    print(f"\n==================================================")
    print(f" Assembling Video: {output_name}")
    print(f"==================================================")
    
    # Copy images
    for i in range(1, 11):
        src = list(ART_DIR.glob(f"{v_prefix}_shot_{i:02d}_*.jpg"))
        if src:
            dest = DEST_DIR / f"shot_{i:02d}.jpg"
            shutil.copy2(src[0], dest)
            print(f"  Copied {src[0].name} -> {dest.name}")
        else:
            print(f"  [ERROR] Missing {v_prefix}_shot_{i:02d}")

    # Build manifest
    manifest = []
    zoom_dirs = ["zoom_in", "zoom_out", "pan_up", "pan_down"]
    labels = [
        "Hook 1 - The Awakening", "Hook 2 - The Choice",
        "Context 1 - The Tempest", "Context 2 - Solitary Horizon", "Context 3 - The Unfinished Hero",
        "Application 1 - Morning Sun", "Application 2 - Writing Journal", "Application 3 - Classical Arch",
        "CTA 1 - The Illuminated Path", "CTA 2 - Stoic Dawn"
    ]

    for i in range(1, 11):
        dest = DEST_DIR / f"shot_{i:02d}.jpg"
        manifest.append({
            "shot": i,
            "label": labels[i-1],
            "prompt": f"Antigravity Renaissance Shot {i:02d}",
            "file": str(dest.resolve()),
            "duration": 4.2,
            "zoom_dir": zoom_dirs[(i-1) % 4]
        })

    (BASE_DIR / "ai_images_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    # Run TTS
    subprocess.run(["python", "tts_generator.py"], cwd=BASE_DIR, check=True)
    # Run Captions
    subprocess.run(["python", "caption_generator.py"], cwd=BASE_DIR, check=True)
    # Run Renderer
    out_mp4 = BASE_DIR / "outputs" / output_name
    subprocess.run(["python", "davinci_video_renderer.py", "--output", str(out_mp4)], cwd=BASE_DIR, check=True)
    print(f"Completed Video: {out_mp4.name}")

if __name__ == "__main__":
    import sys
    prefix = sys.argv[1] if len(sys.argv) > 1 else "v1"
    out_name = sys.argv[2] if len(sys.argv) > 2 else "seneca_fear_and_imagination_9x16.mp4"
    assemble_video(prefix, out_name)
