"""Unit tests for code paths not covered by the e2e smoke tests."""

from __future__ import annotations

import io
import logging
import re
from collections import Counter

import pytest

from distribution import (
    EmptyInputError,
    HistLayout,
    NumericData,
    Settings,
    Stats,
    _hist_layout,
    _prune_keys,
    histogram_bar,
    read_numerics,
    read_pretallied_tokens,
    render_numeric_graph,
    tokenize_input,
    write_hist,
)


def _numeric_stream(values: list[str]) -> io.StringIO:
    """Build a stream of newline-terminated numeric values."""
    return io.StringIO("\n".join(values) + "\n")


def _tokenize(text: str, settings: Settings) -> tuple[Counter[str], Stats]:
    """Run tokenize_input over literal input text."""
    stats = Stats()
    return tokenize_input(settings, stats, stream=io.StringIO(text)), stats


def _tallied(counts: dict[str, int], *, total_objects: int | None = None) -> Stats:
    """Build the Stats a reader would have produced for these counts.

    write_hist() renders every row as a percentage of stats.value_sum, so a
    hand-built token dict needs a matching value_sum or every row reads 0.00%.
    """
    stats = Stats()
    stats.value_sum = sum(counts.values())
    stats.total_objects = stats.value_sum if total_objects is None else total_objects
    return stats


def _write_hist(
    counts: dict[str, int],
    settings: Settings,
    stats: Stats | None = None,
) -> tuple[str, str]:
    """Run write_hist over a token dict and return its (stdout, stderr) text."""
    out, err = io.StringIO(), io.StringIO()
    write_hist(
        settings,
        stats if stats is not None else _tallied(counts),
        Counter(counts),
        stdout=out,
        stderr=err,
    )
    return out.getvalue(), err.getvalue()


# --- tokenize_input() ---


def test_tokenize_input_whole_lines() -> None:
    """Without --tokenize, each line is counted as a single token."""
    token_dict, stats = _tokenize("a\nb\nb\n", Settings())
    assert dict(token_dict) == {"a": 1, "b": 2}
    assert stats.total_objects == 3
    assert stats.value_sum == 3


def test_tokenize_input_splits_on_pattern() -> None:
    """A tokenize regexp splits each line, and boundary empties are skipped."""
    token_dict, stats = _tokenize("  a  b  \n", Settings(tokenize="white"))
    assert dict(token_dict) == {"a": 1, "b": 1}
    # re.split() yields "" before the leading and after the trailing space
    assert stats.total_objects == 2
    assert stats.value_sum == 2


def test_tokenize_input_skips_blank_lines() -> None:
    """A blank line strips to "" and is not counted as a token."""
    token_dict, stats = _tokenize("a\n\nb\n", Settings())
    assert dict(token_dict) == {"a": 1, "b": 1}
    assert stats.total_objects == 2


def test_tokenize_input_match_filters_tokens() -> None:
    """Unmatched tokens are examined but neither counted nor recorded."""
    token_dict, stats = _tokenize(
        "12\nxx\n34\n", Settings(match_regexp="num", tokenize="white")
    )
    assert dict(token_dict) == {"12": 1, "34": 1}
    assert stats.total_objects == 3
    assert stats.value_sum == 2


def test_tokenize_input_match_is_prefix_anchored() -> None:
    """Matching uses re.match, so a prefix match is enough."""
    token_dict, _ = _tokenize("abc\n", Settings(match_regexp="ab"))
    assert dict(token_dict) == {"abc": 1}


def test_tokenize_input_strips_only_newline() -> None:
    r"""Only "\n" is stripped, so CRLF input keeps its carriage return."""
    token_dict, _ = _tokenize("x\r\n", Settings())
    assert dict(token_dict) == {"x\r": 1}


def test_tokenize_input_empty_stream() -> None:
    """An empty stream yields no tokens and leaves the stats untouched."""
    token_dict, stats = _tokenize("", Settings())
    assert token_dict == Counter()
    assert stats.total_objects == 0
    assert stats.value_sum == 0
    assert stats.prune_count == 0


