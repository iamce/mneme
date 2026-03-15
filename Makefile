.PHONY: install-dev test lint typecheck eval check

install-dev:
	python3 -m pip install -e ".[dev]"

test:
	python3 -m unittest discover -s tests

lint:
	python3 -m ruff check .

typecheck:
	python3 -m mypy src

eval:
	PYTHONPATH=src python3 -m mneme.cli eval-retrieval

check: test lint typecheck
