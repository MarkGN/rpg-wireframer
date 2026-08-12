GAME ?= games/demos/toy

.PHONY: test run lint validate-rooms validate export-dot

test:
	PYTHONPATH=. python -m pytest $(GAME)

run:
	PYTHONPATH=. python -m runners.text $(GAME)

validate-dialogue:
	PYTHONPATH=. python -m validate.dialogues $(GAME)

validate-rooms:
	PYTHONPATH=. python -m validate.rooms $(GAME)

validate-game-object:
	PYTHONPATH=. python -m validate.game_objects $(GAME)

validate-quests:
	PYTHONPATH=. python -m validate.quests $(GAME)

validate: validate-rooms validate-game-object

export-dot:
	PYTHONPATH=. python export/export_rooms_to_dot.py $(GAME)

lint:
	ruff check .

typecheck:
	PYTHONPATH=. mypy . --ignore-missing-imports