"""Shared utilities for transcript correction — pure stdlib."""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path


def atomic_write_text(path: Path, content: str) -> None:
    """Write text atomically via temp file + os.replace."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        os.write(fd, content.encode("utf-8"))
        os.close(fd)
        os.replace(tmp, str(path))
    except BaseException:
        try:
            os.close(fd)
        except:
            pass
        try:
            os.unlink(tmp)
        except:
            pass
        raise


def load_corrections(path: Path) -> dict:
    """Load and validate a corrections JSON file.

    Args:
        path: Path to corrections JSON file

    Returns:
        Dict with keys: version, profile, last_updated, corrections

    Raises:
        FileNotFoundError: If file doesn't exist
        json.JSONDecodeError: If invalid JSON
        KeyError: If required fields missing
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    for key in ("version", "corrections"):
        if key not in data:
            raise KeyError(f"Missing required field: {key}")
    return data


def load_profile(profile_path: Path) -> tuple[dict, dict]:
    """Load profile directory: reads profile.json + corrections.json.

    Args:
        profile_path: Path to profile directory (e.g., profiles/acme-engineering/)

    Returns:
        Tuple of (profile_dict, corrections_dict)

    Raises:
        FileNotFoundError: If profile.json missing
    """
    profile_file = profile_path / "profile.json"
    profile = json.loads(profile_file.read_text(encoding="utf-8"))

    corrections_file = profile_path / "corrections.json"
    if corrections_file.exists():
        corrections = json.loads(corrections_file.read_text(encoding="utf-8"))
    else:
        corrections = {"corrections": []}

    return profile, corrections


def merge_corrections(global_corr: list[dict], profile_corr: list[dict]) -> list[dict]:
    """Merge two correction lists.

    Profile entries override global on asr key collision (case-insensitive).
    Result sorted by len(asr) DESCENDING (longest first prevents partial
    matches), then secondary sort by category alphabetically for deterministic
    order.

    Args:
        global_corr: List of correction entries from global
        profile_corr: List of correction entries from profile

    Returns:
        Merged and sorted list of corrections
    """
    merged: dict[str, dict] = {}

    for entry in global_corr:
        key = entry["asr"].lower()
        merged[key] = entry

    for entry in profile_corr:
        key = entry["asr"].lower()
        merged[key] = entry

    return sorted(
        merged.values(),
        key=lambda e: (-len(e["asr"]), e.get("category", "")),
    )


def detect_conflicts(corrections: list[dict]) -> list[dict]:
    """Detect duplicate and overlapping corrections.

    Checks for:
    - Duplicate ASR keys with different targets
    - Phrase corrections that contain shorter corrections as substrings

    Args:
        corrections: List of correction entries

    Returns:
        List of conflict descriptors with keys: type, message, entries
    """
    conflicts: list[dict] = []

    # Check for duplicate ASR keys with different targets
    seen: dict[str, dict] = {}
    for entry in corrections:
        key = entry["asr"].lower()
        if key in seen and seen[key]["correct"] != entry["correct"]:
            conflicts.append({
                "type": "duplicate",
                "message": (
                    f"Duplicate ASR '{entry['asr']}': "
                    f"'{seen[key]['correct']}' vs '{entry['correct']}'"
                ),
                "entries": [seen[key], entry],
            })
        seen[key] = entry

    # Check for phrase overlaps (phrase contains a shorter correction's ASR)
    asr_keys = {e["asr"].lower(): e for e in corrections}
    for entry in corrections:
        words = entry["asr"].lower().split()
        if len(words) < 2:
            continue
        for word in words:
            if word in asr_keys and asr_keys[word]["asr"].lower() != entry["asr"].lower():
                conflicts.append({
                    "type": "overlap",
                    "message": (
                        f"Phrase '{entry['asr']}' contains "
                        f"word-level correction '{asr_keys[word]['asr']}'"
                    ),
                    "entries": [entry, asr_keys[word]],
                })

    return conflicts


def filter_by_confidence(corrections: list[dict], min_level: str) -> list[dict]:
    """Filter corrections to min_level or above.

    Ordinal: high=3, medium=2, low=1.
    'high' -> only high. 'medium' -> high+medium. 'low' -> all.

    Args:
        corrections: List of correction entries
        min_level: "high", "medium", or "low"

    Returns:
        Filtered list
    """
    levels = {"high": 3, "medium": 2, "low": 1}
    threshold = levels.get(min_level, 1)
    return [
        c for c in corrections if levels.get(c.get("confidence", "low"), 1) >= threshold
    ]


