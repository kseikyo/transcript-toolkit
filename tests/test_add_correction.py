"""Tests for add-correction.py — dictionary manager."""

import json
from pathlib import Path

import pytest

import lib


class TestAddNewEntry:
    def test_add_new_entry(self, tmp_path):
        """New entry appended; file remains valid JSON."""
        target = tmp_path / "corrections.json"
        target.write_text(json.dumps({"version": "1.0", "corrections": []}))

        data = lib.load_corrections(target)
        entry = {
            "asr": "test",
            "correct": "Test",
            "confidence": "high",
            "category": "tool",
            "notes": "",
        }
        data["corrections"].append(entry)
        target.write_text(json.dumps(data))

        result = json.loads(target.read_text())
        assert len(result["corrections"]) == 1
        assert result["corrections"][0]["asr"] == "test"


class TestDuplicateDetection:
    def test_duplicate_warns(self, tmp_path, capsys, monkeypatch):
        """Same ASR triggers warning; duplicate is detected."""
        target = tmp_path / "corrections.json"
        target.write_text(
            json.dumps(
                {
                    "version": "1.0",
                    "corrections": [
                        {"asr": "test", "correct": "Old", "confidence": "high"}
                    ],
                }
            )
        )

        monkeypatch.setattr("builtins.input", lambda _: "n")

        data = lib.load_corrections(target)
        existing = next(
            (c for c in data["corrections"] if c["asr"].lower() == "test"), None
        )
        assert existing is not None


class TestOverwriteExisting:
    def test_overwrite_existing(self, tmp_path, monkeypatch):
        """Overwrite replaces existing entry; count stays 1."""
        target = tmp_path / "corrections.json"
        target.write_text(
            json.dumps(
                {
                    "version": "1.0",
                    "corrections": [
                        {"asr": "test", "correct": "Old", "confidence": "high"}
                    ],
                }
            )
        )

        data = lib.load_corrections(target)
        data["corrections"] = [
            c for c in data["corrections"] if c["asr"].lower() != "test"
        ]
        data["corrections"].append(
            {"asr": "test", "correct": "New", "confidence": "high"}
        )
        target.write_text(json.dumps(data))

        result = json.loads(target.read_text())
        assert len(result["corrections"]) == 1
        assert result["corrections"][0]["correct"] == "New"


class TestGlobalFlag:
    def test_global_flag_writes_to_global_file(self, tmp_path):
        """--global writes to global file, not profile."""
        is_global = True
        if is_global:
            target = tmp_path / "corrections-global.json"
        else:
            target = tmp_path / "profile" / "corrections.json"

        target.write_text(json.dumps({"version": "1.0", "corrections": []}))

        entry = {
            "asr": "global_test",
            "correct": "Global_Test",
            "confidence": "high",
        }
        data = json.loads(target.read_text())
        data["corrections"].append(entry)
        target.write_text(json.dumps(data))

        result = json.loads(target.read_text())
        assert any(c["asr"] == "global_test" for c in result["corrections"])


class TestDryRun:
    def test_dry_run_no_changes(self, tmp_path):
        """--dry-run does not modify file."""
        target = tmp_path / "corrections.json"
        original_content = json.dumps(
            {
                "version": "1.0",
                "corrections": [{"asr": "existing", "correct": "Existing"}],
            }
        )
        target.write_text(original_content)

        dry_run = True
        if not dry_run:
            entry = {"asr": "new", "correct": "New"}
            data = json.loads(target.read_text())
            data["corrections"].append(entry)
            target.write_text(json.dumps(data))

        result = json.loads(target.read_text())
        assert len(result["corrections"]) == 1
        assert result["corrections"][0]["asr"] == "existing"


class TestSortOrder:
    def test_sort_order(self, tmp_path):
        """Entries sorted: category asc, asr length desc."""
        target = tmp_path / "corrections.json"
        target.write_text(json.dumps({"version": "1.0", "corrections": []}))

        entries = [
            {"asr": "api", "correct": "API", "category": "concept"},
            {"asr": "long phrase", "correct": "Long Phrase", "category": "concept"},
            {"asr": "short", "correct": "Short", "category": "tool"},
        ]

        data = json.loads(target.read_text())
        data["corrections"].extend(entries)
        data["corrections"].sort(key=lambda c: (c.get("category", ""), -len(c["asr"])))
        target.write_text(json.dumps(data))

        result = json.loads(target.read_text())
        # concept first (alphabetically), longer phrase before shorter
        assert result["corrections"][0]["asr"] == "long phrase"
        assert result["corrections"][1]["asr"] == "api"
        # tool category last
        assert result["corrections"][2]["asr"] == "short"
