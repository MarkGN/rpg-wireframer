test:
	python -m pytest

run:
	python runners/text.py

lint:
	ruff check .

format:
	black .