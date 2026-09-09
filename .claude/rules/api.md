---
paths:
  - "api/**/*.py"
  - "api/pyproject.toml"
---

# API conventions (FastAPI, Python 3.13, uv)

- Pydantic models at every boundary: request bodies, response models, and LLM structured outputs. Endpoints declare a return type so FastAPI validates and documents it.
- Keep parsing and anonymisation as pure functions with no I/O. They are the most tested code in the repo.
- LLM calls live in small functions that take the `genai.Client` as a parameter, so tests pass a fake client instead of hitting the network. Never call the network in tests.
- Structured output from the model: pass a Pydantic `model_json_schema()` as the response schema and parse with `model_validate_json`. Raise HTTP 502 when the model returns nothing usable.
- Errors: raise `HTTPException` with a specific status. No bare `except`. Do not swallow exceptions.
- Type hints on every function. Ruff is the formatter and linter; run `uv run ruff format` before finishing.
- Tests in `api/tests/`, one file per module area, plain `pytest` functions. Name tests after the behaviour, not the function.
- Do not log or print raw transaction descriptions or amounts. Log shapes, counts, and timings.
- Dependencies via `uv add` only after saying why. Prefer the standard library and what is already installed.
