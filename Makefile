.PHONY: up down logs configure backfill-feedback lint test
up:        ; docker compose up --build -d
down:      ; docker compose down
logs:      ; docker compose logs -f
configure: ; uv run --env-file .env --group ops vivia-configure
backfill-feedback: ; uv run --env-file .env --group ops vivia-feedback-backfill
lint:      ; uv run ruff check . && uv run ruff format --check .
test:      ; uv run pytest -q
