# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A command-line tool for generating character-based histograms and graphs in the terminal. Takes input via stdin, tokenizes/aggregates data, and renders ASCII/Unicode bar charts. Written in Python 3 with no external dependencies (stdlib only). The Perl version (`distribution`) is the original; `distribution.py` is the active Python port.

## Running and Testing

```bash
# Run directly
echo "data" | ./distribution.py [options]

# Run all tests (both Perl and Python)
./runTests.sh

# Format
ruff format distribution.py

# Lint
ruff check distribution.py

# Type check
mypy distribution.py
ty check distribution.py
```

Tests are shell-based: each test feeds `stdin.*.txt` files and compares stdout/stderr against `*.expected.txt` files. There are 7 test cases.

## Linting Configuration

- **ruff format**: configured in `.ruff.toml`, selects ALL rules and then disables some of them
- **direnv** (`.envrc`): sets `PYTHONDEVMODE=1` and `PYTHONWARNDEFAULTENCODING=1`

## Architecture

Everything lives in `distribution.py` (~630 lines), organized into three classes that form a pipeline:

1. **Settings** — Parses `~/.distributionrc` config file and command-line arguments. Manages all display parameters (dimensions, colors, Unicode chars, tokenization regexes). Passed to other classes as shared state.

2. **InputReader** — Reads stdin in one of three modes:
   - `tokenize_input()` — splits lines by regex, counts token frequency
   - `read_pretallied_tokens()` — reads pre-counted key/value pairs (vk or kv format)
   - `read_numerics()` — graphs raw numbers or monotonic differences
   - Includes hash pruning to prevent OOM on large datasets

3. **Histogram** — Renders the visualization. Supports logarithmic scaling, Unicode partial-width characters (1/8 or 1/3 resolution), color palettes via ANSI codes. Headers go to stderr, data to stdout (enabling piping to `sort`).

**Data flow:** `main()` → Settings init → InputReader processes stdin into `token_dict` (key→count) → Histogram sorts deterministically by (value, key) and renders bars.
