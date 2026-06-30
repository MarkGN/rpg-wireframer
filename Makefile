GAME ?= demos/toy

test:
	PYTHONPATH=. python -m pytest

run:
	PYTHONPATH=. python -m runners.text $(GAME)

lint:
	ruff check .

format:
	black .