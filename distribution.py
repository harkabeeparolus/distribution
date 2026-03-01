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
import math
import re
import shutil
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import NamedTuple

DEFAULT_PALETTE = "0,0,32,35,34"
DEFAULT_MAX_KEYS = 5000


@dataclass
class Stats:
    """Runtime counters accumulated during input processing."""

    total_objects: int = 0
    total_values: int = 0
    prune_count: int = 0
    start_time: float = field(default_factory=time.monotonic)
    end_time: float = 0.0


class EmptyInputError(Exception):
    """Raised when there is no data to display."""


class DistributionParser(argparse.ArgumentParser):
    """Strip comments and blank lines from @-included config files."""

    def convert_arg_line_to_args(self, arg_line: str) -> list[str]:
        """Return non-empty, non-comment lines from config files."""
        stripped = arg_line.strip()
        if stripped and not stripped.startswith("#"):
            return [stripped]
        return []


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

    one_char = ""
    if settings.char_width < 1:
        zero_char = settings.graph_chars[-1]
    elif len(settings.histogram_char) > 1:
        zero_char = settings.histogram_char[0]
        one_char = settings.histogram_char[1]
    else:
        zero_char = settings.histogram_char
        one_char = settings.histogram_char

    if settings.logarithmic:
        max_log = math.log(max_value)
        bar_log = math.log(bar_value) if bar_value > 0 else 0
        integer_width = int(bar_log / max_log * histogram_width)
        remainder_width = (bar_log / max_log * histogram_width) - integer_width
    else:
        integer_width = int(bar_value / max_value * histogram_width)
        remainder_width = (bar_value / max_value * histogram_width) - integer_width

    bar += zero_char * integer_width

    # FIXME: The remainder partial char printed does not take into  # noqa: FIX001
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


class HistLayout(NamedTuple):
    """Pre-computed column widths for histogram rendering."""

    max_token_length: int
    max_value_width: int
    max_percent_width: int
    histogram_width: int


def _hist_layout(
    output_dict: dict[str, int], total_values: int, display_width: int
) -> HistLayout:
    """Compute column widths from the filtered output dict."""
    max_token_length = max(len(k) for k in output_dict)
    first_value = next(iter(output_dict.values()))
    max_value_width = len(str(first_value))
    max_percent_width = len(f"({first_value / total_values * 100:2.2f}%)")
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


def write_hist(settings: Settings, stats: Stats, token_dict: Counter[str]) -> None:
    """Sort token_dict by frequency and print a histogram to stdout.

    Sorts by (count, key) descending so ties are broken deterministically
    by key name.  Headers go to stderr; data lines carry no colour prefix
    so output can be piped to sort.
    """
    output_dict: dict[str, int] = {}
    max_value = 0
    for key in sorted(token_dict, key=lambda k: (token_dict[k], k), reverse=True):
        if not key:
            # re.split() produces empty strings at boundaries, and blank
            # input lines become "".  Callers filter these, but guard here
            # too: an empty key would render a broken row with no label.
            continue
        output_dict[key] = token_dict[key]
        max_value = max(max_value, output_dict[key])
        if len(output_dict) >= settings.height:
            break

    if not output_dict:
        reason = "All input filtered" if stats.total_objects > 0 else "No input"
        raise EmptyInputError(reason)

    # verbose timing stats
    stats.end_time = time.monotonic()
    elapsed_ms = (stats.end_time - stats.start_time) * 1000
    if settings.verbose:
        print(
            f"tokens/lines examined: {stats.total_objects:,d}",
            file=sys.stderr,
        )
        print(
            f" tokens/lines matched: {stats.total_values:,d}",
            file=sys.stderr,
        )
        print(f"       histogram keys: {len(token_dict):,d}", file=sys.stderr)
        print(f"              runtime: {elapsed_ms:,.2f}ms", file=sys.stderr)

    # compute layout widths from the highest-frequency entry
    layout = _hist_layout(output_dict, stats.total_values, settings.width)

    print(
        f"{'Key':>{layout.max_token_length}}|{'Ct':<{layout.max_value_width}} "
        f"{'(Pct)':<{layout.max_percent_width}} Histogram{settings.key_colour}",
        file=sys.stderr,
    )

    # render bars
    keys = list(output_dict)
    for index, key in enumerate(keys):
        output_value = str(output_dict[key])
        percent = f"({output_dict[key] / stats.total_values * 100:2.2f}%)"
        bar = histogram_bar(
            layout.histogram_width,
            max_value,
            output_dict[key],
            settings,
        )
        # last line resets to regular_colour; all others continue key_colour.
        # FIXME: even with these colour-placement antics, one key will  # noqa: FIX001
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
            f"{settings.graph_colour}{bar}{end_colour}"
        )


