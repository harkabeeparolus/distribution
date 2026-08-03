"""Unit tests for the configuration layer: parser, Settings, and rcfile layering."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import pytest

from distribution import (
    DEFAULT_MAX_KEYS,
    DEFAULT_PALETTE,
    DistributionParser,
    Settings,
    _build_parser,
    _parse_args,
    main,
    settings_from_args,
)

if TYPE_CHECKING:
    import argparse
    from pathlib import Path


def _args(*argv: str) -> argparse.Namespace:
    """Parse argv through a fresh parser, bypassing rcfile discovery."""
    return _build_parser().parse_args(list(argv))


def _write_rcfile(directory: Path, *lines: str, name: str = "distributionrc") -> Path:
    """Write an rcfile containing the given lines and return its path."""
    path = directory / name
    path.write_text("".join(f"{line}\n" for line in lines), encoding="utf-8")
    return path


# --- parser construction ---


def test_parser_defaults() -> None:
    """Every option has the documented default when argv is empty."""
    assert vars(_args()) == {
        "rcfile": None,
        "color": False,
        "graph": "",
        "logarithmic": False,
        "numonly": "",
        "verbose": False,
        "width": 0,
        "height": 0,
        "keys": DEFAULT_MAX_KEYS,
        "char": "-",
        "palette": DEFAULT_PALETTE,
        "size": "",
        "tokenize": "",
        "match": ".",
    }


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (("-g",), "vk"),
        (("-g", "kv"), "kv"),
        (("--graph=kv",), "kv"),
    ],
)
def test_parser_graph_optional_value(argv: tuple[str, ...], expected: str) -> None:
    """The bare -g flag falls back to its const, an explicit value wins."""
    assert _args(*argv).graph == expected


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (("-n",), "abs"),
        (("-n", "diff"), "diff"),
        (("--numonly=diff",), "diff"),
    ],
)
def test_parser_numonly_optional_value(argv: tuple[str, ...], expected: str) -> None:
    """The bare -n flag falls back to its const, an explicit value wins."""
    assert _args(*argv).numonly == expected


def test_parser_optional_value_does_not_swallow_next_flag() -> None:
    """A following flag is not consumed as -g's optional value."""
    args = _args("-g", "-l")
    assert args.graph == "vk"
    assert args.logarithmic is True


def test_parser_help_exits_zero() -> None:
    """--help is a successful exit, not an error."""
    with pytest.raises(SystemExit) as excinfo:
        _args("--help")
    assert excinfo.value.code == 0


@pytest.mark.parametrize("argv", [("-w", "x"), ("-H", "x"), ("-k", "x")])
def test_parser_rejects_non_integer(argv: tuple[str, ...]) -> None:
    """Integer options exit with status 2 on unparseable values."""
    with pytest.raises(SystemExit) as excinfo:
        _args(*argv)
    assert excinfo.value.code == 2


def test_parser_rejects_ambiguous_abbreviation() -> None:
    """--col is ambiguous between --color and --colour."""
    with pytest.raises(SystemExit) as excinfo:
        _args("--col")
    assert excinfo.value.code == 2


def test_parser_accepts_unabbreviated_prefixes() -> None:
    """Unambiguous prefixes are accepted, as argparse allows by default."""
    assert _args("--pal=1,2,3,4,5").palette == "1,2,3,4,5"


def test_parser_accepts_negative_width() -> None:
    """Negative dimensions parse; nothing validates them."""
    assert _args("-w", "-5").width == -5


# --- Settings alias resolution ---


@pytest.mark.parametrize(
    ("supplied", "expected"),
    [
        ("white", r"\s+"),
        ("word", r"\W"),
        ("/", "/"),
        ("", ""),
    ],
)
def test_settings_tokenize_aliases(supplied: str, expected: str) -> None:
    """Tokenize aliases expand; anything else is used as a regexp verbatim."""
    assert Settings(tokenize=supplied).tokenize == expected


@pytest.mark.parametrize(
    ("supplied", "expected"),
    [
        ("word", r"^[A-Z,a-z]+$"),
        ("num", r"^\d+$"),
        ("number", r"^\d+$"),
        (".", "."),
        (r"^a.*$", r"^a.*$"),
    ],
)
def test_settings_match_aliases(supplied: str, expected: str) -> None:
    """Match aliases expand; anything else is used as a regexp verbatim."""
    assert Settings(match_regexp=supplied).match_regexp == expected


