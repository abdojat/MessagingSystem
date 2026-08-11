.PHONY: up up-watch down reset logs migrate test release-verify

up:
	docker compose up --build

up-watch:
	docker compose up --build --watch

down:
	docker compose down

reset:
	docker compose down -v

logs:
	docker compose logs -f backend worker frontend

migrate:
	docker compose run --rm backend alembic upgrade head

test:
	docker compose run --rm backend python -B -m pytest -q

release-verify:
	python scripts/verify_release.py
