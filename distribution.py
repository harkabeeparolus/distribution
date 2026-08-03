#! /usr/bin/env python3

"""Generate character-based histograms in the terminal.

If you find yourself typing:
  long | list | of | commands | sort | uniq -c | sort -rn

Replace "sort | uniq -c | sort -rn" with "distribution" and bask in the
glory of your new-found data visualization. There are other use cases
as well.
"""

from __future__ import annotations

import argparse
import logging
import math
import re
import shutil
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple, NoReturn, TextIO

if TYPE_CHECKING:
    from collections.abc import Sequence

logger = logging.getLogger(__name__)


def main(argv: Sequence[str] | None = None) -> None:
    """Parse arguments, read stdin, and render the histogram."""
    args = _parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(message)s",
        stream=sys.stderr,
    )
    settings = settings_from_args(args)
    stats = Stats()

    try:
        if settings.graph_values:
            token_dict = read_pretallied_tokens(settings, stats)
            write_hist(settings, stats, token_dict)
        elif settings.numeric_mode:
            numeric_data = read_numerics(settings, stats)
            render_numeric_graph(settings, numeric_data)
        else:
            token_dict = tokenize_input(settings, stats)
            write_hist(settings, stats, token_dict)
    except EmptyInputError as exc:
        logger.error(f"{exc}! No histogram for you.")  # noqa: TRY400
        sys.exit(255)


def tokenize_input(
    settings: Settings,
    stats: Stats,
    *,
    stream: TextIO | None = None,
) -> Counter[str]:
    """Split stdin lines into tokens and count their frequency.

    Splits on whitespace or word boundaries by default, but the user
    can specify any regexp. Likewise, matching defaults to everything
    but can be restricted to all-alpha or all-numeric tokens.
    """
    stream = stream or sys.stdin

    token_dict: Counter[str] = Counter()

    # docs say these are cached, but i got about 2x speed boost
    # from doing the compile
    should_tokenize = settings.tokenize
    tokenize_pattern = re.compile(settings.tokenize)
    match_pattern = re.compile(settings.match_regexp)

    next_stat = time.time() + settings.stat_interval

    prune_objects = 0
    for raw_line in stream:
        tokens = (
            tokenize_pattern.split(raw_line.rstrip("\n"))
            if should_tokenize
            else [raw_line.rstrip("\n")]
        )
        for token in tokens:
            if not token:
                continue
            stats.total_objects += 1
            if match_pattern.match(token):
                stats.value_sum += 1
                prune_objects += 1
                token_dict[token] += 1

        # prune the hash if it gets too large
        if prune_objects >= settings.key_prune_interval:
            token_dict = _prune_keys(token_dict, settings, stats)
            prune_objects = 0

        if time.time() > next_stat:
            logger.debug(
                f"tokens/lines examined: {stats.total_objects:,d}"
                f" ; hash prunes: {stats.prune_count:,d}..."
            )
            next_stat = time.time() + settings.stat_interval

    return token_dict


def _prune_keys(
    token_dict: Counter[str], settings: Settings, stats: Stats
) -> Counter[str]:
    """Keep only the top max_keys entries in the token dict."""
    stats.prune_count += 1
    return Counter(dict(token_dict.most_common(settings.max_keys)))


def read_pretallied_tokens(
    settings: Settings,
    stats: Stats,
    *,
    stream: TextIO | None = None,
) -> Counter[str]:
    """Read pre-counted key/value pairs from stdin.

    Input is already tallied (as in `du -sb`). vk means the number
    is first and key second; kv means key first and number second.
    """
    stream = stream or sys.stdin
    token_dict: Counter[str] = Counter()

    if settings.graph_values == "vk":
        pattern = re.compile(r"^\s*(\d+)\s+(.+)$")
        value_group, key_group = 1, 2
        hint = "kv"
    else:
        pattern = re.compile(r"^(.+?)\s+(\d+)$")
        value_group, key_group = 2, 1
        hint = "vk"

    for line in stream:
        match = pattern.match(line)
        if not match:
            logger.warning(
                f" E Input malformed+discarded (perhaps pass -g={hint}?): {line}"
            )
            continue
        value = int(match.group(value_group))
        token_dict[match.group(key_group)] += value
        stats.total_objects += 1

    stats.value_sum = sum(token_dict.values())
    return token_dict


