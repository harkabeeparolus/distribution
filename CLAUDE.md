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

Tests live in `tests/`: 7 shell-based e2e cases (`stdin.*.txt` vs `*.expected.txt`) wrapped by `test_e2e.py`, plus unit tests for the input/render functions in `test_unit.py` and for the configuration layer in `test_config.py`. Tests are plain functions grouped by `# --- banner ---` comments, not classes. `pythonpath = ["."]` in the pytest config makes `import distribution` work, so no `sys.path` manipulation is needed.

## Linting Configuration

All tool config lives in `pyproject.toml` — there are no per-tool config files.

- **ruff** (`[tool.ruff.lint]`): selects ALL rules, then disables a handful; `[tool.ruff.lint.per-file-ignores]` relaxes `INP001` and `S` for `tests/`
- **pylint** (`[tool.pylint]`, `[tool.pylint."messages_control"]`): raises `max-module-lines` because the single-file design is intentional, and fails on `useless-suppression` so stale `# pylint: disable` comments get caught
- **pytest** (`[tool.pytest.ini_options]`): `testpaths = ["tests"]`
- **direnv**: `.envrc` is gitignored, so it's a local-only convention rather than part of the repo. Setting `PYTHONDEVMODE=1` and `PYTHONWARNDEFAULTENCODING=1` there is useful for surfacing encoding warnings; note the `Justfile` deliberately clears `PYTHONWARNDEFAULTENCODING` so it doesn't leak into the tool runs.

## Architecture

Everything lives in `distribution.py` (~740 lines), organized in **newspaper style** (most important code first) with free functions and a `Settings` dataclass threaded through. `from __future__ import annotations` enables forward references so definitions can appear in any order. New code should be added within the appropriate section to preserve this layout.

1. **`main()`** — Entry point, at the top of the file.

2. **Input pipeline** — `tokenize_input()`, `_prune_keys()`, `read_pretallied_tokens()`, `read_numerics()`. Read stdin in one of three modes: split-and-count, pre-tallied key/value pairs, or raw numerics.

3. **Rendering** — `write_hist()`, `_hist_layout()`, `histogram_bar()`, `render_numeric_graph()`. Histogram output with logarithmic scaling, Unicode partial-width characters, and ANSI color palettes. Headers go to stderr, data to stdout.

4. **Data types** — `Stats`, `NumericData`, `HistLayout`, `EmptyInputError`.

5. **Configuration** — `settings_from_args()`, `_parse_args()`, constants, `Settings` dataclass, `_build_parser()`, `DistributionParser`. Parses `~/.distributionrc` and CLI arguments.

6. **`if __name__` guard** — Last line.

**Data flow:** `main()` → Settings init → input function processes stdin into `token_dict` (key→count) or `NumericData` → rendering function sorts deterministically by (value, key) and renders bars.
