#!/usr/bin/env python3
"""Compare raw transcript against ground truth to identify correction gaps.

Cross-references diffs against profile + global correction dictionaries.
Classifies each diff as: covered, gap, or structural.
"""

import argparse
import json
import sys
from difflib import SequenceMatcher
from pathlib import Path


def load_corrections(path: str) -> list[dict]:
    """Load corrections from a JSON file. Returns empty list on missing file."""
    p = Path(path)
    if not p.exists():
        print(f"Warning: corrections file not found: {path}", file=sys.stderr)
        return []
    data = json.loads(p.read_text(encoding="utf-8"))
    return data.get("corrections", [])


def build_correction_map(corrections: list[dict]) -> dict[str, str]:
    """Build asr→correct lookup (case-sensitive)."""
    return {c["asr"]: c["correct"] for c in corrections}


def is_structural(raw_line: str, fixed_line: str) -> bool:
    """Check if diff is structural (whitespace/formatting only)."""
    return raw_line.strip() == fixed_line.strip()


def find_word_diffs(raw_line: str, fixed_line: str) -> list[tuple[str, str]]:
    """Find word-level differences between two lines.

    Returns list of (original_fragment, corrected_fragment) tuples.
    """
    raw_words = raw_line.split()
    fixed_words = fixed_line.split()
    matcher = SequenceMatcher(None, raw_words, fixed_words)
    diffs = []
    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        if op == "replace":
            diffs.append((" ".join(raw_words[i1:i2]), " ".join(fixed_words[j1:j2])))
        elif op == "delete":
            diffs.append((" ".join(raw_words[i1:i2]), ""))
        elif op == "insert":
            diffs.append(("", " ".join(fixed_words[j1:j2])))
    return diffs


def classify_diff(
    raw_frag: str,
    fixed_frag: str,
    correction_map: dict[str, str],
) -> str:
    """Classify a word-level diff as covered, gap, or structural.

    Checks exact match first, then substring containment.
    """
    if not raw_frag.strip() and not fixed_frag.strip():
        return "structural"

    # Case-only change with identical lowered text → might be a correction
    # Check corrections first
    # Exact match
    if correction_map.get(raw_frag) == fixed_frag:
        return "covered"

    # Check if any correction's asr is contained in raw_frag
    # and its correct is contained in fixed_frag
    for asr, correct in correction_map.items():
        if asr in raw_frag and correct in fixed_frag:
            # Verify the rest is the same (not a coincidental overlap)
            remaining_raw = raw_frag.replace(asr, "", 1)
            remaining_fixed = fixed_frag.replace(correct, "", 1)
            if remaining_raw.strip() == remaining_fixed.strip():
                return "covered"

    # Case-only change check (e.g. "antunes" → "Antunes")
    if raw_frag.lower() == fixed_frag.lower():
        # Check if any correction handles this case change
        for asr, correct in correction_map.items():
            if asr.lower() == raw_frag.lower() and correct == fixed_frag:
                return "covered"
            # Partial: correction target within the fragment
            if asr in raw_frag and correct in fixed_frag:
                return "covered"
        return "gap"

    return "gap"


def analyze_files(
    raw_path: str,
    fixed_path: str,
    correction_map: dict[str, str],
) -> dict:
    """Run full diff analysis between raw and fixed files.

    Returns dict with stats and lists of covered/gap/structural diffs.
    """
    raw_lines = Path(raw_path).read_text(encoding="utf-8").splitlines()
    fixed_lines = Path(fixed_path).read_text(encoding="utf-8").splitlines()

    matcher = SequenceMatcher(None, raw_lines, fixed_lines)

    results = {
        "covered": [],
        "gaps": [],
        "structural": [],
    }

    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        if op == "equal":
            continue

        if op == "replace":
            for offset in range(min(i2 - i1, j2 - j1)):
                raw_line = raw_lines[i1 + offset]
                fixed_line = fixed_lines[j1 + offset]
                line_num = i1 + offset + 1  # 1-indexed

                if is_structural(raw_line, fixed_line):
                    results["structural"].append(
                        {"line": line_num, "raw": raw_line, "fixed": fixed_line}
                    )
                    continue

                word_diffs = find_word_diffs(raw_line, fixed_line)
                for raw_frag, fixed_frag in word_diffs:
                    classification = classify_diff(raw_frag, fixed_frag, correction_map)
                    entry = {
                        "line": line_num,
                        "original": raw_frag,
                        "expected": fixed_frag,
                    }
                    if classification == "covered":
                        results["covered"].append(entry)
                    elif classification == "structural":
                        results["structural"].append(entry)
                    else:
                        results["gaps"].append(entry)

            # Handle unmatched lines (length mismatch)
            if i2 - i1 > j2 - j1:
                for idx in range(j2 - j1, i2 - i1):
                    results["gaps"].append(
                        {
                            "line": i1 + idx + 1,
                            "original": raw_lines[i1 + idx],
                            "expected": "(line removed)",
                        }
                    )
            elif j2 - j1 > i2 - i1:
                for idx in range(i2 - i1, j2 - j1):
                    results["gaps"].append(
                        {
                            "line": j1 + idx + 1,
                            "original": "(line added)",
                            "expected": fixed_lines[j1 + idx],
                        }
                    )

        elif op == "delete":
            for idx in range(i1, i2):
                results["gaps"].append(
                    {
                        "line": idx + 1,
                        "original": raw_lines[idx],
                        "expected": "(deleted)",
                    }
                )

        elif op == "insert":
            for idx in range(j1, j2):
                results["gaps"].append(
                    {
                        "line": idx + 1,
                        "original": "(inserted)",
                        "expected": fixed_lines[idx],
                    }
                )

    return results


