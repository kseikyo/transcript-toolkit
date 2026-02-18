#!/usr/bin/env python3
"""Deterministic transcript correction — CLI tool."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import lib


def _tokenize_with_positions(text: str) -> list[tuple[str, int, int]]:
    return [(m.group(), m.start(), m.end()) for m in re.finditer(r"\S+", text)]


def _find_word_index(
    tokens: list[tuple[str, int, int]],
    char_start: int,
    char_end: int,
) -> int:
    for i, (_, ws, we) in enumerate(tokens):
        if ws <= char_start < we or (ws >= char_start and ws < char_end):
            return i
    return -1


def _detect_speaker(line: str) -> str:
    # **Name:** (colon inside bold) or **Name**: (colon outside) or plain Name:
    m = re.match(r"\*\*(.+?):\*\*", line) or re.match(r"\*\*(.+?)\*\*\s*:", line)
    if m:
        return m.group(1).strip()
    m = re.match(r"([^:]{1,40}):\s", line)
    if m and len(m.group(1).split()) <= 4:
        return m.group(1).strip()
    return ""


def process_transcript(
    text: str,
    corrections: list[dict],
    min_confidence: str = "high",
) -> tuple[str, list[dict], list[dict]]:
    filtered = lib.filter_by_confidence(corrections, min_confidence)
    lines = text.split("\n")
    replacements_log: list[dict] = []
    skipped_log: list[dict] = []

    for line_idx in range(len(lines)):
        line = lines[line_idx]
        tokens = _tokenize_with_positions(line)
        word_list = [t[0] for t in tokens]
        # Collect all candidate matches against the ORIGINAL line
        all_matches: list[tuple[int, int, str, str, dict]] = []

        for corr in filtered:
            asr = corr["asr"]
            correct = corr["correct"]
            context_rule = corr.get("context")

            matches = lib.find_matches(line, asr)
            if not matches:
                continue

            for start, end, matched_text in matches:
                word_idx = _find_word_index(tokens, start, end)
                window = (
                    lib.get_word_window(word_list, word_idx) if word_idx >= 0 else []
                )

                if context_rule is None or lib.evaluate_context(window, context_rule):
                    replacement = lib.restore_case(matched_text, correct)
                    all_matches.append((start, end, replacement, matched_text, corr))
                else:
                    strategy = context_rule.get("strategy", "always")
                    skipped_log.append(
                        {
                            "line": line_idx + 1,
                            "original": matched_text,
                            "replacement": None,
                            "reason": f"context rule: {strategy} — condition not met",
                            "action": "skipped",
                            "char_start": start,
                            "char_end": end,
                        }
                    )

        # Select non-overlapping matches — longest span wins
        all_matches.sort(key=lambda x: (-(x[1] - x[0]), x[0]))
        selected: list[tuple[int, int, str, str, dict]] = []
        for match in all_matches:
            s, e = match[0], match[1]
            if not any(ss < e and s < se for ss, se, *_ in selected):
                selected.append(match)

        # Apply right-to-left to preserve character offsets
        selected.sort(key=lambda x: -x[0])
        for start, end, replacement, matched_text, corr in selected:
            line = line[:start] + replacement + line[end:]
            replacements_log.append(
                {
                    "line": line_idx + 1,
                    "original": matched_text,
                    "replacement": replacement,
                    "reason": f"matched '{corr['asr']}' -> '{corr['correct']}'",
                    "action": "replaced",
                }
            )

        lines[line_idx] = line

    skipped_by_line: dict[int, list[dict]] = {}
    for entry in skipped_log:
        skipped_by_line.setdefault(entry["line"], []).append(entry)

    for ln in sorted(skipped_by_line):
        line = lines[ln - 1]
        entries = skipped_by_line[ln]
        for entry in reversed(entries):
            word = entry["original"]
            occurrences = list(re.finditer(re.escape(word), line, re.IGNORECASE))
            if occurrences:
                m = occurrences[-1]
                flag = f' [unclear: "{word}" \u2192 ?]'
                line = line[: m.end()] + flag + line[m.end() :]
                entry["action"] = "flagged"
        lines[ln - 1] = line

    return "\n".join(lines), replacements_log, skipped_log


def build_ai_payload(
    transcript_file: str,
    profile: dict | None,
    skipped: list[dict],
    text: str,
) -> dict:
    src_lines = text.split("\n")
    items: list[dict] = []

    for i, entry in enumerate(skipped, start=1):
        ln = entry["line"]
        line_text = src_lines[ln - 1] if ln <= len(src_lines) else ""
        speaker = _detect_speaker(line_text)

        tokens = _tokenize_with_positions(line_text)
        word_list = [t[0] for t in tokens]
        word_idx = next(
            (
                j
                for j, (w, _, _) in enumerate(tokens)
                if w.lower().startswith(entry["original"].lower())
            ),
            -1,
        )
        window = (
            lib.get_word_window(word_list, word_idx, window_size=5)
            if word_idx >= 0
            else word_list[:10]
        )
        context_str = "..." + " ".join(window) + "..."

        items.append(
            {
                "id": f"rev_{i:03d}",
                "original_word": entry["original"],
                "context_window": context_str,
                "line_number": ln,
                "speaker": speaker,
                "reason_flagged": entry["reason"],
            }
        )

    payload: dict = {
        "version": "1.0",
        "profile_context": {},
        "transcript_file": Path(transcript_file).name,
        "items": items,
    }
    if profile:
        payload["profile_context"] = {
            "language": profile.get("language", ""),
            "domain": profile.get("domain_context", ""),
            "speakers": profile.get("speakers", []),
        }

    return payload


def interactive_review(skipped: list[dict], lines: list[str]) -> list[dict]:
    decisions: list[dict] = []
    for entry in skipped:
        ln = entry["line"]
        line_text = lines[ln - 1] if ln <= len(lines) else ""

        print(f"\n--- Line {ln} ---", file=sys.stderr)
        print(f"  {line_text.strip()}", file=sys.stderr)
        print(f'  Flagged: "{entry["original"]}"', file=sys.stderr)
        print(f"  Reason: {entry['reason']}", file=sys.stderr)
        print(
            "  [r]eplace / [k]eep / [e]dit / [a]dd to dictionary / [s]kip",
            file=sys.stderr,
        )

        choice = input("  > ").strip().lower()
        if choice == "r":
            new_word = input("  Replacement: ").strip()
            decisions.append({**entry, "action": "replaced", "replacement": new_word})
        elif choice == "e":
            new_word = input("  Edit to: ").strip()
            decisions.append({**entry, "action": "edited", "replacement": new_word})
        elif choice == "a":
            decisions.append({**entry, "action": "add_to_dictionary"})
        elif choice == "k":
            decisions.append({**entry, "action": "kept"})
        else:
            decisions.append({**entry, "action": "skipped"})

    return decisions


def write_audit_log(
    replacements: list[dict],
    skipped: list[dict],
    log_path: str | None,
) -> None:
    entries = replacements + skipped
    entries.sort(key=lambda e: e["line"])

    output = "\n".join(json.dumps(e) for e in entries)
    if output:
        output += "\n"

    if log_path:
        lib.atomic_write_text(Path(log_path), output)
    else:
        print(output, file=sys.stderr, end="")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Apply deterministic corrections to meeting transcripts.",
    )
    p.add_argument("transcript", help="Path to raw transcript file (.md or .txt)")
    p.add_argument("--profile", help="Path to profile folder")
    p.add_argument("--out", help="Output file path (default: <input>-fixed.md)")
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without writing",
    )
    p.add_argument(
        "--min-confidence",
        choices=["high", "medium", "low"],
        default="high",
        help="Minimum confidence level (default: high)",
    )
    p.add_argument("--log", help="Audit log path (default: stderr)")
    p.add_argument("--review", choices=["human", "ai"], help="Review mode")
    args = p.parse_args(argv)

    if args.out is None:
        t = Path(args.transcript)
        args.out = str(t.parent / (t.stem + "-fixed.md"))

    return args


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)

    global_path = Path(__file__).resolve().parent.parent / "corrections-global.json"
    global_corr = lib.load_corrections(global_path)

    profile: dict | None = None
    profile_corr_list: list[dict] = []
    if args.profile:
        profile, profile_corr = lib.load_profile(Path(args.profile))
        profile_corr_list = profile_corr.get("corrections", [])

    corrections = lib.merge_corrections(global_corr["corrections"], profile_corr_list)

    text = Path(args.transcript).read_text(encoding="utf-8")

    if args.review == "ai":
        _, _, skipped = process_transcript(text, corrections, args.min_confidence)
        payload = build_ai_payload(args.transcript, profile, skipped, text)
        print(json.dumps(payload, indent=2))
        return

    corrected, replacements, skipped = process_transcript(
        text,
        corrections,
        args.min_confidence,
    )

    if args.review == "human":
        interactive_review(skipped, corrected.split("\n"))

    if not args.dry_run:
        Path(args.out).write_text(corrected, encoding="utf-8")

    write_audit_log(replacements, skipped, args.log)


if __name__ == "__main__":
    main()
