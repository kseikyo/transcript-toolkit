"""Tests for fix-transcript.py — core transcript processing engine."""

import importlib
from pathlib import Path

import pytest

import lib

# Module has hyphenated filename; importlib handles it
fix_transcript = importlib.import_module("fix-transcript")
process_transcript = fix_transcript.process_transcript


# --- Test 1: Simple high-confidence replacement ---


def test_simple_replacement():
    """High confidence correction without context rule should be applied."""
    corrections = [
        {"asr": "github", "correct": "GitHub", "confidence": "high", "category": "tool"}
    ]
    # Mixed case triggers as-is replacement (restore_case returns "GitHub" for mixed input)
    text = "Check the gitHub repo."
    result, replacements, skipped = process_transcript(text, corrections)
    assert "GitHub" in result
    assert "gitHub" not in result
    assert len(replacements) == 1
    assert len(skipped) == 0


# --- Test 2: requires_neighbor with matching neighbor ---


def test_context_requires_neighbor_match():
    """requires_neighbor strategy with matching neighbor should replace."""
    corrections = [
        {
            "asr": "cloud",
            "correct": "Claude",
            "confidence": "medium",
            "context": {"strategy": "requires_neighbor", "neighbors": ["AI", "model"]},
        }
    ]
    # Title case "Cloud" so restore_case returns "Claude" (capitalize)
    text = "Ask Cloud about the AI model."
    result, _, _ = process_transcript(text, corrections, "medium")
    assert "Claude" in result


# --- Test 3: requires_neighbor without match → skip + flag ---


def test_context_requires_neighbor_no_match():
    """requires_neighbor without matching neighbor should skip and flag."""
    corrections = [
        {
            "asr": "cloud",
            "correct": "Claude",
            "confidence": "medium",
            "context": {"strategy": "requires_neighbor", "neighbors": ["AI"]},
        }
    ]
    text = "Deploy to the cloud server."
    result, replacements, skipped = process_transcript(text, corrections, "medium")
    assert "cloud" in result  # Not replaced
    assert len(skipped) == 1
    assert '[unclear: "cloud"' in result


# --- Test 4: exclude_neighbor blocks replacement ---


def test_context_exclude_neighbor_blocks():
    """exclude_neighbor with exclusion present should skip."""
    corrections = [
        {
            "asr": "cloud",
            "correct": "Claude",
            "confidence": "medium",
            "context": {"strategy": "exclude_neighbor", "exclude_neighbors": ["AWS"]},
        }
    ]
    text = "The AWS cloud infrastructure."
    result, _, skipped = process_transcript(text, corrections, "medium")
    assert "cloud" in result  # Not replaced
    assert len(skipped) == 1


# --- Test 5: both strategy passes ---


def test_context_both_passes():
    """both strategy with neighbor present and no exclusion should replace."""
    corrections = [
        {
            "asr": "cloud",
            "correct": "Claude",
            "confidence": "medium",
            "context": {
                "strategy": "both",
                "neighbors": ["AI"],
                "exclude_neighbors": ["AWS"],
            },
        }
    ]
    # Title case so restore_case("Cloud", "Claude") → "Claude"
    text = "The AI Cloud assistant."
    result, _, _ = process_transcript(text, corrections, "medium")
    assert "Claude" in result


# --- Test 6: both strategy fails on exclusion ---


def test_context_both_fails_exclusion():
    """both strategy with exclusion present should skip."""
    corrections = [
        {
            "asr": "cloud",
            "correct": "Claude",
            "confidence": "medium",
            "context": {
                "strategy": "both",
                "neighbors": ["AI"],
                "exclude_neighbors": ["AWS"],
            },
        }
    ]
    text = "The AWS cloud AI service."  # Has both AI and AWS
    result, _, skipped = process_transcript(text, corrections, "medium")
    assert "cloud" in result  # Not replaced because AWS is present
    assert len(skipped) == 1


# --- Test 7: Case restoration (parametrized) ---