def test_tokenize_input_prunes_when_interval_reached() -> None:
    """Reaching key_prune_interval matched tokens prunes the hash."""
    settings = Settings(key_prune_interval=2)
    # assign after construction: __post_init__ floors max_keys to height + 3000
    settings.max_keys = 1
    token_dict, stats = _tokenize("a\na\nb\nc\n", settings)
    assert dict(token_dict) == {"a": 2}
    assert stats.prune_count == 2
    assert stats.value_sum == 4


def test_tokenize_input_logs_progress(caplog: pytest.LogCaptureFixture) -> None:
    """A due stat interval logs a running token count."""
    caplog.set_level(logging.DEBUG, logger="distribution")
    # a negative interval is always already due, so no clock patching is needed
    _tokenize("a\n", Settings(stat_interval=-1))
    assert "tokens/lines examined: 1 ; hash prunes: 0" in caplog.text


def test_tokenize_input_rejects_invalid_tokenize_regexp() -> None:
    """An unparseable tokenize regexp raises before any input is read."""
    with pytest.raises(re.error, match="unterminated subpattern"):
        _tokenize("", Settings(tokenize="("))


# --- _prune_keys() ---


def test_prune_keys_keeps_everything_under_the_limit() -> None:
    """A dict smaller than max_keys survives intact in a new Counter."""
    settings = Settings()
    stats = Stats()
    source = Counter({"a": 3, "b": 2})
    pruned = _prune_keys(source, settings, stats)
    assert dict(pruned) == {"a": 3, "b": 2}
    assert pruned is not source
    assert stats.prune_count == 1


def test_prune_keys_truncates_to_most_common() -> None:
    """Only the most common max_keys entries survive; the source is untouched."""
    settings = Settings()
    settings.max_keys = 2
    source = Counter({"a": 3, "b": 2, "c": 1})
    pruned = _prune_keys(source, settings, Stats())
    assert dict(pruned) == {"a": 3, "b": 2}
    assert dict(source) == {"a": 3, "b": 2, "c": 1}


def test_prune_keys_breaks_ties_by_insertion_order() -> None:
    """Counter.most_common keeps the first-inserted key when counts tie."""
    settings = Settings()
    settings.max_keys = 1
    source: Counter[str] = Counter()
    source["first"] = 1
    source["second"] = 1
    assert dict(_prune_keys(source, settings, Stats())) == {"first": 1}


def test_prune_keys_zero_max_keys_discards_everything() -> None:
    """max_keys=0 prunes the hash down to nothing."""
    settings = Settings()
    settings.max_keys = 0
    assert _prune_keys(Counter({"a": 1}), settings, Stats()) == Counter()


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


# --- write_hist() ---


def test_write_hist_sorts_by_descending_count() -> None:
    """Rows are ordered by count, highest first."""
    stdout, _ = _write_hist({"low": 1, "high": 9, "mid": 5}, Settings(width=40))
    assert [row.split("|")[0].strip() for row in stdout.splitlines()] == [
        "high",
        "mid",
        "low",
    ]


def test_write_hist_breaks_count_ties_by_descending_key() -> None:
    """Equal counts sort by key name, reversed along with the count."""
    stdout, _ = _write_hist({"a": 1, "b": 1, "c": 1}, Settings(width=30))
    assert [row.split("|")[0] for row in stdout.splitlines()] == ["c", "b", "a"]


def test_write_hist_truncates_to_height() -> None:
    """No more rows are printed than the configured height."""
    stdout, _ = _write_hist({"a": 3, "b": 2, "c": 1}, Settings(width=30, height=2))
    assert len(stdout.splitlines()) == 2


def test_write_hist_height_zero_still_prints_one_row() -> None:
    """A height of zero still yields one row.

    The break is checked after inserting, so the first key always survives.
    The CLI cannot reach this with -H 0 (falsy, so the default applies), but
    -H -1 takes the same path.
    """
    stdout, _ = _write_hist({"a": 1, "b": 1}, Settings(width=30, height=0))
    assert len(stdout.splitlines()) == 1


def test_write_hist_no_input_raises() -> None:
    """An empty token dict with no examined tokens reports no input."""
    with pytest.raises(EmptyInputError, match="No input"):
        _write_hist({}, Settings(), Stats())


