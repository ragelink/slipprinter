.PHONY: install hooks scan lint format test test-pr test-nightly test-release test-debug

install:
	uv sync

hooks:
	uv run pre-commit install

scan:
	gitleaks git . --config .gitleaks.toml --redact --no-banner
	gitleaks dir . --config .gitleaks.toml --redact --no-banner

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
