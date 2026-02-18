"""Performance benchmark tests for transcript correction pipeline.

Measures execution time, throughput, and memory usage of process_transcript().
Skips gracefully if fixtures are missing (same pattern as test_e2e.py).
"""

import importlib
import json
import statistics
import time
import tracemalloc
from pathlib import Path

import pytest

import lib

# Module has hyphenated filename; importlib handles it
fix_transcript = importlib.import_module("fix-transcript")
process_transcript = fix_transcript.process_transcript


# --- Fixture detection (same as test_e2e.py) ---

MEETING_RAW = Path(__file__).parent.parent / "meetings" / "17-02-26.md"
MEETING_FIXED = Path(__file__).parent.parent / "meetings" / "17-02-26-fixed.md"
PROFILE_DIR = Path(__file__).parent.parent / "profiles" / "gestay-sync"
GLOBAL_CORRECTIONS = Path(__file__).parent.parent / "corrections-global.json"

FIXTURES_PRESENT = (
    MEETING_RAW.exists() and MEETING_FIXED.exists() and PROFILE_DIR.exists()
)

SKIP_REASON = "meeting fixtures not found: 17-02-26.md, 17-02-26-fixed.md, or profiles/gestay-sync/"

N_RUNS = 10


def _load_test_data():
    """Load raw transcript and merged corrections for benchmarking."""
    raw_text = MEETING_RAW.read_text(encoding="utf-8")

    global_corr_data = json.loads(GLOBAL_CORRECTIONS.read_text(encoding="utf-8"))
    global_corr_list = global_corr_data.get("corrections", [])

    _, profile_corr_data = lib.load_profile(PROFILE_DIR)
    profile_corr_list = profile_corr_data.get("corrections", [])

    merged_corrections = lib.merge_corrections(global_corr_list, profile_corr_list)
    return raw_text, merged_corrections


# --- Benchmark: Execution Time ---


@pytest.mark.skipif(not FIXTURES_PRESENT, reason=SKIP_REASON)
def test_benchmark_execution_time():
    """Measure process_transcript() over N runs — mean/median/stddev."""
    raw_text, corrections = _load_test_data()
    times_ms = []

    for _ in range(N_RUNS):
        start = time.perf_counter()
        process_transcript(raw_text, corrections, "low")
        elapsed = (time.perf_counter() - start) * 1000
        times_ms.append(elapsed)

    mean_ms = statistics.mean(times_ms)
    median_ms = statistics.median(times_ms)
    stdev_ms = statistics.stdev(times_ms) if len(times_ms) > 1 else 0.0

    print(f"\n=== Execution Time Benchmark ({N_RUNS} runs) ===")
    print(f"  Mean:   {mean_ms:.2f} ms")
    print(f"  Median: {median_ms:.2f} ms")
    print(f"  Stdev:  {stdev_ms:.2f} ms")
    print(f"  Min:    {min(times_ms):.2f} ms")
    print(f"  Max:    {max(times_ms):.2f} ms")

    # Bound: each run must complete under 5s
    assert max(times_ms) < 5000, (
        f"Slowest run took {max(times_ms):.2f} ms (limit: 5000 ms)"
    )


# --- Benchmark: Lines per Second ---


@pytest.mark.skipif(not FIXTURES_PRESENT, reason=SKIP_REASON)
def test_benchmark_lines_per_second():
    """Throughput: lines in transcript / execution time."""
    raw_text, corrections = _load_test_data()
    line_count = len(raw_text.splitlines())
    times_s = []

    for _ in range(N_RUNS):
        start = time.perf_counter()
        process_transcript(raw_text, corrections, "low")
        elapsed = time.perf_counter() - start
        times_s.append(elapsed)

    mean_s = statistics.mean(times_s)
    lines_per_sec = line_count / mean_s if mean_s > 0 else float("inf")

    print(f"\n=== Lines/Second Benchmark ({N_RUNS} runs) ===")
    print(f"  Transcript lines: {line_count}")
    print(f"  Mean time:        {mean_s * 1000:.2f} ms")
    print(f"  Lines/sec:        {lines_per_sec:.0f}")

    # Sanity: should process at least 1 line/sec
    assert lines_per_sec > 1, f"Too slow: {lines_per_sec:.2f} lines/sec"


# --- Benchmark: Corrections per Second ---


@pytest.mark.skipif(not FIXTURES_PRESENT, reason=SKIP_REASON)
def test_benchmark_corrections_per_second():
    """Throughput: total replacements applied / execution time."""
    raw_text, corrections = _load_test_data()
    times_s = []
    total_replacements = 0

    for _ in range(N_RUNS):
        start = time.perf_counter()
        _, replacements, _ = process_transcript(raw_text, corrections, "low")
        elapsed = time.perf_counter() - start
        times_s.append(elapsed)
        total_replacements = len(replacements)  # Same each run

    mean_s = statistics.mean(times_s)
    corr_per_sec = total_replacements / mean_s if mean_s > 0 else float("inf")

    print(f"\n=== Corrections/Second Benchmark ({N_RUNS} runs) ===")
    print(f"  Replacements:     {total_replacements}")
    print(f"  Mean time:        {mean_s * 1000:.2f} ms")
    print(f"  Corrections/sec:  {corr_per_sec:.0f}")

    # Sanity: should apply at least 1 correction/sec
    assert corr_per_sec > 1, f"Too slow: {corr_per_sec:.2f} corrections/sec"


# --- Benchmark: Memory Usage ---


@pytest.mark.skipif(not FIXTURES_PRESENT, reason=SKIP_REASON)
def test_benchmark_memory_usage():
    """Peak memory usage via tracemalloc during process_transcript()."""
    raw_text, corrections = _load_test_data()

    tracemalloc.start()
    process_transcript(raw_text, corrections, "low")
    _, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    peak_kb = peak_bytes / 1024
    peak_mb = peak_kb / 1024

    print(f"\n=== Memory Usage Benchmark ===")
    print(f"  Peak memory: {peak_kb:.1f} KB ({peak_mb:.2f} MB)")

    # Bound: peak memory under 50 MB
    assert peak_mb < 50, f"Peak memory {peak_mb:.2f} MB exceeds 50 MB limit"