def _prune_keys(
    token_dict: Counter[str], settings: Settings, stats: Stats
) -> Counter[str]:
    """Keep only the top max_keys entries in the token dict."""
    stats.prune_count += 1
    return Counter(dict(token_dict.most_common(settings.max_keys)))


def tokenize_input(settings: Settings, stats: Stats) -> Counter[str]:
    """Split stdin lines into tokens and count their frequency.

    Splits on whitespace or word boundaries by default, but the user
    can specify any regexp. Likewise, matching defaults to everything
    but can be restricted to all-alpha or all-numeric tokens.
    """
    token_dict: Counter[str] = Counter()

    # docs say these are cached, but i got about 2x speed boost
    # from doing the compile
    should_tokenize = bool(settings.tokenize)
    tokenize_pattern = re.compile(settings.tokenize)
    match_pattern = re.compile(settings.match_regexp)

    next_stat = time.time() + settings.stat_interval

    prune_objects = 0
    for raw_line in sys.stdin:
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
                stats.total_values += 1
                prune_objects += 1
                token_dict[token] += 1

        # prune the hash if it gets too large
        if prune_objects >= settings.key_prune_interval:
            token_dict = _prune_keys(token_dict, settings, stats)
            prune_objects = 0

        if settings.verbose and time.time() > next_stat:
            print(
                f"tokens/lines examined: {stats.total_objects:,d} ; hash prunes: {stats.prune_count:,d}...",
                end="\r",
                file=sys.stderr,
            )
            next_stat = time.time() + settings.stat_interval

    return token_dict


def read_pretallied_tokens(settings: Settings, stats: Stats) -> Counter[str]:
    """Read pre-counted key/value pairs from stdin.

    Input is already tallied (as in `du -sb`). vk means the number
    is first and key second; kv means key first and number second.
    """
    token_dict: Counter[str] = Counter()
    value_key_pattern = re.compile(r"^\s*(\d+)\s+(.+)$")
    key_value_pattern = re.compile(r"^(.+?)\s+(\d+)$")
    if settings.graph_values == "vk":
        for line in sys.stdin:
            match = value_key_pattern.match(line)
            if not match:
                print(
                    f" E Input malformed+discarded (perhaps pass -g=kv?): {line}",
                    file=sys.stderr,
                )
                continue
            token_dict[match.group(2)] += int(match.group(1))
            stats.total_values += int(match.group(1))
            stats.total_objects += 1
    elif settings.graph_values == "kv":
        for line in sys.stdin:
            match = key_value_pattern.match(line)
            if not match:
                print(
                    f" E Input malformed+discarded (perhaps pass -g=vk?): {line}",
                    file=sys.stderr,
                )
                continue
            token_dict[match.group(1)] += int(match.group(2))
            stats.total_values += int(match.group(2))
            stats.total_objects += 1
    return token_dict


class NumericData(NamedTuple):
    """Data returned by read_numerics for rendering a numeric graph."""

    values: list[float]
    max_value: float
    total_value: float
    max_width: int


def read_numerics(settings: Settings, stats: Stats) -> NumericData:
    """Read raw numbers from stdin and return graph data.

    Unlike the main histogram pipeline, numeric mode is a simpler
    visualisation: it graphs every value without aggregation, totals,
    or per-key percentages.  All values are graphed — --height and
    --size are intentionally ignored so nothing is thrown away.
    """
    last_value = 0.0
    max_value = 0.0
    max_width = 0
    total_value = 0.0
    output_list: list[float] = []
    first_line = True
    for raw_line in sys.stdin:
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

        if graph_value > max_value:
            max_value = graph_value
            max_width = len(str(graph_value))

        total_value += graph_value

        if not first_line:
            output_list.append(graph_value)
        first_line = False
        stats.total_objects += 1

    return NumericData(output_list, max_value, total_value, max_width)


