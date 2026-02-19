"""Tests for lib.py — shared utilities."""

import pytest
import lib


def test_evaluate_context_unknown_strategy_raises():
    """Unknown strategy must raise ValueError, not silently return True."""
    with pytest.raises(ValueError, match="Unknown context strategy"):
        lib.evaluate_context([], {"strategy": "require_neighbor"})


def test_evaluate_context_valid_strategies_still_work():
    """All 4 valid strategies must still function."""
    assert lib.evaluate_context([], {"strategy": "always"}) is True
    assert lib.evaluate_context([], {"strategy": "requires_neighbor"}) is False
    assert lib.evaluate_context([], {"strategy": "exclude_neighbor"}) is True
    assert (
        lib.evaluate_context(
            ["AI"], {"strategy": "both", "neighbors": ["AI"], "exclude_neighbors": []}
        )
        is True
    )


@pytest.mark.parametrize(
    "pattern,text,expected_count",
    [
        ("C++", "I write C++ code", 1),
        ("C++", "C++ is great", 1),
        ("C++", "AC++ nonsense", 0),
        ("C#", "Learn C# today", 1),
        ("C#", "C# development", 1),
        (".NET", "Use .NET framework", 1),
        (".NET", "the .NET platform", 1),
        ("Node.js", "Install Node.js first", 1),
        ("github", "Check github repo", 1),
    ],
)
def test_find_matches_special_char_boundaries(pattern, text, expected_count):
    """Word boundary must work for patterns with non-word edge chars."""
    matches = lib.find_matches(text, pattern)
    assert len(matches) == expected_count


@pytest.mark.parametrize(
    "original,replacement,expected",
    [
        ("Github", "GitHub", "GitHub"),  # Internal caps preserved
        ("Openai", "OpenAI", "OpenAI"),  # Internal caps preserved
        ("Cloud", "claude", "Claude"),  # Plain word → capitalize still works
        ("Cloud", "Claude", "Claude"),  # Already correct → pass through
        ("GITHUB", "GitHub", "GITHUB"),  # All-caps → all-caps (unchanged)
        # T1: auto-infer target case when original is lowercase
        ("github", "GitHub", "GitHub"),  # Target has intentional caps → preserve
        ("cloud.md", "CLAUDE.md", "CLAUDE.md"),  # All-caps target → preserve
        ("opus", "Opus", "Opus"),  # Title-case target → preserve
        ("agents.md", "AGENTS.md", "AGENTS.md"),  # All-caps target → preserve
        ("hello", "world", "world"),  # No intentional caps → lowercase
        ("foo", "bar", "bar"),  # Both plain lowercase → lowercase
    ],
)
def test_restore_case_preserves_intentional_caps(original, replacement, expected):
    """Single-word title case must not destroy intentional internal capitals."""
    assert lib.restore_case(original, replacement) == expected


def test_atomic_write_text_writes_content(tmp_path):
    """atomic_write_text writes content correctly."""
    target = tmp_path / "test.json"
    lib.atomic_write_text(target, '{"key": "value"}\n')
    assert target.read_text() == '{"key": "value"}\n'


def test_atomic_write_text_no_temp_leak_on_failure(tmp_path, monkeypatch):
    """On failure, temp file must be cleaned up."""
    import os

    target = tmp_path / "test.json"

    def failing_replace(*a, **kw):
        raise OSError("simulated failure")

    monkeypatch.setattr("os.replace", failing_replace)
    with pytest.raises(OSError, match="simulated failure"):
        lib.atomic_write_text(target, "content")
    remaining = list(tmp_path.glob("*.tmp"))
    assert remaining == []


def test_atomic_write_text_overwrites_existing(tmp_path):
    """atomic_write_text overwrites existing file atomically."""
    target = tmp_path / "test.json"
    target.write_text("old content")
    lib.atomic_write_text(target, "new content")
    assert target.read_text() == "new content"


# --- T3: Correction conflict detection ---


def test_detect_conflicts_duplicate_asr_keys():
    """Two corrections with same ASR key but different targets → conflict."""
    corrections = [
        {"asr": "api", "correct": "API", "confidence": "high"},
        {"asr": "api", "correct": "Api", "confidence": "high"},
    ]
    conflicts = lib.detect_conflicts(corrections)
    assert len(conflicts) >= 1
    assert any(c["type"] == "duplicate" for c in conflicts)


def test_detect_conflicts_phrase_overlap():
    """Phrase correction containing a shorter correction's ASR → overlap warning."""
    corrections = [
        {"asr": "open ai", "correct": "OpenAI", "confidence": "high"},
        {"asr": "ai", "correct": "AI", "confidence": "high"},
    ]
    conflicts = lib.detect_conflicts(corrections)
    assert len(conflicts) >= 1
    assert any(c["type"] == "overlap" for c in conflicts)


def test_detect_conflicts_clean():
    """No conflicts in a clean correction set."""
    corrections = [
        {"asr": "github", "correct": "GitHub", "confidence": "high"},
        {"asr": "api", "correct": "API", "confidence": "high"},
    ]
    conflicts = lib.detect_conflicts(corrections)
    assert conflicts == []
