# Codebase AI

Codebase AI is a fully local repository-understanding assistant for private codebases. It runs as a localhost web application and is designed to help developers explore unfamiliar repositories, trace execution flow, locate implementation details, understand architecture, and plan code changes without sending source code to a cloud coding service.

The current release is optimized for Apple Silicon and uses a local Qwen coding model through MLX-LM together with local semantic embeddings through Ollama.

## Core capabilities

- Open and index a local repository without uploading it.
- Ask natural-language questions about repository structure and implementation.
- Trace likely flows across frontend, backend, tests, configuration, and Lambda functions.
- Retrieve code through a hybrid of lexical, structural, symbol, graph, and semantic search.
- View repository evidence with file and line references.
- Open cited source ranges inside the browser UI.
- Save multiple conversations locally.
- Reopen prior conversations from the sidebar and continue them later.
- Keep chat history associated with the repository it belongs to.
- Record Git commit information with conversation evidence.
- Incrementally reindex changed, added, and removed files.
- Run read-only against selected repositories.

## Repository coverage

Codebase AI is designed as an extensible repository-intelligence platform rather than a tool limited to a fixed set of languages or frameworks.

The current implementation has strong structural and semantic coverage for common application code, including:

| Area | Current coverage |
| --- | --- |
| JavaScript / TypeScript | Structural and semantic indexing |
| React and component-based frontend code | Framework-aware indexing |
| ES modules / `.mjs` | Structural indexing |
| Java | Structural and semantic indexing |
| Spring / Spring Boot | Framework-aware indexing |
| AWS Lambda | Runtime and integration-aware indexing |
| AWS SDK usage | Service and environment-variable signals |
| JSON / YAML / properties / XML | Configuration indexing |
| Gradle / Maven project files | Build and project metadata |
| Terraform / SQL / Markdown | Indexed as repository context |

This list is intentionally not exhaustive. The parsing, retrieval, and framework-awareness layers are designed so additional languages, frameworks, test systems, infrastructure formats, and repository conventions can be added over time without changing the core architecture.

AWS Lambda code does not need to live in a specific directory, but a folder such as `lambdaBackend/` is treated as a strong Lambda signal.

## Typical questions

Examples of questions Codebase AI is intended to answer:

```text
Map the high-level architecture of this repository.

Where are the main entry points?

How does authentication work from the React frontend to the backend?

Which function ultimately writes this value to DynamoDB?

Which Lambda functions reference CUSTOMER_TABLE?

Where is this API response transformed before it reaches the UI?

Which test setup controls authentication for this part of the system?

Which test or automation file calls this helper?

If I add a new field to this request, which files and tests are likely affected?
```

## Architecture

```text
Browser
React + TypeScript
        |
        | localhost
        v
FastAPI
127.0.0.1:8765
        |
        +-- Repository scanner
        |     +-- Git tracked and untracked discovery
        |     +-- ignore handling
        |     +-- secret exclusions
        |     +-- incremental file hashing
        |
        +-- Code parser
        |     +-- Tree-sitter
        |     +-- JavaScript / TypeScript / TSX / MJS
        |     +-- Java / Spring
        |     +-- framework-specific analyzers
        |     +-- AWS Lambda / AWS SDK signals
        |
        +-- SQLite
        |     +-- repository metadata
        |     +-- files
        |     +-- symbols
        |     +-- code chunks
        |     +-- FTS5 search
        |     +-- reference edges
        |     +-- conversations
        |     +-- messages
        |     +-- source citations
        |
        +-- Hybrid retrieval
        |     +-- lexical search
        |     +-- symbol search
        |     +-- semantic search
        |     +-- graph expansion
        |     +-- result fusion
        |
        +-- Ollama
        |     +-- qwen3-embedding:0.6b
        |
        +-- MLX-LM
              +-- Qwen3-Coder 30B A3B 4-bit
```

## Privacy and local-only operation

Codebase AI is designed for code that should remain on the developer's machine.

The application web server binds to:

```text
127.0.0.1
```

The default local services are:

```text
Codebase AI    http://127.0.0.1:8765
MLX-LM         http://127.0.0.1:8080
Ollama         http://127.0.0.1:11434
```

There is no cloud-model fallback, cloud database, analytics SDK, or telemetry sender in the current application.

Repository content, embeddings, indexes, conversations, and citations are stored locally.

Internet access is required when initially downloading dependencies and models. Once the required packages and models are installed, normal repository analysis uses local services.

See `docs/PRIVACY.md` for additional details.

## Supported platform

The current release is developed for macOS on Apple Silicon.

Validated development target:

```text
Apple Silicon Mac
macOS 15 or newer
48 GB unified memory
Python 3.12
Node.js 24
Java 21
```

The default 30B model configuration was selected for a 48 GB unified-memory Mac. Lower-memory configurations have not been validated as part of the current release.

## Prerequisites

Install the following before setting up Codebase AI:

- Apple Command Line Tools
- Homebrew
- Python 3.12
- Node.js 24
- Java 21
- Git
- ripgrep
- Ollama
- MLX-LM
- `qwen3-embedding:0.6b`
- `mlx-community/Qwen3-Coder-30B-A3B-Instruct-4bit`

