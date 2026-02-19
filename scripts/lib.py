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


def remove_fillers(text: str, fillers: list[str]) -> str:
    """Remove filler words from text with cleanup.

    Handles: double spaces, orphaned commas, capitalization after removal
    at sentence start.

    Args:
        text: Input text
        fillers: List of filler words to remove (case-insensitive)

    Returns:
        Text with fillers removed and whitespace/punctuation cleaned up
    """
    if not fillers:
        return text
    # Build pattern: match filler word with optional leading/trailing comma+space
    # Use word boundaries to avoid partial matches
    escaped = [re.escape(f) for f in fillers]
    filler_pat = r"(?:" + "|".join(escaped) + r")"
    # Match: optional comma+space before, the filler, optional comma+space after
    pattern = r"(?:,\s*)?\b" + filler_pat + r"\b(?:\s*,)?\s*"
    result = re.sub(pattern, " ", text, flags=re.IGNORECASE)
    # Collapse multiple spaces
    result = re.sub(r"  +", " ", result).strip()
    # Restore comma when filler was between two commas: "yes, um, no" → "yes, no"
    # The regex above may eat both commas; re-insert one if needed
    # Check if original had "X, filler, Y" pattern and result lost the comma
    for f in fillers:
        # Pattern: word, filler, word → should keep one comma
        comma_pat = r"(\w),\s*\b" + re.escape(f) + r"\b\s*,\s*(\w)"
        text = re.sub(comma_pat, r"\1, \2", text, flags=re.IGNORECASE)
    # Re-run the simple removal on the fixed text
    result = re.sub(
        r"(?:,\s*)?\b" + filler_pat + r"\b(?:\s*,)?\s*",
        " ", text, flags=re.IGNORECASE,
    )
    result = re.sub(r"  +", " ", result).strip()
    # Capitalize first letter if filler was at start
    if result and result[0].islower() and (not text or text[0].isupper()):
        result = result[0].upper() + result[1:]
    return result


def apply_redaction(text: str, rules: dict) -> str:
    """Apply regex-based redaction rules to text.

    Skips speaker labels (bold name before colon) to preserve attribution.
    Compiles regexes once for efficiency.

    Args:
        text: Input text
        rules: Dict with "patterns" (list of {regex, label}) and "placeholder"

    Returns:
        Text with matched patterns replaced by placeholder
    """
    patterns = rules.get("patterns", [])
    if not patterns:
        return text

    placeholder_template = rules.get("placeholder", "[REDACTED:{label}]")
    # Compile all patterns once
    compiled = []
    for p in patterns:
        compiled.append((re.compile(p["regex"]), p["label"]))

    lines = text.split("\n")
    for i, line in enumerate(lines):
        # Detect speaker label region to skip it
        # Matches: **Name:** or **Name**: patterns
        speaker_end = 0
        sm = re.match(r"\*\*(.+?):\*\*\s*", line) or re.match(
            r"\*\*(.+?)\*\*\s*:\s*", line
        )
        if sm:
            speaker_end = sm.end()

        # Apply redaction only to content after speaker label
        prefix = line[:speaker_end]
        content = line[speaker_end:]
        for regex, label in compiled:
            repl = placeholder_template.replace("{label}", label)
            content = regex.sub(repl, content)
        lines[i] = prefix + content

    return "\n".join(lines)


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
    - 'requires_neighbor': return True if enough neighbors found in window
    - 'exclude_neighbor': return True if NO exclude_neighbor found in window
    - 'both': return True if enough neighbors AND NO exclude_neighbor found

    Optional fields in context_rule:
    - min_neighbor_count (int, default 1): minimum neighbors required

    Args:
        window_words: List of words in the context window
        context_rule: Dict with keys: strategy, neighbors?, exclude_neighbors?,
                      min_neighbor_count?

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
    min_count = context_rule.get("min_neighbor_count", 1)

    neighbor_count = 0
    if strategy in ("requires_neighbor", "both"):
        neighbors = context_rule.get("neighbors", [])
        neighbor_count = sum(1 for n in neighbors if n.lower() in window_lower)

    has_exclude = False
    if strategy in ("exclude_neighbor", "both"):
        excludes = context_rule.get("exclude_neighbors", [])
        has_exclude = any(e.lower() in window_lower for e in excludes)

    if strategy == "requires_neighbor":
        return neighbor_count >= min_count
    if strategy == "exclude_neighbor":
        return not has_exclude
    if strategy == "both":
        return neighbor_count >= min_count and not has_exclude

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


def jaro_winkler(s1: str, s2: str, prefix_weight: float = 0.1) -> float:
    """Jaro-Winkler string similarity (pure Python, stdlib only).

    Weights early-string matches more heavily via a prefix bonus.
    Returns 0.0 (no similarity) to 1.0 (identical).

    Args:
        s1: First string
        s2: Second string
        prefix_weight: Prefix scaling factor (default 0.1)

    Returns:
        Similarity score between 0.0 and 1.0
    """
    if s1 == s2:
        return 1.0
    if not s1 or not s2:
        return 0.0

    s1_lower = s1.lower()
    s2_lower = s2.lower()

    len1, len2 = len(s1_lower), len(s2_lower)
    match_distance = max(len1, len2) // 2 - 1
    if match_distance < 0:
        match_distance = 0

    s1_matches = [False] * len1
    s2_matches = [False] * len2

    matches = 0
    transpositions = 0

    for i in range(len1):
        start = max(0, i - match_distance)
        end = min(i + match_distance + 1, len2)
        for j in range(start, end):
            if s2_matches[j] or s1_lower[i] != s2_lower[j]:
                continue
            s1_matches[i] = True
            s2_matches[j] = True
            matches += 1
            break

    if matches == 0:
        return 0.0

    k = 0
    for i in range(len1):
        if not s1_matches[i]:
            continue
        while not s2_matches[k]:
            k += 1
        if s1_lower[i] != s2_lower[k]:
            transpositions += 1
        k += 1

    jaro = (
        matches / len1 + matches / len2 + (matches - transpositions / 2) / matches
    ) / 3

    # Winkler prefix bonus (up to 4 chars)
    prefix_len = 0
    for i in range(min(4, len1, len2)):
        if s1_lower[i] == s2_lower[i]:
            prefix_len += 1
        else:
            break

    return jaro + prefix_len * prefix_weight * (1 - jaro)


def find_fuzzy_suggestions(
    word: str,
    corrections: list[dict],
    threshold: float = 0.85,
) -> list[dict]:
    """Find corrections with ASR patterns similar to the given word.

    Uses both difflib.SequenceMatcher and Jaro-Winkler, taking the max score.
    Returns suggestions sorted by score descending.

    Args:
        word: Word to find suggestions for
        corrections: List of correction entries
        threshold: Minimum similarity score (default 0.85)

    Returns:
        List of dicts with keys: asr, correct, score
    """
    from difflib import SequenceMatcher

    suggestions: list[dict] = []
    word_lower = word.lower()

    for corr in corrections:
        asr = corr["asr"]
        asr_lower = asr.lower()
        # Skip exact matches — those are handled by dictionary matching
        if asr_lower == word_lower:
            continue
        # Compute both scores, take the max
        sm_score = SequenceMatcher(None, word_lower, asr_lower).ratio()
        jw_score = jaro_winkler(word, asr)
        score = max(sm_score, jw_score)
        if score >= threshold:
            suggestions.append({
                "asr": asr,
                "correct": corr["correct"],
                "score": round(score, 3),
            })

    suggestions.sort(key=lambda s: -s["score"])
    return suggestions
