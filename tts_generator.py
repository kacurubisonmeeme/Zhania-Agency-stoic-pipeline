"""
tts_generator.py — Module 3 of the stoic shorts pipeline

Reads script.json (produced by script_generator.py or any hand-written sample),
synthesises speech from the full_text field using edge-tts (free, no API key),
applies FFmpeg audio post-processing (bass boost + soft-clipping saturation),
adds +1.2s trailing silence cushion so the speaker's final sentence is never cut off,
mixes background music with ducking and a smooth fade-out,
and writes audio.mp3 and audio_meta.json.

Usage:
    python tts_generator.py                              # default voice + post-processing
    python tts_generator.py --no-process                 # raw edge-tts audio for A/B testing
    python tts_generator.py --voice en-US-ChristopherNeural
    python tts_generator.py --script path/to/script.json

Requires:
    pip install edge-tts mutagen imageio-ffmpeg
"""

import argparse
import asyncio
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import edge_tts
from mutagen.mp3 import MP3

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR           = Path(__file__).parent
DEFAULT_SCRIPT     = BASE_DIR / "script.json"
OUTPUT_AUDIO       = BASE_DIR / "audio.mp3"
OUTPUT_META        = BASE_DIR / "audio_meta.json"

# ── Voice selection ───────────────────────────────────────────────────────────
DEFAULT_VOICE = "en-US-ChristopherNeural"

# ── Duration target from spec ─────────────────────────────────────────────────
DURATION_MIN = 38.0   # seconds
DURATION_MAX = 48.0   # seconds

# ── Trailing silence cushion ──────────────────────────────────────────────────
# Prevents video cut-off before the speaker finishes speaking the last sentence
TRAILING_SILENCE_SEC = 1.2

# ── Speaking rate & pitch ─────────────────────────────────────────────────────
SPEAKING_RATE = "-10%"
PITCH         = "-3Hz"

# ── Audio Post-Processing (FFmpeg Filters) ──────────────────────────────────
ENABLE_POST_PROCESSING = True

BASS_BOOST_GAIN_DB     = 3.5    # +3.5 dB gain boost
BASS_BOOST_FREQ_HZ     = 140.0  # Cutoff frequency in Hz

SATURATION_TYPE        = "tanh"
SATURATION_THRESHOLD   = 0.94
SATURATION_PARAM       = 1.1

# ── Background Music Layer ──────────────────────────────────────────────────
ENABLE_BACKGROUND_MUSIC = True
MUSIC_DIR               = BASE_DIR / "music"
MUSIC_GAIN_DB           = "-2dB"
MUSIC_FADE_OUT_SEC      = 1.5


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def get_ffmpeg_cmd() -> str:
    try:
        import imageio_ffmpeg as _iff
        _ffdir = os.path.dirname(_iff.get_ffmpeg_exe())
        _ffexe = os.path.join(_ffdir, "ffmpeg.exe")
        if not os.path.exists(_ffexe):
            shutil.copy2(_iff.get_ffmpeg_exe(), _ffexe)
        if _ffdir not in os.environ.get("PATH", ""):
            os.environ["PATH"] = _ffdir + os.pathsep + os.environ.get("PATH", "")
        return _ffexe
    except ImportError:
        return "ffmpeg"