### 1. Apple Command Line Tools

```bash
xcode-select --install
```

Verify:

```bash
xcode-select -p
```

### 2. Homebrew

Official site:

```text
https://brew.sh/
```

Install:

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

On Apple Silicon:

```bash
echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> ~/.zprofile
eval "$(/opt/homebrew/bin/brew shellenv)"
```

### 3. Python, Node.js, Git, ripgrep, and Java

```bash
brew install python@3.12
brew install node@24
brew install git ripgrep
brew install --cask temurin@21
```

Add versioned Node to the shell path if required:

```bash
echo 'export PATH="/opt/homebrew/opt/node@24/bin:$PATH"' >> ~/.zshrc
export PATH="/opt/homebrew/opt/node@24/bin:$PATH"
```

Verify:

```bash
python3.12 --version
node --version
npm --version
java -version
git --version
rg --version
```

### 4. Ollama and the embedding model

Official site:

```text
https://ollama.com/
```

After installing Ollama:

```bash
ollama pull qwen3-embedding:0.6b
```

Verify:

```bash
ollama list
```

### 5. MLX-LM

Create a dedicated MLX environment:

```bash
mkdir -p ~/CodebaseAI-ModelTools
cd ~/CodebaseAI-ModelTools

python3.12 -m venv .venv
source .venv/bin/activate

python -m pip install --upgrade pip
pip install --upgrade mlx-lm
```

Verify:

```bash
python -c "import mlx; import mlx_lm; print('MLX-LM OK')"
```

### 6. Download the local coding model

With the MLX environment active:

```bash
mlx_lm.generate \
  --model mlx-community/Qwen3-Coder-30B-A3B-Instruct-4bit \
  --prompt "Reply with exactly: Codebase AI model ready." \
  --max-tokens 20
```

The first execution downloads the model into the local Hugging Face cache.

When complete:

```bash
deactivate
```

## Installation

Clone the repository:

```bash
git clone https://github.com/YOUR_USERNAME/codebase-ai.git
cd codebase-ai
```

Make the local launcher scripts executable:

```bash
chmod +x setup.command start.command stop.command verify.command
```

Run the one-time project setup:

```bash
./setup.command
```

The setup script:

1. Creates an isolated Python virtual environment in `.venv/`.
2. Installs backend and indexing dependencies.
3. Warms the Tree-sitter parsers.
4. Installs frontend dependencies.
5. Builds the React frontend.
6. Runs the automated backend test suite.

## Verify the installation

Run:

```bash
./verify.command
```

This performs local environment checks, Python compilation checks, automated tests, backend route/import checks, and frontend build verification.

## Start Codebase AI

Run:

```bash
./start.command
```

The launcher:

1. Verifies that setup has completed.
2. Starts or reuses local Ollama.
3. Verifies that `qwen3-embedding:0.6b` is available.
4. Starts or reuses the MLX-LM model server.
5. Starts FastAPI on `127.0.0.1:8765`.
6. Opens Codebase AI in the default browser.

The application is available at:

```text
http://127.0.0.1:8765
```

Keep the Terminal window running while using the application.

## Stop Codebase AI

To stop the application and local services started by Codebase AI:

```bash
./stop.command
```

## Using the application

1. Start Codebase AI.
2. Click `Open local repository`.
3. Select a repository using the macOS folder picker.
4. Wait until indexing completes.
5. Start a conversation or select one of the suggested repository questions.
6. Click repository evidence in an answer to inspect the cited source range.
7. Start additional conversations from the sidebar as needed.
8. Reopen a saved conversation later and continue from where you left off.

## Persistent chat history

Conversations are stored locally in SQLite and are not kept inside the cloned Codebase AI repository.

Each conversation stores:

- repository association
- title
- timestamps
- user messages
- assistant messages
- source citations
- source file hashes
- repository commit information

This allows multiple independent conversations per repository and makes them reopenable from the sidebar.

## Local application data

By default, runtime data is stored at:

```text
~/Library/Application Support/CodebaseAI/
```

Important files and directories include:

```text
codebase-ai.db
logs/
pids/
```

The SQLite database contains repository metadata, indexes, conversations, messages, and source citations.

Do not commit this directory to Git.

## Repository indexing

For Git repositories, Codebase AI discovers tracked and untracked files while respecting Git ignore rules.

For non-Git directories, it walks the repository while excluding common generated, dependency, IDE, and build directories.

The scanner excludes common secret-bearing files such as:

```text
.env
.env.*
*.pem
*.key
*.p12
*.pfx
*.jks
*.keystore
```

The current implementation indexes both structural symbols and bounded file windows. This is intentional: symbol-only indexing can miss top-level module logic and configuration, while fixed-size text chunking can lose source-code structure.

## Semantic retrieval

Semantic embeddings are generated locally using:

```text
qwen3-embedding:0.6b
```

If Ollama or the embedding model is unavailable, indexing can still complete using lexical and structural retrieval. Semantic retrieval becomes available after embeddings are successfully generated.

