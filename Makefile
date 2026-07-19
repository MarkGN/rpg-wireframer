GAME ?= games/demos/toy

.PHONY: test run lint format validate-rooms validate

test:
	PYTHONPATH=. python -m pytest $(GAME)

run:
	PYTHONPATH=. python -m runners.text $(GAME)

validate-rooms:
	PYTHONPATH=. python -m validate.rooms $(GAME)

validate-game-object:
	PYTHONPATH=. python -m validate.game_objects $(GAME)

validate: validate-rooms validate-game-object

lint:
	ruff check .

format:
	black .

typecheck:
	PYTHONPATH=. mypy . --ignore-missing-imports