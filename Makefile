.PHONY: install-dev test lint typecheck check

install-dev:
	python3 -m pip install -e ".[dev]"

test:
	python3 -m unittest discover -s tests

lint:
	python3 -m ruff check .

typecheck:
	python3 -m mypy src

check: test lint typecheck
