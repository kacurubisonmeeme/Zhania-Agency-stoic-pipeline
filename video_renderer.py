"""
video_renderer.py — Module 6 of the stoic shorts pipeline

Reads broll_manifest.json, audio.mp3, and captions.ass, and produces
a final 1080x1920 vertical MP4 with:
  - Each b-roll clip scaled/cropped to 1080x1920 (regardless of source orientation)
  - A 5-second window taken from 20% into each source clip (avoids static opening)
  - Mild brightness/contrast normalization across all clips (eq filter)
  - All segments concatenated in manifest order
  - audio.mp3 muxed in, synced from 0 (with trailing silence cushion)
  - captions.ass burned in as subtitles with single-word active yellow highlighting

Usage:
    python video_renderer.py
    python video_renderer.py --output my_video.mp4
    python video_renderer.py --no-captions        # skip subtitle burn-in
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

# ── Ensure ffmpeg is on PATH ──────────────────────────────────────────────────
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

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR        = Path(__file__).parent
MANIFEST_PATH   = BASE_DIR / "broll_manifest.json"
AUDIO_PATH      = BASE_DIR / "audio.mp3"
CAPTIONS_PATH   = BASE_DIR / "captions.ass"
SCRIPT_PATH     = BASE_DIR / "script.json"
OUTPUTS_DIR     = BASE_DIR / "outputs"


def build_output_path(script_path: Path = SCRIPT_PATH) -> Path:
    from datetime import datetime
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M")

    quote_id = "video"
    if script_path.exists():
        try:
            data = json.loads(script_path.read_text(encoding="utf-8"))
            quote_id = data.get("quote_id", "video") or "video"
        except Exception:
            pass

    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    return OUTPUTS_DIR / f"{timestamp}_{quote_id}.mp4"


# ─────────────────────────────────────────────────────────────────────────────
# Beat Alignment Verification
# ─────────────────────────────────────────────────────────────────────────────

def parse_ass_word_timestamps(ass_path: Path) -> list[dict]:
    if not ass_path.exists():
        return []

    words = []
    dialogue_re = re.compile(r"^Dialogue:\s*\d+,(\d+:\d+:\d+\.\d+),(\d+:\d+:\d+\.\d+),.*?,.*?,0,0,0,,(.*)$")

    with open(ass_path, "r", encoding="utf-8-sig") as f:
        for line in f:
            m = dialogue_re.match(line.strip())
            if not m:
                continue
            start_str, end_str, text = m.groups()
            
            parts = start_str.split(":")
            h = int(parts[0])
            m_sec = int(parts[1])
            s_part = float(parts[2])
            line_start = h * 3600 + m_sec * 60 + s_part

            eparts = end_str.split(":")
            eh = int(eparts[0])
            em_sec = int(eparts[1])
            es_part = float(eparts[2])
            line_end = eh * 3600 + em_sec * 60 + es_part

            clean_text = re.sub(r"\{\\c&H[0-9A-Fa-f]+&\}", "", text).strip()
            if clean_text:
                words.append({
                    "word": clean_text,
                    "start": line_start,
                    "end": line_end
                })

    return words


def get_spoken_beat_timings(
    script_path: Path,
    captions_path: Path,
    total_audio_dur: float
) -> dict[str, dict]:
    if not script_path.exists():
        return {}

    try:
        script_data = json.loads(script_path.read_text(encoding="utf-8"))
    except Exception:
        return {}

    words_json_path = captions_path.with_name("captions_words.json")
    beats = ["hook", "context", "application", "cta"]
    beat_words = {}
    total_words = 0

    for b in beats:
        text = script_data.get(b, "").strip()
        w_list = text.split()
        beat_words[b] = len(w_list)
        total_words += len(w_list)

    if total_words == 0:
        return {}

    spoken_timings = {}
    ass_words = []

    if words_json_path.exists():
        try:
            ass_words = json.loads(words_json_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    if not ass_words:
        ass_words = parse_ass_word_timestamps(captions_path)

    if ass_words and len(ass_words) >= total_words - 5:
        word_idx = 0
        for b in beats:
            count = beat_words[b]
            if count == 0:
                continue
            start_w_idx = min(word_idx, len(ass_words) - 1)
            end_w_idx = min(word_idx + count - 1, len(ass_words) - 1)
            
            b_start = float(ass_words[start_w_idx]["start"])
            b_end = float(ass_words[end_w_idx]["end"])
            spoken_timings[b] = {
                "start": b_start,
                "end": b_end,
                "duration": b_end - b_start
            }
            word_idx += count
    else:
        curr_t = 0.0
        for b in beats:
            count = beat_words[b]
            dur = (count / total_words) * total_audio_dur if total_words > 0 else 0.0
            spoken_timings[b] = {
                "start": curr_t,
                "end": curr_t + dur,
                "duration": dur
            }
            curr_t += dur

    return spoken_timings


def assign_beat_clip_durations(
    manifest_clips: list[dict],
    script_path: Path,
    captions_path: Path,
    total_audio_dur: float,
) -> None:
    spoken = get_spoken_beat_timings(script_path, captions_path, total_audio_dur)
    if not spoken:
        return

    beat_clips_map: dict[str, list[dict]] = {}
    for c in manifest_clips:
        beat = c.get("beat", "unknown")
        beat_clips_map.setdefault(beat, []).append(c)

    # Ensure total B-roll duration matches or slightly exceeds total_audio_dur
    sum_spoken = sum(sp["duration"] for sp in spoken.values())
    extra_tail = max(0.0, total_audio_dur - sum_spoken)

    for b_name, sp_info in spoken.items():
        spoken_dur = sp_info["duration"]
        if b_name == "cta":
            spoken_dur += extra_tail

        b_clips = beat_clips_map.get(b_name, [])
        n = len(b_clips)
        if n == 0:
            continue

        default_len = 5.0
        remainder = spoken_dur - (n - 1) * default_len
        if remainder >= 1.5:
            durs = [default_len] * (n - 1)
            durs.append(round(spoken_dur - sum(durs), 3))
        else:
            each = spoken_dur / n
            durs = [round(each, 3)] * (n - 1)
            durs.append(round(spoken_dur - sum(durs), 3))

        for clip, target_dur in zip(b_clips, durs):
            clip["target_duration"] = target_dur


def verify_beat_alignment(
    manifest_clips: list[dict],
    script_path: Path,
    captions_path: Path,
    total_audio_dur: float
) -> list[str]:
    spoken = get_spoken_beat_timings(script_path, captions_path, total_audio_dur)
    if not spoken:
        print("  (Skipping beat alignment check: script.json or timing data missing)")
        return []

    manifest_broll = {}
    curr_t = 0.0
    for clip in manifest_clips:
        beat = clip.get("beat", "unknown")
        dur = float(clip.get("target_duration", clip.get("duration", 5.0)))
        if beat not in manifest_broll:
            manifest_broll[beat] = {"start": curr_t, "end": curr_t + dur, "duration": dur}
        else:
            manifest_broll[beat]["end"] += dur
            manifest_broll[beat]["duration"] += dur
        curr_t += dur

    beats = ["hook", "context", "application", "cta"]
    warnings = []

    print("\n" + "=" * 80)
    print("  BEAT ALIGNMENT VERIFICATION SUMMARY")
    print("=" * 80)
    print(f"  {'Beat':<12} | {'Spoken Range (Audio)':<22} | {'B-Roll Range (Manifest)':<23} | {'Delta':<8} | {'Status'}")
    print("-" * 80)

    for b in beats:
        sp = spoken.get(b, {"start": 0.0, "end": 0.0, "duration": 0.0})
        br = manifest_broll.get(b, {"start": 0.0, "end": 0.0, "duration": 0.0})

        sp_str = f"{sp['start']:4.1f}s -> {sp['end']:4.1f}s ({sp['duration']:4.1f}s)"
        br_str = f"{br['start']:4.1f}s -> {br['end']:4.1f}s ({br['duration']:4.1f}s)"
        
        delta = br["duration"] - sp["duration"]
        delta_str = f"{delta:+5.1f}s"

        if abs(delta) > 1.5 and b != "cta":
            status = "[WARN]"
            warn_msg = (
                f"WARN: Beat '{b}' b-roll duration ({br['duration']:.1f}s) differs from "
                f"spoken duration ({sp['duration']:.1f}s) by {delta:+.1f}s (> 1.5s threshold)."
            )
            warnings.append(warn_msg)
        else:
            status = "[OK]"

        print(f"  {b:<12} | {sp_str:<22} | {br_str:<23} | {delta_str:<8} | {status}")

    print("=" * 80)
    if warnings:
        print("\nBeat Timing Alignment Warnings:")
        for w in warnings:
            print(f"  {w}")
    else:
        print("  [OK] All beats aligned cleanly.")
    print("=" * 80 + "\n")

    return warnings

# ── Output spec ───────────────────────────────────────────────────────────────
OUT_W           = 1080
OUT_H           = 1920
CLIP_DURATION   = 5.0
TRIM_START_PCT  = 0.20
EQ_FILTER       = "eq=brightness=0.02:contrast=1.05:saturation=1.05:gamma=1.0"


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def run(cmd: list[str], label: str) -> None:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"\nERROR: ffmpeg failed during [{label}]", file=sys.stderr)
        print("Command:", " ".join(cmd), file=sys.stderr)
        print("stderr:", result.stderr[-2000:], file=sys.stderr)
        sys.exit(1)


def get_clip_duration(path: Path) -> float:
    result = subprocess.run(
        [FFMPEG, "-i", str(path)],
        capture_output=True, text=True
    )
    m = re.search(r"Duration:\s*(\d+):(\d+):([\d.]+)", result.stderr)
    if not m:
        return 0.0
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))


def check_input(path: Path, label: str) -> None:
    if not path.exists():
        print(f"ERROR: Missing required input [{label}]: {path}", file=sys.stderr)
        sys.exit(1)
    if path.stat().st_size == 0:
        print(f"ERROR: Input file is empty [{label}]: {path}", file=sys.stderr)
        sys.exit(1)


def trim_start(source_dur: float, clip_dur: float, pct: float) -> float:
    ideal     = source_dur * pct
    max_start = max(0.0, source_dur - clip_dur)
    return min(ideal, max_start)


# ─────────────────────────────────────────────────────────────────────────────
# Per-clip processing & Concat + mux + caption burn-in
# ─────────────────────────────────────────────────────────────────────────────

def process_clip(
    source: Path,
    out_path: Path,
    source_dur: float,
    target_dur: float = CLIP_DURATION,
) -> None:
    ss = trim_start(source_dur, target_dur, TRIM_START_PCT)

    vf = (
        f"trim=duration={target_dur:.3f},setpts=PTS-STARTPTS,"
        f"scale={OUT_W}:{OUT_H}:force_original_aspect_ratio=increase,"
        f"crop={OUT_W}:{OUT_H},"
        f"{EQ_FILTER},"
        f"fps=30"
    )

    cmd = [
        FFMPEG, "-y",
        "-ss", f"{ss:.3f}",
        "-i", str(source),
        "-t", f"{target_dur:.3f}",
        "-vf", vf,
        "-an",
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "20",
        "-pix_fmt", "yuv420p",
        str(out_path),
    ]
    run(cmd, f"process {source.name}")


def concat_segments(
    segment_paths: list[Path],
    audio_path: Path,
    captions_path: Path | None,
    output_path: Path,
) -> None:
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, encoding="utf-8"
    ) as f:
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
            str(concat_tmp),
        ], "concat")

        if captions_path and captions_path.exists():
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
                "-crf", "20",
                "-c:a", "aac",
                "-b:a", "192k",
                "-pix_fmt", "yuv420p",
                str(output_path),
            ]
        else:
            cmd = [
                FFMPEG, "-y",
                "-i", str(concat_tmp),
                "-i", str(audio_path),
                "-map", "0:v",
                "-map", "1:a",
                "-c:v", "copy",
                "-c:a", "aac",
                "-b:a", "192k",
                str(output_path),
            ]
        run(cmd, "mux + captions")

        concat_tmp.unlink(missing_ok=True)

    finally:
        os.unlink(concat_file)


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Render the final 1080x1920 video from b-roll, audio, and captions."
    )
    parser.add_argument(
        "--output", type=Path, default=None,
        help="Output MP4 path",
    )
    parser.add_argument(
        "--no-captions", action="store_true",
        help="Skip subtitle burn-in",
    )
    parser.add_argument(
        "--manifest", type=Path, default=MANIFEST_PATH,
        help="Path to broll_manifest.json",
    )
    parser.add_argument(
        "--script", type=Path, default=SCRIPT_PATH,
        help="Path to script.json",
    )
    parser.add_argument(
        "--audio", type=Path, default=AUDIO_PATH,
        help="Path to audio.mp3",
    )
    parser.add_argument(
        "--captions", type=Path, default=CAPTIONS_PATH,
        help="Path to captions.ass",
    )
    args = parser.parse_args()

    output_path = args.output if args.output else build_output_path(args.script)

    check_input(args.manifest, "broll_manifest.json")
    check_input(args.audio,    "audio.mp3")
    if not args.no_captions:
        check_input(args.captions, "captions.ass")

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    clips    = manifest.get("clips", [])
    if not clips:
        print("ERROR: broll_manifest.json contains no clips.", file=sys.stderr)
        sys.exit(1)

    print(f"Renderer — {len(clips)} clips  ->  {output_path.name}")
    print(f"  Output  : {OUT_W}x{OUT_H}")
    print(f"  Trim    : starting at {int(TRIM_START_PCT*100)}% into each source clip")
    print(f"  Captions: {'yes' if not args.no_captions else 'no'}")

    audio_dur = get_clip_duration(args.audio)
    assign_beat_clip_durations(clips, args.script, args.captions, audio_dur)
    verify_beat_alignment(clips, args.script, args.captions, audio_dur)

    for clip in clips:
        src = BASE_DIR / clip["local_path"]
        check_input(src, clip["local_path"])

    segment_dir   = BASE_DIR / "broll" / "_segments"
    segment_dir.mkdir(parents=True, exist_ok=True)
    segment_paths = []

    for i, clip in enumerate(clips, 1):
        src        = BASE_DIR / clip["local_path"]
        seg_out    = segment_dir / f"seg{i:02d}.mp4"
        target_dur = float(clip.get("target_duration", CLIP_DURATION))

        src_dur  = get_clip_duration(src)
        if src_dur < target_dur:
            print(
                f"  WARN: {src.name} is only {src_dur:.1f}s (need {target_dur:.1f}s) — using ss=0",
                file=sys.stderr,
            )

        ss = trim_start(src_dur, target_dur, TRIM_START_PCT)
        print(f"  [{i}/{len(clips)}] {src.name}  [{clip.get('beat', 'shot')}]  "
              f"{clip['resolution']}  {src_dur:.1f}s  "
              f"-> trim to {target_dur:.2f}s from {ss:.1f}s")

        process_clip(src, seg_out, src_dur, target_dur)
        segment_paths.append(seg_out)

    print("\nConcatenating segments + muxing audio...")
    captions = None if args.no_captions else args.captions
    concat_segments(segment_paths, args.audio, captions, output_path)

    if not output_path.exists() or output_path.stat().st_size == 0:
        print(f"ERROR: Output file missing or empty: {output_path}", file=sys.stderr)
        sys.exit(1)

    size_mb = output_path.stat().st_size // (1024 * 1024)
    print(f"\nDone.  {size_mb} MB")
    print(f"  Saved to: {output_path}")


if __name__ == "__main__":
    main()
