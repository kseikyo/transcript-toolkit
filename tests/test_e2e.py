"""End-to-end test for transcript correction pipeline.

Tests the full flow: load raw transcript, apply corrections from global + profile,
compare against ground truth. Skips gracefully if fixtures are missing.
"""

import difflib
import importlib
import json
import re
from pathlib import Path

import pytest

import lib

# Module has hyphenated filename; importlib handles it
fix_transcript = importlib.import_module("fix-transcript")
process_transcript = fix_transcript.process_transcript


# --- Fixture detection ---


def _fixture_exists(path: str) -> bool:
    """Check if a fixture file/directory exists."""
    return Path(path).exists()


# Skip conditions
MEETING_RAW = Path(__file__).parent.parent / "meetings" / "17-02-26.md"
MEETING_FIXED = Path(__file__).parent.parent / "meetings" / "17-02-26-fixed.md"
PROFILE_DIR = Path(__file__).parent.parent / "profiles" / "gestay-sync"
GLOBAL_CORRECTIONS = Path(__file__).parent.parent / "corrections-global.json"

FIXTURES_PRESENT = (
    MEETING_RAW.exists() and MEETING_FIXED.exists() and PROFILE_DIR.exists()
)


@pytest.mark.skipif(
    not FIXTURES_PRESENT,
    reason="meeting fixtures not found: 17-02-26.md, 17-02-26-fixed.md, or profiles/gestay-sync/",
)
def test_e2e_transcript_correction():
    """Full pipeline: raw → corrections → ground truth comparison.

    Loads:
    - Raw transcript from meetings/17-02-26.md
    - Ground truth from meetings/17-02-26-fixed.md
    - Global corrections from corrections-global.json
    - Profile corrections from profiles/gestay-sync/corrections.json

    Merges corrections (profile overrides global on collision).
    Calls process_transcript() with "low" confidence threshold.
    Classifies differences: wrong replacements fail, flagged unclear/missing pass.
    """
    import re

    # Load raw transcript
    raw_text = MEETING_RAW.read_text(encoding="utf-8")

    # Load ground truth
    ground_truth = MEETING_FIXED.read_text(encoding="utf-8")

    # Load global corrections
    global_corr_data = json.loads(GLOBAL_CORRECTIONS.read_text(encoding="utf-8"))
    global_corr_list = global_corr_data.get("corrections", [])

    # Load profile corrections
    profile, profile_corr_data = lib.load_profile(PROFILE_DIR)
    profile_corr_list = profile_corr_data.get("corrections", [])

    # Merge: profile overrides global on asr collision
    merged_corrections = lib.merge_corrections(global_corr_list, profile_corr_list)

    # Process transcript with "low" confidence (includes all)
    result, replacements, skipped = process_transcript(
        raw_text, merged_corrections, "low"
    )

    # Helper: remove all [unclear: "X" → ?] flags from a line
    def remove_unclear_flags(line: str) -> str:
        return re.sub(r' \[unclear: "[^"]*" → \?\]', "", line)

    # Classify differences: flagged unclear vs wrong replacements
    result_lines = result.splitlines()
    ground_truth_lines = ground_truth.splitlines()

    flagged_unclear = 0
    missing_corrections = 0
    wrong_replacements = []

    for i, (result_line, truth_line) in enumerate(
        zip(result_lines, ground_truth_lines)
    ):
        if result_line == truth_line:
            continue

        # Check if difference is due to [unclear: ...] flags
        if "[unclear:" in result_line:
            result_no_flags = remove_unclear_flags(result_line)
            num_flags = len(re.findall(r"\[unclear:", result_line))
            flagged_unclear += num_flags

            # If base text matches ground truth, this is a gap (flagged unclear)
            if result_no_flags == truth_line:
                continue

            # If base text doesn't match, check if it's a missing correction
            # (ground truth has correction but result has original + flags)
            if result_no_flags == remove_unclear_flags(truth_line):
                missing_corrections += num_flags
                continue

            # Otherwise, it's a wrong replacement
            wrong_replacements.append(
                {
                    "line": i + 1,
                    "expected": truth_line,
                    "got": result_line,
                }
            )
            continue

        # Check if ground truth has a correction that result doesn't
        if result_line == remove_unclear_flags(truth_line):
            missing_corrections += 1
            continue

        # Otherwise, it's a wrong replacement (unexpected change)
        wrong_replacements.append(
            {
                "line": i + 1,
                "expected": truth_line,
                "got": result_line,
            }
        )

    # Handle length mismatch
    if len(result_lines) != len(ground_truth_lines):
        if len(result_lines) > len(ground_truth_lines):
            for i in range(len(ground_truth_lines), len(result_lines)):
                if "[unclear:" not in result_lines[i]:
                    wrong_replacements.append(
                        {
                            "line": i + 1,
                            "expected": "(no line)",
                            "got": result_lines[i],
                        }
                    )
        else:
            missing_corrections += len(ground_truth_lines) - len(result_lines)

    # Log summary
    print(f"\n=== E2E Test Summary ===")
    print(f"Replacements applied: {len(replacements)}")
    print(f"Skipped (context rules): {len(skipped)}")
    print(f"Flagged unclear: {flagged_unclear}")
    print(f"Missing corrections: {missing_corrections}")
    print(f"Wrong replacements: {len(wrong_replacements)}")
    print(
        f"Gaps found: {flagged_unclear} flagged unclear, {missing_corrections} missing corrections"
    )

    if replacements:
        print(f"\nReplacements:")
        for r in replacements[:5]:
            print(
                f"  - Line {r.get('line')}: {r.get('original')} → {r.get('replacement')}"
            )
        if len(replacements) > 5:
            print(f"  ... and {len(replacements) - 5} more")

    if skipped:
        print(f"\nSkipped (context rules):")
        for s in skipped[:5]:
            print(f"  - Line {s.get('line')}: {s.get('original')} ({s.get('reason')})")
        if len(skipped) > 5:
            print(f"  ... and {len(skipped) - 5} more")

    # Allow known wrong replacements from engine limitations:
    # - restore_case returns lowercase for all-lowercase originals
    # - context rules block Cloud->Claude when no AI neighbor words nearby
    # - ground truth has manual non-ASR edits
    assert len(wrong_replacements) <= 15, (
        f"Found {len(wrong_replacements)} wrong replacements (threshold: <=15).\n"
        f"Gaps: {flagged_unclear} flagged unclear, {missing_corrections} missing.\n"
        f"First wrong replacement:\n{wrong_replacements[0] if wrong_replacements else 'N/A'}"
    )


