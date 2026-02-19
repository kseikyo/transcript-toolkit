"""Tests for lib.py — shared utilities."""

import pytest
import importlib
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


# --- T4: Filler word removal ---


@pytest.mark.parametrize(
    "text,fillers,expected",
    [
        ("I um think uh yes", ["um", "uh"], "I think yes"),
        ("Um so basically", ["um"], "So basically"),
        ("yes, um, no", ["um"], "yes, no"),
        ("no fillers here", ["um"], "no fillers here"),
        ("hello world", [], "hello world"),
    ],
)
def test_remove_fillers(text, fillers, expected):
    """Filler words removed, cleanup handled."""
    assert lib.remove_fillers(text, fillers) == expected


# --- T5: Privacy/redaction ---


def test_apply_redaction_email():
    """Email pattern redacts correctly."""
    rules = {
        "patterns": [{"regex": r"\b\S+@\S+\.\S+\b", "label": "EMAIL"}],
        "placeholder": "[REDACTED:{label}]",
    }
    result = lib.apply_redaction("email me at john@acme.com please", rules)
    assert "[REDACTED:EMAIL]" in result
    assert "john@acme.com" not in result


def test_apply_redaction_phone():
    """Phone pattern redacts correctly."""
    rules = {
        "patterns": [{"regex": r"\b\d{3}[-.]?\d{4}\b", "label": "PHONE"}],
        "placeholder": "[REDACTED:{label}]",
    }
    result = lib.apply_redaction("call 555-1234 now", rules)
    assert "[REDACTED:PHONE]" in result
    assert "555-1234" not in result


def test_apply_redaction_empty_patterns():
    """Empty patterns list → no-op."""
    rules = {"patterns": [], "placeholder": "[REDACTED:{label}]"}
    text = "nothing to redact"
    assert lib.apply_redaction(text, rules) == text


def test_apply_redaction_skips_speaker_labels():
    """Redaction must not touch speaker labels (bold name before colon)."""
    rules = {
        "patterns": [{"regex": r"\b[A-Z][a-z]+ [A-Z][a-z]+\b", "label": "NAME"}],
        "placeholder": "[REDACTED:{label}]",
    }
    text = "**John Smith:** hello John Smith"
    result = lib.apply_redaction(text, rules)
    # Speaker label preserved, content redacted
    assert "**John Smith:**" in result
    assert result.count("John Smith") == 1  # Only the speaker label remains


# --- T6: Smarter context rules ---


def test_evaluate_context_min_neighbor_count_fails():
    """min_neighbor_count=2 with only 1 neighbor → False."""
    rule = {
        "strategy": "requires_neighbor",
        "neighbors": ["AI", "model", "assistant"],
        "min_neighbor_count": 2,
    }
    # Only 1 neighbor ("AI") in window
    assert lib.evaluate_context(["the", "AI", "thing"], rule) is False


def test_evaluate_context_min_neighbor_count_passes():
    """min_neighbor_count=2 with 2 neighbors → True."""
    rule = {
        "strategy": "requires_neighbor",
        "neighbors": ["AI", "model", "assistant"],
        "min_neighbor_count": 2,
    }
    # 2 neighbors ("AI", "model") in window
    assert lib.evaluate_context(["the", "AI", "model", "thing"], rule) is True


def test_evaluate_context_default_min_neighbor_count():
    """Without min_neighbor_count, default behavior (1 neighbor suffices)."""
    rule = {
        "strategy": "requires_neighbor",
        "neighbors": ["AI"],
    }
    assert lib.evaluate_context(["the", "AI", "thing"], rule) is True


def test_context_window_size_limits_reach():
    """Per-correction window_size=1 limits context to immediate neighbors."""
    corrections = [
        {
            "asr": "cloud",
            "correct": "Claude",
            "confidence": "high",
            "context": {
                "strategy": "requires_neighbor",
                "neighbors": ["AI"],
                "window_size": 1,
            },
        }
    ]
    # AI is 3 words away — outside window_size=1
    text = "the cloud is great AI tool"
    fix_transcript = importlib.import_module("fix-transcript")
    result, replacements, skipped = fix_transcript.process_transcript(
        text, corrections
    )
    # With window_size=1, "AI" is too far → skipped
    assert len(skipped) == 1
    assert "cloud" in result


# --- T7: Fuzzy matching suggestions ---


@pytest.mark.parametrize(
    "s1,s2,min_score",
    [
        ("Claude", "Cloud", 0.85),
        ("Claudinho", "Claudio", 0.85),
    ],
)
def test_jaro_winkler_similar(s1, s2, min_score):
    """Similar strings score above threshold."""
    score = lib.jaro_winkler(s1, s2)
    assert score >= min_score, f"jaro_winkler({s1!r}, {s2!r}) = {score:.3f} < {min_score}"


def test_jaro_winkler_dissimilar():
    """Dissimilar strings score low."""
    score = lib.jaro_winkler("Python", "Figma")
    assert score < 0.5


def test_jaro_winkler_identical():
    """Identical strings score 1.0."""
    assert lib.jaro_winkler("hello", "hello") == 1.0


def test_jaro_winkler_empty():
    """Empty strings handled gracefully."""
    assert lib.jaro_winkler("", "") == 1.0
    assert lib.jaro_winkler("hello", "") == 0.0


def test_find_fuzzy_suggestions_match():
    """Fuzzy suggestion found for similar word."""
    corrections = [
        {"asr": "cloud", "correct": "Claude", "confidence": "high"},
        {"asr": "github", "correct": "GitHub", "confidence": "high"},
    ]
    suggestions = lib.find_fuzzy_suggestions("claud", corrections, threshold=0.80)
    assert len(suggestions) >= 1
    assert suggestions[0]["asr"] == "cloud"


def test_find_fuzzy_suggestions_no_match():
    """No suggestion for very different word."""
    corrections = [
        {"asr": "github", "correct": "GitHub", "confidence": "high"},
    ]
    suggestions = lib.find_fuzzy_suggestions("banana", corrections, threshold=0.80)
    assert suggestions == []