@pytest.mark.parametrize(
    ("supplied", "expected"),
    [
        ("diff", "mon"),
        ("increasing", "mon"),
        ("monotonic", "mon"),
        ("mon", "mon"),
        ("abs", "abs"),
        ("actual", "abs"),
        ("noop", "abs"),
        ("", ""),
        # unrecognised first letters pass through unchanged
        ("zebra", "zebra"),
        # the mapping is case-sensitive
        ("Diff", "Diff"),
        ("M", "M"),
    ],
)
def test_settings_numeric_mode_aliases(supplied: str, expected: str) -> None:
    """Numeric mode collapses to mon/abs based on its first letter."""
    assert Settings(numeric_mode=supplied).numeric_mode == expected


# --- Settings colours ---


def test_settings_colours_absent_without_colourised_output() -> None:
    """Colour fields stay empty when colour is off, even for a bad palette."""
    settings = Settings(colour_palette="nonsense", colourised_output=False)
    assert settings.regular_colour == ""
    assert settings.key_colour == ""
    assert settings.count_colour == ""
    assert settings.percent_colour == ""
    assert settings.graph_colour == ""


def test_settings_colours_expand_default_palette() -> None:
    """The default palette expands to five ANSI escape sequences."""
    settings = Settings(colourised_output=True)
    assert settings.regular_colour == "\033[0m"
    assert settings.key_colour == "\033[0m"
    assert settings.count_colour == "\033[32m"
    assert settings.percent_colour == "\033[35m"
    assert settings.graph_colour == "\033[34m"


def test_settings_colours_are_not_validated() -> None:
    """Palette entries are interpolated without checking they are numeric."""
    settings = Settings(colour_palette="a,b,c,d,e", colourised_output=True)
    assert settings.regular_colour == "\033[am"
    assert settings.graph_colour == "\033[em"


@pytest.mark.parametrize("palette", ["1,2,3", "1,2,3,4,5,6", ""])
def test_settings_colours_reject_wrong_field_count(palette: str) -> None:
    """A palette without exactly five fields raises an uncaught ValueError.

    This pins today's behaviour: the tuple unpack in _resolve_colours() is
    unguarded, so the user sees a traceback rather than a usage error.
    """
    with pytest.raises(ValueError, match="expected 5"):
        Settings(colour_palette=palette, colourised_output=True)


# --- Settings histogram character ---


@pytest.mark.parametrize(
    ("supplied", "expected"),
    [
        ("ba", "▬"),
        ("bl", "Ξ"),
        ("em", "—"),
        ("me", "⋯"),
        ("di", "♦"),
        ("dt", "•"),
        ("sq", "□"),
        # not a substitution key: used literally
        ("*", "*"),
        ("-o", "-o"),
        ("", ""),
    ],
)
def test_settings_histogram_char_substitutions(supplied: str, expected: str) -> None:
    """Two-letter mnemonics expand to Unicode glyphs; the rest pass through."""
    settings = Settings(histogram_char=supplied)
    assert settings.histogram_char == expected
    assert settings.char_width == 1.0
    assert settings.graph_chars == []


def test_settings_histogram_char_partial_blocks() -> None:
    """char=pb selects eighth-width blocks at 8x resolution."""
    settings = Settings(histogram_char="pb")
    assert settings.char_width == 0.125
    assert settings.graph_chars == ["▏", "▎", "▍", "▌", "▋", "▊", "▉", "█"]


def test_settings_histogram_char_partial_lines() -> None:
    """char=pl selects third-width lines at 3x resolution."""
    settings = Settings(histogram_char="pl")
    assert settings.char_width == 0.3334
    assert settings.graph_chars == ["╸", "╾", "━"]


# --- Settings max_keys floor ---


def test_settings_max_keys_default() -> None:
    """The default height leaves the default max_keys untouched."""
    assert Settings().max_keys == DEFAULT_MAX_KEYS


def test_settings_max_keys_floored_by_height() -> None:
    """max_keys is raised to height + 3000 when the height demands it."""
    assert Settings(height=5000).max_keys == 8000