def read_numerics(
    settings: Settings, stats: Stats, *, stream: TextIO | None = None
) -> NumericData:
    """Read raw numbers from stdin and return graph data.

    Unlike the main histogram pipeline, numeric mode is a simpler
    visualisation: it graphs every value without aggregation, totals,
    or per-key percentages.  All values are graphed — --height and
    --size are intentionally ignored so nothing is thrown away.
    """
    stream = stream or sys.stdin
    last_value = 0.0
    output_list: list[float] = []
    first_line = True
    for raw_line in stream:
        try:
            numeric = float(raw_line.rstrip())
        except ValueError:
            numeric = last_value

        graph_value = 0.0
        if settings.numeric_mode == "mon":
            if not first_line:
                graph_value = numeric - last_value
            last_value = numeric
        else:
            graph_value = numeric

        if settings.numeric_mode != "mon" or not first_line:
            output_list.append(graph_value)
        first_line = False
        stats.total_objects += 1

    max_value = max(output_list, default=0.0)
    return NumericData(
        output_list,
        max_value,
        sum(output_list),
        len(str(max_value)) if output_list else 0,
    )


def write_hist(  # pylint: disable=too-many-locals
    settings: Settings,
    stats: Stats,
    token_dict: Counter[str],
    *,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> None:
    """Sort token_dict by frequency and print a histogram to stdout.

    Sorts by (count, key) descending so ties are broken deterministically
    by key name.  Headers go to stderr; data lines carry no colour prefix
    so output can be piped to sort.

    Every row is rendered as a percentage of stats.value_sum; when that is
    zero, percentages render as 0.00% rather than dividing by zero.
    """
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr

    output_dict: dict[str, int] = {}
    for key in sorted(token_dict, key=lambda k: (token_dict[k], k), reverse=True):
        if not key:
            # re.split() produces empty strings at boundaries, and blank
            # input lines become "".  Callers filter these, but guard here
            # too: an empty key would render a broken row with no label.
            continue
        output_dict[key] = token_dict[key]
        if len(output_dict) >= settings.height:
            break

    if not output_dict:
        reason = "All input filtered" if stats.total_objects > 0 else "No input"
        raise EmptyInputError(reason)

    max_value = max(output_dict.values())

    # verbose timing stats
    stats.end_time = time.monotonic()
    elapsed_ms = (stats.end_time - stats.start_time) * 1000
    logger.debug(f"tokens/lines examined: {stats.total_objects:,d}")
    logger.debug(f" tokens/lines matched: {stats.value_sum:,d}")
    logger.debug(f"       histogram keys: {len(token_dict):,d}")
    logger.debug(f"              runtime: {elapsed_ms:,.2f}ms")

    # compute layout widths from the highest count
    layout = _hist_layout(output_dict, stats.value_sum, settings.width)

    print(
        f"{'Key':>{layout.max_token_length}}|{'Ct':<{layout.max_value_width}} "
        f"{'(Pct)':<{layout.max_percent_width}} Histogram{settings.key_colour}",
        file=stderr,
    )

    # render bars
    keys = list(output_dict)
    for index, key in enumerate(keys):
        output_value = str(output_dict[key])
        pct = output_dict[key] / stats.value_sum * 100 if stats.value_sum else 0.0
        percent = f"({pct:2.2f}%)"
        bar = histogram_bar(
            layout.histogram_width,
            max_value,
            output_dict[key],
            settings,
        )
        # last line resets to regular_colour; all others continue key_colour.
        # FIXME: even with these colour-placement antics, one key will
        # still be printed with the wrong colour on sorted output most
        # of the time. The only real fix would be to sort within the
        # script itself.
        end_colour = (
            settings.regular_colour if index == len(keys) - 1 else settings.key_colour
        )
        print(
            f"{key:>{layout.max_token_length}}{settings.regular_colour}|"
            f"{settings.count_colour}{output_value:>{layout.max_value_width}} "
            f"{settings.percent_colour}{percent:>{layout.max_percent_width}} "
            f"{settings.graph_colour}{bar}{end_colour}",
            file=stdout,
        )


def _hist_layout(
    output_dict: dict[str, int], value_sum: int, display_width: int
) -> HistLayout:
    """Compute column widths from the filtered output dict.

    output_dict must be non-empty; the count and percentage columns are sized
    from its largest value, so any ordering is safe.
    """
    max_token_length = max(len(k) for k in output_dict)
    max_value = max(output_dict.values())
    max_value_width = len(str(max_value))
    max_percent = max_value / value_sum * 100 if value_sum else 0.0
    max_percent_width = len(f"({max_percent:2.2f}%)")
    histogram_width = (
        display_width
        - (max_token_length + 1)
        - (max_value_width + 1)
        - (max_percent_width + 1)
        - 1
    )
    return HistLayout(
        max_token_length, max_value_width, max_percent_width, histogram_width
    )


def histogram_bar(
    histogram_width: int,
    max_value: float,
    bar_value: float,
    settings: Settings,
) -> str:
    """Return a histogram bar string scaled to the given value.

    The bar has two parts: a run of full-width characters sized to the
    integer portion of the scaled width, then a single trailing character
    — either full-width or a partial-width Unicode glyph chosen to
    represent the fractional remainder.
    """
    bar = ""

    if settings.char_width < 1:
        zero_char = settings.graph_chars[-1]
        one_char = ""
    elif len(settings.histogram_char) > 1:
        zero_char, one_char = settings.histogram_char[0], settings.histogram_char[1]
    else:
        zero_char = one_char = settings.histogram_char

    if max_value == 0:
        return one_char or zero_char

    if settings.logarithmic:
        max_log = math.log(max_value)
        bar_log = math.log(bar_value) if bar_value > 0 else 0
        scaled = bar_log / max_log * histogram_width
    else:
        scaled = bar_value / max_value * histogram_width
    integer_width = int(scaled)
    remainder_width = scaled - integer_width

    bar += zero_char * integer_width

    # FIXME: The remainder partial char printed does not take into
    # account logarithmic scale (can humans notice?).
    if settings.char_width == 1:
        bar += one_char
    elif settings.char_width < 1:
        if remainder_width > settings.char_width:
            # high-resolution: figure out what partial-width char to use
            which_char = int(remainder_width / settings.char_width)
            bar += settings.graph_chars[which_char]
        else:
            # minimum-width character so we always see something
            bar += settings.graph_chars[0]

    return bar


def render_numeric_graph(
    settings: Settings, data: NumericData, *, stdout: TextIO | None = None
) -> None:
    """Print a simple bar graph for numeric values.

    This is deliberately simpler than write_hist: no key labels, no
    height limit, no sorting.  Every input value gets a bar.
    """
    stdout = stdout or sys.stdout
    for value in data.values:
        pct = value / data.total_value * 100 if data.total_value else 0
        percent = f"({pct:2.2f}%)"
        bar = histogram_bar(
            settings.width - 11 - data.max_width,
            data.max_value,
            value,
            settings,
        )
        print(
            f"{settings.key_colour}{int(value):>{data.max_width}}"
            f"{settings.percent_colour}{percent:>9} "
            f"{settings.graph_colour}{bar}{settings.regular_colour}",
            file=stdout,
        )


@dataclass
class Stats:
    """Runtime counters accumulated during input processing."""

    total_objects: int = 0
    value_sum: int = 0
    prune_count: int = 0
    start_time: float = field(default_factory=time.monotonic)
    end_time: float = 0.0


class NumericData(NamedTuple):
    """Data returned by read_numerics for rendering a numeric graph."""

    values: list[float]
    max_value: float
    total_value: float
    max_width: int


class HistLayout(NamedTuple):
    """Pre-computed column widths for histogram rendering."""

    max_token_length: int
    max_value_width: int
    max_percent_width: int
    histogram_width: int


class EmptyInputError(Exception):
    """Raised when there is no data to display."""


DEFAULT_RCFILE = "~/.distributionrc"
DEFAULT_PALETTE = "0,0,32,35,34"
DEFAULT_MAX_KEYS = 5000
PALETTE_FIELDS = 5  # regular, key, count, percent, graph
SIZE_PRESETS: dict[str, tuple[int, int]] = {
    name: dimensions
    for dimensions, names in [
        ((60, 10), ("small", "sm", "s")),
        ((100, 20), ("medium", "med", "m")),
        ((140, 35), ("large", "lg", "l")),
    ]
    for name in names
}
FULL_SIZE_ALIASES = ("full", "fl", "f")
PARTIAL_BLOCKS = ("▏", "▎", "▍", "▌", "▋", "▊", "▉", "█")  # char=pb
PARTIAL_LINES = ("╸", "╾", "━")  # char=pl


def settings_from_args(args: argparse.Namespace) -> Settings:
    """Create Settings from command-line arguments and config file."""
    # TODO: these duplicate the Settings field defaults; the two can drift.
    width = 80
    height = 15

    # the parser's choices= has already rejected any other non-empty --size
    if args.size in FULL_SIZE_ALIASES:
        width, height = shutil.get_terminal_size()
        height -= 3
        if args.verbose:
            height -= 4  # need room for the verbosity output
        width = max(width, 40)
        height = max(height, 10)
    elif args.size in SIZE_PRESETS:
        width, height = SIZE_PRESETS[args.size]

    # explicit --width/--height override everything
    if args.width:
        width = args.width
    if args.height:
        height = args.height

    colourised_output = args.color or args.palette != DEFAULT_PALETTE

    settings = Settings(
        width=width,
        height=height,
        histogram_char=args.char,
        logarithmic=args.logarithmic,
        verbose=args.verbose,
        colourised_output=colourised_output,
        colour_palette=args.palette,
        tokenize=args.tokenize,
        match_regexp=args.match,
        graph_values=args.graph,
        numeric_mode=args.numonly,
        max_keys=args.keys,
    )

    # max_keys was silently floored by __post_init__; report if verbose
    if args.keys < settings.max_keys:
        logger.debug(f"Updated max_keys to {settings.max_keys} (height + 3000)")

    return settings


def _parse_args(
    argv: Sequence[str] | None = None,
    *,
    default_rcfile: str = DEFAULT_RCFILE,
) -> argparse.Namespace:
    """Two-pass parse: discover --rcfile from argv, then re-parse with rcfile defaults.

    If --rcfile is given, use that file; otherwise fall back to
    default_rcfile.  The rcfile is read as a set of defaults that
    CLI arguments override.  argv defaults to sys.argv[1:]; both
    parameters exist so callers (and tests) need not touch global state.
    """
    # Two passes are inherent: we must read CLI args to learn the rcfile path
    # before we can load its defaults underneath.
    parser = _build_parser()

    # Pass 1: discover which rcfile to load.
    cli_args = parser.parse_args(argv)
    # FIXME: an empty --rcfile= is falsy, so it silently falls back to
    # default_rcfile rather than reporting that no path was given.
    rcfile = Path(cli_args.rcfile or default_rcfile).expanduser()

    if not rcfile.is_file():
        if cli_args.rcfile:
            parser.error(f"rcfile not found: {rcfile}")
        return cli_args

    # Pass 2: re-parse with rcfile values as the base layer; CLI args override.
    parser.rcfile_path = str(rcfile)
    rcfile_defaults = parser.parse_args([f"@{rcfile}"])
    parser.rcfile_path = ""
    return parser.parse_args(argv, namespace=rcfile_defaults)


@dataclass
class Settings:
    """Display parameters for histogram rendering."""

    width: int = 80
    height: int = 15
    histogram_char: str = "-"
    char_width: float = 1.0
    graph_chars: list[str] = field(default_factory=list)
    logarithmic: bool = False
    verbose: bool = False
    colourised_output: bool = False
    colour_palette: str = DEFAULT_PALETTE
    regular_colour: str = ""
    key_colour: str = ""
    count_colour: str = ""
    percent_colour: str = ""
    graph_colour: str = ""
    tokenize: str = ""
    match_regexp: str = "."
    graph_values: str = ""
    numeric_mode: str = ""
    max_keys: int = DEFAULT_MAX_KEYS
    stat_interval: float = 1.0
    key_prune_interval: int = 1500000

    def __post_init__(self) -> None:
        """Resolve aliases, histogram char, colours, and max_keys floor."""
        self._resolve_aliases()
        self._resolve_histogram_char()
        self._resolve_colours()
        self.max_keys = max(self.max_keys, self.height + 3000)

    def _resolve_aliases(self) -> None:
        """Expand tokenize/match/numeric_mode aliases into actual values."""
        tokenize_aliases = {"white": r"\s+", "word": r"\W"}
        self.tokenize = tokenize_aliases.get(self.tokenize, self.tokenize)
        match_aliases = {"word": r"^[A-Z,a-z]+$", "num": r"^\d+$", "number": r"^\d+$"}
        self.match_regexp = match_aliases.get(self.match_regexp, self.match_regexp)

        # synonyms "monotonically-increasing": derivative, difference, delta, increasing
        # so all "d" "i" and "m" words will be graphing those differences
        # synonyms "actual values": absolute, actual, number, normal, noop,
        # so all "a" and "n" words will graph straight up numbers
        if self.numeric_mode:
            if self.numeric_mode[0] in {"d", "i", "m"}:
                self.numeric_mode = "mon"
            elif self.numeric_mode[0] in {"a", "n"}:
                self.numeric_mode = "abs"

    def _resolve_colours(self) -> None:
        """Expand the colour palette string into ANSI escape codes."""
        if self.colourised_output:
            colours = self.colour_palette.split(",")
            # ANSI color code is ESC+[+NN+m where ESC=chr(27), [ and m are
            # the literal characters, and NN is a two-digit number, typically
            # from 31 to 37 - why is this knowledge still useful in 2014?
            colours = [f"\033[{code}m" for code in colours]
            # _palette_arg() has already rejected any other field count
            (
                self.regular_colour,
                self.key_colour,
                self.count_colour,
                self.percent_colour,
                self.graph_colour,
            ) = colours

    def _resolve_histogram_char(self) -> None:
        """Apply character substitutions and set up partial-width graphing."""
        char_substitutions = {
            "ba": "▬",
            "bl": "Ξ",
            "em": "—",
            "me": "⋯",
            "di": "♦",
            "dt": "•",
            "sq": "□",
        }
        self.histogram_char = char_substitutions.get(
            self.histogram_char, self.histogram_char
        )

        # sub-full character width graphing systems
        if self.histogram_char == "pb":
            self.char_width = 0.125
            self.graph_chars = list(PARTIAL_BLOCKS)
        elif self.histogram_char == "pl":
            self.char_width = 0.3334
            self.graph_chars = list(PARTIAL_LINES)


def _palette_arg(value: str) -> str:
    """Reject a palette that does not name exactly five colours."""
    if len(value.split(",")) != PALETTE_FIELDS:
        msg = f"expected {PALETTE_FIELDS} comma-separated colours: {value!r}"
        raise argparse.ArgumentTypeError(msg)
    return value


def _build_parser() -> DistributionParser:
    """Build the argument parser with all options defined."""
    parser = DistributionParser(
        fromfile_prefix_chars="@",
        usage="<command_with_output> | %(prog)s [options]",
        description=__doc__,
        epilog=(
            "Samples:\n"
            "  du -sb /etc/* | %(prog)s --palette=0,37,34,33,32 --graph\n"
            "  du -sk /etc/* | awk '{print $2\" \"$1}' | %(prog)s --graph=kv\n"
            "  zcat /var/log/syslog*gz | %(prog)s --char=o --tokenize=white\n"
            "  zcat /var/log/syslog*gz | awk '{print $5}' | %(prog)s -t word -m word -H 15 -c /\n"
            "  zcat /var/log/syslog*gz | cut -c 1-9 | %(prog)s --width=60 --height=10 --char=em\n"
            "  find /etc -type f | cut -c 6- | %(prog)s --tokenize=/ -w 90 -H 35 -c dt\n"
            "  cat /usr/share/dict/words | awk '{print length($1)}'"
            " | %(prog)s -c '*' -w 50 -H 10 | sort -n"
        ),
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "--rcfile",
        default=None,
        metavar="F",
        help=f"use this rcfile instead of {DEFAULT_RCFILE}",
    )
    # TODO: the store_true flags below (--color, --logarithmic, --verbose) have
    # no negative form, so once an rcfile enables one there is no command line
    # that turns it back off. argparse.BooleanOptionalAction would add --no-*.
    parser.add_argument(
        "--color", "--colour", action="store_true", help="colourise the output"
    )
    parser.add_argument(
        "-g",
        "--graph",
        nargs="?",
        const="vk",
        default="",
        metavar="G",
        help="input is already key/value pairs. vk is default:\n"
        "  kv   input is ordered key then value\n"
        "  vk   input is ordered value then key",
    )
    parser.add_argument(
        "-l", "--logarithmic", action="store_true", help="logarithmic graph"
    )
    parser.add_argument(
        "-n",
        "--numonly",
        nargs="?",
        const="abs",
        default="",
        metavar="N",
        help="input is numerics, simply graph values without labels\n"
        "  actual   input is just values (default)\n"
        "  diff     input monotonically-increasing, graph differences",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="be verbose")
    parser.add_argument(
        "-w",
        "--width",
        type=int,
        default=0,
        metavar="N",
        help="width of the histogram report, overrides --size",
    )
    parser.add_argument(
        "-H",
        "--height",
        type=int,
        default=0,
        metavar="N",
        help="height of histogram, headers non-inclusive, overrides --size",
    )
    parser.add_argument(
        "-k",
        "--keys",
        type=int,
        default=DEFAULT_MAX_KEYS,
        metavar="K",
        # FIXME: the first %(default)s renders this option's own default, so the
        # help claims pruning happens every 5000 values. The real interval is
        # Settings.key_prune_interval (1,500,000), which has no CLI option.
        help="prune hash to K keys every %(default)s values (default: %(default)s)",
    )
    parser.add_argument(
        "-c",
        "--char",
        default="-",
        metavar="C",
        help="character(s) to use for histogram bars, or a substitution:\n"
        "  pl   1/3-width unicode partial lines (3x resolution)\n"
        "  pb   1/8-width unicode partial blocks (8x resolution)\n"
        "  ba   (▬) Bar\n"
        "  bl   (Ξ) Building\n"
        "  em   (—) Emdash\n"
        "  me   (⋯) Mid-Elipses\n"
        "  di   (♦) Diamond\n"
        "  dt   (•) Dot\n"
        "  sq   (□) Square",
    )
    parser.add_argument(
        "-p",
        "--palette",
        type=_palette_arg,
        default=DEFAULT_PALETTE,
        metavar="P",
        help="comma-separated ANSI colour values: regular,key,count,pct,graph\nimplies --color",
    )
    parser.add_argument(
        "-s",
        "--size",
        choices=(*SIZE_PRESETS, *FULL_SIZE_ALIASES),
        default="",
        metavar="S",
        help="size of histogram, overridden by --width/--height:\n"
        "  small    60x10\n"
        "  medium   100x20\n"
        "  large    140x35\n"
        "  full     terminal width x terminal height",
    )
    parser.add_argument(
        "-t",
        "--tokenize",
        default="",
        metavar="RE",
        help="split input on regexp RE and make histogram of resulting tokens\n"
        "  word    split on non-word characters\n"
        "  white   split on whitespace",
    )
    parser.add_argument(
        "-m",
        "--match",
        default=".",
        metavar="RE",
        help="only match lines/tokens matching this regexp:\n"
        "  word   tokens/lines must be entirely alphabetic\n"
        "  num    tokens/lines must be entirely numeric",
    )
    return parser


class DistributionParser(argparse.ArgumentParser):
    """Strip comments and blank lines from @-included config files."""

    rcfile_path: str = ""

    def error(self, message: str) -> NoReturn:
        """Prepend rcfile path to the error message when set."""
        if self.rcfile_path:
            message = f"in {self.rcfile_path}: {message}"
        super().error(message)

    def convert_arg_line_to_args(self, arg_line: str) -> list[str]:
        """Return non-empty, non-comment lines from config files."""
        stripped = arg_line.strip()
        if stripped and not stripped.startswith("#"):
            return [stripped]
        return []


if __name__ == "__main__":
    main()
