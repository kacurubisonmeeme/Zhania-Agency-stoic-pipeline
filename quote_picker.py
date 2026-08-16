"""
quote_picker.py — Module 1 of the stoic shorts pipeline

Reads stoic_quotes_database.csv, selects one quote (filtered by optional
--theme argument or random across all themes), tracks used quotes in
used_quotes.json to avoid repeats, and writes the selected quote to quote.json.

Usage:
    python quote_picker.py                  # random theme
    python quote_picker.py --theme fear     # specific theme
"""

import argparse
import csv
import json
import os
import random
import sys
from pathlib import Path

# ── Paths (all relative to this script's directory) ──────────────────────────
BASE_DIR = Path(__file__).parent
CSV_PATH = BASE_DIR / "stoic_quotes_database.csv"
USED_PATH = BASE_DIR / "used_quotes.json"
OUTPUT_PATH = BASE_DIR / "quote.json"


def load_csv() -> list[dict]:
    """Load all quotes from the CSV into a list of dicts."""
    if not CSV_PATH.exists():
        print(f"ERROR: Cannot find quote database at {CSV_PATH}", file=sys.stderr)
        sys.exit(1)

    quotes = []
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Strip any accidental whitespace around field values
            quotes.append({k: v.strip() for k, v in row.items()})

    if not quotes:
        print("ERROR: stoic_quotes_database.csv is empty.", file=sys.stderr)
        sys.exit(1)

    return quotes


def load_used() -> dict:
    """
    Load used_quotes.json.  Structure:
        { "theme_name": ["quote text 1", "quote text 2", ...], ... }
    Returns an empty dict if the file doesn't exist yet.
    """
    if not USED_PATH.exists():
        return {}
    with open(USED_PATH, encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            # Corrupted file — start fresh rather than crashing
            print(
                "WARNING: used_quotes.json was corrupted and has been reset.",
                file=sys.stderr,
            )
            return {}


def save_used(used: dict) -> None:
    with open(USED_PATH, "w", encoding="utf-8") as f:
        json.dump(used, f, indent=2, ensure_ascii=False)


def pick_quote(theme: str | None) -> dict:
    """
    Core selection logic:
    1. Filter CSV by theme (or use all quotes if theme is None).
    2. Check which quotes in that pool have already been used.
    3. If all have been used, reset the used list for that theme (exhaustion cycle).
    4. Pick randomly from the remaining unused quotes.
    """
    all_quotes = load_csv()

    # ── Validate theme ────────────────────────────────────────────────────────
    available_themes = {q["theme"] for q in all_quotes}

    if theme is not None:
        if theme not in available_themes:
            print(
                f"ERROR: Theme '{theme}' does not exist in the database.\n"
                f"       Available themes: {', '.join(sorted(available_themes))}",
                file=sys.stderr,
            )
            sys.exit(2)
        pool = [q for q in all_quotes if q["theme"] == theme]
    else:
        pool = all_quotes
        theme = "__all__"  # internal key used in used_quotes.json for random mode

    # ── Filter out already-used quotes ───────────────────────────────────────
    used = load_used()
    used_for_theme: list[str] = used.get(theme, [])

    unused = [q for q in pool if q["quote"] not in used_for_theme]

    # All exhausted — reset and start fresh from the full pool
    if not unused:
        print(
            f"INFO: All quotes for theme '{theme}' have been used. Resetting cycle.",
            file=sys.stderr,
        )
        used[theme] = []
        unused = pool

    # ── Pick one ──────────────────────────────────────────────────────────────
    chosen = random.choice(unused)

    # ── Record as used ────────────────────────────────────────────────────────
    used.setdefault(theme, []).append(chosen["quote"])
    save_used(used)

    return chosen


def build_output(quote_row: dict) -> dict:
    """Shape the CSV row into the exact output format specified in the spec."""
    return {
        "quote": quote_row["quote"],
        "author": quote_row["author"],
        "source": quote_row["source"],
        "theme": quote_row["theme"],
        "length_bucket": quote_row["length_bucket"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Pick a stoic quote from the database."
    )
    parser.add_argument(
        "--theme",
        type=str,
        default=None,
        help="Filter by theme (e.g. fear, anger, control). Omit for random.",
    )
    args = parser.parse_args()

    chosen = pick_quote(args.theme)
    output = build_output(chosen)

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    # Human-readable confirmation to stdout
    print(f"[OK] Quote written to {OUTPUT_PATH}")
    print(f"  Theme  : {output['theme']}")
    print(f"  Author : {output['author']}")
    print(f"  Bucket : {output['length_bucket']}")
    print(f"  Quote  : {output['quote'][:80]}{'...' if len(output['quote']) > 80 else ''}")


if __name__ == "__main__":
    main()