def test_settings_max_keys_above_floor_is_kept() -> None:
    """An explicit max_keys above the floor survives."""
    assert Settings(max_keys=99_999, height=10).max_keys == 99_999


# --- settings_from_args() ---


def test_settings_from_args_defaults() -> None:
    """With no size or dimensions, the report is 80x15."""
    settings = settings_from_args(_args())
    assert (settings.width, settings.height) == (80, 15)


@pytest.mark.parametrize(
    ("size", "expected"),
    [
        ("small", (60, 10)),
        ("sm", (60, 10)),
        ("s", (60, 10)),
        ("medium", (100, 20)),
        ("med", (100, 20)),
        ("m", (100, 20)),
        ("large", (140, 35)),
        ("lg", (140, 35)),
        ("l", (140, 35)),
    ],
)
def test_settings_from_args_size_presets(size: str, expected: tuple[int, int]) -> None:
    """Each size alias maps to its documented dimensions."""
    settings = settings_from_args(_args(f"--size={size}"))
    assert (settings.width, settings.height) == expected


def test_settings_from_args_unknown_size_is_ignored() -> None:
    """An unrecognised --size silently falls back to the 80x15 default.

    This pins today's behaviour: there is no validation of --size.
    """
    settings = settings_from_args(_args("--size=bogus"))
    assert (settings.width, settings.height) == (80, 15)


def test_settings_from_args_size_full(monkeypatch: pytest.MonkeyPatch) -> None:
    """size=full takes the terminal size, reserving 3 lines for headers."""
    monkeypatch.setenv("COLUMNS", "150")
    monkeypatch.setenv("LINES", "50")
    settings = settings_from_args(_args("--size=full"))
    assert (settings.width, settings.height) == (150, 47)


