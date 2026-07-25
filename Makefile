.PHONY: up up-watch down logs migrate seed test

up:
	docker compose up --build

up-watch:
	docker compose up --build --watch

down:
	docker compose down -v

logs:
	docker compose logs -f backend worker frontend

migrate:
	docker compose run --rm backend alembic upgrade head

seed:
	python scripts/seed_demo.py

test:
	docker compose run --rm backend pytest -q
