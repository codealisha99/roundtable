.PHONY: install test lint web demo replay agent serve

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

# Publish the last demo run (out/e2e) to site/replay: timeline JSON and room audio as MP3.
replay:
	uv run --with lameenc python scripts/publish_replay.py

agent:
	uv run roundtable agent

serve:
	uv run roundtable serve --port 4501
