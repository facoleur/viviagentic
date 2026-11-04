.PHONY: up down logs configure annotate lint test
up:        ; docker compose up -d
down:      ; docker compose down
logs:      ; docker compose logs -f
configure: ; uv run --group ops vivia-configure
annotate:  ; uv run --group ops vivia-annotate
lint:      ; uv run ruff check . && uv run ruff format --check .
test:      ; uv run pytest -q
