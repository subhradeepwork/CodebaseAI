# Changelog

## 1.1.0

- Added multi-repository conversation context. A primary repository can be combined with additional indexed repositories and queries retrieve evidence across the full saved context.
- Added repository-aware source citations so evidence opens from the correct repository in multi-repository conversations.
- Added a draggable sidebar divider with persisted width and a one-click full collapse/expand control.
- Added database migrations that preserve existing v1.0.x conversations while seeding their original repository into the new conversation context model.
- Generalized default prompts and documentation so the application remains extensible rather than bounded to a fixed framework list.

## 1.0.2

- Replaced the chat panel CSS Grid sizing with a viewport-bounded column flex layout so the composer always retains its own visible space after long responses.
- Added `100dvh` viewport sizing and explicit overflow containment for desktop browser viewport changes.
- Prevented cached `index.html` from keeping an older frontend after an upgrade.
- `start.command` now detects when an older Codebase AI process is still serving port 8765 instead of silently opening the stale instance.
- Corrected runtime version reporting.

## 1.0.1

- Fixed the chat composer disappearing after the first assistant response.
- Stabilized the main chat grid so the message list is the only vertically scrolling region and the input composer remains visible at the bottom.
- Added a regression test for the persistent composer layout.

## 1.0.0

- Localhost React/TypeScript interface.
- FastAPI backend bound to localhost only.
- Persistent ChatGPT-style per-repository conversation history in SQLite.
- Automatic chat titles, rename, delete and conversation search.
- Incremental repository indexing.
- JavaScript, TypeScript, React, `.mjs`, Java/Spring and Karate structural extraction.
- AWS Lambda handler, AWS SDK and environment-variable metadata.
- Hybrid FTS, symbol, graph and semantic retrieval.
- Local Qwen3 embeddings through Ollama.
- Local Qwen3-Coder inference through MLX-LM.
- Repository evidence chips and source code viewer.
- Git commit provenance stored with messages.
- Read-only source access and common-secret file exclusions.
