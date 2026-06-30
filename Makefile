test:
	PYTHONPATH=. python -m pytest

run:
	PYTHONPATH=. python -m runners.text

lint:
	ruff check .

format:
	black .