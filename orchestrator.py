"""
orchestrator.py — runs the full stoic shorts pipeline end-to-end with telemetry tracking.

Calls modules 1-6 in sequence as subprocesses:
    quote_picker → script_generator → tts_generator →
    caption_generator → broll_matcher → video_renderer

Each module writes its output file(s) to this folder; the next module
reads them.  If any module exits with a non-zero code, the pipeline
stops immediately and reports which module failed.

Usage:
    python orchestrator.py                  # random theme
    python orchestrator.py --theme fear     # specific theme
    python orchestrator.py --no-download    # skip b-roll downloads (dry run)
"""

import argparse
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

BASE_DIR = Path(__file__).parent
TELEMETRY_FILE = BASE_DIR / "telemetry_run.json"


# ── Peak Memory Monitor ───────────────────────────────────────────────────────

class MemoryMonitor:
    def __init__(self, interval: float = 0.1):
        self.interval = interval
        self.peak_rss_bytes = 0
        self._stop_event = threading.Event()
        self._thread = None

    def _sample_loop(self):
        parent_pid = os.getpid()
        while not self._stop_event.is_set():
            if HAS_PSUTIL:
                try:
                    parent = psutil.Process(parent_pid)
                    total_rss = parent.memory_info().rss
                    for child in parent.children(recursive=True):
                        try:
                            total_rss += child.memory_info().rss
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            pass
                    if total_rss > self.peak_rss_bytes:
                        self.peak_rss_bytes = total_rss
                except Exception:
                    pass
            time.sleep(self.interval)

    def start(self):
        self._thread = threading.Thread(target=self._sample_loop, daemon=True)
        self._thread.start()

    def stop(self) -> float:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=1.0)
        return self.peak_rss_bytes / (1024 * 1024)


# ── Pipeline step definitions ─────────────────────────────────────────────────

def _quote_picker_args(args: argparse.Namespace) -> list[str]:
    return ["--theme", args.theme] if args.theme else []

def _broll_matcher_args(args: argparse.Namespace) -> list[str]:
    return ["--no-download"] if args.no_download else []

def _video_renderer_args(args: argparse.Namespace) -> list[str]:
    return ["--no-captions"] if getattr(args, "no_captions", False) else []

PIPELINE: list[tuple[str, str, object]] = [
    ("quote_picker",      "quote_picker.py",      _quote_picker_args),
    ("script_generator",  "script_generator.py",  None),
    ("tts_generator",     "tts_generator.py",      None),
    ("caption_generator", "caption_generator.py",  None),
    ("broll_matcher",     "broll_matcher.py",       _broll_matcher_args),
    ("video_renderer",    "video_renderer.py",      _video_renderer_args),
]


# ─────────────────────────────────────────────────────────────────────────────
# Runner
# ─────────────────────────────────────────────────────────────────────────────

def run_module(
    name: str,
    script: str,
    extra_args: list[str],
) -> tuple[bool, str]:
    cmd = [sys.executable, str(BASE_DIR / script)] + extra_args
    print(f"\n{'-' * 60}")
    print(f"  [{name}]")
    print(f"{'-' * 60}")

    result = subprocess.run(
        cmd,
        cwd=str(BASE_DIR),
        capture_output=False,
    )

    if result.returncode != 0:
        return False, f"exited with code {result.returncode}"

    return True, ""


# ─────────────────────────────────────────────────────────────────────────────
# Summary helpers
# ─────────────────────────────────────────────────────────────────────────────

