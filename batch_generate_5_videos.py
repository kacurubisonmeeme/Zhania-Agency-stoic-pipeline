import json
import shutil
import subprocess
from pathlib import Path

BASE_DIR = Path(r"C:\data-science\Personal Projects\stoic-pipeline")
ART_DIR = Path(r"C:\Users\SmartKid\.gemini\antigravity\brain\18d713e4-a056-4113-a177-38ea55996a47")
DEST_DIR = BASE_DIR / "broll" / "generated_art"
OUTPUTS_DIR = BASE_DIR / "outputs"

DEST_DIR.mkdir(parents=True, exist_ok=True)
OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)

# Define 5 Videos
VIDEOS = [
    {
        "output_filename": "seneca_fear_and_imagination_9x16.mp4",
        "quote_data": {
            "quote_id": "seneca_fear_and_imagination",
            "philosopher": "Seneca",
            "quote": "We suffer more often in imagination than in reality.",
            "theme": "fear",
            "source": "Letters from a Stoic",
            "key_takeaway": "Anxiety is born from imaginary futures. Ground your mind in the present reality to conquer fear."
        },
        "script_data": {
            "quote_id": "seneca_fear_and_imagination",
            "philosopher": "Seneca",
            "quote": "We suffer more often in imagination than in reality.",
            "theme": "fear",
            "target_duration_seconds": 38.0,
            "hook": "Seneca warned Lucilius about the invisible enemy that destroys peace before trouble even arrives.",
            "analysis": "We suffer more often in imagination than in reality. Mindless anxiety projects false catastrophes into tomorrow. You torment yourself with shadows that do not exist. Strip away the panic, inspect the present moment, and you will find you are safe.",
            "call_to_action": "Stop rehearsing grief in your mind. Face today with calm clarity and conquer your imaginary fears.",
            "full_text": "Seneca warned Lucilius about the invisible enemy that destroys peace before trouble even arrives. We suffer more often in imagination than in reality. Mindless anxiety projects false catastrophes into tomorrow. You torment yourself with shadows that do not exist. Strip away the panic, inspect the present moment, and you will find you are safe. Stop rehearsing grief in your mind. Face today with calm clarity and conquer your imaginary fears."
        },
        "image_patterns": [f"v1_shot_{i:02d}_" for i in range(1, 11)]
    },
    {
        "output_filename": "epictetus_reaction_is_everything_9x16.mp4",
        "quote_data": {
            "quote_id": "epictetus_reaction_is_everything",
            "philosopher": "Epictetus",
            "quote": "It's not what happens to you, but how you react to it that matters.",
            "theme": "control",
            "source": "Enchiridion",
            "key_takeaway": "External events have no power over your peace until you assign meaning to them."
        },
        "script_data": {
            "quote_id": "epictetus_reaction_is_everything",
            "philosopher": "Epictetus",
            "quote": "It's not what happens to you, but how you react to it that matters.",
            "theme": "control",
            "target_duration_seconds": 38.0,
            "hook": "Epictetus taught that your power does not lie in controlling external events.",
            "analysis": "It's not what happens to you, but how you react to it that matters. Circumstances are neutral until your mind passes judgment. When chaos strikes, pause. Choose composure over anger, focus over panic, and virtue over weakness.",
            "call_to_action": "Master your response today. Guard your internal citadel and remain undisturbed.",
            "full_text": "Epictetus taught that your power does not lie in controlling external events. It's not what happens to you, but how you react to it that matters. Circumstances are neutral until your mind passes judgment. When chaos strikes, pause. Choose composure over anger, focus over panic, and virtue over weakness. Master your response today. Guard your internal citadel and remain undisturbed."
        },
        "image_patterns": [f"epictetus_control_shot{i:02d}_" for i in range(1, 11)]
    },
    {
        "output_filename": "marcus_aurelius_morning_privilege_9x16.mp4",
        "quote_data": {
            "quote_id": "marcus_aurelius_morning_privilege",
            "philosopher": "Marcus Aurelius",
            "quote": "When you arise in the morning think of what a privilege it is to be alive, to think, to enjoy, to love.",
            "theme": "discipline",
            "source": "Meditations Book 5",
            "key_takeaway": "Each morning is a gift of consciousness to fulfill your duty with gratitude."
        },
        "script_data": {
            "quote_id": "marcus_aurelius_morning_privilege",
            "philosopher": "Marcus Aurelius",
            "quote": "When you arise in the morning think of what a privilege it is to be alive, to think, to enjoy, to love.",
            "theme": "discipline",
            "target_duration_seconds": 38.0,
            "hook": "Emperor Marcus Aurelius forced himself out of bed with a single powerful reminder.",
            "analysis": "When you arise in the morning think of what a privilege it is to be alive, to think, to enjoy, to love. You were not made to hide under warm blankets. You were built for action, for virtue, and for service to human fellowship.",
            "call_to_action": "Awaken with purpose today. Embrace your life's duty with joy and unshakeable gratitude.",
            "full_text": "Emperor Marcus Aurelius forced himself out of bed with a single powerful reminder. When you arise in the morning think of what a privilege it is to be alive, to think, to enjoy, to love. You were not made to hide under warm blankets. You were built for action, for virtue, and for service to human fellowship. Awaken with purpose today. Embrace your life's duty with joy and unshakeable gratitude."
        },
        "image_patterns": [f"marcus_memento_shot{i:02d}_" for i in range(1, 11)]
    },
    {
        "output_filename": "zeno_mastery_of_silence_9x16.mp4",
        "quote_data": {
            "quote_id": "zeno_mastery_of_silence",
            "philosopher": "Zeno of Citium",
            "quote": "We have two ears and one mouth so that we can listen twice as much as we speak.",
            "theme": "wisdom",
            "source": "Fragments of Zeno",
            "key_takeaway": "Silence yields wisdom. Listen deeply before offering words."
        },
        "script_data": {
            "quote_id": "zeno_mastery_of_silence",
            "philosopher": "Zeno of Citium",
            "quote": "We have two ears and one mouth so that we can listen twice as much as we speak.",
            "theme": "wisdom",
            "target_duration_seconds": 38.0,
            "hook": "Zeno, the founder of Stoicism, taught his disciples the art of intentional listening.",
            "analysis": "We have two ears and one mouth so that we can listen twice as much as we speak. Fools rush to voice opinion, while the wise observe in silence. True understanding requires quiet perception and deep contemplation.",
            "call_to_action": "Speak less and listen more today. Master your tongue and gain profound clarity.",
            "full_text": "Zeno, the founder of Stoicism, taught his disciples the art of intentional listening. We have two ears and one mouth so that we can listen twice as much as we speak. Fools rush to voice opinion, while the wise observe in silence. True understanding requires quiet perception and deep contemplation. Speak less and listen more today. Master your tongue and gain profound clarity."
        },
        "image_patterns": [
            "zeno_mastery_shot01_", "zeno_mastery_shot02_", "zeno_mastery_shot03_",
            "zeno_mastery_shot04_", "zeno_mastery_shot05_", "zeno_mastery_shot06_",
            "v2_shot_01_", "v2_shot_02_", "shot_08_", "shot_09_"
        ]
    },
    {
        "output_filename": "seneca_value_of_time_9x16.mp4",
        "quote_data": {
            "quote_id": "seneca_value_of_time",
            "philosopher": "Seneca",
            "quote": "It is not that we have a short time to live, but that we waste a lot of it.",
            "theme": "time_management",
            "source": "On the Shortness of Life",
            "key_takeaway": "Time is your most precious non-renewable asset. Guard it fiercely."
        },
        "script_data": {
            "quote_id": "seneca_value_of_time",
            "philosopher": "Seneca",
            "quote": "It is not that we have a short time to live, but that we waste a lot of it.",
            "theme": "time_management",
            "target_duration_seconds": 38.0,
            "hook": "Seneca observed how people guard their money fiercely but throw away their time carelessly.",
            "analysis": "It is not that we have a short time to live, but that we waste a lot of it. Life is long enough if you know how to use it. Reclaim your hours from trivial distractions, empty obligations, and pointless pursuits.",
            "call_to_action": "Treat every hour as sacred today. Live intentionally and reclaim your life.",
            "full_text": "Seneca observed how people guard their money fiercely but throw away their time carelessly. It is not that we have a short time to live, but that we waste a lot of it. Life is long enough if you know how to use it. Reclaim your hours from trivial distractions, empty obligations, and pointless pursuits. Treat every hour as sacred today. Live intentionally and reclaim your life."
        },
        "image_patterns": [f"seneca_imagination_shot{i:02d}_" for i in range(1, 11)]
    }
]

