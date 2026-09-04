# Privacy and local-only operation

Codebase AI intentionally binds its web server to `127.0.0.1`.

The package contains no cloud LLM integration, cloud database integration, analytics SDK or telemetry sender.

Repository reads occur directly from the selected local path. Indexes and chats are written only under the Codebase AI application-data directory, never inside the selected repository.

## Network connections in normal operation

Normal inference uses only localhost:

- FastAPI: `127.0.0.1:8765`
- MLX-LM: `127.0.0.1:8080`
- Ollama: `127.0.0.1:11434`

The first-time setup uses package registries to install Python/npm dependencies, and the model runtimes may use the Internet if a required model has not already been cached. Once dependencies/models are present, repository analysis itself does not require external services.

For a highly controlled environment, install dependencies/models first and then use an OS/network policy that blocks outbound traffic for the runtime processes.
