"""
caption_generator.py — Module 4 of the stoic shorts pipeline

Reads audio.mp3 (produced by tts_generator.py or any sample .mp3),
transcribes it with local Whisper to get word-level timestamps, and writes
captions.srt and captions.ass synced to the actual speech.

ASS Subtitles Feature:
- Single-word active highlighting: The subtitle line defaults to WHITE text.
- Only the single word being spoken at that exact moment turns YELLOW.
- Unspoken and previously spoken words remain WHITE.

Optionally reads script.json to cross-check the caption word count.

Usage:
    python caption_generator.py                          # reads audio.mp3 in this folder
    python caption_generator.py --audio path/to/file.mp3
    python caption_generator.py --audio file.mp3 --script path/to/script.json
    python caption_generator.py --model small            # override Whisper model
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

# ── Ensure ffmpeg is on PATH using imageio-ffmpeg's bundled binary ────────────
try:
    import imageio_ffmpeg as _iff
    _ffdir = os.path.dirname(_iff.get_ffmpeg_exe())
    _ffexe = os.path.join(_ffdir, "ffmpeg.exe")
    if not os.path.exists(_ffexe):
        import shutil as _shutil
        _shutil.copy2(_iff.get_ffmpeg_exe(), _ffexe)
    if _ffdir not in os.environ.get("PATH", ""):
        os.environ["PATH"] = _ffdir + os.pathsep + os.environ.get("PATH", "")
except ImportError:
    pass

import whisper

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR        = Path(__file__).parent
DEFAULT_AUDIO   = BASE_DIR / "audio.mp3"
DEFAULT_SCRIPT  = BASE_DIR / "script.json"
OUTPUT_SRT      = BASE_DIR / "captions.srt"
OUTPUT_WORDS    = BASE_DIR / "captions_words.json"

# ── Whisper settings ──────────────────────────────────────────────────────────
DEFAULT_MODEL   = "base"

# ── Confidence thresholds ─────────────────────────────────────────────────────
WORD_LOW_PROB   = 0.6
NO_SPEECH_THRESH = 0.3

# ── Caption grouping ──────────────────────────────────────────────────────────
WORDS_PER_LINE  = 6

# ── Word-count tolerance for cross-check (±N words) ──────────────────────────
WORDCOUNT_TOLERANCE = 2


# ─────────────────────────────────────────────────────────────────────────────
# SRT / ASS helpers
# ─────────────────────────────────────────────────────────────────────────────

def ms_to_srt_time(seconds: float) -> str:
    """Convert a float seconds value to SRT timestamp format HH:MM:SS,mmm."""
    total_ms  = int(round(seconds * 1000))
    ms        = total_ms % 1000
    total_sec = total_ms // 1000
    secs      = total_sec % 60
    total_min = total_sec // 60
    mins      = total_min % 60
    hours     = total_min // 60
    return f"{hours:02d}:{mins:02d}:{secs:02d},{ms:03d}"


def ms_to_ass_time(seconds: float) -> str:
    """Convert seconds to ASS timestamp format H:MM:SS.cc (centiseconds)."""
    cs        = int(round(seconds * 100))
    centis    = cs % 100
    total_sec = cs // 100
    secs      = total_sec % 60
    total_min = total_sec // 60
    mins      = total_min % 60
    hours     = total_min // 60
    return f"{hours}:{mins:02d}:{secs:02d}.{centis:02d}"


def normalize_word_punctuation(
    words: list[dict],
    script_words_raw: list[str],
) -> list[dict]:
    normalised = []
    for i, w in enumerate(words):
        if i < len(script_words_raw):
            script_raw  = script_words_raw[i]
            script_punc = re.sub(r"[A-Za-z0-9']+", "", script_raw)

            whisper_raw  = w["word"]
            leading_ws   = len(whisper_raw) - len(whisper_raw.lstrip())
            core         = whisper_raw.strip()
            core_alpha   = re.sub(r"[^A-Za-z0-9'\-]+$", "", core)
            rebuilt      = " " * leading_ws + core_alpha + script_punc

            if rebuilt != whisper_raw:
                w = dict(w)
                w["word"] = rebuilt
        normalised.append(w)
    return normalised


def group_words_into_lines(words: list[dict], words_per_line: int) -> list[dict]:
    lines = []
    for i in range(0, len(words), words_per_line):
        chunk = words[i : i + words_per_line]
        text  = " ".join(w["word"].strip() for w in chunk)
        lines.append({
            "text":  text,
            "start": chunk[0]["start"],
            "end":   chunk[-1]["end"],
        })
    return lines


def write_srt(lines: list[dict], output_path: Path) -> None:
    with open(output_path, "w", encoding="utf-8") as f:
        for idx, line in enumerate(lines, start=1):
            f.write(f"{idx}\n")
            f.write(f"{ms_to_srt_time(line['start'])} --> {ms_to_srt_time(line['end'])}\n")
            f.write(f"{line['text']}\n\n")


def write_ass(words: list[dict], output_path: Path) -> None:
    """
    Write an ASS subtitle file with discrete per-word active highlighting.

    - Every word in the 6-word display line is WHITE (&H00FFFFFF&).
    - ONLY the word currently being spoken between [word.start, word.end] turns YELLOW (&H0000FFFF&).
    - Before and after a word is spoken, it remains/returns to clean WHITE.
    """
    groups = []
    for i in range(0, len(words), WORDS_PER_LINE):
        groups.append(words[i : i + WORDS_PER_LINE])

    ass_header = """\