def test_settings_from_args_size_full_verbose(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verbose output needs 4 more lines than the plain headers."""
    monkeypatch.setenv("COLUMNS", "150")
    monkeypatch.setenv("LINES", "50")
    settings = settings_from_args(_args("--size=full", "--verbose"))
    assert (settings.width, settings.height) == (150, 43)


def test_settings_from_args_size_full_clamps_tiny_terminal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A cramped terminal is clamped up to a usable 40x10."""
    monkeypatch.setenv("COLUMNS", "30")
    monkeypatch.setenv("LINES", "5")
    settings = settings_from_args(_args("--size=full"))
    assert (settings.width, settings.height) == (40, 10)


def test_settings_from_args_dimensions_override_preset() -> None:
    """Explicit --width/--height beat --size."""
    settings = settings_from_args(_args("--size=large", "-w", "50", "-H", "5"))
    assert (settings.width, settings.height) == (50, 5)


def test_settings_from_args_dimensions_override_full(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Explicit --width/--height beat size=full, clamping included."""
    monkeypatch.setenv("COLUMNS", "150")
    monkeypatch.setenv("LINES", "50")
    settings = settings_from_args(_args("--size=full", "-w", "20", "-H", "4"))
    assert (settings.width, settings.height) == (20, 4)


def test_settings_from_args_colour_flag_enables_colour() -> None:
    """--color turns on colourised output."""
    assert settings_from_args(_args("--color")).colourised_output is True


def test_settings_from_args_custom_palette_implies_colour() -> None:
    """A non-default palette turns on colour without --color."""
    settings = settings_from_args(_args("--palette=0,31,33,35,37"))
    assert settings.colourised_output is True


def test_settings_from_args_palette_equal_to_default_does_not_imply_colour() -> None:
    """A palette spelled out identically to the default does not imply --color.

    This pins today's behaviour: the check is a string comparison against
    DEFAULT_PALETTE, so passing the default explicitly is indistinguishable
    from not passing it at all.
    """
    settings = settings_from_args(_args(f"--palette={DEFAULT_PALETTE}"))
    assert settings.colourised_output is False


def test_settings_from_args_maps_renamed_fields() -> None:
    """Namespace names are mapped onto their differently-named Settings fields."""
    settings = settings_from_args(
        _args(
            "--char=*",
            "--match=num",
            "--graph=kv",
            "--numonly=diff",
            "--keys=99999",
            "--tokenize=white",
            "--logarithmic",
            "--verbose",
        )
    )
    assert settings.histogram_char == "*"
    assert settings.match_regexp == r"^\d+$"
    assert settings.graph_values == "kv"
    assert settings.numeric_mode == "mon"
    assert settings.max_keys == 99_999
    assert settings.tokenize == r"\s+"
    assert settings.logarithmic is True
    assert settings.verbose is True


def test_settings_from_args_logs_floored_max_keys(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A --keys below the height floor is reported at debug level."""
    caplog.set_level(logging.DEBUG, logger="distribution")
    settings = settings_from_args(_args("--keys=10"))
    assert settings.max_keys == 3015
    assert "Updated max_keys to 3015" in caplog.text


def test_settings_from_args_does_not_log_when_max_keys_is_kept(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A --keys above the floor is used as-is and logs nothing."""
    caplog.set_level(logging.DEBUG, logger="distribution")
    assert settings_from_args(_args("--keys=99999")).max_keys == 99_999
    assert caplog.text == ""


# --- rcfile line conversion ---


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("--color", ["--color"]),
        ("  --char=-o  ", ["--char=-o"]),
        ("\t--verbose\n", ["--verbose"]),
        ("", []),
        ("   ", []),
        ("\n", []),
        ("# a comment", []),
        ("   # an indented comment", []),
        ("#", []),
        # trailing comments are not supported: the whole line is one token
        ("--char=x # why", ["--char=x # why"]),
    ],
)
def test_convert_arg_line_to_args(line: str, expected: list[str]) -> None:
    """Blank lines and comments are dropped; other lines yield one token."""
    assert DistributionParser().convert_arg_line_to_args(line) == expected


# --- parser error messages ---


def test_parser_error_without_rcfile_path(capsys: pytest.CaptureFixture[str]) -> None:
    """A plain error message is not attributed to any file."""
    parser = DistributionParser(prog="dist")
    with pytest.raises(SystemExit) as excinfo:
        parser.error("something broke")
    assert excinfo.value.code == 2
    assert "dist: error: something broke" in capsys.readouterr().err


def test_parser_error_with_rcfile_path(capsys: pytest.CaptureFixture[str]) -> None:
    """Errors raised while reading an rcfile name that file."""
    parser = DistributionParser(prog="dist")
    parser.rcfile_path = "/etc/distributionrc"
    with pytest.raises(SystemExit) as excinfo:
        parser.error("something broke")
    assert excinfo.value.code == 2
    err = capsys.readouterr().err
    assert "dist: error: in /etc/distributionrc: something broke" in err


# --- rcfile discovery and layering ---


def test_parse_args_missing_default_rcfile_is_not_an_error(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """An absent default rcfile leaves the CLI arguments untouched."""
    args = _parse_args(["-w", "5"], default_rcfile=str(tmp_path / "nonexistent"))
    assert args.width == 5
    assert args.rcfile is None
    assert capsys.readouterr().err == ""


def test_parse_args_missing_explicit_rcfile_is_an_error(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """An explicitly requested rcfile must exist."""
    missing = tmp_path / "nonexistent"
    with pytest.raises(SystemExit) as excinfo:
        _parse_args([f"--rcfile={missing}"])
    assert excinfo.value.code == 2
    # not yet attributed to a file: rcfile_path is still unset at this point
    assert f"error: rcfile not found: {missing}" in capsys.readouterr().err


def test_parse_args_directory_as_rcfile_is_an_error(tmp_path: Path) -> None:
    """A directory is not a usable rcfile."""
    with pytest.raises(SystemExit) as excinfo:
        _parse_args([f"--rcfile={tmp_path}"])
    assert excinfo.value.code == 2


def test_parse_args_default_rcfile_is_applied(tmp_path: Path) -> None:
    """The default rcfile is read without being named on the command line."""
    rcfile = _write_rcfile(tmp_path, "--char=Z", "--width=42")
    args = _parse_args([], default_rcfile=str(rcfile))
    assert args.char == "Z"
    assert args.width == 42


def test_parse_args_empty_rcfile_option_falls_back_to_default(tmp_path: Path) -> None:
    """--rcfile= is treated as unset rather than as an error.

    This pins today's behaviour: the option is only honoured when truthy.
    """
    rcfile = _write_rcfile(tmp_path, "--char=Z")
    args = _parse_args(["--rcfile="], default_rcfile=str(rcfile))
    assert args.char == "Z"


def test_parse_args_explicit_rcfile_is_applied(tmp_path: Path) -> None:
    """--rcfile reads that file instead of the default."""
    default = _write_rcfile(tmp_path, "--char=D", name="default")
    explicit = _write_rcfile(tmp_path, "--char=E", name="explicit")
    args = _parse_args([f"--rcfile={explicit}"], default_rcfile=str(default))
    assert args.char == "E"


def test_parse_args_cli_overrides_rcfile(tmp_path: Path) -> None:
    """Command-line arguments win, while unmentioned rcfile values survive."""
    rcfile = _write_rcfile(
        tmp_path, "--char=Z", "--palette=0,32,34,35,37", "--width=42"
    )
    args = _parse_args(["--char=Q"], default_rcfile=str(rcfile))
    assert args.char == "Q"
    assert args.palette == "0,32,34,35,37"
    assert args.width == 42


def test_parse_args_rcfile_ignores_comments_and_blank_lines(tmp_path: Path) -> None:
    """Comments, blank lines and indentation are stripped from the rcfile."""
    rcfile = _write_rcfile(
        tmp_path,
        "# the character to graph with",
        "",
        "   ",
        "  --char=Z  ",
        "\t# trailing note",
    )
    args = _parse_args([], default_rcfile=str(rcfile))
    assert args.char == "Z"


def test_parse_args_rcfile_boolean_flags_cannot_be_disabled(tmp_path: Path) -> None:
    """A store_true flag set in the rcfile cannot be turned off from the CLI.

    This pins today's behaviour: the flags have no --no-* counterpart, so
    once the rcfile enables one there is no argv that clears it.
    """
    rcfile = _write_rcfile(tmp_path, "--color", "--logarithmic", "--verbose")
    args = _parse_args(["--char=Q"], default_rcfile=str(rcfile))
    assert args.color is True
    assert args.logarithmic is True
    assert args.verbose is True


def test_parse_args_rcfile_supports_nested_includes(tmp_path: Path) -> None:
    """An @-prefixed line inside an rcfile includes another file."""
    included = _write_rcfile(tmp_path, "--char=Z", name="included")
    rcfile = _write_rcfile(tmp_path, "--color", f"@{included}")
    args = _parse_args([], default_rcfile=str(rcfile))
    assert args.color is True
    assert args.char == "Z"


def test_parse_args_malformed_rcfile_names_the_file(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A bad value in the rcfile is reported against that file, not argv."""
    rcfile = _write_rcfile(tmp_path, "--keys=abc")
    with pytest.raises(SystemExit) as excinfo:
        _parse_args([], default_rcfile=str(rcfile))
    assert excinfo.value.code == 2
    assert f"error: in {rcfile}: argument -k/--keys" in capsys.readouterr().err


def test_parse_args_nested_include_errors_name_the_outer_file(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Errors from an included file are attributed to the outer rcfile."""
    included = _write_rcfile(tmp_path, "--keys=abc", name="included")
    rcfile = _write_rcfile(tmp_path, f"@{included}")
    with pytest.raises(SystemExit) as excinfo:
        _parse_args([], default_rcfile=str(rcfile))
    assert excinfo.value.code == 2
    assert f"error: in {rcfile}: " in capsys.readouterr().err


def test_parse_args_rcfile_requires_one_option_per_line(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Space-separated options on one rcfile line are a single unknown token.

    Each line becomes exactly one argv token, so --char=-o is the required
    form; --char -o cannot be matched.
    """
    rcfile = _write_rcfile(tmp_path, "--char -o")
    with pytest.raises(SystemExit) as excinfo:
        _parse_args([], default_rcfile=str(rcfile))
    assert excinfo.value.code == 2
    assert "unrecognized arguments: --char -o" in capsys.readouterr().err


# --- main() argv plumbing ---


def test_main_forwards_argv() -> None:
    """main() parses the argv it is handed rather than sys.argv."""
    with pytest.raises(SystemExit) as excinfo:
        main(["--help"])
    assert excinfo.value.code == 0
