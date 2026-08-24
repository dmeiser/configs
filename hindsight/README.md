# Hindsight Configuration

Configurations and systemd service definitions for running [Hindsight](https://github.com/vectorize-io/hindsight) (agent memory service) with local GPU-accelerated embedding and reranking servers.

---

## Overview

Hindsight provides persistent, adaptive memory for AI agents with mental models, entity extraction, observation histories, and graph link traversal.

This deployment runs Hindsight via Podman on the host network, connected to a local PostgreSQL instance, a cloud LLM provider for reasoning/reflection, and dedicated local `llama.cpp` instances for embedding and reranking.

```
                  ┌───────────────────────────────┐
                  │    Hindsight Memory Engine    │
                  │  (ghcr.io/vectorize-io/... )  │
                  │  API: :8888 | Web UI: :9999   │
                  └──────┬────────┬────────┬──────┘
                         │        │        │
         ┌───────────────┘        │        └────────────────┐
         ▼                        ▼                         ▼
┌───────────────────┐  ┌─────────────────────┐  ┌───────────────────────┐
│ PostgreSQL DB     │  │ Local Embeddings    │  │ Local Reranker        │
│ localhost:5432    │  │ llama.cpp (:8081)   │  │ llama.cpp (:8080)     │
│ db: hindsight     │  │ pplx-embed-context  │  │ Qwen3-Reranker-0.6B   │
└───────────────────┘  └─────────────────────┘  └───────────────────────┘
                                  │
                                  ▼
                       ┌─────────────────────┐
                       │ Cloud LLM Provider  │
                       │ Cloud Provider API  │
                       │ deepseek-v4-flash   │
                       └─────────────────────┘
```

---

## File Structure

- [`env`](./env): Environment variables file containing credentials, model endpoints, and database connection strings. All sensitive tokens are masked with `****` and username is replaced with `username`.
- [`mental_models.md`](./mental_models.md): Prompt templates for Hindsight mental models (`SOUL.md` and `USER.md`).
- [`systemd/hindsight.service`](./systemd/hindsight.service): Systemd user service managing the Hindsight container lifecycle via Podman.
- [`systemd/llama-embedding.service`](./systemd/llama-embedding.service): Systemd user service running local `llama.cpp` embedding server.
- [`systemd/llama-reranking.service`](./systemd/llama-reranking.service): Systemd user service running local `llama.cpp` reranking server.

---

## Component Configurations

### 1. Core Service & Database
- **Container Image**: `ghcr.io/vectorize-io/hindsight:latest`
- **Network Mode**: Host networking (`--network host`)
- **Ports**:
  - `8888`: Hindsight Dataplane API
  - `9999`: Hindsight Control Plane (Web UI)
- **Database**: PostgreSQL at `localhost:5432/hindsight`

### 2. LLM Reasoning & Reflection
- **Provider**: OpenAI-compatible cloud provider (`HINDSIGHT_API_LLM_PROVIDER=openai`)
- **Base URL**: `****` (Cloud provider endpoint)
- **Model**: `deepseek-v4-flash`
- *Alternative Configurations (Commented in `env`)*: Cloud-backed models (`nemotron-3-nano:30b-cloud`, `gemma4:cloud`, `gpt-oss:20b-cloud`).

### 3. Local Embedding Server (`llama-embedding.service`)
- **Binary**: `~/.local/bin/llama serve`
- **Model**: `argus-ai/pplx-embed-context-v1-0.6b-GGUF:Q8_0`
- **Host / Port**: `0.0.0.0:8081` (`http://127.0.0.1:8081/v1`)
- **Compute Acceleration**: CUDA device 1 (`--device CUDA1`), offloading all layers (`-ngl 99999`).
- **Context & Batch Size**: Context 4096, Batch Size 4096.

### 4. Local Reranker Server (`llama-reranking.service`)
- **Binary**: `~/.local/bin/llama serve`
- **Model**: `ggml-org/Qwen3-Reranker-0.6B-Q8_0-GGUF`
- **Host / Port**: `0.0.0.0:8080` (`http://127.0.0.1:8080/v1/rerank`)
- **Compute Acceleration**: CUDA device 0 (`--device CUDA0`), offloading all layers (`-ngl 99999`).
- **Context & Batch Size**: Context 16384, Batch Size 1024.
