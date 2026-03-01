export PYTHONWARNDEFAULTENCODING := ""

check: lint typing test

lint:
    uv run ruff check --fix
    uv run ruff format
    uv run pylint distribution.py

typing:
    uv run ty check
    uv run mypy --strict distribution.py

test *args:
    uv run pytest {{ args }}