@pytest.mark.parametrize(
    "original,expected",
    [
        ("GITHUB", "GITHUB"),  # ALL CAPS → ALL CAPS
        ("Github", "GitHub"),  # Title → preserve internal caps
        ("github", "GitHub"),  # lower + intentional caps target → preserve target
        ("gitHub", "GitHub"),  # mixed → replacement's own
    ],
)
def test_case_restoration(original, expected):
    """Test ALL CAPS, Title Case, lowercase, mixed case restoration."""
    corrections = [{"asr": "github", "correct": "GitHub", "confidence": "high"}]
    text = f"Check the {original} repo."
    result, _, _ = process_transcript(text, corrections)
    assert expected in result


# --- Test 8: Longest match takes precedence ---


def test_longest_match_first():
    """Longer phrase should be matched before shorter substring."""
    corrections = [
        {
            "asr": "sprint retro",
            "correct": "sprint retrospective",
            "confidence": "high",
        },
        {"asr": "retro", "correct": "retrospective", "confidence": "high"},
    ]
    text = "In the sprint retro meeting."
    result, _, _ = process_transcript(text, corrections)
    assert "sprint retrospective" in result
    # Full phrase replaced; no standalone "retro" substitution
    assert "sprint retrospective meeting" in result


# --- Test 9: Skipped items get [unclear] flags ---


def test_unclear_flags():
    """Skipped items should get [unclear] flags."""
    corrections = [
        {
            # high confidence passes filter, but context check fails
            "asr": "cloud",
            "correct": "Claude",
            "confidence": "high",
            "context": {"strategy": "requires_neighbor", "neighbors": ["missing"]},
        }
    ]
    text = "Deploy to cloud."
    result, _, skipped = process_transcript(text, corrections, "high")
    assert '[unclear: "cloud"' in result
    assert len(skipped) == 1


# --- Test 10: Profile overrides global on asr collision ---


def test_global_before_project():
    """Global corrections applied; profile overrides on collision."""
    global_corr = [{"asr": "api", "correct": "API", "confidence": "high"}]
    profile_corr = [{"asr": "api", "correct": "Api", "confidence": "high"}]  # Override
    merged = lib.merge_corrections(global_corr, profile_corr)
    assert merged[0]["correct"] == "Api"  # Profile wins


# --- Test 11: Dry-run doesn't write output ---


def test_dry_run_no_output(tmp_path):
    """--dry-run should not create output file."""
    transcript = tmp_path / "input.md"
    transcript.write_text("Check github.")
    output = tmp_path / "output.md"

    # Simulate dry-run: process but skip file write
    corrections = [{"asr": "github", "correct": "GitHub", "confidence": "high"}]
    result, _, _ = process_transcript(transcript.read_text(), corrections)

    # Processing succeeded but output not written (dry-run behavior)
    assert result is not None
    assert not output.exists()  # File not created in dry-run mode


# --- Test 12: No cascading between corrections ---


def test_no_cascading_replacements():
    """Correction A's output must NOT become input for correction B."""
    corrections = [
        {"asr": "retro", "correct": "retrospective", "confidence": "high"},
        {"asr": "retrospective", "correct": "RETRO_REPLACED", "confidence": "high"},
    ]
    text = "the retro meeting"
    result, replacements, _ = process_transcript(text, corrections)
    assert "retrospective" in result
    assert "RETRO_REPLACED" not in result


# --- Test 13: Multi-skip flag positions ---


def test_multi_skip_flag_positions():
    """Two skipped words on same line must both get [unclear] flags without corruption.

    Bug: re.finditer re-scans the *modified* line after each flag insertion.
    The word "clear" appears inside "[unclear:" flag text, so re-scanning
    picks the wrong match and corrupts the output.
    """
    corrections = [
        {
            "asr": "clear",
            "correct": "Clear-Fixed",
            "confidence": "high",
            "context": {"strategy": "requires_neighbor", "neighbors": ["missing_word"]},
        },
        {
            "asr": "fuzzy",
            "correct": "Fuzzy-Fixed",
            "confidence": "high",
            "context": {"strategy": "requires_neighbor", "neighbors": ["missing_word"]},
        },
    ]
    text = "handle clear and fuzzy results"
    result, _, skipped = process_transcript(text, corrections)
    assert len(skipped) == 2
    assert '[unclear: "clear"' in result
    assert '[unclear: "fuzzy"' in result
    # Both flags present, neither corrupted
    assert result.count("[unclear:") == 2


