"""Unit tests for code paths not covered by the e2e smoke tests."""

from __future__ import annotations

import sys
from pathlib import Path

# Make the project root importable so we can "import distribution".
PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))

from distribution import Settings, histogram_bar  # noqa: E402


class TestHistogramBar:
    """Tests for histogram_bar() covering paths the e2e tests don't reach."""

    def test_logarithmic_scaling(self) -> None:
        """Log scaling produces longer bars than linear for small values."""
        linear = histogram_bar(40, 1000, 10, Settings(histogram_char="*"))
        log = histogram_bar(
            40, 1000, 10, Settings(histogram_char="*", logarithmic=True)
        )
        # log(10)/log(1000) ≈ 0.333 vs 10/1000 = 0.01
        assert len(log) > len(linear)

    def test_partial_width_chars(self) -> None:
        """Fractional char_width selects partial-width Unicode glyphs."""
        partial_blocks = ["▏", "▎", "▍", "▌", "▋", "▊", "▉", "█"]
        bar = histogram_bar(20, 100, 50, Settings(histogram_char="pb"))
        assert all(c in partial_blocks for c in bar)
        # 50/100 * 20 = 10 full blocks + 1 partial
        expected_full_blocks = 10
        assert bar.count("█") == expected_full_blocks

    def test_zero_value(self) -> None:
        """Zero value produces a minimal single-char bar."""
        bar = histogram_bar(20, 100, 0, Settings(histogram_char="*"))
        assert bar == "*"
