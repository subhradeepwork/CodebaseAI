# Architecture

Codebase AI is a localhost-only repository intelligence application with four major layers.

## Frontend

The React/TypeScript frontend is served by the FastAPI process in production and communicates only with same-origin `/api` routes.

Primary responsibilities:

- repository selection and multi-repository context management
- persistent conversation navigation
- conversation deletion and confirmation
- resizable/collapsible sidebar state
- chat input and rendering
- source evidence navigation
- local runtime status

## Backend API

FastAPI owns repository registration, indexing requests, chat persistence, local source reading, system status, and static frontend delivery.

The API binds to `127.0.0.1` by default.

## Repository intelligence

Each registered repository is indexed independently. The index stores:

- files and hashes
- structural symbols
- source chunks
- FTS5 text search data
- approximate reference edges
- optional semantic embeddings
- framework and runtime signals

A conversation has one primary repository and may persist additional repository IDs in `conversation_repositories`. Retrieval runs against every repository in the saved conversation context, reserves evidence opportunities across repositories, then globally ranks the remaining candidates within a shared context budget.

Source citations retain their originating repository ID, path, line range, and file hash so the UI can open the correct repository and report stale evidence after code changes.

## Retrieval

The retrieval pipeline combines:

1. FTS5 lexical retrieval
2. symbol-name matching
3. local semantic embeddings
4. graph expansion from retrieved symbols
5. reciprocal-rank-style score fusion
6. cross-repository evidence balancing when a conversation contains multiple repositories

The resulting source windows are packed into a bounded prompt for the local coding model.

## Local inference

Semantic embeddings are produced through the configured local Ollama service. Answer generation uses the configured local MLX-LM server.

No cloud model fallback is implemented.

## Persistence

SQLite stores repositories, indexes, conversations, messages, conversation-to-repository context, source citations, and application metadata under the Codebase AI application-support directory.

Existing v1.0.x databases are migrated in place at startup. Their original repository is automatically seeded as the primary repository context for each existing conversation.
