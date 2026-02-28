check: lint typing tests

lint:
    ruff check --fix distribution.py
    ruff format distribution.py

typing:
    ty check distribution.py
    uv run mypy --strict distribution.py

tests:
    uv run pytest
