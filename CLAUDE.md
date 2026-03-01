# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A command-line tool for generating character-based histograms and graphs in the terminal. Takes input via stdin, tokenizes/aggregates data, and renders ASCII/Unicode bar charts. Written in Python 3 with no external dependencies (stdlib only). The Perl version (`distribution`) is the original; `distribution.py` is the active Python port.

## Running and Testing

```bash
# Run directly
echo "data" | ./distribution.py [options]

# Full check suite (ruff, pylint, ty, mypy --strict, pytest)
just check

# Run tests (args passed through to pytest)
just test
just test -k "test_foo"
just test -v

# Individual tools
just lint     # ruff check+format, pylint
just typing   # ty check, mypy --strict

# Legacy shell-based e2e tests (both Perl and Python)
./runTests.sh
```

Tests live in `tests/`: 7 shell-based e2e cases (`stdin.*.txt` vs `*.expected.txt`) wrapped by `test_e2e.py`, plus unit tests in `test_unit.py`.

## Linting Configuration

- **ruff format**: configured in `.ruff.toml`, selects ALL rules and then disables some of them
- **direnv** (`.envrc`): sets `PYTHONDEVMODE=1` and `PYTHONWARNDEFAULTENCODING=1`

## Architecture

Everything lives in `distribution.py` (~740 lines), organized as free functions with a `Settings` dataclass threaded through:

1. **Settings** — Parses `~/.distributionrc` config file and command-line arguments. Manages all display parameters (dimensions, colors, Unicode chars, tokenization regexes). Passed to other functions as shared state.

2. **Input functions** — Read stdin in one of three modes:
   - `tokenize_input()` — splits lines by regex, counts token frequency (includes hash pruning to prevent OOM)
   - `read_pretallied_tokens()` — reads pre-counted key/value pairs (vk or kv format)
   - `read_numerics()` — graphs raw numbers or monotonic differences

3. **Rendering functions** — `write_hist()` renders the histogram; `render_numeric_graph()` handles numeric mode. Support logarithmic scaling, Unicode partial-width characters (1/8 or 1/3 resolution), color palettes via ANSI codes. Headers go to stderr, data to stdout (enabling piping to `sort`).

**Data flow:** `main()` → Settings init → input function processes stdin into `token_dict` (key→count) or `NumericData` → rendering function sorts deterministically by (value, key) and renders bars.
