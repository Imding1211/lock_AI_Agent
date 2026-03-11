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
python scripts/seed_db.py

# Run mock order API server (for testing db_order_api retriever)
uvicorn scripts.mock_api:app --port 8001
```

## Architecture

### LangGraph Pipeline (`graph/`)

The core is a **StateGraph** compiled in `graph/builder.py`. The flow:

```
START → pre_process → router → {agents | out_of_domain | human} → post_process → END
```

- **`state.py`** — `GraphState` TypedDict with `history` and `chat_history` as append-only (`Annotated[list, operator.add]`) fields
- **`nodes.py`** — All LangGraph node functions: `pre_process`, `router`, `handle_out_of_domain`, `handle_transfer_human`, `post_process`
- **`builder.py`** — Wires nodes and conditional edges; dynamically creates agent subgraphs from `config.toml` `[[agents]]` entries

### Multi-Agent Architecture

Each agent is a LLM+Tools subgraph with its own prompt and tool set. The router classifies user intent and dispatches to the appropriate agent. Each agent has access to `transfer_to_human` tool for self-escalation when it cannot answer.

### Configuration-Driven Design (`config.toml`)

Nearly everything is configured via `config.toml`, parsed by `core/config.py`:
- **`[system]`** — Domain definition for the chatbot
- **`[debounce]`** — Message buffering settings (`buffer_wait` seconds)
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

### User Profile Management (`profiles/`, `memory/`)

- **`profiles/manager.py`** — Persists user conversation state to `data/profiles/` directory
- **`memory/__init__.py`** — `get_checkpointer()` factory supporting `MemorySaver`, `SqliteSaver`, and PostgreSQL backends

### LINE Bot Integration (`app.py`)

FastAPI webhook at `/webhook`. Implements simple **message buffering** — buffers rapid messages per user, waits `buffer_wait` seconds (new messages reset the timer), then merges and sends to LangGraph. Uses Reply API first, falls back to Push API if the reply token expires.

## Key Conventions

- All node functions are **async** and return dicts that get merged into `GraphState`
- The `history` field tracks the path through the graph (append-only via `operator.add`)
- Environment variables override `config.toml` values when `_env` suffix fields are set
- The project language is primarily Traditional Chinese (zh-TW) for user-facing text; English for LLM system prompts
