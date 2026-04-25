<div align="center">

# 🛡️ DocSentinel

### Agentic Document Intelligence — Powered by Actian VectorAI DB

**Self-Healing · Multimodal · 100% Offline · ARM Ready**

![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-009688?style=flat-square&logo=fastapi&logoColor=white)
![Actian VectorAI](https://img.shields.io/badge/Actian-VectorAI%20DB-7C3AED?style=flat-square)
![Qwen2.5-VL](https://img.shields.io/badge/LLM-Qwen2.5--VL-F97316?style=flat-square)
![Offline](https://img.shields.io/badge/Cloud-Zero%20Dependency-22C55E?style=flat-square)
![ARM](https://img.shields.io/badge/ARM-Supported-00B4D8?style=flat-square)

*Submitted to the **Actian VectorAI DB Build Challenge** · April 2026*

</div>

---

## What Is DocSentinel?

DocSentinel is a fully offline, self-healing document intelligence system. Upload any technical PDF — safety manual, legal filing, financial report, medical protocol — and ask questions in plain English. Every answer is:

- **Grounded** — cited to the exact page and section of your document
- **Scored** — confidence rated 0–10, computed from the retrieval critique score
- **Self-corrected** — if the first retrieval is poor, the agent rewrites the query and retries automatically
- **Auditable** — every reasoning step, retry, and query trace is stored back into Actian VectorAI DB
- **Private** — nothing ever leaves your machine. No API keys. No cloud.

---

## The Problem It Solves

Enterprise and industrial teams can't send confidential documents to cloud AI services. Compliance rules, IP protection, and data sovereignty requirements make tools like ChatGPT and Claude off-limits for sensitive content.

Existing local RAG systems are single-pass: one retrieval attempt, no quality gate, no self-correction. If the first search misses, the user gets a hallucinated answer with no warning.

DocSentinel solves both problems:

1. **Runs entirely on-device** using Actian VectorAI DB — no cloud, no data leakage
2. **Implements a critique-and-retry agent loop** — it detects poor retrievals and fixes them before they reach the user

---

## Demo

> **All tabs visible in the UI: Agent Log (live reasoning trace) · Persona · Audit**

| Upload & Ingest | Query with Self-Healing | Audit Tab |
|---|---|---|
| Drag PDF → MinerU parses → chunks stored in Actian VectorAI DB | Ask a question → agent retrieves, critiques, retries if needed | Full query history with retry counts and confidence scores |

**Suggested demo PDFs:**

| Document | Domain Persona Auto-Detected | Best Question |
|---|---|---|
| [WHO Situation Report (Jan 2020)](https://www.who.int/docs/default-source/coronaviruse/situation-reports/20200121-sitrep-1-2019-ncov.pdf) | 🏥 Public Health — HIGH safety | *"What disease is reported and where did it originate?"* |
| [US Constitution](https://constitutioncenter.org/media/files/constitution.pdf) | ⚖️ Legal / Constitutional | *"What does Amendment XIX say?"* |
| [NASA Technical Report](https://ntrs.nasa.gov/api/citations/19940015200/downloads/19940015200.pdf) | 🔬 Engineering — technical tone | *"What materials and specifications are listed?"* |
| [Tesla 10-K](https://ir.tesla.com/sec-filings/annual-reports/content/0000950170-23-001409/0000950170-23-001409.pdf) | 📊 Financial Analyst | *"What was total revenue and key risk factors?"* |

---

## How It Works

### The Agentic Pipeline

```
PDF Upload
    │
    ▼
MinerU Parser ──────────────────────────────────────────────────────────┐
  Layout-aware text extraction                                           │
  Table detection & image separation                                     │
    │                                                                    │
    ▼                                                                    ▼
Chunk & Embed                                              Qwen2.5-VL Persona Generator
  512 tokens / 128 overlap                                   Reads doc → detects domain
  sentence-transformers (768d)                               Generates expert system prompt
  CLIP image embeddings (512d)                               Stores persona in Actian VectorAI
    │
    ▼
Actian VectorAI DB ◄──────────────────────────────────────────────────────
  Collection 1: document chunks (text + image vectors)
  Collection 2: audit log (reasoning traces, query-searchable)
    │
    ▼  ◄── User asks a question
Triple Retrieval Engine
  ├── Engine 1: Dense vector search (cosine similarity)
  ├── Engine 2: Sparse BM25 keyword search
  └── Engine 3: Structural parent retrieval (sibling chunks)
         │
         ▼
    RRF Fusion → Top 5 chunks ranked
         │
         ▼
  ┌──────────────────────────────┐
  │   SELF-HEALING AGENT LOOP    │
  │                              │
  │  Qwen2.5-VL critiques chunks │
  │  Relevance score: 0–10       │
  │                              │
  │  Score ≥ 6.5 → Generate      │
  │  Score < 6.5 → Rewrite query │◄── HyDE rewriting
  │               → Retry        │    (max 3 attempts)
  └──────────────────────────────┘
         │
         ▼
  Answer Generation
  Domain-expert persona system prompt
  Page + section citations mandatory
  Confidence score computed
         │
         ▼
  Audit Log → Actian VectorAI DB
  Full reasoning trace stored
  Semantically searchable
```

### Actian VectorAI DB — Central Role

Actian VectorAI DB is not a peripheral component — it is the entire storage and retrieval layer:

| Collection | Vectors | Purpose |
|---|---|---|
| `documents` | 768-dim text + 512-dim image | All document chunks — text and multimodal retrieval |
| `audit_log` | Embedded query traces | Compliance audit — stores every reasoning step, retry count, confidence score — and is itself vector-searchable |

Every stage of the pipeline reads from or writes to Actian VectorAI DB:
- **Ingestion** writes chunk embeddings and persona data
- **Retrieval** queries with cosine similarity across three strategies simultaneously
- **Critique** scores are written to the audit collection after each attempt
- **Audit search** uses vector similarity to find semantically related past queries

---

## Key Features

### 🔁 Self-Healing Agent Loop
The system knows when its retrieval is bad. Qwen2.5-VL scores each retrieved chunk set for relevance (0–10). Below 6.5, the agent rewrites the query using HyDE (Hypothetical Document Embedding) and tries again — up to 3 times. Every retry is logged.

### 🧠 Auto-Configuring Domain Persona
On every document upload, Qwen2.5-VL reads the content and auto-generates a domain expert identity: domain classification, tone, key topics, safety level, and a custom system prompt. A safety manual becomes a *Certified Industrial Safety Expert*. A legal filing becomes a *Corporate Attorney*. This persona is stored in Actian VectorAI DB and used for all subsequent queries against that document.

### 🔍 Triple-Engine Retrieval + RRF Fusion
Three retrieval strategies run in parallel against Actian VectorAI DB:
- **Dense vector search** — semantic similarity for conceptual questions
- **Sparse BM25** — exact keyword match for serial numbers, codes, and technical terms
- **Structural parent retrieval** — after a chunk hits, fetch its siblings for full context

Results are fused with Reciprocal Rank Fusion (RRF) for the best combined ranking.

### 🖼️ Multimodal Visual Search
Upload a photo of a component alongside your question. CLIP embeddings let the system match your image against diagrams, schematics, and figures stored in Actian VectorAI DB — finding relevant technical illustrations even when text search alone would miss them.

### 📋 Semantically Searchable Audit Log
Every query, retry, rewrite, confidence score, and final answer is stored in Actian VectorAI DB as a searchable audit record. The Audit tab lets you search past queries with semantic search — *"find all queries about pressure valves"* finds related questions even if they used different wording.

### 🔴 Real-Time Agent Log
WebSocket streaming broadcasts every step of the agent loop to the UI as it happens — retrieval events, critique scores, retry rewrites, persona activation — making the entire reasoning process transparent.

---

## Tech Stack

| Layer | Technology |
|---|---|
| **Vector Database** | Actian VectorAI DB (3 collections, cosine similarity, metadata filtering) |
| **LLM** | Qwen2.5-VL via LM Studio (persona generation, critique scoring, answer generation) |
| **Text Embeddings** | sentence-transformers `all-mpnet-base-v2` (768-dim) |
| **Image Embeddings** | CLIP `ViT-B/32` (512-dim) |
| **PDF Parsing** | MinerU (layout-aware) with PyPDF fallback |
| **Backend** | Python 3.11 + FastAPI + WebSockets |
| **Frontend** | Vanilla JS + HTML (single file, no build step) |
| **Deployment** | Local / Docker / ARM64 |

---

## Project Structure

```
docsentinel/
├── backend/
│   ├── main.py            # FastAPI app — REST endpoints + WebSocket log broadcaster
│   ├── agent.py           # Agentic loop: retrieve → critique → retry → generate
│   ├── ingestion.py       # MinerU parsing, chunking, embedding, Actian insertion
│   ├── vector_store.py    # Actian VectorAI DB abstraction (3 collections)
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/
│   └── index.html         # Full UI — Agent Log, Persona, Audit tabs (single file)
├── docker/
│   └── docker-compose.yml
├── start.bat              # One-click Windows launcher
├── start.sh               # One-click Mac / Linux launcher
└── README.md
```

---

## Quick Start

### Prerequisites

- Python 3.11+
- [LM Studio](https://lmstudio.ai/) with **Qwen2.5-VL** model loaded, server running on port `1234`
- Actian VectorAI DB running on port `5432`
- A modern browser (Chrome, Firefox, Edge)

### Windows

```bat
start.bat
```

### Mac / Linux

```bash
chmod +x start.sh
./start.sh
```

### Docker

```bash
cd docker
docker-compose up
```

Then open `frontend/index.html` in your browser. The UI auto-connects to the backend on port `8000`.

### Environment Variables

Copy `.env.example` to `.env` and configure:

```env
VECTORAI_HOST=localhost
VECTORAI_PORT=5432
LM_STUDIO_URL=http://localhost:1234/v1
LM_MODEL=qwen2.5-vl
EMBED_MODEL=sentence-transformers/all-mpnet-base-v2
CLIP_MODEL=openai/clip-vit-base-patch32
```

---

## Hackathon Alignment

*Actian VectorAI DB Build Challenge · April 13–18, 2026*

| Judging Criterion | Weight | How DocSentinel Meets It |
|---|---|---|
| **Use of Actian VectorAI DB** | 30% | VectorAI DB is the sole persistence and retrieval layer. Three collections. Triple retrieval runs directly against it. The audit log is itself stored and queried via VectorAI. |
| **Real-World Impact** | 25% | Solves a genuine compliance problem: regulated industries cannot use cloud AI for sensitive documents. Self-healing loop actively prevents hallucination in safety-critical contexts. |
| **Technical Execution** | 25% | Full agentic pipeline with critique scoring, HyDE query rewriting, RRF fusion, CLIP multimodal retrieval, and WebSocket real-time streaming. Clean modular architecture. |
| **Demo & Presentation** | 20% | Single-file frontend opens in any browser with no setup. Real-time agent log makes every pipeline step visible. Persona card, confidence scores, and audit search tell the full story. |

**Bonus points claimed:**
- ✅ Runs 100% offline — zero cloud dependency of any kind
- ✅ ARM supported — tested on ARM hardware via Actian VectorAI ARM release
- ✅ Works without internet — embedding models and LLM run locally via LM Studio

---

## Why Actian VectorAI DB?

Standard vector databases are cloud-first. Actian VectorAI DB is built to run **at the edge, on-premises, and on ARM** — exactly where enterprise document intelligence needs to live.

DocSentinel pushes Actian VectorAI beyond basic chunk storage:

- **Multimodal collections** — text and image vectors coexist in the same database
- **Audit as a vector store** — reasoning traces are stored as embeddings, making the audit log itself semantically searchable
- **Offline-first design** — the entire system is designed around Actian's ability to run without cloud infrastructure, not as an afterthought

---

<div align="center">

Built for the **Actian VectorAI DB Build Challenge** · April 2026

*Self-Healing · Multimodal · Air-Gapped · Auditable*

</div>
