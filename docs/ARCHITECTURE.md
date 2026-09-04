# Architecture

```text
Browser / React + TypeScript
        |
        | same-origin localhost API
        v
FastAPI on 127.0.0.1:8765
        |
        +-- Repository scanner
        |      +-- Git tracked + untracked discovery
        |      +-- ignore / secret exclusions
        |      +-- incremental hash tracking
        |
        +-- Code parser
        |      +-- Tree-sitter language pack
        |      +-- JS/TS/TSX/MJS framework heuristics
        |      +-- Java/Spring heuristics
        |      +-- Karate parser
        |      +-- AWS Lambda / AWS SDK signals
        |
        +-- SQLite
        |      +-- files
        |      +-- symbols
        |      +-- code chunks
        |      +-- FTS5 indexes
        |      +-- approximate reference edges
        |      +-- conversations/messages
        |      +-- message source citations
        |
        +-- Hybrid retrieval
        |      +-- FTS lexical search
        |      +-- symbol search
        |      +-- semantic search
        |      +-- graph expansion
        |      +-- reciprocal-rank fusion
        |
        +-- Ollama 127.0.0.1:11434
        |      +-- qwen3-embedding:0.6b
        |
        +-- MLX-LM 127.0.0.1:8080
               +-- Qwen3-Coder 30B A3B 4-bit
```

## Why symbol-level + file-window chunks

Only splitting every N characters loses method/class boundaries. Only indexing symbols misses top-level module glue, configuration and executable statements. Codebase AI stores both symbol chunks and overlapping bounded file windows, then fuses retrieval paths.

## Why SQLite

SQLite keeps the installation self-contained and local while supporting transactions, relational metadata and FTS5. Embeddings are stored as float32 BLOBs. A per-repository in-memory NumPy matrix accelerates cosine retrieval after first use.

## Reference graph

Version 1 builds an approximate graph using uniquely named symbols and identifier references inside symbol chunks. It is deliberately conservative when a symbol name is ambiguous. Tree-sitter provides structural extraction while framework metadata adds higher-level signals.

A later version can add SCIP/LSP-derived exact cross-references without changing the database/chat/API shape.

## Chat context

Full history remains in SQLite. Model calls send only a bounded recent-history window plus the freshly retrieved repository evidence. This prevents very old conversations from consuming the entire model context while preserving every prior message in the UI.

## Staleness provenance

Assistant message source rows record the indexed file hash and repository commit at message time. This gives the database enough provenance for a future UI warning when old source citations no longer match current files.