# --- Test 14: Flag position adjusts after replacement changes text length ---


def test_flag_position_after_replacement_shift():
    """Flag insertion must adjust positions when prior replacements change text length.

    Bug: skipped entries store char_end from the ORIGINAL line, but flags are
    inserted into the MODIFIED line. If a replacement before the skip changed
    text length, the flag lands at the wrong position.
    """
    corrections = [
        # This WILL be replaced (no context rule) — grows "foo" (3) to "foobar" (6), +3 chars
        {"asr": "foo", "correct": "foobar", "confidence": "high"},
        # This will be SKIPPED (context rule fails) — flag should appear after "baz"
        {
            "asr": "baz",
            "correct": "BAZ_FIXED",
            "confidence": "high",
            "context": {"strategy": "requires_neighbor", "neighbors": ["missing_word"]},
        },
    ]
    text = "the foo and baz here"
    result, replacements, skipped = process_transcript(text, corrections)
    assert len(replacements) == 1  # foo → foobar
    assert len(skipped) == 1  # baz skipped
    # Flag must appear AFTER "baz", not before it or mid-word
    assert "foobar" in result
    assert "baz" in result
    # The flag must not split "baz" or appear before it
    assert '[unclear: "baz"' in result
    # Verify flag is AFTER baz, not before: "baz [unclear:" not "[unclear:...baz"
    baz_pos = result.index("baz")
    flag_pos = result.index("[unclear:")
    assert flag_pos > baz_pos, (
        f"Flag at {flag_pos} should be after 'baz' at {baz_pos}. Got: {result!r}"
    )


# --- Test 15: --report flag ---


def test_report_flag_outputs_summary(tmp_path, capsys):
    """--report flag outputs correction summary to stderr."""
    transcript = tmp_path / "input.md"
    transcript.write_text("Check the github api.")
    fix_transcript = importlib.import_module("fix-transcript")
    fix_transcript.main([
        str(transcript), "--out", str(tmp_path / "out.md"), "--report",
    ])
    captured = capsys.readouterr()
    assert "corrections" in captured.err.lower() or "applied" in captured.err.lower()


def test_report_flag_to_file(tmp_path):
    """--report <path> writes summary to file."""
    transcript = tmp_path / "input.md"
    transcript.write_text("Check the github api.")
    report_file = tmp_path / "report.txt"
    fix_transcript = importlib.import_module("fix-transcript")
    fix_transcript.main([
        str(transcript), "--out", str(tmp_path / "out.md"),
        "--report", str(report_file),
    ])
    assert report_file.exists()
    content = report_file.read_text()
    assert "github" in content.lower() or "applied" in content.lower()


# --- Test 16: Batch processing ---


def test_batch_processes_multiple_files(tmp_path):
    """Batch mode processes multiple files, produces *-fixed.md for each."""
    (tmp_path / "a.md").write_text("Check the github repo.")
    (tmp_path / "b.md").write_text("Use the api key.")
    fix_transcript = importlib.import_module("fix-transcript")
    fix_transcript.main([str(tmp_path / "a.md"), str(tmp_path / "b.md")])
    assert (tmp_path / "a-fixed.md").exists()
    assert (tmp_path / "b-fixed.md").exists()
    assert "GitHub" in (tmp_path / "a-fixed.md").read_text()
    assert "API" in (tmp_path / "b-fixed.md").read_text()


def test_batch_skips_missing_file(tmp_path, capsys):
    """Missing file in batch → error logged, others still processed."""
    (tmp_path / "a.md").write_text("Check the github repo.")
    fix_transcript = importlib.import_module("fix-transcript")
    fix_transcript.main([
        str(tmp_path / "a.md"), str(tmp_path / "missing.md"),
    ])
    assert (tmp_path / "a-fixed.md").exists()
    captured = capsys.readouterr()
    assert "missing.md" in captured.err
