"""Unit tests for code paths not covered by the e2e smoke tests."""

from __future__ import annotations

import io

from distribution import (
    NumericData,
    Settings,
    Stats,
    histogram_bar,
    read_numerics,
    read_pretallied_tokens,
    render_numeric_graph,
)


def _numeric_stream(values: list[str]) -> io.StringIO:
    """Build a stream of newline-terminated numeric values."""
    return io.StringIO("\n".join(values) + "\n")


# --- histogram_bar() ---


def test_histogram_bar_logarithmic_scaling() -> None:
    """Log scaling produces longer bars than linear for small values."""
    linear = histogram_bar(40, 1000, 10, Settings(histogram_char="*"))
    log = histogram_bar(40, 1000, 10, Settings(histogram_char="*", logarithmic=True))
    # log(10)/log(1000) ≈ 0.333 vs 10/1000 = 0.01
    assert len(log) > len(linear)


def test_histogram_bar_partial_width_chars() -> None:
    """Fractional char_width selects partial-width Unicode glyphs."""
    partial_blocks = ["▏", "▎", "▍", "▌", "▋", "▊", "▉", "█"]
    bar = histogram_bar(20, 100, 50, Settings(histogram_char="pb"))
    assert all(c in partial_blocks for c in bar)
    # 50/100 * 20 = 10 full blocks + 1 partial
    assert bar.count("█") == 10


def test_histogram_bar_zero_value() -> None:
    """Zero value produces a minimal single-char bar."""
    bar = histogram_bar(20, 100, 0, Settings(histogram_char="*"))
    assert bar == "*"


def test_histogram_bar_max_value_zero() -> None:
    """All-zero input should not crash (max_value=0)."""
    bar = histogram_bar(20, 0, 0, Settings())
    assert bar == "-"


def test_histogram_bar_max_value_zero_logarithmic() -> None:
    """All-zero input in log mode should not crash."""
    bar = histogram_bar(20, 0, 0, Settings(logarithmic=True))
    assert bar == "-"


# --- read_numerics() ---


def test_read_numerics_abs_mode_includes_first_value() -> None:
    """Abs mode should include all values, including the first."""
    settings = Settings(numeric_mode="abs")
    stats = Stats()
    data = read_numerics(settings, stats, stream=_numeric_stream(["10", "20", "30"]))
    assert data.values == [10.0, 20.0, 30.0]
    assert data.total_value == 60.0
    assert data.max_value == 30.0
    assert data.max_width == len("30.0")


def test_read_numerics_mon_mode_skips_first_value() -> None:
    """Mon mode computes differences, so the first value has no predecessor."""
    settings = Settings(numeric_mode="mon")
    stats = Stats()
    data = read_numerics(settings, stats, stream=_numeric_stream(["10", "30", "60"]))
    assert data.values == [20.0, 30.0]
    assert data.total_value == 50.0
    assert data.max_value == 30.0
    assert data.max_width == len("30.0")


def test_read_numerics_empty_input() -> None:
    """Empty stream produces empty NumericData."""
    settings = Settings(numeric_mode="abs")
    stats = Stats()
    data = read_numerics(settings, stats, stream=io.StringIO(""))
    assert data == NumericData([], 0.0, 0.0, 0)


# --- read_pretallied_tokens() ---


def test_read_pretallied_tokens_vk_mode() -> None:
    """Vk mode parses 'value key' lines and accumulates stats."""
    settings = Settings(graph_values="vk")
    stats = Stats()
    stream = io.StringIO("5 foo\n3 bar\n")
    token_dict = read_pretallied_tokens(settings, stats, stream=stream)
    assert dict(token_dict) == {"foo": 5, "bar": 3}
    assert stats.value_sum == 8
    assert stats.total_objects == 2


def test_read_pretallied_tokens_duplicate_keys() -> None:
    """Duplicate keys should have their values summed."""
    settings = Settings(graph_values="vk")
    stats = Stats()
    stream = io.StringIO("2 x\n3 x\n")
    token_dict = read_pretallied_tokens(settings, stats, stream=stream)
    assert token_dict["x"] == 5
    assert stats.value_sum == 5


# --- render_numeric_graph() ---


def test_render_numeric_graph_all_zero_values() -> None:
    """All-zero input should not crash."""
    settings = Settings(numeric_mode="abs")
    data = NumericData([0, 0, 0], 0, 0, 1)
    out = io.StringIO()
    render_numeric_graph(settings, data, stdout=out)
    assert out.getvalue().count("\n") == 3
