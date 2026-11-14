.PHONY: install test lint web demo agent serve

install:
	uv sync
	cd web && pnpm install

test:
	uv run pytest -q

lint:
	uv run ruff check src tests

web:
	cd web && pnpm build

# Keyless end-to-end run: starts LiveKit in Docker, the agent, three simulated participants, then asserts.
demo:
	uv run roundtable demo

agent:
	uv run roundtable agent

serve:
	uv run roundtable serve --port 4501
