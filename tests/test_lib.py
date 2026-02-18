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
