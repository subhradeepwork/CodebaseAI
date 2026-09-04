# Verification report — Codebase AI 1.0.1

The package was checked before ZIP creation with the following local tests.

## Automated backend tests

`PYTHONPATH=backend python -m pytest -q backend/tests`

Result at packaging time:

```text
11 passed
```

Coverage includes:

- AWS Lambda `.mjs` handler detection
- AWS SDK package/environment-variable extraction
- React component and hook detection
- Karate scenario / feature-call / Java interop detection
- Playwright test detection
- SQLite schema + FTS behavior
- repository scanning and secret/generated-directory exclusions
- incremental index/retrieval integration on a temporary repository
- persistent chat storage
- source-citation staleness detection after a file changes
- MLX response parsing for both plain-string and OpenAI-style message shapes
- persistent chat-composer layout regression (input remains in a fixed grid row after responses)

## Additional integration checks

A temporary mixed repository was indexed containing:

- Java/Spring source
- React/TSX source
- AWS Lambda `.mjs`

The test confirmed:

- repository status becomes `ready`
- symbols are extracted
- Lambda handler is classified as `aws_lambda_handler`
- Spring service/method symbols are extracted
- React component symbol is extracted
- lexical/symbol retrieval returns the expected source

A FastAPI `TestClient` integration test confirmed:

- health endpoint
- add repository
- repository indexing
- conversation creation
- message-history retrieval
- indexed file tree
- safe source-file excerpt endpoint

A mocked localhost Ollama + MLX pipeline was also exercised end-to-end to verify:

- semantic embedding storage
- semantic-ready repository state
- conversation POST path
- local LLM request/response integration
- persisted assistant source citations

## Static checks

- Python `compileall`: passed
- shell script parse checks: passed
- Frontend layout regression source check: passed

## What could not be executed in the packaging container

The packaging environment does not contain the user's downloaded 17 GB Apple-MLX Qwen model or npm registry access. Therefore the exact physical M5 Pro inference speed and the final `npm install && npm run build` were not executed here.

The package's `setup.command` performs the real frontend install/build and reruns backend tests on the target Mac. `verify.command` provides a second post-install verification pass.