def render_numeric_graph(settings: Settings, data: NumericData) -> None:
    """Print a simple bar graph for numeric values.

    This is deliberately simpler than write_hist: no key labels, no
    height limit, no sorting.  Every input value gets a bar.
    """
    for value in data.values:
        percent = f"({value / data.total_value * 100:2.2f}%)"
        bar = histogram_bar(
            settings.width - 11 - data.max_width,
            data.max_value,
            value,
            settings,
        )
        print(
            f"{settings.key_colour}{int(value):>{data.max_width}}"
            f"{settings.percent_colour}{percent:>9} "
            f"{settings.graph_colour}{bar}{settings.regular_colour}"
        )


def _build_parser() -> DistributionParser:
    """Build the argument parser with all options defined."""
    parser = DistributionParser(
        fromfile_prefix_chars="@",
        usage="<commandWithOutput> | %(prog)s [options]",
        description=__doc__,
        epilog=(
            "Samples:\n"
            "  du -sb /etc/* | %(prog)s --palette=0,37,34,33,32 --graph\n"
            "  du -sk /etc/* | awk '{print $2\" \"$1}' | %(prog)s --graph=kv\n"
            "  zcat /var/log/syslog*gz | %(prog)s --char=o --tokenize=white\n"
            "  zcat /var/log/syslog*gz | awk '{print $5}' | %(prog)s -t word -m word -H 15 -c /\n"
            "  zcat /var/log/syslog*gz | cut -c 1-9 | %(prog)s --width=60 --height=10 --char=em\n"
            "  find /etc -type f | cut -c 6- | %(prog)s --tokenize=/ -w 90 -H 35 -c dt\n"
            "  cat /usr/share/dict/words | awk '{print length($1)}' | %(prog)s -c '*' -w 50 -H 10 | sort -n"
        ),
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "--rcfile",
        default=None,
        metavar="F",
        help="use this rcfile instead of ~/.distributionrc",
    )
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
        default=None,
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
        default=DEFAULT_PALETTE,
        metavar="P",
        help="comma-separated ANSI colour values: regular,key,count,pct,graph\nimplies --color",
    )
    parser.add_argument(
        "-s",
        "--size",
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


def _parse_args() -> argparse.Namespace:
    """Run two-pass parsing: CLI args first, then rcfile defaults underneath.

    If --rcfile is given, use that file; otherwise fall back to
    ~/.distributionrc.  The rcfile is read as a set of defaults that
    CLI arguments override.
    """
    parser = _build_parser()
    first_pass = parser.parse_args()
    if first_pass.rcfile is not None:
        rcfile = Path(first_pass.rcfile).expanduser()
    else:
        rcfile = Path.home() / ".distributionrc"
    defaults = [f"@{rcfile}"] if rcfile.is_file() else []
    return parser.parse_args(namespace=parser.parse_args(defaults))


class Settings:
    """Parse config file and command-line arguments into display parameters."""

    def __init__(self) -> None:
        """Load defaults, then overlay rcfile and CLI arguments."""
        args = _parse_args()

        # display dimensions (overridden by _resolve_size)
        self.width = 80
        self.height = 15
        # fields not controlled by argparse
        self.stat_interval = 1.0
        self.key_prune_interval = 1500000
        self.regular_colour = ""
        self.key_colour = ""
        self.count_colour = ""
        self.percent_colour = ""
        self.graph_colour = ""
        self.char_width = 1.0
        self.graph_chars: list[str] = []
        self.partial_blocks = ["▏", "▎", "▍", "▌", "▋", "▊", "▉", "█"]  # char=pb
        self.partial_lines = ["╸", "╾", "━"]  # char=pl

        # fields from argparse
        self.colourised_output: bool = args.color or args.palette != DEFAULT_PALETTE
        self.graph_values: str = args.graph
        self.logarithmic: bool = args.logarithmic
        self.numeric_mode: str | None = args.numonly
        self.verbose: bool = args.verbose
        self.max_keys: int = args.keys
        self.histogram_char: str = args.char
        self.tokenize: str = args.tokenize
        self.match_regexp: str = args.match
        self.colour_palette: str = args.palette

        # resolve tokenize/match aliases into actual regexps
        tokenize_aliases = {"white": r"\s+", "word": r"\W"}
        if self.tokenize in tokenize_aliases:
            self.tokenize = tokenize_aliases[self.tokenize]
        match_aliases = {"word": r"^[A-Z,a-z]+$", "num": r"^\d+$", "number": r"^\d+$"}
        if self.match_regexp in match_aliases:
            self.match_regexp = match_aliases[self.match_regexp]

        # synonyms "monotonically-increasing": derivative, difference, delta, increasing
        # so all "d" "i" and "m" words will be graphing those differences
        # synonyms "actual values": absolute, actual, number, normal, noop,
        # so all "a" and "n" words will graph straight up numbers
        if self.numeric_mode is not None:
            if self.numeric_mode[0] in ("d", "i", "m"):
                self.numeric_mode = "mon"
            elif self.numeric_mode[0] in ("a", "n"):
                self.numeric_mode = "abs"

        self._resolve_size(args.size, args.width, args.height)
        self._resolve_colours()
        self._resolve_histogram_char()

    def _resolve_size(self, size: str, width_arg: int, height_arg: int) -> None:
        """Apply size presets, terminal size, and explicit width/height overrides."""
        size_presets = {}
        for names, dimensions in [
            (("small", "sm", "s"), (60, 10)),
            (("medium", "med", "m"), (100, 20)),
            (("large", "lg", "l"), (140, 35)),
        ]:
            for name in names:
                size_presets[name] = dimensions
        if size in ("full", "fl", "f"):
            self.width, self.height = shutil.get_terminal_size()
            self.height -= 3
            if self.verbose:
                self.height -= 4  # need room for the verbosity output
            self.width = max(self.width, 40)
            self.height = max(self.height, 10)
        elif size in size_presets:
            self.width, self.height = size_presets[size]

        # explicit --width/--height override everything
        if width_arg != 0:
            self.width = width_arg
        if height_arg != 0:
            self.height = height_arg

        # max_keys should be at least a few thousand greater than height to reduce odds
        # of throwing away high-count values that appear sparingly in the data
        if self.max_keys < self.height + 3000:
            self.max_keys = self.height + 3000
            if self.verbose:
                print(
                    f"Updated max_keys to {self.max_keys} (height + 3000)",
                    file=sys.stderr,
                )

    def _resolve_colours(self) -> None:
        """Expand the colour palette string into ANSI escape codes."""
        if self.colourised_output:
            colours = self.colour_palette.split(",")
            # ANSI color code is ESC+[+NN+m where ESC=chr(27), [ and m are
            # the literal characters, and NN is a two-digit number, typically
            # from 31 to 37 - why is this knowledge still useful in 2014?
            colours = [f"\033[{code}m" for code in colours]
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
        if self.histogram_char in char_substitutions:
            self.histogram_char = char_substitutions[self.histogram_char]

        # sub-full character width graphing systems
        if self.histogram_char == "pb":
            self.char_width = 0.125
            self.graph_chars = self.partial_blocks
        elif self.histogram_char == "pl":
            self.char_width = 0.3334
            self.graph_chars = self.partial_lines


def main() -> None:
    """Parse arguments, read stdin, and render the histogram."""
    settings = Settings()
    stats = Stats()

    try:
        if settings.graph_values:
            token_dict = read_pretallied_tokens(settings, stats)
            write_hist(settings, stats, token_dict)
        elif settings.numeric_mode is not None:
            numeric_data = read_numerics(settings, stats)
            render_numeric_graph(settings, numeric_data)
        else:
            token_dict = tokenize_input(settings, stats)
            write_hist(settings, stats, token_dict)
    except EmptyInputError as exc:
        print(f"{exc}! No histogram for you.", file=sys.stderr)
        sys.exit(255)


if __name__ == "__main__":
    main()
