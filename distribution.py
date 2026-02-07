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
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

DEFAULT_PALETTE = "0,0,32,35,34"
DEFAULT_MAX_KEYS = 5000


class DistributionParser(argparse.ArgumentParser):
    """Strip comments and blank lines from @-included config files."""

    def convert_arg_line_to_args(self, arg_line: str) -> list[str]:
        """Return non-empty, non-comment lines from config files."""
        stripped = arg_line.strip()
        if stripped and not stripped.startswith("#"):
            return [stripped]
        return []


class Histogram:
    """Render a histogram for the highest-frequency entries in a token dict.

    Takes the token_dict built in the InputReader class and goes through it,
    printing a histogram for each of the highest height entries.
    """

    def histogram_bar(
        self,
        settings: Settings,
        histogram_width: int,
        max_value: float,
        bar_value: float,
    ) -> str:
        """Return a histogram bar string scaled to the given value.

        Given a value and max, return a string of the proper number of
        characters, including unicode partial-width characters.
        """
        bar = ""

        # first case is partial-width chars
        one_char = ""
        if settings.char_width < 1:
            zero_char = settings.graph_chars[-1]
        elif len(settings.histogram_char) > 1:
            zero_char = settings.histogram_char[0]
            one_char = settings.histogram_char[1]
        else:
            zero_char = settings.histogram_char
            one_char = settings.histogram_char

        # write out the full-width integer portion of the histogram
        if settings.logarithmic:
            max_log = math.log(max_value)
            bar_log = math.log(bar_value) if bar_value > 0 else 0
            integer_width = int(bar_log / max_log * histogram_width)
            remainder_width = (bar_log / max_log * histogram_width) - integer_width
        else:
            integer_width = int(bar_value / max_value * histogram_width)
            remainder_width = (bar_value / max_value * histogram_width) - integer_width

        # write the zeroeth character integer_width times...
        bar += zero_char * integer_width

        # we always have at least one remaining char for histogram - if
        # we have full-width chars, then just print it, otherwise do a
        # calculation of how much remainder we need to print
        #
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

    def write_hist(self, settings: Settings, token_dict: Counter[str]) -> None:
        """Sort token_dict by frequency and print a histogram to stdout."""
        max_token_length = 0
        output_dict = {}

        item_count = 0
        max_value = 0
        settings.total_values = int(settings.total_values)

        # sort first by the value of a key, then by the key itself in case
        # of a tie.  this allows us to create deterministic sorts when we have
        # multiple entries in our histogram with the same frequency.
        def value_key_compare(
            token_counts: Counter[str],
        ) -> Callable[[str], tuple[int | None, str]]:
            return lambda key: (token_counts.get(key), key)

        for key in sorted(token_dict, key=value_key_compare(token_dict), reverse=True):
            # can't remember what feature "if key:" adds - i think there's an
            # off-by-one death the script sometimes suffers without it.
            if key:
                output_dict[key] = token_dict[key]
                max_token_length = max(max_token_length, len(key))
                max_value = max(max_value, output_dict[key])
                item_count += 1
                if item_count >= settings.height:
                    break

        settings.end_time = time.monotonic()
        elapsed_ms = (settings.end_time - settings.start_time) * 1000
        if settings.verbose:
            print(
                f"tokens/lines examined: {settings.total_objects:,d}",
                file=sys.stderr,
            )
            print(
                f" tokens/lines matched: {settings.total_values:,d}",
                file=sys.stderr,
            )
            print(f"       histogram keys: {len(token_dict):,d}", file=sys.stderr)
            print(f"              runtime: {elapsed_ms:,.2f}ms", file=sys.stderr)

        # the first entry will determine these values
        histogram_width = 0
        max_value_width = 0
        max_percent_width = 0
        keys = list(output_dict)
        for index, key in enumerate(keys):
            # can't remember what feature "if key:" adds - i think there's an
            # off-by-one death the script sometimes suffers without it.
            if key:
                if max_value_width == 0:
                    max_value_width = len(str(output_dict[key]))
                    max_percent_width = len(
                        f"({output_dict[key] / settings.total_values * 100:2.2f}%)"
                    )

                    # we always output a single histogram char at the end, so
                    # we output one less than actual number here
                    histogram_width = (
                        settings.width
                        - (max_token_length + 1)
                        - (max_value_width + 1)
                        - (max_percent_width + 1)
                        - 1
                    )

                    # output a header; key_colour goes on this line so piping
                    # stdout to sort works (no colour prefix on data lines)
                    print(
                        f"{'Key':>{max_token_length}}|{'Ct':<{max_value_width}} "
                        f"{'(Pct)':<{max_percent_width}} Histogram{settings.key_colour}",
                        file=sys.stderr,
                    )

                output_value = str(output_dict[key])
                percent = f"({output_dict[key] / settings.total_values * 100:2.2f}%)"
                bar = self.histogram_bar(
                    settings, histogram_width, max_value, output_dict[key]
                )
                # print key_colour at end of each line so that piping
                # stdout to sort works (no colour prefix on data lines);
                # on the last line, reset to regular_colour instead
                end_colour = (
                    settings.regular_colour
                    if index == len(keys) - 1
                    else settings.key_colour
                )
                print(
                    f"{key:>{max_token_length}}{settings.regular_colour}|"
                    f"{settings.count_colour}{output_value:>{max_value_width}} "
                    f"{settings.percent_colour}{percent:>{max_percent_width}} "
                    f"{settings.graph_colour}{bar}{end_colour}"
                )


