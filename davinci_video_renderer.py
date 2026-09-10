"""
davinci_video_renderer.py — Sequences Leonardo da Vinci master visual assets (9:16 Vertical)
with motion transitions, audio, music, and burned-in subtitles into a 1080x1920 vertical MP4 short.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    import imageio_ffmpeg as _iff
    _ffdir = Path(_iff.get_ffmpeg_exe()).parent
    _ffexe = _ffdir / "ffmpeg.exe"
    if not _ffexe.exists():
        import shutil as _shutil
        _shutil.copy2(_iff.get_ffmpeg_exe(), str(_ffexe))
    if str(_ffdir) not in os.environ.get("PATH", ""):
        os.environ["PATH"] = str(_ffdir) + os.pathsep + os.environ.get("PATH", "")
    FFMPEG = str(_ffexe)
except ImportError:
    FFMPEG = "ffmpeg"

BASE_DIR      = Path(__file__).parent
AUDIO_PATH    = BASE_DIR / "audio.mp3"
CAPTIONS_PATH = BASE_DIR / "captions.ass"
SCRIPT_PATH   = BASE_DIR / "script.json"
OUTPUTS_DIR   = BASE_DIR / "outputs"

UPLOAD_DIR = Path(r"C:\Users\SmartKid\.gemini\antigravity\brain\18d713e4-a056-4113-a177-38ea55996a47\.user_uploaded")

# Mapping of all 9 vertical (9:16) da Vinci master artwork images across the 11 fast-paced shots (max ~4s duration)
BEAT_ASSETS = [
    {
        "shot": 1,
        "label": "Hook - Balcony Chairs",
        "file": UPLOAD_DIR / "media_1788980958753.jpg",
        "duration": 3.86,
        "zoom_dir": "zoom_in",
    },
    {
        "shot": 2,
        "label": "Hook - Two Friends Seated",
        "file": UPLOAD_DIR / "media_1788980886577.jpg",
        "duration": 3.02,
        "zoom_dir": "zoom_out",
    },
    {
        "shot": 3,
        "label": "Context - Orator Shouting",
        "file": UPLOAD_DIR / "media_1788980785099.jpg",
        "duration": 2.84,
        "zoom_dir": "pan_up",
    },
    {
        "shot": 4,
        "label": "Context - Man on Foggy Bridge",
        "file": UPLOAD_DIR / "media_1788980710219.jpg",
        "duration": 3.66,
        "zoom_dir": "zoom_in",
    },
    {
        "shot": 5,
        "label": "Context - Isolated Man Portrait",
        "file": UPLOAD_DIR / "media_1788980464725.jpg",
        "duration": 3.10,
        "zoom_dir": "zoom_out",
    },
    {
        "shot": 6,
        "label": "App - Open Hands on Table",
        "file": UPLOAD_DIR / "media_1788980502628.jpg",
        "duration": 3.98,
        "zoom_dir": "zoom_in",
    },
    {
        "shot": 7,
        "label": "App - Attentive Listener Portrait",
        "file": UPLOAD_DIR / "media_1788980560366.jpg",
        "duration": 3.88,
        "zoom_dir": "pan_down",
    },
    {
        "shot": 8,
        "label": "App - Unbuckling Leather Strap",
        "file": UPLOAD_DIR / "media_1788980596931.jpg",
        "duration": 3.66,
        "zoom_dir": "zoom_out",
    },
    {
        "shot": 9,
        "label": "App - Unburdened Strap Focus",
        "file": UPLOAD_DIR / "media_1788980596931.jpg",
        "duration": 3.56,
        "zoom_dir": "zoom_in",
    },
    {
        "shot": 10,
        "label": "CTA - Attentive Listener Portrait",
        "file": UPLOAD_DIR / "media_1788980560366.jpg",
        "duration": 4.40,
        "zoom_dir": "zoom_in",
    },
    {
        "shot": 11,
        "label": "CTA - Solitary Horse in Fog",
        "file": UPLOAD_DIR / "media_1788980655798.jpg",
        "duration": 5.87,
        "zoom_dir": "zoom_out",
    },
]

OUT_W = 1080
OUT_H = 1920
FPS   = 30

def run(cmd: list[str], label: str) -> None:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"\nERROR: ffmpeg failed during [{label}]", file=sys.stderr)
        print("Command:", " ".join(cmd), file=sys.stderr)
        print("stderr:", result.stderr[-2000:], file=sys.stderr)
        sys.exit(1)

def get_audio_duration(path: Path) -> float:
    result = subprocess.run([FFMPEG, "-i", str(path)], capture_output=True, text=True)
    m = re.search(r"Duration:\s*(\d+):(\d+):([\d.]+)", result.stderr)
    if not m:
        return 41.83
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))

def process_image_to_video_segment(
    img_path: Path,
    out_path: Path,
    duration: float,
    zoom_dir: str = "zoom_in"
) -> None:
    num_frames = int(round(duration * FPS))

    if zoom_dir == "zoom_in":
        zoom_expr = "min(pzoom+0.0008,1.15)"
        x_expr = "iw/2-(iw/zoom/2)"
        y_expr = "ih/2-(ih/zoom/2)"
    elif zoom_dir == "zoom_out":
        zoom_expr = "max(1.15-0.0008*on,1.0)"
        x_expr = "iw/2-(iw/zoom/2)"
        y_expr = "ih/2-(ih/zoom/2)"
    elif zoom_dir == "pan_up":
        zoom_expr = "1.10"
        x_expr = "iw/2-(iw/zoom/2)"
        y_expr = f"ih/zoom/2 + (ih - ih/zoom) * (1 - on/{num_frames})"
    elif zoom_dir == "pan_down":
        zoom_expr = "1.10"
        x_expr = "iw/2-(iw/zoom/2)"
        y_expr = f"(ih - ih/zoom) * (on/{num_frames})"
    else:
        zoom_expr = "min(pzoom+0.0008,1.15)"
        x_expr = "iw/2-(iw/zoom/2)"
        y_expr = "ih/2-(ih/zoom/2)"

    vf = (
        f"scale=1080:1920:force_original_aspect_ratio=increase,"
        f"crop=1080:1920,"
        f"zoompan=z='{zoom_expr}':x='{x_expr}':y='{y_expr}':d={num_frames}:s={OUT_W}x{OUT_H}:fps={FPS},"
        f"eq=brightness=0.01:contrast=1.03:saturation=1.05,"
        f"setsar=1"
    )

    cmd = [
        FFMPEG, "-y",
        "-loop", "1",
        "-i", str(img_path),
        "-t", f"{duration:.3f}",
        "-vf", vf,
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "18",
        "-pix_fmt", "yuv420p",
        str(out_path)
    ]
    run(cmd, f"render segment {img_path.name}")

def concat_and_mux(
    segment_paths: list[Path],
    audio_path: Path,
    captions_path: Path,
    output_path: Path
) -> None:
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as f:
        for seg in segment_paths:
            f.write(f"file '{seg.as_posix()}'\n")
        concat_file = f.name

    try:
        concat_tmp = output_path.with_suffix(".concat.mp4")
        run([
            FFMPEG, "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", concat_file,
            "-c", "copy",
            str(concat_tmp)
        ], "concat video segments")

        ass_escaped = str(captions_path).replace("\\", "/").replace(":", "\\:")
        vf_sub = f"subtitles='{ass_escaped}'"

        cmd = [
            FFMPEG, "-y",
            "-i", str(concat_tmp),
            "-i", str(audio_path),
            "-map", "0:v",
            "-map", "1:a",
            "-vf", vf_sub,
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "18",
            "-c:a", "aac",
            "-b:a", "192k",
            "-pix_fmt", "yuv420p",
            "-shortest",
            str(output_path)
        ]
        run(cmd, "mux audio + burn subtitles")
        concat_tmp.unlink(missing_ok=True)
    finally:
        os.unlink(concat_file)

def main() -> None:
    parser = argparse.ArgumentParser(description="Render 9:16 Da Vinci Custom Image Sequence Video")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = args.output if args.output else OUTPUTS_DIR / "davinci_stoic_short_9x16.mp4"

    print("=" * 60)
    print("  Da Vinci Master 9:16 TikTok / YouTube Shorts Video Renderer")
    print("=" * 60)
    print(f"  Output       : {out_path}")
    print(f"  Resolution   : {OUT_W}x{OUT_H} (Native 9:16 Vertical)")
    print(f"  Visual Assets: {len(BEAT_ASSETS)} Vertical 9:16 Shots (Each ≤ 4-5 seconds)")
    print("-" * 60)

    audio_dur = get_audio_duration(AUDIO_PATH)
    print(f"  Audio Duration: {audio_dur:.2f}s")

    seg_dir = BASE_DIR / "scratch" / "davinci_segments_9x16"
    seg_dir.mkdir(parents=True, exist_ok=True)

    segment_paths = []
    for i, asset in enumerate(BEAT_ASSETS, 1):
        img_file = asset["file"]
        dur = asset["duration"]
        zoom_dir = asset["zoom_dir"]
        seg_out = seg_dir / f"davinci_seg_9x16_{i:02d}.mp4"

        print(f"  [{i:02d}/{len(BEAT_ASSETS)}] Rendering {asset['label']:<32} ({dur:.2f}s) | Motion: {zoom_dir:<9} | Image: {img_file.name}")
        process_image_to_video_segment(img_file, seg_out, dur, zoom_dir)
        segment_paths.append(seg_out)

    print("\nConcatenating 9:16 video segments & muxing audio + subtitles...")
    concat_and_mux(segment_paths, AUDIO_PATH, CAPTIONS_PATH, out_path)

    if not out_path.exists() or out_path.stat().st_size == 0:
        print("ERROR: Output video missing or empty!", file=sys.stderr)
        sys.exit(1)

    size_mb = out_path.stat().st_size / (1024 * 1024)
    print(f"\n{'=' * 60}")
    print(f"  9:16 VERTICAL VIDEO RENDERING COMPLETE!")
    print(f"  File     : {out_path.name}")
    print(f"  Size     : {size_mb:.2f} MB")
    print(f"  Path     : {out_path}")
    print(f"{'=' * 60}\n")

if __name__ == "__main__":
    main()
