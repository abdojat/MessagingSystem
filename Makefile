.PHONY: up down logs migrate seed test

up:
	docker compose up --build

down:
	docker compose down -v

logs:
	docker compose logs -f backend worker

migrate:
	docker compose run --rm backend alembic upgrade head

seed:
	python scripts/seed_demo.py

test:
	docker compose run --rm backend pytest -q
