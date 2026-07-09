GAME ?= games/demos/toy

.PHONY: test run lint format validate-rooms validate

test:
	PYTHONPATH=. python -m pytest $(GAME)

run:
	PYTHONPATH=. python -m runners.text $(GAME)

validate-rooms:
	PYTHONPATH=. python -m runners.world validate-rooms $(GAME)

validate: validate-rooms

lint:
	ruff check .

format:
	black .