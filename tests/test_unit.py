"""Unit tests for code paths not covered by the e2e smoke tests."""

from __future__ import annotations

import io
import sys
from pathlib import Path

# Make the project root importable so we can "import distribution".
PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))

from distribution import (  # noqa: E402
    NumericData,
    Settings,
    Stats,
    histogram_bar,
    read_numerics,
    read_pretallied_tokens,
    render_numeric_graph,
)


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

    def test_max_value_zero(self) -> None:
        """All-zero input should not crash (max_value=0)."""
        bar = histogram_bar(20, 0, 0, Settings())
        assert bar == "-"

    def test_max_value_zero_logarithmic(self) -> None:
        """All-zero input in log mode should not crash."""
        bar = histogram_bar(20, 0, 0, Settings(logarithmic=True))
        assert bar == "-"


class TestReadNumerics:
    """Tests for read_numerics() covering abs and mon modes."""

    @staticmethod
    def _make_stream(values: list[str]) -> io.StringIO:
        return io.StringIO("\n".join(values) + "\n")

    def test_abs_mode_includes_first_value(self) -> None:
        """Abs mode should include all values, including the first."""
        settings = Settings(numeric_mode="abs")
        stats = Stats()
        data = read_numerics(
            settings, stats, stream=self._make_stream(["10", "20", "30"])
        )
        expected_total = 10.0 + 20.0 + 30.0
        expected_max = 30.0
        assert data.values == [10.0, 20.0, 30.0]
        assert data.total_value == expected_total
        assert data.max_value == expected_max
        assert data.max_width == len(str(expected_max))

    def test_mon_mode_skips_first_value(self) -> None:
        """Mon mode computes differences, so the first value has no predecessor."""
        settings = Settings(numeric_mode="mon")
        stats = Stats()
        data = read_numerics(
            settings, stats, stream=self._make_stream(["10", "30", "60"])
        )
        expected_total = 20.0 + 30.0
        expected_max = 30.0
        assert data.values == [20.0, 30.0]
        assert data.total_value == expected_total
        assert data.max_value == expected_max
        assert data.max_width == len(str(expected_max))

    def test_empty_input(self) -> None:
        """Empty stream produces empty NumericData."""
        settings = Settings(numeric_mode="abs")
        stats = Stats()
        data = read_numerics(settings, stats, stream=io.StringIO(""))
        assert data == NumericData([], 0.0, 0.0, 0)


class TestReadPretalliedTokens:
    """Tests for read_pretallied_tokens() aggregate stats."""

    def test_vk_mode(self) -> None:
        """Vk mode parses 'value key' lines and accumulates stats."""
        settings = Settings(graph_values="vk")
        stats = Stats()
        stream = io.StringIO("5 foo\n3 bar\n")
        token_dict = read_pretallied_tokens(settings, stats, stream=stream)
        expected_sum = 5 + 3
        expected_lines = 2
        assert dict(token_dict) == {"foo": 5, "bar": 3}
        assert stats.value_sum == expected_sum
        assert stats.total_objects == expected_lines

    def test_duplicate_keys(self) -> None:
        """Duplicate keys should have their values summed."""
        settings = Settings(graph_values="vk")
        stats = Stats()
        stream = io.StringIO("2 x\n3 x\n")
        token_dict = read_pretallied_tokens(settings, stats, stream=stream)
        expected_merged = 2 + 3
        assert token_dict["x"] == expected_merged
        assert stats.value_sum == expected_merged


class TestRenderNumericGraph:
    """Tests for render_numeric_graph() edge cases."""

    def test_all_zero_values(self) -> None:
        """All-zero input should not crash."""
        settings = Settings(numeric_mode="abs")
        data = NumericData([0, 0, 0], 0, 0, 1)
        out = io.StringIO()
        render_numeric_graph(settings, data, stdout=out)
        expected_lines = 3
        assert out.getvalue().count("\n") == expected_lines
