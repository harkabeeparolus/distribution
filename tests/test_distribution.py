"""Tests for distribution.py histogram tool."""

from __future__ import annotations

import subprocess
from pathlib import Path

TESTS_DIR = Path(__file__).parent
PROJECT_DIR = TESTS_DIR.parent
DISTRIBUTION = str(PROJECT_DIR / "distribution.py")
RCFILE = str(PROJECT_DIR / "distributionrc")


def run_distribution(
    args: list[str],
    input_text: str,
) -> subprocess.CompletedProcess[str]:
    """Run distribution.py with given arguments and stdin."""
    return subprocess.run(
        [DISTRIBUTION, f"--rcfile={RCFILE}", *args],
        input=input_text,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


def awk_fields(text: str, *fields: int) -> str:
    """Extract whitespace-delimited fields (1-indexed, like awk)."""
    lines = []
    for line in text.splitlines():
        parts = line.split()
        selected = [parts[f - 1] if f <= len(parts) else "" for f in fields]
        lines.append(" ".join(selected))
    return "\n".join(lines) + "\n"


def grep_filter(text: str, pattern: str) -> str:
    """Keep only lines containing the given substring."""
    return "\n".join(line for line in text.splitlines() if pattern in line) + "\n"


def normalize_ws(text: str) -> list[str]:
    """Strip all whitespace per line, equivalent to diff -w."""
    return ["".join(line.split()) for line in text.splitlines()]


def read_fixture(name: str) -> str:
    """Read a test fixture file from the tests directory."""
    return (TESTS_DIR / name).read_text(encoding="utf-8")


def assert_ws_equal(actual: str, expected: str) -> None:
    """Assert two strings match after whitespace normalization."""
    assert normalize_ws(actual) == normalize_ws(expected)


def assert_stdout(
    result: subprocess.CompletedProcess[str],
    expected_file: str,
) -> None:
    """Assert stdout matches expected fixture file (whitespace-normalized)."""
    assert_ws_equal(result.stdout, read_fixture(expected_file))


def _numeric_sort_key(line: str) -> tuple[float, str]:
    """Sort key mimicking sort -n: by leading number, then lexicographic."""
    stripped = line.lstrip()
    num_str = ""
    for ch in stripped:
        if ch in "0123456789.-+":
            num_str += ch
        else:
            break
    try:
        return (float(num_str), line) if num_str else (0.0, line)
    except ValueError:
        return (0.0, line)


# --- Test Cases ---


def test_01_pretallied_graph() -> None:
    """Pre-tallied graph with dt characters and color."""
    result = run_distribution(
        ["--graph", "--height=35", "--width=120", "--char=dt", "--color", "--verbose"],
        read_fixture("stdin.01.txt"),
    )
    assert_stdout(result, "stdout.01.expected.txt")


def test_02_awk_fields_tokenize_word() -> None:
    """Tokenize=word on awk-extracted fields 4 and 5."""
    input_text = awk_fields(read_fixture("stdin.02.txt"), 4, 5)
    result = run_distribution(
        [
            "--size=med",
            "--width=110",
            "--tokenize=word",
            "--match=word",
            "--verbose",
            "--color",
        ],
        input_text,
    )
    assert_stdout(result, "stdout.02.expected.txt")


def test_03_grep_modem_sorted() -> None:
    """Grep modem, awk field 1, sorted output."""
    raw = read_fixture("stdin.02.txt")
    input_text = awk_fields(grep_filter(raw, "modem"), 1)
    result = run_distribution(
        ["--width=110", "--height=15", "--char=|", "--verbose", "--color"],
        input_text,
    )
    sorted_stdout = "\n".join(sorted(result.stdout.splitlines()))
    assert_ws_equal(sorted_stdout, read_fixture("stdout.03.expected.txt"))


def test_04_tokenize_slash_custom_palette() -> None:
    """Tokenize by / with custom color palette and () chars."""
    result = run_distribution(
        [
            "--size=large",
            "--height=8",
            "--width=60",
            "--tokenize=/",
            "--palette=0,31,33,35,37",
            "--char=()",
        ],
        read_fixture("stdin.03.txt"),
    )
    assert_stdout(result, "stdout.04.expected.txt")


def test_05_match_num_sort_numeric() -> None:
    """Match=num with numerically sorted output."""
    result = run_distribution(
        [
            "--char=pc",
            "--width=48",
            "--tokenize=word",
            "--match=num",
            "--size=large",
            "--verbose",
        ],
        read_fixture("stdin.03.txt"),
    )
    sorted_stdout = "\n".join(sorted(result.stdout.splitlines(), key=_numeric_sort_key))
    assert_ws_equal(sorted_stdout, read_fixture("stdout.05.expected.txt"))


def test_06_generated_xor_numbers() -> None:
    """Large XOR-generated dataset testing hash pruning."""
    xor_iterations = 3_141_592
    lines = []
    i = 0
    while i < xor_iterations:
        old_i = i
        i += 17
        lines.append(str(old_i ^ i)[1:6])
    result = run_distribution(
        [
            "--width=124",
            "--height=29",
            "--palette=0,32,34,36,31",
            "--char=^",
            "--verbose",
        ],
        "\n".join(lines) + "\n",
    )
    assert_stdout(result, "stdout.06.expected.txt")


def test_07_awk_field_8_unicode_char() -> None:
    """Awk field 8 with Unicode Xi bar character."""
    input_text = awk_fields(read_fixture("stdin.04.txt"), 8)
    result = run_distribution(
        ["--size=s", "--width=90", "--char=\u039e"],
        input_text,
    )
    assert_stdout(result, "stdout.07.expected.txt")
