GAME ?= games/demos/toy

test:
	PYTHONPATH=. python -m pytest $(GAME)

run:
	PYTHONPATH=. python -m runners.text $(GAME)

lint:
	ruff check .

format:
	black .