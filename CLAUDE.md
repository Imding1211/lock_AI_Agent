# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Smart lock (電子鎖) customer service chatbot built with **LangGraph** and served via **LINE Bot** (FastAPI webhook). The system uses RAG (Retrieval-Augmented Generation) with a multi-source fallback chain, intent routing, slot filling, and conversation memory.

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run LINE Bot webhook server (production entry point)
uvicorn app:app --reload

# Run CLI test scenarios (no LINE Bot needed)
python main.py

# Seed ChromaDB with demo data (clears and rebuilds both vector stores)
python seed_db.py

# Build individual vector databases from raw documents
python build_default_db.py       # -> ./chroma_db_default
python build_troubleshoot_db.py  # -> ./chroma_db_troubleshoot

# Run mock order API server (for testing db_order_api retriever)
uvicorn mock_api:app --port 8001

# Run debounce tests
python -m pytest tests/test_debounce.py
```

## Architecture

### LangGraph Pipeline (`graph/`)

The core is a **StateGraph** compiled in `graph/builder.py`. The flow:

```
START -> load_user_profile -> rewrite_query -> detect_intent -> extract_slots
  -> (conditional) ask_missing_slots -> END  (if required slots missing)
  -> (conditional) [retriever node] -> (grader) -> generate -> update_user_profile -> END
  -> (conditional) human -> END  (transfer to human agent)
```

- **`state.py`** — `GraphState` TypedDict with `history` and `chat_history` as append-only (`Annotated[list, operator.add]`) fields
- **`nodes.py`** — All LangGraph node functions: `load_user_profile`, `rewrite_query`, `detect_intent`, `extract_slots`, `ask_missing_slots`, `create_retrieve_node`, `generate_answer`, `transfer_to_human`, `decide_sufficiency`, `update_user_profile`
- **`builder.py`** — Wires nodes and conditional edges; dynamically creates retriever nodes from `config.toml` `[[databases]]` entries

### Retrieval Fallback Chain

Retriever nodes are tried in `[[databases]]` array order from `config.toml`. After each retriever, `decide_sufficiency` (LLM grader) checks both domain relevance and answer quality. If insufficient, falls through to the next retriever. Final fallback is `transfer_to_human`.

Chain: Chroma (manual) -> Chroma (troubleshoot) -> API -> Web Search -> Human

### Configuration-Driven Design (`config.toml`)

Nearly everything is configured via `config.toml`, parsed by `core/config.py`:
- **`[system]`** — Domain definition for the chatbot
- **`[debounce]`** — Message buffering settings (wait time, completeness threshold)
- **`[llm]`** — Provider (`ollama`/`gemini`), model name, temperature
- **`[[databases]]`** — Ordered retriever definitions (type: `chroma`, `api`, `web_search`)
- **`[[intents]]`** — Intent routing rules mapping intent names to target retriever nodes
- **`[required_slots]`** — Slot filling requirements (e.g., `device_model`, `device_brand`)
- **`[memory]`** — Checkpointer type (currently in-memory via `MemorySaver`)
- **`[user_profile]`** — User profile persistence settings
- **`[line_bot]`** / **`[templates]`** — LINE Bot behavior settings

Secrets (API keys, tokens) use `_env` suffix fields that reference `.env` variable names.

### Plugin/Registry Pattern

New providers/retrievers are added by:
1. Creating a module in the appropriate directory
2. Registering it in the `__init__.py` registry dict

Registries:
- **`retrievers/__init__.py`** — `REGISTRY` maps type strings (`chroma`, `api`, `web_search`) to retriever classes. All retrievers extend `BaseRetriever` (abc) with `setup()` and `async aretrieve()`.
- **`llms/__init__.py`** — `LLM_REGISTRY` maps provider strings to builder functions
- **`embeddings/__init__.py`** — `REGISTRY` maps embedding provider strings to builder functions

### Message Debouncing (`core/debounce.py`)

Intelligent message completeness evaluation using rule-based heuristics (6 rules) combined with LLM assessment. Determines whether a user's buffered messages form a complete query or if more input should be awaited. Configurable via `[debounce]` in `config.toml`.

### User Profile Management (`profiles/`, `memory/`)

- **`profiles/manager.py`** — Persists user conversation state to `user_profiles/` directory
- **`memory/__init__.py`** — `get_checkpointer()` factory supporting `MemorySaver`, `SqliteSaver`, and PostgreSQL backends

### LINE Bot Integration (`app.py`)

FastAPI webhook at `/webhook`. Implements **message debouncing** — buffers rapid messages per user, waits `debounce_wait_time` seconds, then merges and processes. Uses Reply API first, falls back to Push API if the reply token expires.

## Key Conventions

- All node functions are **async** and return dicts that get merged into `GraphState`
- The `history` field tracks the path through the graph (append-only via `operator.add`)
- Environment variables override `config.toml` values when `_env` suffix fields are set
- The project language is primarily Traditional Chinese (zh-TW) for user-facing text; English for LLM system prompts
