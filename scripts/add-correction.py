#!/usr/bin/env python3
"""CLI tool for managing ASR correction dictionaries."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import lib

VALID_CONFIDENCE = ("high", "medium", "low")
VALID_CATEGORY = ("tool", "person", "concept", "place", "other")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Add or update entries in ASR correction dictionaries.",
    )
    target = p.add_mutually_exclusive_group(required=True)
    target.add_argument(
        "--profile",
        type=str,
        help="Path to profile folder (writes to that profile's corrections.json)",
    )
    target.add_argument(
        "--global",
        dest="global_flag",
        action="store_true",
        help="Write to corrections-global.json instead of a profile",
    )
    p.add_argument(
        "--asr", type=str, help="The wrong ASR word (as it appears in raw transcript)"
    )
    p.add_argument("--correct", type=str, help="The correct replacement")
    p.add_argument(
        "--confidence",
        type=str,
        choices=VALID_CONFIDENCE,
        default="high",
        help="Confidence level (default: high)",
    )
    p.add_argument(
        "--category",
        type=str,
        choices=VALID_CATEGORY,
        help="Category of the correction",
    )
    p.add_argument("--notes", type=str, default="", help="Brief description or context")
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview entry without writing to file",
    )
    return p.parse_args()


def interactive_prompt() -> dict:
    """Interactive mode when --asr/--correct not provided."""
    asr = input("ASR word (as it appears in transcript): ").strip()
    correct = input("Correct replacement: ").strip()
    confidence = (
        input("Confidence [high/medium/low] (default: high): ").strip() or "high"
    )
    category = input("Category [tool/person/concept/place/other]: ").strip()
    notes = input("Notes (optional): ").strip()
    return {
        "asr": asr,
        "correct": correct,
        "confidence": confidence,
        "category": category,
        "notes": notes,
    }


def validate_entry(entry: dict) -> None:
    """Validate entry fields. Exits on failure."""
    if not entry.get("asr"):
        print("Error: asr cannot be empty", file=sys.stderr)
        sys.exit(1)
    if not entry.get("correct"):
        print("Error: correct cannot be empty", file=sys.stderr)
        sys.exit(1)
    if entry["confidence"] not in VALID_CONFIDENCE:
        print(
            f"Error: confidence must be one of {VALID_CONFIDENCE}, got '{entry['confidence']}'",
            file=sys.stderr,
        )
        sys.exit(1)
    if entry.get("category") and entry["category"] not in VALID_CATEGORY:
        print(
            f"Error: category must be one of {VALID_CATEGORY}, got '{entry['category']}'",
            file=sys.stderr,
        )
        sys.exit(1)
    if not entry.get("category"):
        entry["category"] = "other"


def find_by_asr(corrections: list[dict], asr: str) -> dict | None:
    """Case-insensitive lookup by asr field."""
    asr_lower = asr.lower()
    for c in corrections:
        if c["asr"].lower() == asr_lower:
            return c
    return None


def confirm(prompt: str) -> bool:
    """Prompt user for y/N confirmation."""
    response = input(f"{prompt} [y/N]: ").strip().lower()
    return response == "y"


def sort_corrections(corrections: list[dict]) -> list[dict]:
    """Sort by category asc, then asr length desc."""
    return sorted(corrections, key=lambda c: (c.get("category", ""), -len(c["asr"])))


def load_or_init(target: Path) -> dict:
    """Load existing corrections file or create empty structure."""
    if target.exists():
        return lib.load_corrections(target)
    return {
        "version": "1.0",
        "last_updated": "",
        "corrections": [],
    }


def main() -> None:
    args = parse_args()

    if args.asr and args.correct:
        entry = {
            "asr": args.asr,
            "correct": args.correct,
            "confidence": args.confidence or "high",
            "category": args.category or "other",
            "notes": args.notes or "",
        }
    else:
        entry = interactive_prompt()

    validate_entry(entry)

    if args.global_flag:
        target = Path(__file__).resolve().parent.parent / "corrections-global.json"
    else:
        target = Path(args.profile) / "corrections.json"

    data = load_or_init(target)

    existing = find_by_asr(data["corrections"], entry["asr"])
    if existing:
        print(f"Warning: '{entry['asr']}' already exists:", file=sys.stderr)
        print(json.dumps(existing, indent=2), file=sys.stderr)
        if not confirm("Overwrite?"):
            print("Aborted.")
            return
        data["corrections"] = [
            c for c in data["corrections"] if c["asr"].lower() != entry["asr"].lower()
        ]

    print("New entry:")
    print(json.dumps(entry, indent=2))

    if args.dry_run:
        print("(dry-run: not writing)")
        return

    data["corrections"].append(entry)
    data["corrections"] = sort_corrections(data["corrections"])
    data["last_updated"] = datetime.now(timezone.utc).isoformat()

    target.parent.mkdir(parents=True, exist_ok=True)
    lib.atomic_write_text(target, json.dumps(data, indent=2) + "\n")
    print(f"Added to {target}")


if __name__ == "__main__":
    main()