def process_video(item: dict):
    out_name = item["output_filename"]
    print(f"\n==================================================")
    print(f" PROCESSING VIDEO: {out_name}")
    print(f"==================================================")

    # 1. Save quote.json and script.json
    (BASE_DIR / "quote.json").write_text(json.dumps(item["quote_data"], indent=2), encoding="utf-8")
    (BASE_DIR / "script.json").write_text(json.dumps(item["script_data"], indent=2), encoding="utf-8")

    # 2. Copy matching images
    patterns = item["image_patterns"]
    for i in range(1, 11):
        pat = patterns[i-1]
        matches = list(ART_DIR.glob(f"{pat}*.jpg"))
        dest = DEST_DIR / f"shot_{i:02d}.jpg"
        if matches:
            shutil.copy2(matches[0], dest)
            print(f"  Copied {matches[0].name} -> shot_{i:02d}.jpg")
        else:
            # Fallback to general shot_01..10 if specific pattern missing
            fallback = list(ART_DIR.glob(f"shot_{i:02d}_*.jpg"))
            if fallback:
                shutil.copy2(fallback[0], dest)
                print(f"  Fallback Copied {fallback[0].name} -> shot_{i:02d}.jpg")
            else:
                print(f"  [ERROR] Missing image for shot_{i:02d}")

    # 3. Create manifest
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
            "prompt": f"Caravaggio Renaissance Shot {i:02d}",
            "file": str(dest.resolve()),
            "duration": 4.2,
            "zoom_dir": zoom_dirs[(i-1) % 4]
        })

    (BASE_DIR / "ai_images_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    # 4. Generate Voiceover TTS
    print("  -> Generating voiceover...")
    res_tts = subprocess.run(["python", "tts_generator.py"], cwd=BASE_DIR, capture_output=True, text=True)
    if res_tts.returncode != 0:
        print("  [TTS ERROR]", res_tts.stderr)

    # 5. Generate Captions
    print("  -> Generating Whisper ASS subtitles...")
    res_cap = subprocess.run(["python", "caption_generator.py"], cwd=BASE_DIR, capture_output=True, text=True)
    if res_cap.returncode != 0:
        print("  [CAPTION ERROR]", res_cap.stderr)

    # 6. Render Final MP4 Video
    out_mp4 = OUTPUTS_DIR / out_name
    print(f"  -> Rendering MP4 via FFmpeg -> {out_mp4.name}...")
    res_vid = subprocess.run(["python", "davinci_video_renderer.py", "--output", str(out_mp4)], cwd=BASE_DIR, capture_output=True, text=True)
    if res_vid.returncode != 0:
        print("  [RENDER ERROR]", res_vid.stderr)
    else:
        sz = out_mp4.stat().st_size / (1024 * 1024)
        print(f"  [SUCCESS] {out_mp4.name} created! File size: {sz:.2f} MB")

if __name__ == "__main__":
    for vid in VIDEOS:
        process_video(vid)
