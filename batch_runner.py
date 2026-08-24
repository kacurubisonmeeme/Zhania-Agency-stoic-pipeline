"""
batch_runner.py — Batch execution wrapper for Stoic Shorts Video Pipeline.

Repeatedly runs orchestrator.py across all 8 themes in rotation until quotes or Gemini API quotas are exhausted.

Behavior:
  1. Cycles through all 8 themes (fear, control, mortality, discipline, anger, judgment, adversity, wealth).
  2. Continues into subsequent cycles until a stop condition is met:
     - Stop Condition A: ALL Gemini API keys report quota exhausted.
     - Stop Condition B: A full cycle through all 8 themes completes where every theme reports resetting (one full pass complete).
  3. Logs a running summary after each run.
  4. Recovers from single video failures (moves to next theme unless failure is API quota exhaustion).
  5. Prints a comprehensive summary upon completion.

Usage:
    python batch_runner.py
    python batch_runner.py --no-download
    python batch_runner.py --max-videos 10
"""

import argparse
import csv
import json
import os
import subprocess
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).parent
CSV_PATH = BASE_DIR / "stoic_quotes_database.csv"
USED_PATH = BASE_DIR / "used_quotes.json"
QUOTE_PATH = BASE_DIR / "quote.json"

THEMES = [
    "fear",
    "control",
    "mortality",
    "discipline",
    "anger",
    "judgment",
    "adversity",
    "wealth",
]


