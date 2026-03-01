check: lint typing tests

lint:
    uv run ruff check --fix
    uv run ruff format
    uv run pylint distribution.py

typing:
    uv run ty check
    uv run mypy --strict distribution.py

tests:
    uv run pytest
