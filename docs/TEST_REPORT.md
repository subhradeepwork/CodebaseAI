# Verification report — Codebase AI 1.1.0

Verification completed for the v1.1.0 source package.

## Automated backend and regression tests

```text
15 passed
```

The suite covers database initialization/migration, repository discovery, secret exclusion, parsing, indexing, lexical retrieval, multi-repository retrieval, persistent conversation context, per-source repository attribution, chat source staleness, conversation deletion, LLM request handling, localhost API integration, persistent composer layout, repository context controls, and sidebar resize/collapse controls.

## Additional checks

- Python source compilation completed successfully.
- Shell launcher syntax checks completed successfully.
- ZIP archive integrity and clean-extraction tests completed successfully.
- Frontend source was parsed by the available TypeScript compiler; a full frontend dependency build cannot be executed in the isolated packaging environment because npm registry access is unavailable. `setup.command` performs the normal `npm install` and production build on the target Mac.

## Runtime scope

The packaging environment does not contain the user's local MLX Qwen model or Ollama embedding model. Model-backed responses therefore remain target-machine integration steps, while the local application logic and mocked LLM path are covered by automated tests.