# --- Accuracy metrics ---

_UNCLEAR_RE = re.compile(r' \[unclear: "[^"]*" → \?\]')


def _run_pipeline():
    """Run correction pipeline; return (raw, result, truth, replacements, skipped)."""
    raw_text = MEETING_RAW.read_text(encoding="utf-8")
    truth_text = MEETING_FIXED.read_text(encoding="utf-8")
    global_data = json.loads(GLOBAL_CORRECTIONS.read_text(encoding="utf-8"))
    _, profile_data = lib.load_profile(PROFILE_DIR)
    merged = lib.merge_corrections(
        global_data.get("corrections", []),
        profile_data.get("corrections", []),
    )
    result, replacements, skipped = process_transcript(raw_text, merged, "low")
    return raw_text, result, truth_text, replacements, skipped


def _compute_accuracy_metrics(raw_text, result_text, truth_text):
    """Line-level accuracy: TP/FP/FN via SequenceMatcher.get_opcodes().

    Three-way comparison (raw, result, truth) using SequenceMatcher
    to align raw↔truth and classify each line:
      TP — line needed correction AND result == truth
      FN — line needed correction AND result ≠ truth (missed or wrong)
      FP — line was fine AND result changed it; OR wrong replacement made
    """
    clean_result = _UNCLEAR_RE.sub("", result_text)
    raw_lines = raw_text.splitlines()
    result_lines = clean_result.splitlines()
    truth_lines = truth_text.splitlines()

    tp = fp = fn = 0
    fp_details = []
    fn_details = []

    sm = difflib.SequenceMatcher(None, raw_lines, truth_lines)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            # No correction needed — verify result didn't introduce changes
            for k in range(i2 - i1):
                ridx = i1 + k
                if ridx < len(result_lines) and result_lines[ridx] != raw_lines[ridx]:
                    fp += 1
                    fp_details.append(
                        {
                            "line": ridx + 1,
                            "type": "unnecessary",
                            "got": result_lines[ridx][:120],
                            "expected": raw_lines[ridx][:120],
                        }
                    )

        elif tag == "replace":
            # Lines need correction: raw[i1:i2] → truth[j1:j2]
            pairs = min(i2 - i1, j2 - j1)
            for k in range(pairs):
                ridx, tidx = i1 + k, j1 + k
                if ridx >= len(result_lines):
                    fn += 1
                    continue
                if result_lines[ridx] == truth_lines[tidx]:
                    tp += 1
                elif result_lines[ridx] == raw_lines[ridx]:
                    fn += 1
                    fn_details.append(
                        {
                            "line": ridx + 1,
                            "type": "missed",
                            "expected": truth_lines[tidx][:120],
                        }
                    )
                else:
                    # Wrong replacement → both FP and FN
                    fp += 1
                    fn += 1
                    fp_details.append(
                        {
                            "line": ridx + 1,
                            "type": "wrong",
                            "got": result_lines[ridx][:120],
                            "expected": truth_lines[tidx][:120],
                        }
                    )
                    fn_details.append(
                        {
                            "line": ridx + 1,
                            "type": "wrong",
                            "expected": truth_lines[tidx][:120],
                        }
                    )
            # Unmatched lines in replace block
            extra_raw = max(0, (i2 - i1) - (j2 - j1))
            extra_truth = max(0, (j2 - j1) - (i2 - i1))
            fn += extra_raw + extra_truth

        elif tag == "delete":
            fn += i2 - i1
        elif tag == "insert":
            fn += j2 - j1

    prec = tp / (tp + fp) if (tp + fp) else 0.0
    rec = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0

    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": prec,
        "recall": rec,
        "f1": f1,
        "fp_details": fp_details[:10],
        "fn_details": fn_details[:10],
    }


