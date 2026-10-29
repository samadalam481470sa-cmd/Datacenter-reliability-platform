.PHONY: install run test lint build smoke
install:
	python -m pip install -e '.[dev]'
run:
	uvicorn rackhelm.api:app --host 127.0.0.1 --port 8000 --reload
test:
	pytest -q
lint:
	ruff check src tests scripts
build:
	python -m build --wheel
smoke:
	python scripts/smoke.py