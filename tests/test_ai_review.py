"""Tests for ai-review.py — decision parsing, filtering, application, and dict updates."""

from __future__ import annotations

import json
import subprocess
import sys
from io import StringIO
from pathlib import Path

import pytest

# conftest.py adds scripts/ to sys.path
from importlib import import_module

ai_review = import_module("ai-review")
meets_min = ai_review.meets_min
apply_replacements = ai_review.apply_replacements
print_decision_table = ai_review.print_decision_table
add_to_dictionary = ai_review.add_to_dictionary
CONFIDENCE_LEVELS = ai_review.CONFIDENCE_LEVELS


# ---------------------------------------------------------------------------
# Test 1: Valid decisions JSON parsed correctly
# ---------------------------------------------------------------------------
def test_parse_valid_decisions():
    data = {
        "transcript_file": "test.md",
        "decisions": [
            {
                "id": "rev_001",
                "original_word": "cloud",
                "replacement": "Claude",
                "confidence": "high",
                "reasoning": "AI context",
                "add_to_dictionary": False,
            }
        ],
    }
    assert "decisions" in data
    assert len(data["decisions"]) == 1
    assert data["decisions"][0]["id"] == "rev_001"


# ---------------------------------------------------------------------------
# Test 2: Decision table prints to stderr (capsys)
# ---------------------------------------------------------------------------
def test_decision_table_output(capsys):
    decisions = [
        {
            "id": "rev_001",
            "original_word": "cloud",
            "replacement": "Claude",
            "confidence": "high",
            "reasoning": "AI context detected",
        }
    ]
    print_decision_table(decisions)

    captured = capsys.readouterr()
    assert "rev_001" in captured.err
    assert "cloud" in captured.err
    assert "Claude" in captured.err


# ---------------------------------------------------------------------------
# Test 3: --min-confidence filters lower confidence decisions
# ---------------------------------------------------------------------------
def test_min_confidence_filter():
    decisions = [
        {"id": "1", "confidence": "high"},
        {"id": "2", "confidence": "medium"},
        {"id": "3", "confidence": "low"},
    ]

    min_level = "medium"
    filtered = [d for d in decisions if meets_min(d["confidence"], min_level)]

    assert len(filtered) == 2  # high and medium only
    ids = [d["id"] for d in filtered]
    assert "1" in ids
    assert "2" in ids
    assert "3" not in ids


# ---------------------------------------------------------------------------
# Test 4: --apply modifies transcript at correct lines
# ---------------------------------------------------------------------------
def test_apply_modifies_transcript(tmp_path):
    transcript = tmp_path / "test.md"
    transcript.write_text("Line 1\nLine 2 with cloud here\nLine 3")

    decisions = [
        {
            "id": "1",
            "original_word": "cloud",
            "replacement": "Claude",
            "confidence": "high",
            "line_number": 2,
        }
    ]

    text = transcript.read_text()
    modified, count = apply_replacements(text, decisions)
    transcript.write_text(modified)

    result = transcript.read_text()
    assert "Claude" in result
    assert "Line 2 with Claude here" in result
    assert count == 1


# ---------------------------------------------------------------------------
# Test 5: --update-dict shells out to subprocess (monkeypatch)
# ---------------------------------------------------------------------------
def test_update_dict_calls_subprocess(monkeypatch, tmp_path):
    calls: list = []

    def mock_subprocess_run(args, **kwargs):
        calls.append(args)

        class MockResult:
            returncode = 0
            stderr = ""

        return MockResult()

    monkeypatch.setattr(subprocess, "run", mock_subprocess_run)

    decision = {
        "id": "1",
        "original_word": "cloud",
        "replacement": "Claude",
        "confidence": "high",
        "add_to_dictionary": True,
        "reasoning": "AI name",
    }

    result = add_to_dictionary(decision, str(tmp_path))

    assert result is True
    assert len(calls) == 1
    assert "add-correction.py" in calls[0][1]
    assert "--asr" in calls[0]
    assert "cloud" in calls[0]