def load_quote_database_counts() -> dict[str, int]:
    """Return total number of quotes per theme in CSV."""
    counts = {}
    if CSV_PATH.exists():
        with open(CSV_PATH, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                t = row.get("theme", "").strip()
                if t:
                    counts[t] = counts.get(t, 0) + 1
    return counts


def get_current_quote() -> dict:
    """Load latest quote from quote.json."""
    if QUOTE_PATH.exists():
        try:
            return json.loads(QUOTE_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def is_quota_exhausted_output(output_text: str) -> bool:
    """Check if output contains indications that all Gemini API keys hit daily quota."""
    t = output_text.lower()
    if "all" in t and "gemini api key" in t and "quota" in t:
        return True
    if "hit their daily quota" in t or "all gemini api keys have hit" in t:
        return True
    if "resource_exhausted" in t or "quota exceeded" in t or "quota_exceeded" in t:
        return True
    if "429" in t and ("quota" in t or "rate limit" in t or "resource" in t):
        return True
    return False


def is_theme_reset_output(output_text: str, theme: str) -> bool:
    """Check if output indicates theme quotes reached end of cycle and reset."""
    t = output_text.lower()
    theme_lower = theme.lower()
    return (f"all quotes for theme '{theme_lower}' have been used" in t) or (
        "all quotes for theme" in t and theme_lower in t and "resetting cycle" in t
    )


def run_orchestrator_single(
    theme: str, extra_flags: list[str]
) -> tuple[bool, bool, bool, str]:
    """
    Executes orchestrator.py --theme <theme> [extra_flags].
    Streams output live to terminal while capturing full text.

    Returns:
        (success: bool, quota_exhausted: bool, theme_reset: bool, full_output: str)
    """
    cmd = [sys.executable, str(BASE_DIR / "orchestrator.py"), "--theme", theme] + extra_flags
    captured_lines = []
    quota_exhausted = False
    theme_reset = False

    try:
        process = subprocess.Popen(
            cmd,
            cwd=str(BASE_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )

        for line in iter(process.stdout.readline, ""):
            try:
                sys.stdout.write(line)
                sys.stdout.flush()
            except UnicodeEncodeError:
                sys.stdout.write(line.encode("ascii", "replace").decode("ascii"))
                sys.stdout.flush()
            captured_lines.append(line)

            if is_quota_exhausted_output(line):
                quota_exhausted = True
            if is_theme_reset_output(line, theme):
                theme_reset = True

        process.stdout.close()
        return_code = process.wait()

        full_output = "".join(captured_lines)
        if not quota_exhausted and is_quota_exhausted_output(full_output):
            quota_exhausted = True
        if not theme_reset and is_theme_reset_output(full_output, theme):
            theme_reset = True

        success = (return_code == 0) and not quota_exhausted
        return success, quota_exhausted, theme_reset, full_output

    except Exception as exc:
        err_msg = f"Subprocess execution error for theme {theme}: {exc}\n"
        sys.stderr.write(err_msg)
        return False, False, False, err_msg


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(
        description="Repeatedly run stoic shorts pipeline across themes."
    )
    parser.add_argument(
        "--no-download",
        action="store_true",
        help="Pass --no-download to orchestrator (skip clip downloads).",
    )
    parser.add_argument(
        "--no-captions",
        action="store_true",
        help="Pass --no-captions to orchestrator (skip caption burn-in).",
    )
    parser.add_argument(
        "--max-videos",
        type=int,
        default=None,
        help="Optional maximum number of videos to produce before stopping.",
    )
    args = parser.parse_args()

    extra_flags = []
    if args.no_download:
        extra_flags.append("--no-download")
    if args.no_captions:
        extra_flags.append("--no-captions")

    start_time = time.time()
    videos_produced = 0
    successful_runs = 0
    failed_runs = 0
    cycle_count = 0
    stop_reason = ""

    db_counts = load_quote_database_counts()
    print("=" * 70)
    print("  STOIC SHORTS BATCH RUNNER")
    print("=" * 70)
    print(f"Themes in rotation ({len(THEMES)}): {', '.join(THEMES)}")
    print(f"Quote Database Total: {sum(db_counts.values())} quotes")
    if args.max_videos:
        print(f"Max videos cap set: {args.max_videos}")
    print("=" * 70 + "\n")

    try:
        while not stop_reason:
            cycle_count += 1
            print(f"\n{'=' * 70}")
            print(f"  CYCLE #{cycle_count} — STARTING PASS ACROSS ALL {len(THEMES)} THEMES")
            print(f"{'=' * 70}\n")

            themes_reset_in_cycle = set()

            for idx, theme in enumerate(THEMES, 1):
                if args.max_videos and videos_produced >= args.max_videos:
                    stop_reason = f"Reached specified --max-videos limit ({args.max_videos})"
                    break

                print(f"\n{'-' * 70}")
                print(f"  [Cycle #{cycle_count} | Theme {idx}/{len(THEMES)}] Starting run for '{theme}'")
                print(f"  Current Session Total Videos Produced: {videos_produced}")
                print(f"{'-' * 70}\n")

                success, quota_exhausted, theme_reset, output_log = run_orchestrator_single(
                    theme, extra_flags
                )

                if theme_reset:
                    themes_reset_in_cycle.add(theme)
                    print(f"\n  [INFO] Theme '{theme}' reached end of quote pool (Reset cycle triggered).")

                if quota_exhausted:
                    stop_reason = "Gemini API quota exhausted (All keys hit daily rate limit)"
                    failed_runs += 1
                    print(f"\n  [STOP TRIGGERED] {stop_reason}")
                    break

                if success:
                    videos_produced += 1
                    successful_runs += 1
                    quote_meta = get_current_quote()
                    author = quote_meta.get("author", "Unknown")
                    q_text = quote_meta.get("quote", "N/A")
                    print(f"\n  [SUCCESS] Video #{videos_produced} produced!")
                    print(f"            Theme : {theme}")
                    print(f"            Author: {author}")
                    print(f"            Quote : \"{q_text[:75]}{'...' if len(q_text) > 75 else ''}\"")
                else:
                    failed_runs += 1
                    print(f"\n  [FAILURE] Run failed for theme '{theme}'. Continuing to next theme in batch.")

            if stop_reason:
                break

            # Check if all 8 themes reported reset during this cycle
            if len(themes_reset_in_cycle) == len(THEMES):
                stop_reason = "One full pass complete (every theme reported all quotes used across the cycle)"
                break

    except KeyboardInterrupt:
        stop_reason = "Interrupted by user (KeyboardInterrupt)"
        print("\n\n[NOTICE] Batch run interrupted by user.")

    elapsed = time.time() - start_time
    mins, secs = divmod(int(elapsed), 60)
    runtime_str = f"{mins}m {secs}s" if mins else f"{secs}s"

    print("\n" + "=" * 70)
    print("                     BATCH RUNNER FINAL SUMMARY")
    print("=" * 70)
    print(f"  Total Videos Produced : {videos_produced}")
    print(f"  Stop Condition        : {stop_reason if stop_reason else 'Completed'}")
    print(f"  Total Run Time        : {runtime_str} ({elapsed:.1f}s)")
    print(f"  Cycles Processed      : {cycle_count}")
    print(f"  Successful Video Runs : {successful_runs}")
    print(f"  Failed Video Runs     : {failed_runs}")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    main()
