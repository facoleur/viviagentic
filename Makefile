.PHONY: up down logs configure lint test
up:        ; docker compose up --build -d
down:      ; docker compose down
logs:      ; docker compose logs -f
configure: ; uv run --group ops vivia-configure
lint:      ; uv run ruff check . && uv run ruff format --check .
test:      ; uv run pytest -q