## Configuration

The launcher and backend support environment-variable overrides.

### Application

```bash
export CODEBASE_AI_PORT=8765
export CODEBASE_AI_DATA_DIR="$HOME/Library/Application Support/CodebaseAI"
```

### MLX

```bash
export CODEBASE_AI_MLX_VENV="$HOME/CodebaseAI-ModelTools/.venv"
export CODEBASE_AI_MLX_URL="http://127.0.0.1:8080"
export CODEBASE_AI_LLM_MODEL="mlx-community/Qwen3-Coder-30B-A3B-Instruct-4bit"
```

### Ollama

```bash
export CODEBASE_AI_OLLAMA_URL="http://127.0.0.1:11434"
export CODEBASE_AI_EMBEDDING_MODEL="qwen3-embedding:0.6b"
```

### Indexing and context

```bash
export CODEBASE_AI_MAX_FILE_BYTES=2000000
export CODEBASE_AI_MAX_CHUNK_CHARS=12000
export CODEBASE_AI_INDEX_EMBEDDINGS=1
export CODEBASE_AI_EMBED_BATCH_SIZE=12
export CODEBASE_AI_CONTEXT_CHAR_BUDGET=120000
export CODEBASE_AI_RECENT_CHAT_MESSAGES=14
```

Environment variables can be exported in the current Terminal session before running `./start.command`.

## API documentation

While the application is running:

```text
http://127.0.0.1:8765/api/docs
```

The React UI and FastAPI API are served from the same localhost origin in the built application.

## Project structure

```text
CodebaseAI/
├── backend/
│   ├── app/
│   │   ├── services/
│   │   └── ...
│   ├── tests/
│   └── requirements.txt
│
├── frontend/
│   ├── src/
│   ├── package.json
│   ├── tsconfig.json
│   └── vite.config.ts
│
├── docs/
│   ├── ARCHITECTURE.md
│   ├── CHANGELOG.md
│   ├── PRIVACY.md
│   └── TEST_REPORT.md
│
├── scripts/
│   └── doctor.py
│
├── setup.command
├── start.command
├── stop.command
├── verify.command
└── VERSION
```

## Development

Run the normal project setup first:

```bash
./setup.command
```

### Backend

```bash
source .venv/bin/activate

PYTHONPATH="$PWD/backend" \
uvicorn app.main:app \
  --host 127.0.0.1 \
  --port 8765 \
  --reload
```

### Frontend

In another Terminal:

```bash
cd frontend
npm run dev
```

The Vite development server runs on:

```text
http://127.0.0.1:5173
```

and proxies `/api` requests to FastAPI on port `8765`.

## Tests

Run the packaged verification:

```bash
./verify.command
```

Or run backend tests directly:

```bash
source .venv/bin/activate
PYTHONPATH="$PWD/backend" python -m pytest -q backend/tests
```

Build the frontend directly:

```bash
cd frontend
npm run build
```

## Troubleshooting

### The frontend is not built

Run:

```bash
./setup.command
```

### An older Codebase AI instance is already using port 8765

Run:

```bash
./stop.command
./start.command
```

Verify the running version:

```bash
curl -s http://127.0.0.1:8765/api/health
```

### Ollama is unavailable

Check:

```bash
ollama list
```

If needed:

```bash
ollama serve
```

Confirm that this model is installed:

```text
qwen3-embedding:0.6b
```

### MLX-LM is unavailable

Check the configured environment:

```bash
~/CodebaseAI-ModelTools/.venv/bin/mlx_lm.server --help
```

Review the log:

```bash
cat "$HOME/Library/Application Support/CodebaseAI/logs/mlx.log"
```

### Backend startup failure

Review:

```bash
cat "$HOME/Library/Application Support/CodebaseAI/logs/backend.log"
```

### Reindex after changing repository code

Use `Refresh index` in the UI. Incremental indexing processes files that were added, changed, or removed.

## Current limitations

The current release is intentionally focused on repository understanding rather than autonomous editing.

- Repository access is read-only.
- Cross-reference graphs are currently approximate in some languages and frameworks rather than full compiler/LSP semantic graphs everywhere.
- Apple Silicon is the supported runtime target for the bundled model strategy.
- Large repository answers depend on retrieval quality and should be verified against the cited source.
- No cloud model fallback is provided.

Future versions can add exact SCIP/LSP-backed cross references, diff generation, approval-based edits, and deeper framework-specific analysis without changing the core conversation and persistence architecture.

## Security note

A public GitHub repository should contain only the Codebase AI source code.

Do not commit:

- selected private repositories
- `~/Library/Application Support/CodebaseAI/`
- SQLite databases
- chat exports
- model files
- `.env` files
- credentials
- private keys
- `.venv/`
- `frontend/node_modules/`

The included `.gitignore` excludes common generated, local-runtime, model, credential, and IDE files.

## License

No open-source license is included by default. Publishing the repository publicly makes the source visible, but does not by itself grant reuse, modification, or redistribution rights.

Add a `LICENSE` file only after choosing the terms under which you want other people to use the project.