def print_report(results: dict, raw_path: str, fixed_path: str) -> None:
    """Print human-readable gap report."""
    total = len(results["covered"]) + len(results["gaps"]) + len(results["structural"])

    print("=" * 70)
    print("DIFF ANALYSIS REPORT")
    print("=" * 70)
    print(f"  Raw file:          {raw_path}")
    print(f"  Ground truth:      {fixed_path}")
    print("-" * 70)
    print(f"  Total diffs:       {total}")
    print(f"  Covered:           {len(results['covered'])}")
    print(f"  Gaps:              {len(results['gaps'])}")
    print(f"  Structural:        {len(results['structural'])}")
    print("=" * 70)

    if results["covered"]:
        print(f"\n{'COVERED CORRECTIONS':^70}")
        print("-" * 70)
        for entry in results["covered"]:
            print(
                f"  L{entry['line']:>4}: {entry['original']!r} → {entry['expected']!r}"
            )

    if results["gaps"]:
        print(f"\n{'GAPS (uncovered corrections)':^70}")
        print("-" * 70)
        for entry in results["gaps"]:
            print(f"  L{entry['line']:>4}: {entry['original']!r}")
            print(f"         → {entry['expected']!r}")

    if results["structural"]:
        print(f"\n{'STRUCTURAL (formatting only)':^70}")
        print("-" * 70)
        for entry in results["structural"]:
            raw_text = entry.get("original", entry.get("raw", ""))
            print(f"  L{entry['line']:>4}: {raw_text!r}")

    print()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare raw transcript against ground truth to find correction gaps.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Example:
  uv run python scripts/diff-analysis.py meetings/17-02-26.md meetings/17-02-26-fixed.md \\
    --profile profiles/gestay-sync --global corrections-global.json
        """,
    )
    parser.add_argument("raw_file", help="Path to raw transcript")
    parser.add_argument(
        "ground_truth_file", help="Path to ground truth (corrected) transcript"
    )
    parser.add_argument(
        "--profile",
        help="Path to profile directory (reads corrections.json inside)",
    )
    parser.add_argument(
        "--global",
        dest="global_file",
        default="corrections-global.json",
        help="Path to global corrections file (default: corrections-global.json)",
    )

    args = parser.parse_args()

    # Validate input files exist
    for label, path in [
        ("Raw file", args.raw_file),
        ("Ground truth", args.ground_truth_file),
    ]:
        if not Path(path).exists():
            print(f"Error: {label} not found: {path}", file=sys.stderr)
            return 1

    # Load corrections
    profile_corrections: list[dict] = []
    global_corrections: list[dict] = []

    if args.profile:
        profile_corrections_path = Path(args.profile) / "corrections.json"
        profile_corrections = load_corrections(str(profile_corrections_path))

    if args.global_file:
        global_corrections = load_corrections(args.global_file)

    all_corrections = profile_corrections + global_corrections
    correction_map = build_correction_map(all_corrections)
    print(
        f"Loaded {len(correction_map)} corrections "
        f"(profile: {len(profile_corrections)}, global: {len(global_corrections)})",
        file=sys.stderr,
    )

    # Run analysis
    results = analyze_files(args.raw_file, args.ground_truth_file, correction_map)
    print_report(results, args.raw_file, args.ground_truth_file)

    return 0


if __name__ == "__main__":
    sys.exit(main())