def test_write_hist_all_input_filtered_raises() -> None:
    """An empty token dict after examining tokens reports filtering."""
    stats = Stats()
    stats.total_objects = 7
    with pytest.raises(EmptyInputError, match="All input filtered"):
        _write_hist({}, Settings(), stats)


def test_write_hist_skips_empty_key() -> None:
    """An empty key would render a label-less row, so it is dropped."""
    stdout, _ = _write_hist({"": 5, "a": 1}, Settings(width=30))
    rows = stdout.splitlines()
    assert len(rows) == 1
    assert rows[0].startswith("a|")


def test_write_hist_only_empty_key_raises() -> None:
    """A dict holding nothing but the empty key leaves nothing to render."""
    with pytest.raises(EmptyInputError, match="All input filtered"):
        _write_hist({"": 5}, Settings())


def test_write_hist_header_goes_to_stderr_only() -> None:
    """The header is on stderr so stdout stays pipeable to sort."""
    stdout, stderr = _write_hist({"a": 1}, Settings(width=30))
    assert stderr == "Key|Ct (Pct)     Histogram\n"
    assert "Histogram" not in stdout


def test_write_hist_row_format() -> None:
    """Keys, counts and percentages are right-justified into fixed columns."""
    stdout, _ = _write_hist({"bb": 2, "aaa": 1}, Settings(width=40))
    assert stdout.splitlines() == [
        " bb|2 (66.67%) -------------------------",
        "aaa|1 (33.33%) -------------",
    ]


def test_write_hist_colour_placement() -> None:
    """Every row but the last continues in key_colour; the last resets."""
    settings = Settings(
        width=40, colourised_output=True, colour_palette="0,31,32,33,34"
    )
    stdout, stderr = _write_hist({"a": 2, "b": 1}, settings)
    rows = stdout.splitlines()
    assert stderr.endswith("\033[31m\n")
    assert rows[0].endswith("\033[31m")
    assert rows[-1].endswith("\033[0m")
    # the key itself carries no colour prefix, so sorted output stays aligned
    assert rows[0].startswith("a\033[0m|")


def test_write_hist_zero_value_sum_renders_zero_percent() -> None:
    """All-zero values render as 0.00% rather than dividing by zero.

    `echo "0 foo" | distribution.py -g` reaches here, because
    read_pretallied_tokens sums the values it was given.
    """
    stats = Stats()
    stats.total_objects = 1
    stdout, _ = _write_hist({"foo": 0}, Settings(width=30), stats)
    # max_value is 0, so histogram_bar returns a single minimum-width char
    assert stdout.splitlines() == ["foo|0 (0.00%) -"]


def test_write_hist_logs_summary_stats(caplog: pytest.LogCaptureFixture) -> None:
    """Verbose runs report counts and elapsed time, and stamp end_time."""
    caplog.set_level(logging.DEBUG, logger="distribution")
    stats = _tallied({"a": 2, "b": 1})
    _write_hist({"a": 2, "b": 1}, Settings(width=30), stats)
    assert "tokens/lines examined: 3" in caplog.text
    assert "tokens/lines matched: 3" in caplog.text
    assert "histogram keys: 2" in caplog.text
    assert "runtime: " in caplog.text
    assert stats.end_time > 0


# --- _hist_layout() ---


def test_hist_layout_column_widths() -> None:
    """Column widths come from the widest key and the largest count."""
    layout = _hist_layout({"bb": 21, "a": 7}, 28, 80)
    # "(75.00%)" is 8 wide; 80 - (2+1) - (2+1) - (8+1) - 1 = 64
    assert layout == HistLayout(
        max_token_length=2,
        max_value_width=2,
        max_percent_width=8,
        histogram_width=64,
    )


def test_hist_layout_takes_count_width_from_largest_value() -> None:
    """Column widths come from the largest count, whatever the dict order."""
    layout = _hist_layout({"a": 5, "bbb": 1000}, 1005, 80)
    assert layout.max_value_width == len("1000")
    # 1000/1005 renders as "(99.50%)", 8 wide
    assert layout.max_percent_width == 8


def test_hist_layout_allows_negative_histogram_width() -> None:
    """A key wider than the display leaves no room for the bar."""
    layout = _hist_layout({"x" * 90: 1}, 1, 80)
    assert layout.histogram_width < 0
