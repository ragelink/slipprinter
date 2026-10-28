.PHONY: install lint format test test-pr test-nightly test-release test-debug

install:
	uv sync

lint:
	uv run ruff format --check .
	uv run ruff check .

format:
	uv run ruff format .
	uv run ruff check --fix .

test:
	uv run pytest -m always

test-pr:
	uv run pytest -m "always or sometimes"

test-nightly:
	uv run pytest -m "always or sometimes or rarely"

test-release:
	uv run pytest -m "not debug"

test-debug:
	uv run pytest -m debug -k "$(T)"