[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,117,&H00FFFFFF,&H0000FFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,3,1,5,20,20,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    dialogue_lines = []

    for group in groups:
        if not group:
            continue

        group_start = float(group[0]["start"])
        group_end   = float(group[-1]["end"])

        for j, active_w in enumerate(group):
            w_start = float(active_w["start"])
            w_end   = float(active_w["end"])

            # Check for gap before active word
            if j == 0:
                gap_start = group_start
            else:
                gap_start = float(group[j - 1]["end"])

            if w_start - gap_start > 0.01:
                # Emit unhighlighted (all white) line during gap
                white_text = " ".join(w["word"].strip() for w in group)
                dialogue_lines.append(
                    f"Dialogue: 0,{ms_to_ass_time(gap_start)},{ms_to_ass_time(w_start)},Default,,0,0,0,,{white_text}"
                )

            # Build line with ONLY active_w highlighted in Yellow (&H0000FFFF&)
            parts = []
            for idx, w in enumerate(group):
                text_clean = w["word"].strip()
                if idx == j:
                    parts.append(f"{{\\c&H0000FFFF&}}{text_clean}{{\\c&H00FFFFFF&}}")
                else:
                    parts.append(text_clean)

            active_line_text = " ".join(parts)
            dialogue_lines.append(
                f"Dialogue: 0,{ms_to_ass_time(w_start)},{ms_to_ass_time(w_end)},Default,,0,0,0,,{active_line_text}"
            )

        # Gap after the last word in group before next group/end
        last_w_end = float(group[-1]["end"])
        if group_end - last_w_end > 0.01:
            white_text = " ".join(w["word"].strip() for w in group)
            dialogue_lines.append(
                f"Dialogue: 0,{ms_to_ass_time(last_w_end)},{ms_to_ass_time(group_end)},Default,,0,0,0,,{white_text}"
            )

    with open(output_path, "w", encoding="utf-8-sig") as f:
        f.write(ass_header)
        f.write("\n".join(dialogue_lines) + "\n")


# ─────────────────────────────────────────────────────────────────────────────
# Confidence checks
# ─────────────────────────────────────────────────────────────────────────────

def check_confidence(segments: list[dict]) -> list[str]:
    warnings = []
    for seg in segments:
        seg_text = seg.get("text", "").strip()
        nsp = seg.get("no_speech_prob", 0.0)
        if nsp > NO_SPEECH_THRESH:
            warnings.append(
                f"WARN: low-confidence segment (no_speech_prob={nsp:.2f} > {NO_SPEECH_THRESH}) "
                f"at {seg['start']:.1f}s–{seg['end']:.1f}s: \"{seg_text[:60]}\""
            )

        for w in seg.get("words", []):
            if w.get("_corrected"):
                continue
            prob = float(w.get("probability", 1.0))
            if prob < WORD_LOW_PROB:
                warnings.append(
                    f"WARN: low-confidence word (prob={prob:.2f}) "
                    f"at {float(w['start']):.1f}s: \"{w['word'].strip()}\""
                )
    return warnings


# ─────────────────────────────────────────────────────────────────────────────
# Word-count cross-check & Script-guided correction pass
# ─────────────────────────────────────────────────────────────────────────────

def caption_word_count(lines: list[dict]) -> int:
    return sum(len(line["text"].split()) for line in lines)


def script_word_count(script_path: Path) -> int | None:
    if not script_path.exists():
        return None
    try:
        data = json.loads(script_path.read_text(encoding="utf-8"))
        return data.get("word_count")
    except (json.JSONDecodeError, OSError):
        return None


def load_script_words(script_path: Path) -> tuple[list[str], list[str]] | None:
    if not script_path.exists():
        return None
    try:
        data = json.loads(script_path.read_text(encoding="utf-8"))
        full_text = data.get("full_text", "").strip()
        if not full_text:
            return None
        raw_words     = full_text.split()
        stripped_words = [re.sub(r"[^\w']", "", w) for w in raw_words]
        return stripped_words, raw_words
    except (json.JSONDecodeError, OSError):
        return None


def _edit_distance(a: str, b: str) -> int:
    a, b = a.lower(), b.lower()
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        curr = [i]
        for j, cb in enumerate(b, 1):
            curr.append(min(prev[j] + 1, curr[j - 1] + 1,
                            prev[j - 1] + (0 if ca == cb else 1)))
        prev = curr
    return prev[-1]


def correct_words_against_script(
    all_words: list[dict],
    script_words: list[str],
) -> tuple[list[dict], list[str]]:
    corrections     = []
    corrected_words = []

    for i, w in enumerate(all_words):
        if i < len(script_words):
            whisper_text = re.sub(r"[^\w']", "", w["word"]).lower()
            script_text  = script_words[i].lower()

            if whisper_text != script_text:
                dist     = _edit_distance(whisper_text, script_text)
                max_dist = max(2, len(script_text) // 2)

                if dist <= max_dist:
                    original  = w["word"]
                    corrected = re.sub(r"[A-Za-z']+", script_words[i],
                                       original, count=1)
                    prob = float(w.get("probability", 1.0))
                    corrections.append(
                        f"  corrected [{i}] \"{original.strip()}\" -> \"{corrected.strip()}\" "
                        f"(prob={prob:.2f}, edit_dist={dist})"
                    )
                    w = dict(w)
                    w["word"]       = corrected
                    w["_corrected"] = True

        corrected_words.append(w)

    return corrected_words, corrections


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Transcribe audio.mp3 with Whisper and write captions.srt and captions.ass."
    )
    parser.add_argument(
        "--audio",
        type=Path,
        default=DEFAULT_AUDIO,
        help="Path to the .mp3 file to transcribe (default: audio.mp3)",
    )
    parser.add_argument(
        "--script",
        type=Path,
        default=DEFAULT_SCRIPT,
        help="Path to script.json for word-count cross-check (optional)",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=DEFAULT_MODEL,
        choices=["tiny", "base", "small", "medium", "large"],
        help=f"Whisper model size (default: {DEFAULT_MODEL})",
    )
    args = parser.parse_args()

    if not args.audio.exists():
        print(f"ERROR: Audio file not found: {args.audio}", file=sys.stderr)
        sys.exit(1)

    print(f"-> Loading Whisper model '{args.model}'...")
    model = whisper.load_model(args.model)

    print(f"-> Transcribing: {args.audio.name}")
    result = model.transcribe(
        str(args.audio),
        word_timestamps=True,
        language="en",
        verbose=False,
    )

    segments: list[dict] = result["segments"]
    if not segments:
        print("ERROR: Whisper returned no segments.", file=sys.stderr)
        sys.exit(1)

    all_words = [w for seg in segments for w in seg.get("words", [])]
    if not all_words:
        print("ERROR: Whisper returned no word-level timestamps.", file=sys.stderr)
        sys.exit(1)

    script_data = load_script_words(args.script)
    if script_data:
        script_words, script_words_raw = script_data
        all_words, correction_log = correct_words_against_script(all_words, script_words)
        if correction_log:
            print(f"-> Applied {len(correction_log)} script-guided correction(s):")
            for entry in correction_log:
                print(entry)
        all_words = normalize_word_punctuation(all_words, script_words_raw)

    word_iter = iter(all_words)
    for seg in segments:
        seg_words = seg.get("words", [])
        for i in range(len(seg_words)):
            seg_words[i] = next(word_iter)

    conf_warnings = check_confidence(segments)
    for w in conf_warnings:
        print(w, file=sys.stderr)

    caption_lines = group_words_into_lines(all_words, WORDS_PER_LINE)
    cap_wc = caption_word_count(caption_lines)
    ref_wc = script_word_count(args.script)

    if ref_wc is not None:
        diff = abs(cap_wc - ref_wc)
        if diff > WORDCOUNT_TOLERANCE:
            print(
                f"WARN: caption word count ({cap_wc}) differs from script.json word_count ({ref_wc}) by {diff} words.",
                file=sys.stderr,
            )

    # ── Write SRT, ASS, and JSON ─────────────────────────────────────────────
    write_srt(caption_lines, OUTPUT_SRT)
    output_ass = OUTPUT_SRT.with_suffix(".ass")
    write_ass(all_words, output_ass)

    words_json = [
        {
            "word": w["word"].strip(),
            "start": round(float(w["start"]), 3),
            "end": round(float(w["end"]), 3),
        }
        for w in all_words
    ]
    OUTPUT_WORDS.write_text(json.dumps(words_json, indent=2), encoding="utf-8")

    status = "[WARN]" if conf_warnings else "[OK]"
    print(f"\n{status} captions written ({len(caption_lines)} lines, {cap_wc} words)")
    print(f"  captions.srt   — plain subtitles")
    print(f"  captions.ass   — single-word active yellow highlighting")
    print(f"  captions_words.json — word timestamps")


if __name__ == "__main__":
    main()