def load_script(path: Path) -> dict:
    if not path.exists():
        print(f"ERROR: File not found: {path}", file=sys.stderr)
        sys.exit(1)
    with open(path, encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError as exc:
            print(f"ERROR: {path} is not valid JSON — {exc}", file=sys.stderr)
            sys.exit(1)


def measure_duration(mp3_path: Path) -> float:
    audio = MP3(str(mp3_path))
    return audio.info.length


async def synthesise(text: str, voice: str, output_path: Path) -> None:
    communicate = edge_tts.Communicate(text, voice, rate=SPEAKING_RATE, pitch=PITCH)
    await communicate.save(str(output_path))


def process_audio(input_path: Path, output_path: Path) -> dict:
    ffmpeg_exe = get_ffmpeg_cmd()

    bass_filter = f"bass=g={BASS_BOOST_GAIN_DB}:f={BASS_BOOST_FREQ_HZ}"
    sat_filter = f"asoftclip=type={SATURATION_TYPE}:threshold={SATURATION_THRESHOLD}:param={SATURATION_PARAM}"
    filter_chain = f"{bass_filter},{sat_filter}"

    cmd = [
        ffmpeg_exe, "-y",
        "-i", str(input_path),
        "-af", filter_chain,
        "-c:a", "libmp3lame",
        "-q:a", "2",
        str(output_path),
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print("ERROR: FFmpeg audio post-processing failed.", file=sys.stderr)
        sys.exit(1)

    return {
        "bass_boost": {
            "gain_db": BASS_BOOST_GAIN_DB,
            "frequency_hz": BASS_BOOST_FREQ_HZ,
            "filter": bass_filter,
        },
        "saturation": {
            "type": SATURATION_TYPE,
            "threshold": SATURATION_THRESHOLD,
            "param": SATURATION_PARAM,
            "filter": sat_filter,
        },
        "filter_chain": filter_chain,
    }


def select_music_track(theme: str) -> tuple[Path | None, str, str, dict]:
    keywords_path = MUSIC_DIR / "music_keywords.json"
    mapping = {}
    if keywords_path.exists():
        try:
            with open(keywords_path, encoding="utf-8") as f:
                mapping = json.load(f)
        except Exception:
            pass

    theme_info = mapping.get(theme.lower(), {})
    track_name = theme_info.get("track")
    mood = theme_info.get("mood", "ambient background")

    attr_info = {
        "title": theme_info.get("title", "Unknown"),
        "artist": theme_info.get("artist", "Unknown"),
        "license": theme_info.get("license", "CC-BY"),
        "attribution_required": theme_info.get("attribution_required", True),
        "attribution_text": theme_info.get("attribution_text", "")
    }

    if track_name and (MUSIC_DIR / track_name).exists():
        return MUSIC_DIR / track_name, mood, f"local_library ({track_name})", attr_info

    mp3_files = list(MUSIC_DIR.glob("*.mp3"))
    if mp3_files:
        return mp3_files[0], "generic ambient fallback", f"local_library ({mp3_files[0].name})", attr_info

    return None, "none", "none", attr_info


def mix_voice_and_music(voice_path: Path, music_path: Path, output_path: Path, total_target_dur: float) -> dict:
    """
    Mix voice audio (voice_path) with background music (music_path).
    Pads voice with trailing silence to total_target_dur, applies sidechain ducking,
    and fades music out smoothly over the final 1.5s.
    """
    ffmpeg_exe = get_ffmpeg_cmd()
    fade_start = max(0.0, total_target_dur - MUSIC_FADE_OUT_SEC)
    total_dur_r = round(total_target_dur, 3)
    fade_start_r = round(fade_start, 3)

    # Filter graph:
    # 1. Pad voice audio with silence at end to total_target_dur [v_padded]
    # 2. Loop music & trim to total_target_dur [m_loop]
    # 3. Apply volume + sidechain compression triggered by voice
    # 4. Mix voice and ducked music using amix
    filter_complex = (
        f"[0:a]apad=whole_dur={total_dur_r}[v_padded]; "
        f"[1:a]aloop=loop=-1:size=2e+09,atrim=0:{total_dur_r}[m_loop]; "
        f"[m_loop]dynaudnorm=f=150:g=15:m=12.0,volume={MUSIC_GAIN_DB}[m_vol]; "
        f"[m_vol][v_padded]sidechaincompress=threshold=0.05:ratio=20:attack=15:release=700[m_duck]; "
        f"[m_duck]volume=-4dB,afade=t=out:st={fade_start_r}:d={MUSIC_FADE_OUT_SEC}[m_fade]; "
        f"[v_padded][m_fade]amix=inputs=2:weights=1 1:normalize=0:duration=first[out]"
    )

    cmd = [
        ffmpeg_exe, "-y",
        "-i", str(voice_path),
        "-i", str(music_path),
        "-filter_complex", filter_complex,
        "-map", "[out]",
        "-c:a", "libmp3lame",
        "-q:a", "2",
        str(output_path),
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        fallback_filter = (
            f"[0:a]apad=whole_dur={total_dur_r}[v_padded]; "
            f"[1:a]aloop=loop=-1:size=2e+09,atrim=0:{total_dur_r},volume={MUSIC_GAIN_DB},"
            f"afade=t=out:st={fade_start_r}:d={MUSIC_FADE_OUT_SEC}[m]; "
            f"[v_padded][m]amix=inputs=2:duration=first[out]"
        )
        cmd_fb = [
            ffmpeg_exe, "-y",
            "-i", str(voice_path),
            "-i", str(music_path),
            "-filter_complex", fallback_filter,
            "-map", "[out]",
            "-c:a", "libmp3lame",
            "-q:a", "2",
            str(output_path),
        ]
        result_fb = subprocess.run(cmd_fb, capture_output=True, text=True)
        if result_fb.returncode != 0:
            print("ERROR: Music mixing failed, keeping voice-only.", file=sys.stderr)
            shutil.copy2(voice_path, output_path)
            return {"enabled": False, "error": result_fb.stderr[-500:]}

        return {
            "enabled": True,
            "method": "fixed_volume_fallback",
            "volume_db": MUSIC_GAIN_DB,
            "fade_out_seconds": MUSIC_FADE_OUT_SEC,
            "filter_complex": fallback_filter,
        }

    return {
        "enabled": True,
        "method": "sidechaincompress_ducking",
        "volume_db": MUSIC_GAIN_DB,
        "sidechain_params": "threshold=0.05:ratio=20:attack=15:release=700",
        "post_compression_volume_db": "-4dB",
        "fade_out_seconds": MUSIC_FADE_OUT_SEC,
        "filter_complex": filter_complex,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Synthesise speech from script.json using edge-tts with audio post-processing and background music."
    )
    parser.add_argument(
        "--script",
        type=Path,
        default=DEFAULT_SCRIPT,
        help="Path to script.json (default: script.json)",
    )
    parser.add_argument(
        "--voice",
        type=str,
        default=DEFAULT_VOICE,
        help=f"edge-tts voice name (default: {DEFAULT_VOICE})",
    )
    parser.add_argument(
        "--no-process",
        action="store_true",
        help="Disable FFmpeg audio post-processing",
    )
    parser.add_argument(
        "--no-music",
        action="store_true",
        help="Disable background music mixing",
    )
    args = parser.parse_args()

    script = load_script(args.script)

    full_text = script.get("full_text", "").strip()
    if not full_text:
        print("ERROR: script.json has an empty 'full_text' field.", file=sys.stderr)
        sys.exit(1)

    quote_id = script.get("quote_id", "unknown")
    theme = script.get("theme", "control")
    should_process = ENABLE_POST_PROCESSING and not args.no_process
    should_add_music = ENABLE_BACKGROUND_MUSIC and not args.no_music

    print(f"-> Synthesising audio for: {quote_id}")
    print(f"  Voice     : {args.voice}")
    print(f"  Processed : {'yes (FFmpeg filters)' if should_process else 'no (raw edge-tts)'}")
    print(f"  Music     : {'yes (ducked background)' if should_add_music else 'no (voice only)'}")
    print(f"  Text      : {full_text[:70]}{'...' if len(full_text) > 70 else ''}")

    raw_audio_path = BASE_DIR / "audio_raw_temp.mp3"
    voice_processed_path = BASE_DIR / "voice_processed_temp.mp3"
    try:
        asyncio.run(synthesise(full_text, args.voice, raw_audio_path))

        if not raw_audio_path.exists() or raw_audio_path.stat().st_size == 0:
            print("ERROR: edge-tts returned empty audio.", file=sys.stderr)
            sys.exit(1)

        if should_process:
            print("-> Applying FFmpeg audio filters (bass boost + soft clipping)...")
            filter_meta = process_audio(raw_audio_path, voice_processed_path)
        else:
            shutil.copy2(raw_audio_path, voice_processed_path)
            filter_meta = None

        voice_speech_dur = measure_duration(voice_processed_path)
        total_audio_target_dur = voice_speech_dur + TRAILING_SILENCE_SEC
        music_meta = None

        if should_add_music:
            track_path, mood, source_info, attr_info = select_music_track(theme)
            if track_path and track_path.exists():
                print(f"-> Mixing background music track: {track_path.name} (mood: '{mood}')...")
                mix_info = mix_voice_and_music(voice_processed_path, track_path, OUTPUT_AUDIO, total_audio_target_dur)
                music_meta = {
                    "enabled": True,
                    "theme": theme,
                    "mood": mood,
                    "track_file": str(track_path.relative_to(BASE_DIR)),
                    "source": source_info,
                    "attribution": attr_info,
                    "mix_details": mix_info,
                }
            else:
                print("WARN: No background music track found, outputting padded voice-only.", file=sys.stderr)
                # Pad voice with silence up to total_audio_target_dur
                ffmpeg_exe = get_ffmpeg_cmd()
                cmd_pad = [
                    ffmpeg_exe, "-y",
                    "-i", str(voice_processed_path),
                    "-af", f"apad=whole_dur={total_audio_target_dur:.3f}",
                    "-c:a", "libmp3lame", "-q:a", "2",
                    str(OUTPUT_AUDIO)
                ]
                subprocess.run(cmd_pad, capture_output=True)
                music_meta = {"enabled": False, "reason": "no_track_found"}
        else:
            ffmpeg_exe = get_ffmpeg_cmd()
            cmd_pad = [
                ffmpeg_exe, "-y",
                "-i", str(voice_processed_path),
                "-af", f"apad=whole_dur={total_audio_target_dur:.3f}",
                "-c:a", "libmp3lame", "-q:a", "2",
                str(OUTPUT_AUDIO)
            ]
            subprocess.run(cmd_pad, capture_output=True)
            music_meta = {"enabled": False, "reason": "disabled_by_user" if args.no_music else "disabled_in_config"}

    finally:
        for temp_p in (raw_audio_path, voice_processed_path):
            if temp_p.exists():
                temp_p.unlink()

    duration = measure_duration(OUTPUT_AUDIO)

    meta = {
        "audio_file":       OUTPUT_AUDIO.name,
        "duration_seconds": round(duration, 2),
        "speech_duration_seconds": round(voice_speech_dur, 2),
        "trailing_silence_seconds": TRAILING_SILENCE_SEC,
        "voice_used":       args.voice,
        "processed":        should_process,
        "audio_processing": filter_meta if should_process else None,
        "background_music": music_meta,
    }
    with open(OUTPUT_META, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)

    status = "[OK]"
    print(f"\n{status} audio.mp3 written ({duration:.1f}s — speech {voice_speech_dur:.1f}s + {TRAILING_SILENCE_SEC}s silence padding)")
    print(f"  audio_meta.json  -> {OUTPUT_META}")


if __name__ == "__main__":
    main()
