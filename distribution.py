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
        self, s: Settings, hist_width: int, max_val: float, bar_val: float
    ) -> str:
        """Return a histogram bar string scaled to the given value.

        Given a value and max, return a string of the proper number of
        characters, including unicode partial-width characters.
        """
        return_bar = ""

        # first case is partial-width chars
        if s.char_width < 1:
            zero_char = s.graph_chars[-1]
        elif len(s.histogram_char) > 1:
            zero_char = s.histogram_char[0]
            one_char = s.histogram_char[1]
        else:
            zero_char = s.histogram_char
            one_char = s.histogram_char

        # write out the full-width integer portion of the histogram
        if s.logarithmic:
            max_log = math.log(max_val)
            bar_log = math.log(bar_val) if bar_val > 0 else 0
            int_width = int(bar_log / max_log * hist_width)
            remainder_width = (bar_log / max_log * hist_width) - int_width
        else:
            int_width = int(bar_val / max_val * hist_width)
            remainder_width = (bar_val / max_val * hist_width) - int_width

        # write the zeroeth character int_width times...
        return_bar += zero_char * int_width

        # we always have at least one remaining char for histogram - if
        # we have full-width chars, then just print it, otherwise do a
        # calculation of how much remainder we need to print
        #
        # FIXME: The remainder partial char printed does not take into  # noqa: FIX001
        # account logarithmic scale (can humans notice?).
        if s.char_width == 1:
            return_bar += one_char
        elif s.char_width < 1 and remainder_width > s.char_width:
            # high-resolution: figure out what partial-width char to use
            which_char = int(remainder_width / s.char_width)
            return_bar += s.graph_chars[which_char]

        return return_bar

    def write_hist(self, s: Settings, token_dict: Counter[str]) -> None:
        """Sort token_dict by frequency and print a histogram to stdout."""
        max_token_len = 0
        output_dict = {}

        num_items = 0
        max_val = 0
        s.total_values = int(s.total_values)

        def value_key_compare(
            d: Counter[str],
        ) -> Callable[[str], tuple[int | None, str]]:
            return lambda key: (d.get(key), key)

        for k in sorted(token_dict, key=value_key_compare(token_dict), reverse=True):
            # can't remember what feature "if k:" adds - i think there's an
            # off-by-one death the script sometimes suffers without it.
            if k:
                output_dict[k] = token_dict[k]
                max_token_len = max(max_token_len, len(str(k)))
                max_val = max(max_val, output_dict[k])
                num_items += 1
                if num_items >= s.height:
                    break

        s.end_time = time.monotonic()
        elapsed_ms = (s.end_time - s.start_time) * 1000
        if s.verbose:
            print(f"tokens/lines examined: {s.total_objects:,d}", file=sys.stderr)
            print(f" tokens/lines matched: {s.total_values:,d}", file=sys.stderr)
            print(f"       histogram keys: {len(token_dict):,d}", file=sys.stderr)
            print(f"              runtime: {elapsed_ms:,.2f}ms", file=sys.stderr)

        # the first entry will determine these values
        max_value_width = 0
        max_pct_width = 0
        keys = list(output_dict)
        for i, k in enumerate(keys):
            # can't remember what feature "if k:" adds - i think there's an
            # off-by-one death the script sometimes suffers without it.
            if k:
                if max_value_width == 0:
                    max_value_width = len(str(output_dict[k]))
                    max_pct_width = len(
                        f"({output_dict[k] / s.total_values * 100:2.2f}%)"
                    )

                    # we always output a single histogram char at the end, so
                    # we output one less than actual number here
                    hist_width = (
                        s.width
                        - (max_token_len + 1)
                        - (max_value_width + 1)
                        - (max_pct_width + 1)
                        - 1
                    )

                    # output a header; key_colour goes on this line so piping
                    # stdout to sort works (no colour prefix on data lines)
                    print(
                        "Key".rjust(max_token_len)
                        + "|"
                        + "Ct".ljust(max_value_width)
                        + " "
                        + "(Pct)".ljust(max_pct_width)
                        + " "
                        + "Histogram"
                        + s.key_colour,
                        file=sys.stderr,
                    )

                out_val = str(output_dict[k])
                pct = f"({output_dict[k] / s.total_values * 100:2.2f}%)"
                bar = self.histogram_bar(s, hist_width, max_val, output_dict[k])
                end_colour = s.regular_colour if i == len(keys) - 1 else s.key_colour
                print(
                    str(k).rjust(max_token_len)
                    + s.regular_colour
                    + "|"
                    + s.ct_colour
                    + out_val.rjust(max_value_width)
                    + " "
                    + s.pct_colour
                    + pct.rjust(max_pct_width)
                    + " "
                    + s.graph_colour
                    + bar
                    + end_colour
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

    def prune_keys(self, s: Settings) -> None:
        """Keep only the top max_keys entries in the token dict."""
        new_dict: Counter[str] = Counter()
        num_keys_transferred = 0
        for k in sorted(self.token_dict, key=self.token_dict.__getitem__, reverse=True):
            if k:
                new_dict[k] = self.token_dict[k]
                num_keys_transferred += 1
                if num_keys_transferred > s.max_keys:
                    break
        self.token_dict = new_dict
        s.num_prunes += 1

    def tokenize_input(self, s: Settings) -> None:  # noqa: C901
        """Split stdin lines into tokens and count their frequency.

        Splits on whitespace or word boundaries by default, but the user
        can specify any regexp. Likewise, matching defaults to everything
        but can be restricted to all-alpha or all-numeric tokens.
        """
        if s.tokenize == "white":
            s.tokenize = r"\s+"
        elif s.tokenize == "word":
            s.tokenize = r"\W"

        # how to match (filter) the input... typically we want either
        # all-alpha or all-numeric, but again, user can specify
        if s.match_regexp == "word":
            s.match_regexp = r"^[A-Z,a-z]+$"
        elif s.match_regexp in ["num", "number"]:
            s.match_regexp = r"^\d+$"

        # docs say these are cached, but i got about 2x speed boost
        # from doing the compile
        should_tokenize = bool(s.tokenize)
        pt = re.compile(s.tokenize)
        pm = re.compile(s.match_regexp)

        next_stat = time.time() + s.stat_interval

        prune_objects = 0
        # ruff: disable[PLW2901]
        for line in sys.stdin:
            line = line.rstrip("\n")
            if should_tokenize:
                for token in pt.split(line):
                    # user desires to break line into tokens...
                    s.total_objects += 1
                    if pm.match(token):
                        s.total_values += 1
                        prune_objects += 1
                        self.token_dict[token] += 1
            else:
                # user just wants every line to be a token
                s.total_objects += 1
                if pm.match(line):
                    s.total_values += 1
                    prune_objects += 1
                    self.token_dict[line] += 1

            # prune the hash if it gets too large
            if prune_objects >= s.key_prune_interval:
                self.prune_keys(s)
                prune_objects = 0

            if s.verbose and time.time() > next_stat:
                print(
                    f"tokens/lines examined: {s.total_objects:,d} ; hash prunes: {s.num_prunes:,d}...",
                    end="\r",
                    file=sys.stderr,
                )
                next_stat = time.time() + s.stat_interval
        # ruff: enable[PLW2901]

    def read_pretallied_tokens(self, s: Settings) -> None:
        """Read pre-counted key/value pairs from stdin.

        Input is already tallied (as in `du -sb`). vk means the number
        is first and key second; kv means key first and number second.
        """
        vk = re.compile(r"^\s*(\d+)\s+(.+)$")
        kv = re.compile(r"^(.+?)\s+(\d+)$")
        if s.graph_values == "vk":
            for line in sys.stdin:
                m = vk.match(line)
                if not m:
                    print(
                        f" E Input malformed+discarded (perhaps pass -g=kv?): {line}",
                        file=sys.stderr,
                    )
                    continue
                self.token_dict[m.group(2)] += int(m.group(1))
                s.total_values += int(m.group(1))
                s.total_objects += 1
        elif s.graph_values == "kv":
            for line in sys.stdin:
                m = kv.match(line)
                if not m:
                    print(
                        f" E Input malformed+discarded (perhaps pass -g=vk?): {line}",
                        file=sys.stderr,
                    )
                    continue
                self.token_dict[m.group(1)] += int(m.group(2))
                s.total_values += int(m.group(2))
                s.total_objects += 1

    def read_numerics(self, s: Settings, h: Histogram) -> None:
        """Read raw numbers from stdin and print a simple graph directly.

        Unlike the other modes, output is printed here rather than in
        Histogram, since it is a simpler graph without totals or
        percentages — just a bar for each numeric value or its
        monotonic difference.
        """
        last_val = 0.0
        max_val = 0.0
        max_width = 0
        sum_val = 0.0
        out_list: list[float] = []
        # ruff: disable[PLW2901]
        for line in sys.stdin:
            try:
                line = float(line.rstrip())
            except ValueError:
                line = last_val

            graph_val = 0.0
            if s.num_only == "mon":
                if s.total_objects > 0:
                    graph_val = line - last_val
                last_val = line
            else:
                graph_val = line

            if graph_val > max_val:
                max_val = graph_val
                max_width = len(str(graph_val))

            sum_val += graph_val

            if s.total_objects > 0:
                out_list.append(graph_val)
            s.total_objects += 1
        # ruff: enable[PLW2901]

        # simple graphical output
        for k in out_list:
            pct = f"({k / sum_val * 100:2.2f}%)"
            bar = h.histogram_bar(s, s.width - 11 - max_width, max_val, k)
            print(
                s.key_colour
                + str(int(k)).rjust(max_width)
                + s.pct_colour
                + pct.rjust(9)
                + " "
                + s.graph_colour
                + bar
                + s.regular_colour
            )


def _build_parser() -> DistributionParser:
    """Build the argument parser with all options defined."""
    parser = DistributionParser(
        fromfile_prefix_chars="@",
        prog=script_name,
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
        self.num_only = None
        self.verbose = False
        self.graph_values = ""
        self.size = ""
        self.tokenize = ""
        # by default, everything matches (nothing is stripped out)
        self.match_regexp = "."
        # how often to give status if verbose
        self.stat_interval = 1.0
        self.num_prunes = 0
        # for colourised output
        self.colour_palette = DEFAULT_PALETTE
        self.regular_colour = ""
        self.key_colour = ""
        self.ct_colour = ""
        self.pct_colour = ""
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
        self.num_only = args.numonly
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
        for names, dims in [
            (("small", "sm", "s"), (60, 10)),
            (("medium", "med", "m"), (100, 20)),
            (("large", "lg", "l"), (140, 35)),
        ]:
            for name in names:
                size_presets[name] = dims
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
        if self.num_only is not None:
            if self.num_only[0] in ("d", "i", "m"):
                self.num_only = "mon"
            elif self.num_only[0] in ("a", "n"):
                self.num_only = "abs"

        # override variables if they were explicitly given
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
            cl = self.colour_palette.split(",")
            # ANSI color code is ESC+[+NN+m where ESC=chr(27), [ and m are
            # the literal characters, and NN is a two-digit number, typically
            # from 31 to 37 - why is this knowledge still useful in 2014?
            cl = [f"\033[{e}m" for e in cl]
            (
                self.regular_colour,
                self.key_colour,
                self.ct_colour,
                self.pct_colour,
                self.graph_colour,
            ) = cl

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
    s = Settings()
    i = InputReader()
    h = Histogram()

    if s.graph_values:
        # user passed g=vk or g=kv
        i.read_pretallied_tokens(s)
    elif s.num_only is not None:
        # s.num_only was specified by the user
        i.read_numerics(s, h)
        # read_numerics will have output a graph already, so exit
        sys.exit(0)
    else:
        # this is the original behaviour of distribution
        i.tokenize_input(s)

    h.write_hist(s, i.token_dict)


# what is this magic?
script_name = str(Path(sys.argv[0]).name)
if __name__ == "__main__":
    main()
