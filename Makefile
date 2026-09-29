.PHONY: install lint format test data features train evaluate serve docker-build compose-up compose-down deploy smoke-test drift retrain rollback
install:
	uv sync --frozen
lint:
	uv run ruff check .
	uv run ruff format --check .
format:
	uv run ruff check --fix .
	uv run ruff format .
test:
	uv run pytest
data:
	uv run gridpulse data
features:
	uv run gridpulse features
train:
	uv run gridpulse train --promote
evaluate:
	uv run gridpulse evaluate
serve:
	uv run uvicorn apps.api.main:app --host 0.0.0.0 --port 8000
docker-build:
	docker compose build
compose-up:
	docker compose up -d --build
compose-down:
	docker compose down
deploy:
	uv run python scripts/deploy_local.py
smoke-test:
	uv run gridpulse smoke --url http://localhost:8000
drift:
	uv run gridpulse monitor
retrain:
	uv run gridpulse retrain --trigger scheduled
rollback:
	uv run gridpulse rollback