def restore_case(original: str, replacement: str) -> str:
    """Match replacement casing to original's pattern.

    Rules:
    - original.isupper() -> replacement.upper()          # "GITHUB" -> "GITHUB"
    - original.istitle() -> replacement.capitalize()     # "Github" -> "Github"
      BUT: for multi-word like "Open Ai", use replacement's own casing
    - original.islower():
        - if replacement has intentional casing → preserve it  # "github" -> "GitHub"
        - else → replacement.lower()                           # "hello" -> "world"
    - else -> replacement as-is                          # mixed case

    Args:
        original: Original word as it appeared in transcript
        replacement: Correct replacement word

    Returns:
        Replacement with case matched to original pattern
    """
    if not original or not replacement:
        return replacement

    if original.isupper():
        return replacement.upper()

    if original.istitle():
        # Multi-word title case: use replacement's own casing to avoid
        # mangling things like "OpenAI" via str.capitalize()
        if " " in original:
            return replacement
        # Preserve intentional internal caps (GitHub, OpenAI, etc.)
        if any(c.isupper() for c in replacement[1:]):
            return replacement
        return replacement.capitalize()

    if original.islower():
        # Preserve intentional casing in target (CLAUDE.md, GitHub, Opus)
        if any(c.isupper() for c in replacement):
            return replacement
        return replacement.lower()

    return replacement


def get_word_window(
    words: list[str], center_index: int, window_size: int = 10
) -> list[str]:
    """Extract words within +/-window_size of center_index.

    Args:
        words: List of words from a line
        center_index: Index of the word being evaluated
        window_size: Number of words each side (default 10)

    Returns:
        List of surrounding words (excludes center word itself)
    """
    if not words or center_index < 0 or center_index >= len(words):
        return []

    start = max(0, center_index - window_size)
    end = min(len(words), center_index + window_size + 1)
    return [w for i, w in enumerate(words[start:end], start=start) if i != center_index]


VALID_STRATEGIES = {"always", "requires_neighbor", "exclude_neighbor", "both"}


def evaluate_context(window_words: list[str], context_rule: dict) -> bool:
    """Evaluate whether a match should be replaced based on context rule.

    Strategies:
    - 'always' (default if no context): return True
    - 'requires_neighbor': return True if ANY neighbor found in window
      (case-insensitive)
    - 'exclude_neighbor': return True if NO exclude_neighbor found in window
    - 'both': return True if ANY neighbor found AND NO exclude_neighbor found

    Args:
        window_words: List of words in the context window
        context_rule: Dict with keys: strategy, neighbors?, exclude_neighbors?

    Returns:
        True if replacement should proceed
    """
    strategy = context_rule.get("strategy", "always")
    if strategy not in VALID_STRATEGIES:
        raise ValueError(
            f"Unknown context strategy: '{strategy}'. Valid: {VALID_STRATEGIES}"
        )

    if strategy == "always":
        return True

    window_lower = [w.lower() for w in window_words]

    has_neighbor = False
    if strategy in ("requires_neighbor", "both"):
        neighbors = context_rule.get("neighbors", [])
        has_neighbor = any(n.lower() in window_lower for n in neighbors)

    has_exclude = False
    if strategy in ("exclude_neighbor", "both"):
        excludes = context_rule.get("exclude_neighbors", [])
        has_exclude = any(e.lower() in window_lower for e in excludes)

    if strategy == "requires_neighbor":
        return has_neighbor
    if strategy == "exclude_neighbor":
        return not has_exclude
    if strategy == "both":
        return has_neighbor and not has_exclude

    return True


def find_matches(text: str, asr_pattern: str) -> list[tuple[int, int, str]]:
    """Case-insensitive word-boundary regex search.

    Uses re.finditer with re.IGNORECASE.
    For multi-word patterns, matches contiguous tokens with word boundaries.

    Pattern is escaped (re.escape) then word-boundary wrapped.
    For multi-word: "ci cd" -> r'\\bci cd\\b' (matches the phrase)

    Args:
        text: Text to search within
        asr_pattern: The ASR pattern to find (e.g., "github" or "ci cd")

    Returns:
        List of tuples: (start_pos, end_pos, matched_text)
    """
    if not asr_pattern:
        return []

    escaped = re.escape(asr_pattern)
    # Adaptive boundary: \b only works at word↔non-word transitions.
    # For patterns starting/ending with non-word chars, use lookaround instead.
    left = r"\b" if re.match(r"\w", asr_pattern) else r"(?<!\w)"
    right = r"\b" if re.search(r"\w$", asr_pattern) else r"(?!\w)"
    pattern = f"{left}{escaped}{right}"
    return [
        (m.start(), m.end(), m.group())
        for m in re.finditer(pattern, text, re.IGNORECASE | re.UNICODE)
    ]
