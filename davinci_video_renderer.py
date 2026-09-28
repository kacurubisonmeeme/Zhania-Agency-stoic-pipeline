"""
davinci_video_renderer.py — Sequences AI-generated 9:16 vertical master images
with dynamic motion transitions (Ken Burns + xfade dissolves), audio narration,
background music, and clean burned-in ASS subtitles.
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

MANIFEST_PATH = BASE_DIR / "ai_images_manifest.json"
ARTIFACT_DIR  = Path(r"C:\Users\SmartKid\.gemini\antigravity\brain\18d713e4-a056-4113-a177-38ea55996a47")

DEFAULT_BEAT_ASSETS = [
    {
        "shot": 1,
        "label": "Hook 1 - Elder Philosopher & Water Clock",
        "file": ARTIFACT_DIR / "seneca_shot01_1789656214453.jpg",
        "duration": 2.80,
        "zoom_dir": "zoom_in",
    },
    {
        "shot": 2,
        "label": "Hook 2 - Gold Coins Slipping Into Water",
        "file": ARTIFACT_DIR / "seneca_shot02_1789656257459.jpg",
        "duration": 2.70,
        "zoom_dir": "zoom_out",
    },
    {
        "shot": 3,
        "label": "Context 1 - Marketplace & Hourglass Shadows",
        "file": ARTIFACT_DIR / "seneca_shot03_1789656297956.jpg",
        "duration": 3.30,
        "zoom_dir": "pan_up",
    },
    {
        "shot": 4,
        "label": "Context 2 - Stormy Sea & Stoic Scholar",
        "file": ARTIFACT_DIR / "seneca_shot04_1789656345219.jpg",
        "duration": 2.70,
        "zoom_dir": "zoom_in",
    },
    {
        "shot": 5,
        "label": "Context 3 - Unfinished Dusty Marble Hero",
        "file": ARTIFACT_DIR / "seneca_shot05_1789656391063.jpg",
        "duration": 3.30,
        "zoom_dir": "zoom_out",
    },
    {
        "shot": 6,
        "label": "App 1 - Reclaiming Hours Balcony Sun",
        "file": ARTIFACT_DIR / "seneca_shot06_1789656460638.jpg",
        "duration": 3.00,
        "zoom_dir": "zoom_in",
    },
    {
        "shot": 7,
        "label": "App 2 - Scholar Writing in Journal",
        "file": ARTIFACT_DIR / "seneca_shot07_1789656515355.jpg",
        "duration": 3.20,
        "zoom_dir": "pan_down",
    },
    {
        "shot": 8,
        "label": "App 3 - Serene Garden & Horizon Archways",
        "file": ARTIFACT_DIR / "seneca_shot08_1789656566471.jpg",
        "duration": 3.20,
        "zoom_dir": "zoom_out",
    },
    {
        "shot": 9,
        "label": "CTA 1 - Stepping Over Broken Sundial",
        "file": ARTIFACT_DIR / "seneca_shot09_1789656616754.jpg",
        "duration": 3.30,
        "zoom_dir": "zoom_in",
    },
    {
        "shot": 10,
        "label": "CTA 2 - Seneca Smile & Scroll Loop",
        "file": ARTIFACT_DIR / "seneca_shot10_1789656666122.jpg",
        "duration": 4.40,
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
        return 31.90
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

def build_xfade_filtergraph(segment_paths: list[Path], assets: list[dict], transition_duration: float = 0.4) -> tuple[str, list[str]]:
    inputs = []
    for p in segment_paths:
        inputs.extend(["-i", str(p)])

    n = len(segment_paths)
    if n == 1:
        return "[0:v]copy[outv]", inputs

    filter_chunks = []
    current_offset = assets[0]["duration"] - transition_duration
    prev_stream = "0:v"

    transitions = ["dissolve", "fade", "zoomin", "dissolve", "fade", "zoomin", "dissolve", "fade", "zoomin"]

    for i in range(1, n):
        trans = transitions[(i - 1) % len(transitions)]
        out_stream = "outv" if i == n - 1 else f"xf{i}"
        
        filter_chunks.append(
            f"[{prev_stream}][{i}:v]xfade=transition={trans}:duration={transition_duration:.2f}:offset={current_offset:.2f}[{out_stream}]"
        )
        prev_stream = out_stream
        if i < n - 1:
            current_offset += assets[i]["duration"] - transition_duration

    filtergraph = ";".join(filter_chunks)
    return filtergraph, inputs

def concat_and_mux(
    segment_paths: list[Path],
    assets: list[dict],
    audio_path: Path,
    captions_path: Path,
    output_path: Path,
    use_xfade: bool = True
) -> None:
    ass_escaped = str(captions_path).replace("\\", "/").replace(":", "\\:")

    if use_xfade and len(segment_paths) > 1:
        filtergraph, input_args = build_xfade_filtergraph(segment_paths, assets, transition_duration=0.4)
        full_vf = f"{filtergraph};[outv]subtitles='{ass_escaped}'[finalv]"

        cmd = [FFMPEG, "-y"]
        cmd.extend(input_args)
        cmd.extend([
            "-i", str(audio_path),
            "-filter_complex", full_vf,
            "-map", "[finalv]",
            "-map", f"{len(segment_paths)}:a",
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "18",
            "-c:a", "aac",
            "-b:a", "192k",
            "-pix_fmt", "yuv420p",
            "-shortest",
            str(output_path)
        ])
        run(cmd, "xfade transition render + subtitles")
    else:
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

def get_beat_assets() -> list[dict]:
    if MANIFEST_PATH.exists():
        try:
            data = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
            assets = []
            for item in data:
                assets.append({
                    "shot": item["shot"],
                    "label": item.get("label", f"Shot {item['shot']}"),
                    "file": Path(item["file"]),
                    "duration": item.get("duration", 3.0),
                    "zoom_dir": item.get("zoom_dir", "zoom_in")
                })
            if assets:
                return assets
        except Exception:
            pass
    return DEFAULT_BEAT_ASSETS

def main() -> None:
    parser = argparse.ArgumentParser(description="Render Seneca 9:16 Vertical Video")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    
    quote_id = "stoic_short"
    if SCRIPT_PATH.exists():
        try:
            s_data = json.loads(SCRIPT_PATH.read_text(encoding="utf-8"))
            quote_id = s_data.get("quote_id", "stoic_short")
        except Exception:
            pass

    import time
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    default_name = f"{quote_id}_{timestamp}_9x16.mp4"
    out_path = args.output if args.output else OUTPUTS_DIR / default_name

    assets = get_beat_assets()

    print("=" * 60)
    print("  Stoic Shorts 9:16 Vertical Video Renderer")
    print("=" * 60)
    print(f"  Output       : {out_path}")
    print(f"  Resolution   : {OUT_W}x{OUT_H} (Native 9:16 Vertical)")
    print(f"  Visual Assets: {len(assets)} AI-Generated 9:16 Images")
    print(f"  Transitions  : Native FFmpeg xfade (dissolve/fade/zoomin)")
    print("-" * 60)

    audio_dur = get_audio_duration(AUDIO_PATH)
    print(f"  Audio Duration: {audio_dur:.2f}s")

    seg_dir = BASE_DIR / "scratch" / "seneca_segments_9x16"
    seg_dir.mkdir(parents=True, exist_ok=True)

    segment_paths = []
    for i, asset in enumerate(assets, 1):
        img_file = asset["file"]
        dur = asset["duration"]
        zoom_dir = asset["zoom_dir"]
        seg_out = seg_dir / f"seneca_seg_9x16_{i:02d}.mp4"

        print(f"  [{i:02d}/{len(assets)}] Rendering {asset['label']:<36} ({dur:.2f}s) | Motion: {zoom_dir:<9}")
        process_image_to_video_segment(img_file, seg_out, dur, zoom_dir)
        segment_paths.append(seg_out)

    print("\nApplying xfade transitions, audio muxing & burning clean ASS subtitles...")
    concat_and_mux(segment_paths, assets, AUDIO_PATH, CAPTIONS_PATH, out_path, use_xfade=True)

    if not out_path.exists() or out_path.stat().st_size == 0:
        print("ERROR: Output video missing or empty!", file=sys.stderr)
        sys.exit(1)

    size_mb = out_path.stat().st_size / (1024 * 1024)
    print(f"\n{'=' * 60}")
    print(f"  STOIC SHORTS 9:16 VIDEO RENDERING COMPLETE!")
    print(f"  File        : {out_path.name}")
    print(f"  Size        : {size_mb:.2f} MB")
    print(f"  Path        : {out_path}")
    print(f"{'=' * 60}\n")

if __name__ == "__main__":
    main()