def load_json_safe(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def count_srt_lines(srt_path: Path) -> int:
    if not srt_path.exists():
        return 0
    text = srt_path.read_text(encoding="utf-8")
    return sum(1 for line in text.splitlines() if line.strip().isdigit())


def print_summary(elapsed: float, peak_ram_mb: float) -> None:
    quote      = load_json_safe(BASE_DIR / "quote.json")
    script     = load_json_safe(BASE_DIR / "script.json")
    audio_meta = load_json_safe(BASE_DIR / "audio_meta.json")
    manifest   = load_json_safe(BASE_DIR / "broll_manifest.json")
    caption_n  = count_srt_lines(BASE_DIR / "captions.srt")

    mins, secs = divmod(int(elapsed), 60)
    runtime    = f"{mins}m {secs}s" if mins else f"{secs}s"

    print(f"\n{'=' * 60}")
    print("  PIPELINE COMPLETE")
    print(f"{'=' * 60}")
    print(f"  Quote      : {quote.get('quote', '?')[:70]}")
    print(f"  Author     : {quote.get('author', '?')}")
    print(f"  Theme      : {quote.get('theme', '?')}")
    print(f"  Word count : {script.get('word_count', '?')} words")
    print(f"  Audio      : {audio_meta.get('duration_seconds', '?')}s  "
          f"({audio_meta.get('voice_used', '?')})")
    print(f"  Captions   : {caption_n} lines  (captions.srt)")
    print(f"  B-roll     : {len(manifest.get('clips', []))} clips  "
          f"({manifest.get('total_duration', '?')}s total)")

    outputs_dir = BASE_DIR / "outputs"
    if outputs_dir.exists():
        mp4s = sorted(outputs_dir.glob("*.mp4"), key=lambda p: p.stat().st_mtime)
        if mp4s:
            latest  = mp4s[-1]
            size_mb = latest.stat().st_size // (1024 * 1024)
            print(f"  Output     : {latest.name}  ({size_mb} MB)")
            print(f"  Saved to   : {latest}")

    print(f"  Run time   : {runtime}")
    print(f"{'=' * 60}\n")

    # ── Telemetry Report ─────────────────────────────────────────────────────
    telemetry = {"api_calls": [], "thumbnail_bytes": 0, "broll_bytes": 0}
    if TELEMETRY_FILE.exists():
        try:
            telemetry = json.loads(TELEMETRY_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass

    api_calls = telemetry.get("api_calls", [])
    total_prompt_tokens     = sum(c.get("prompt_tokens", 0) for c in api_calls)
    total_candidates_tokens = sum(c.get("candidates_tokens", 0) for c in api_calls)
    total_tokens            = sum(c.get("total_tokens", 0) for c in api_calls)

    thumb_bytes = telemetry.get("thumbnail_bytes", 0)
    broll_bytes = telemetry.get("broll_bytes", 0)
    thumb_mb    = thumb_bytes / (1024 * 1024)
    broll_mb    = broll_bytes / (1024 * 1024)
    total_mb    = (thumb_bytes + broll_bytes) / (1024 * 1024)

    print(f"{'=' * 60}")
    print("  TELEMETRY & PERFORMANCE REPORT")
    print(f"{'=' * 60}")
    print(f"  Gemini API Calls : {len(api_calls)} calls made")
    for i, c in enumerate(api_calls, 1):
        print(f"    - Call {i}: [{c.get('module', '?')}] model={c.get('model', '?')}")
        print(f"      Tokens: {c.get('prompt_tokens', 0):,} prompt + {c.get('candidates_tokens', 0):,} candidate = {c.get('total_tokens', 0):,} total")
    print(f"  Total Token Usage: {total_prompt_tokens:,} prompt | {total_candidates_tokens:,} candidate | {total_tokens:,} total tokens")
    print(f"  Downloaded Bytes : {total_mb:.2f} MB ({thumb_bytes:,} B thumbnails [{thumb_mb:.2f} MB] + {broll_bytes:,} B clips [{broll_mb:.2f} MB])")
    print(f"  Peak RAM Usage   : {peak_ram_mb:.1f} MB (sampled via psutil)")
    print(f"  Total Run Time   : {runtime} ({elapsed:.2f}s)")
    print(f"{'=' * 60}\n")


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the full stoic shorts pipeline end-to-end with telemetry."
    )
    parser.add_argument(
        "--theme",
        type=str,
        default=None,
        help="Theme to pass to quote_picker (e.g. fear, anger, control). Omit for random.",
    )
    parser.add_argument(
        "--no-download",
        action="store_true",
        help="Pass --no-download to broll_matcher (skip clip downloads).",
    )
    parser.add_argument(
        "--no-captions",
        action="store_true",
        help="Pass --no-captions to video_renderer (skip subtitle burn-in).",
    )
    args = parser.parse_args()

    # Reset telemetry log for this run
    TELEMETRY_FILE.write_text(
        json.dumps({"api_calls": [], "thumbnail_bytes": 0, "broll_bytes": 0}, indent=2),
        encoding="utf-8"
    )

    print("Stoic Shorts Pipeline")
    if args.theme:
        print(f"Theme: {args.theme}")
    print()

    mem_monitor = MemoryMonitor(interval=0.1)
    mem_monitor.start()

    start = time.time()
    failed_at = None

    for name, script, args_builder in PIPELINE:
        extra = args_builder(args) if args_builder else []
        ok, reason = run_module(name, script, extra)

        if not ok:
            failed_at = name
            mem_monitor.stop()
            print(f"\n{'!' * 60}", file=sys.stderr)
            print(f"  PIPELINE FAILED at [{name}]: {reason}", file=sys.stderr)
            print(f"  Subsequent modules were not run.", file=sys.stderr)
            print(f"{'!' * 60}\n", file=sys.stderr)
            sys.exit(1)

    elapsed = time.time() - start
    peak_ram_mb = mem_monitor.stop()

    print_summary(elapsed, peak_ram_mb)


if __name__ == "__main__":
    main()