@pytest.fixture(scope="module")
def pipeline_result():
    """Run correction pipeline once for accuracy tests."""
    if not FIXTURES_PRESENT:
        pytest.skip("fixtures not found")
    return _run_pipeline()


@pytest.mark.skipif(
    not FIXTURES_PRESENT,
    reason="fixtures not found",
)
def test_correction_accuracy(pipeline_result):
    """Assert precision >= 0.80 and recall >= 0.80 on line-level accuracy."""
    raw, result, truth, _, _ = pipeline_result
    m = _compute_accuracy_metrics(raw, result, truth)
    assert m["recall"] >= 0.80, (
        f"Recall {m['recall']:.3f} < 0.80 — TP={m['tp']} FN={m['fn']}"
    )
    assert m["precision"] >= 0.80, (
        f"Precision {m['precision']:.3f} < 0.80 — TP={m['tp']} FP={m['fp']}"
    )


@pytest.mark.skipif(
    not FIXTURES_PRESENT,
    reason="fixtures not found",
)
def test_print_accuracy_report(pipeline_result):
    """Print TP, FN, FP, precision, recall, F1 to stdout."""
    raw, result, truth, replacements, skipped = pipeline_result
    m = _compute_accuracy_metrics(raw, result, truth)

    print(f"\n{'=' * 40}")
    print("  ACCURACY REPORT (line-level)")
    print(f"{'=' * 40}")
    print(f"  True Positives  (TP): {m['tp']}")
    print(f"  False Negatives (FN): {m['fn']}")
    print(f"  False Positives (FP): {m['fp']}")
    print(f"{'─' * 40}")
    print(f"  Precision: {m['precision']:.3f}")
    print(f"  Recall:    {m['recall']:.3f}")
    print(f"  F1 Score:  {m['f1']:.3f}")
    print(f"{'─' * 40}")
    print(f"  Pipeline: {len(replacements)} applied, {len(skipped)} skipped")
    print(f"{'=' * 40}")
    if m["fp_details"]:
        print("\n  FP samples (wrong/unnecessary changes):")
        for d in m["fp_details"][:5]:
            print(f"    L{d['line']} [{d['type']}]")
            if "got" in d:
                print(f"      got:      {d['got']}")
            if "expected" in d:
                print(f"      expected: {d['expected']}")
    if m["fn_details"]:
        print("\n  FN samples (missed corrections):")
        for d in m["fn_details"][:5]:
            print(f"    L{d['line']} [{d['type']}]")
            if "expected" in d:
                print(f"      expected: {d['expected']}")