class InputReader:
    """Read stdin and build a token frequency dict.

    Parses input into a dictionary where each key is a token and the value
    is its number of appearances. Prunes the dict after a certain number
    of insertions to prevent OOM on large datasets.
    """

    def __init__(self) -> None:
        """Initialize an empty token frequency counter."""
        self.token_dict: Counter[str] = Counter()

    def prune_keys(self, settings: Settings) -> None:
        """Keep only the top max_keys entries in the token dict."""
        new_dict: Counter[str] = Counter()
        keys_transferred = 0
        for key in sorted(
            self.token_dict, key=self.token_dict.__getitem__, reverse=True
        ):
            if key:
                new_dict[key] = self.token_dict[key]
                keys_transferred += 1
                if keys_transferred > settings.max_keys:
                    break
        self.token_dict = new_dict
        settings.prune_count += 1

    def tokenize_input(self, settings: Settings) -> None:  # noqa: C901
        """Split stdin lines into tokens and count their frequency.

        Splits on whitespace or word boundaries by default, but the user
        can specify any regexp. Likewise, matching defaults to everything
        but can be restricted to all-alpha or all-numeric tokens.
        """
        if settings.tokenize == "white":
            settings.tokenize = r"\s+"
        elif settings.tokenize == "word":
            settings.tokenize = r"\W"

        # how to match (filter) the input... typically we want either
        # all-alpha or all-numeric, but again, user can specify
        if settings.match_regexp == "word":
            settings.match_regexp = r"^[A-Z,a-z]+$"
        elif settings.match_regexp in ["num", "number"]:
            settings.match_regexp = r"^\d+$"

        # docs say these are cached, but i got about 2x speed boost
        # from doing the compile
        should_tokenize = bool(settings.tokenize)
        tokenize_pattern = re.compile(settings.tokenize)
        match_pattern = re.compile(settings.match_regexp)

        next_stat = time.time() + settings.stat_interval

        prune_objects = 0
        # ruff: disable[PLW2901]
        for line in sys.stdin:
            line = line.rstrip("\n")
            if should_tokenize:
                for token in tokenize_pattern.split(line):
                    # user desires to break line into tokens...
                    settings.total_objects += 1
                    if match_pattern.match(token):
                        settings.total_values += 1
                        prune_objects += 1
                        self.token_dict[token] += 1
            else:
                # user just wants every line to be a token
                settings.total_objects += 1
                if match_pattern.match(line):
                    settings.total_values += 1
                    prune_objects += 1
                    self.token_dict[line] += 1

            # prune the hash if it gets too large
            if prune_objects >= settings.key_prune_interval:
                self.prune_keys(settings)
                prune_objects = 0

            if settings.verbose and time.time() > next_stat:
                print(
                    f"tokens/lines examined: {settings.total_objects:,d} ; hash prunes: {settings.prune_count:,d}...",
                    end="\r",
                    file=sys.stderr,
                )
                next_stat = time.time() + settings.stat_interval
        # ruff: enable[PLW2901]

    def read_pretallied_tokens(self, settings: Settings) -> None:
        """Read pre-counted key/value pairs from stdin.

        Input is already tallied (as in `du -sb`). vk means the number
        is first and key second; kv means key first and number second.
        """
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
                self.token_dict[match.group(2)] += int(match.group(1))
                settings.total_values += int(match.group(1))
                settings.total_objects += 1
        elif settings.graph_values == "kv":
            for line in sys.stdin:
                match = key_value_pattern.match(line)
                if not match:
                    print(
                        f" E Input malformed+discarded (perhaps pass -g=vk?): {line}",
                        file=sys.stderr,
                    )
                    continue
                self.token_dict[match.group(1)] += int(match.group(2))
                settings.total_values += int(match.group(2))
                settings.total_objects += 1

    def read_numerics(self, settings: Settings, histogram: Histogram) -> None:
        """Read raw numbers from stdin and print a simple graph directly.

        Unlike the other modes, output is printed here rather than in
        Histogram, since it is a simpler graph without totals or
        percentages — just a bar for each numeric value or its
        monotonic difference.
        """
        last_value = 0.0
        max_value = 0.0
        max_width = 0
        total_value = 0.0
        output_list: list[float] = []
        # ruff: disable[PLW2901]
        for line in sys.stdin:
            try:
                line = float(line.rstrip())
            except ValueError:
                line = last_value

            graph_value = 0.0
            if settings.numeric_mode == "mon":
                if settings.total_objects > 0:
                    graph_value = line - last_value
                last_value = line
            else:
                graph_value = line

            if graph_value > max_value:
                max_value = graph_value
                max_width = len(str(graph_value))

            total_value += graph_value

            if settings.total_objects > 0:
                output_list.append(graph_value)
            settings.total_objects += 1
        # ruff: enable[PLW2901]

        # simple graphical output
        for value in output_list:
            percent = f"({value / total_value * 100:2.2f}%)"
            bar = histogram.histogram_bar(
                settings, settings.width - 11 - max_width, max_value, value
            )
            print(
                f"{settings.key_colour}{int(value):>{max_width}}"
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

    def __init__(self) -> None:  # noqa: C901, PLR0912, PLR0915
        """Load defaults, then overlay rcfile and CLI arguments."""
        self.start_time = time.monotonic()
        self.end_time = 0.0
        self.width_arg = 0
        self.height_arg = 0
        self.width = 80
        self.height = 15
        self.histogram_char = "-"
        self.colourised_output = False
        self.logarithmic = False
        self.numeric_mode = None
        self.verbose = False
        # whether to parse input into bins, or just present pre-tallied data
        self.graph_values = ""
        self.size = ""
        self.tokenize = ""
        # by default, everything matches (nothing is stripped out)
        self.match_regexp = "."
        # how often to give status if verbose
        self.stat_interval = 1.0
        self.prune_count = 0
        # for colourised output
        self.colour_palette = DEFAULT_PALETTE
        self.regular_colour = ""
        self.key_colour = ""
        self.count_colour = ""
        self.percent_colour = ""
        self.graph_colour = ""
        # for stats
        self.total_objects = 0
        self.total_values = 0
        # every key_prune_interval keys, prune the hash to max_keys top keys
        self.key_prune_interval = 1500000
        self.max_keys = DEFAULT_MAX_KEYS
        # for advanced graphing
        self.char_width = 1.0
        self.graph_chars = []
        self.partial_blocks = ["▏", "▎", "▍", "▌", "▋", "▊", "▉", "█"]  # char=pb
        self.partial_lines = ["╸", "╾", "━"]  # char=hl

        args = _parse_args()

        self.colourised_output = args.color
        self.graph_values = args.graph
        self.logarithmic = args.logarithmic
        self.numeric_mode = args.numonly
        self.verbose = args.verbose
        self.width_arg = args.width
        self.height_arg = args.height
        self.max_keys = args.keys
        self.histogram_char = args.char
        self.size = args.size
        self.tokenize = args.tokenize
        self.match_regexp = args.match
        self.colour_palette = args.palette
        if args.palette != DEFAULT_PALETTE:
            self.colourised_output = True

        # first, size, which might be further overridden by width/height later
        size_presets = {}
        for names, dimensions in [
            (("small", "sm", "s"), (60, 10)),
            (("medium", "med", "m"), (100, 20)),
            (("large", "lg", "l"), (140, 35)),
        ]:
            for name in names:
                size_presets[name] = dimensions
        if self.size in ("full", "fl", "f"):
            self.width, self.height = shutil.get_terminal_size()
            self.width = int(self.width)
            self.height = int(self.height) - 3
            # need room for the verbosity output
            if self.verbose:
                self.height -= 4
            # in case tput went all bad, ensure some minimum size
            self.width = max(self.width, 40)
            self.height = max(self.height, 10)
        elif self.size in size_presets:
            self.width, self.height = size_presets[self.size]

        # synonyms "monotonically-increasing": derivative, difference, delta, increasing
        # so all "d" "i" and "m" words will be graphing those differences
        # synonyms "actual values": absolute, actual, number, normal, noop,
        # so all "a" and "n" words will graph straight up numbers
        if self.numeric_mode is not None:
            if self.numeric_mode[0] in ("d", "i", "m"):
                self.numeric_mode = "mon"
            elif self.numeric_mode[0] in ("a", "n"):
                self.numeric_mode = "abs"

        # if they passed --width or --height, they probably meant it more
        # than defaults or the --size parameter - so apply this last
        if self.width_arg != 0:
            self.width = self.width_arg
        if self.height_arg != 0:
            self.height = self.height_arg

        # max_keys should be at least a few thousand greater than height to reduce odds
        # of throwing away high-count values that appear sparingly in the data
        if self.max_keys < self.height + 3000:
            self.max_keys = self.height + 3000
            if self.verbose:
                print(
                    f"Updated max_keys to {self.max_keys} (height + 3000)",
                    file=sys.stderr,
                )

        # colour palette
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

        # some useful ASCII-->utf-8 substitutions
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
    reader = InputReader()
    histogram = Histogram()

    if settings.graph_values:
        # user passed g=vk or g=kv
        reader.read_pretallied_tokens(settings)
    elif settings.numeric_mode is not None:
        # numeric_mode was specified by the user
        reader.read_numerics(settings, histogram)
        # read_numerics will have output a graph already, so exit
        sys.exit(0)
    else:
        # this is the original behaviour of distribution
        reader.tokenize_input(settings)

    histogram.write_hist(settings, reader.token_dict)


if __name__ == "__main__":
    main()
