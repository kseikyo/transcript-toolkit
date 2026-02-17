#!/usr/bin/env python3
"""Apply AI-generated review decisions to transcripts — no API calls, pure stdlib."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

CONFIDENCE_LEVELS = {"high": 3, "medium": 2, "low": 1}


def meets_min(confidence: str, min_level: str) -> bool:
    """Check if confidence meets minimum threshold (ordinal comparison)."""
    return CONFIDENCE_LEVELS.get(confidence, 1) >= CONFIDENCE_LEVELS.get(min_level, 1)


def apply_decision(line: str, original: str, replacement: str) -> str:
    """Replace first occurrence of original with replacement, case-insensitive."""
    pattern = re.compile(re.escape(original), re.IGNORECASE)
    return pattern.sub(replacement, line, count=1)


def print_decision_table(decisions: list[dict]) -> None:
    """Print formatted decision table to stderr."""
    if not decisions:
        print("No decisions to display.", file=sys.stderr)
        return

    id_w = max(8, max((len(d.get("id", "")) for d in decisions), default=8))
    orig_w = max(
        10, max((len(d.get("original_word", "")) for d in decisions), default=10)
    )
    repl_w = max(
        13, max((len(d.get("replacement", "")) for d in decisions), default=13)
    )
    conf_w = 10
    reason_w = 40

    header = (
        f"{'ID':<{id_w}} | {'Original':<{orig_w}} | {'->':^3} "
        f"| {'Replacement':<{repl_w}} | {'Confidence':<{conf_w}} | Reasoning"
    )
    sep = (
        f"{'-' * id_w}-+-{'-' * orig_w}-+-----"
        f"+-{'-' * repl_w}-+-{'-' * conf_w}-+-{'-' * reason_w}"
    )

    print(header, file=sys.stderr)
    print(sep, file=sys.stderr)

    for d in decisions:
        reasoning = d.get("reasoning", "")
        if len(reasoning) > reason_w:
            reasoning = reasoning[: reason_w - 3] + "..."
        print(
            f"{d.get('id', ''):<{id_w}} | {d.get('original_word', ''):<{orig_w}} "
            f"| {'->':^3} | {d.get('replacement', ''):<{repl_w}} "
            f"| {d.get('confidence', ''):<{conf_w}} | {reasoning}",
            file=sys.stderr,
        )


def apply_replacements(text: str, decisions: list[dict]) -> tuple[str, int]:
    """Apply decisions to transcript text. Returns (modified_text, count)."""
    lines = text.split("\n")
    applied = 0

    for d in decisions:
        original = d.get("original_word", "")
        replacement = d.get("replacement", "")
        if not original or not replacement:
            continue

        ln = d.get("line_number", 0)

        if 1 <= ln <= len(lines):
            # Targeted: apply to specific line
            old_line = lines[ln - 1]
            new_line = apply_decision(old_line, original, replacement)
            if new_line != old_line:
                lines[ln - 1] = new_line
                applied += 1
        else:
            # No line_number: scan all lines, replace first occurrence found
            for i, line in enumerate(lines):
                new_line = apply_decision(line, original, replacement)
                if new_line != line:
                    lines[i] = new_line
                    applied += 1
                    break

    return "\n".join(lines), applied


def add_to_dictionary(decision: dict, profile_path: str) -> bool:
    """Shell out to add-correction.py to add entry to profile dictionary."""
    scripts_dir = Path(__file__).resolve().parent
    add_script = scripts_dir / "add-correction.py"

    reasoning = decision.get("reasoning", "")[:50]
    notes = f"Added via ai-review: {reasoning}"

    result = subprocess.run(
        [
            sys.executable,
            str(add_script),
            "--profile",
            profile_path,
            "--asr",
            decision["original_word"],
            "--correct",
            decision["replacement"],
            "--confidence",
            decision.get("confidence", "high"),
            "--category",
            "other",
            "--notes",
            notes,
        ],
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
    )
    if result.returncode != 0:
        print(
            f"Warning: Failed to add '{decision['original_word']}': {result.stderr.strip()}",
            file=sys.stderr,
        )
        return False
    return True


def validate_input(data: dict) -> None:
    """Validate input JSON structure. Exits on failure."""
    if "decisions" not in data:
        print("Error: Missing 'decisions' array in input", file=sys.stderr)
        sys.exit(1)
    if "transcript_file" not in data:
        print("Error: Missing 'transcript_file' in input", file=sys.stderr)
        sys.exit(1)
    if not isinstance(data["decisions"], list):
        print("Error: 'decisions' must be an array", file=sys.stderr)
        sys.exit(1)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Apply AI review decisions to transcripts (reads JSON from stdin).",
    )
    p.add_argument(
        "--apply",
        action="store_true",
        help="Apply decisions to transcript file",
    )
    p.add_argument(
        "--update-dict",
        action="store_true",
        help="Add confirmed corrections to profile dictionary",
    )
    p.add_argument(
        "--min-confidence",
        choices=["high", "medium", "low"],
        default="medium",
        help="Minimum confidence to include (default: medium)",
    )
    p.add_argument(
        "--profile",
        type=str,
        help="Path to profile folder (needed for --update-dict)",
    )
    p.add_argument(
        "--out",
        type=str,
        help="Output file (default: overwrite transcript_file)",
    )
    args = p.parse_args(argv)

    if args.update_dict and not args.profile:
        p.error("--profile is required when using --update-dict")

    return args


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)

    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON on stdin: {e}", file=sys.stderr)
        sys.exit(1)

    validate_input(data)

    decisions = data["decisions"]
    transcript_file = data["transcript_file"]
    profile = args.profile or data.get("profile", "")

    filtered = [
        d
        for d in decisions
        if meets_min(d.get("confidence", "low"), args.min_confidence)
    ]
    skipped = len(decisions) - len(filtered)

    print_decision_table(filtered)

    applied = 0
    added_to_dict = 0

    if args.apply:
        transcript_path = Path(transcript_file)
        if not transcript_path.exists():
            print(f"Error: Transcript not found: {transcript_file}", file=sys.stderr)
            sys.exit(1)

        text = transcript_path.read_text(encoding="utf-8")
        modified, applied = apply_replacements(text, filtered)

        out_path = Path(args.out) if args.out else transcript_path
        out_path.write_text(modified, encoding="utf-8")
        print(f"\nApplied {applied} replacements to {out_path}", file=sys.stderr)

    if args.update_dict and profile:
        for d in filtered:
            if d.get("add_to_dictionary"):
                if add_to_dictionary(d, profile):
                    added_to_dict += 1

    print(
        f"\nSummary: {applied} applied, {added_to_dict} added to dictionary, "
        f"{skipped} skipped (below {args.min_confidence})",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
