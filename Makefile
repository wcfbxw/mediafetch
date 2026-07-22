.PHONY: up down logs test test-backend test-frontend build lint clean

up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f

test: test-backend test-frontend

test-backend:
	docker compose --profile test run --rm backend-test

test-frontend:
	docker compose --profile test run --rm frontend-test

build:
	docker compose build

lint:
	docker compose --profile test run --rm backend-test ruff check app tests
	docker compose --profile test run --rm backend-test mypy app
	docker compose --profile test run --rm frontend-test npm run lint
	docker compose --profile test run --rm frontend-test npm run typecheck

clean:
	docker compose run --rm cleanup python -m app.services.cleanup --once
