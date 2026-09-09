# budget-buddy dev tasks. Run `make` or `make help` for the list.
# The recipes mirror the command groups documented in CLAUDE.md so CI and
# local dev call the same thing.

.DEFAULT_GOAL := help
.PHONY: help dev dev-api dev-app install check check-api check-app test test-api test-app

help: ## Show this help
	@grep -hE '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

# uv run does not read api/.env on its own, so pass it explicitly when it exists
# (fall back to no env file so the server still starts without a key -- it just
# can't reach the model). Keep this in sync with the dev-server line in CLAUDE.md.
ENV_FILE = $$([ -f .env ] && echo --env-file .env)

dev: ## Run the API (:8000) and app (:5173) together; Ctrl-C stops both
	@trap 'kill 0' INT TERM EXIT; \
	(cd api && uv run $(ENV_FILE) fastapi dev src/budget_buddy/main.py) & \
	(cd app && npm run dev) & \
	wait

dev-api: ## Run just the API dev server (needs api/.env with GEMINI_API_KEY)
	cd api && uv run $(ENV_FILE) fastapi dev src/budget_buddy/main.py

dev-app: ## Run just the app dev server
	cd app && npm run dev

install: ## Install dependencies for both sides
	cd api && uv sync
	cd app && npm install

check: check-api check-app ## Lint, typecheck and test both sides

check-api: ## Lint, format-check and test the API
	cd api && uv run ruff check . && uv run ruff format --check . && uv run pytest

check-app: ## Lint, typecheck and test the app
	cd app && npm run lint && npx tsc -b && npm test

test: test-api test-app ## Run both test suites only

test-api: ## Run the API tests
	cd api && uv run pytest

test-app: ## Run the app tests
	cd app && npm test
