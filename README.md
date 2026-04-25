# 🛡️ DocSentinel — Agentic Document Intelligence

> **Self-Healing · Multimodal · Air-Gapped · Powered by Actian VectorAI DB**

DocSentinel is a production-grade document intelligence system that understands your documents like a human expert — running **100% offline**, with **zero cloud dependency**, featuring a self-healing agent loop and full audit trail stored in Actian VectorAI DB.

---

## 🚀 Quick Start

### Windows
```
Double-click  start.bat
```

### Mac / Linux
```bash
chmod +x start.sh
./start.sh
```

That's it. The script:
1. Checks Python 3.9+
2. Starts Actian VectorAI DB (via binary, Docker, or mock mode)
3. Installs Python dependencies
4. Checks LM Studio
5. Starts the backend API
6. Opens the browser UI

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    DOCSENTINEL SYSTEM                       │
├─────────────┬───────────────────────┬───────────────────────┤
│  PDF Upload │   MinerU Parser       │  Auto Persona (Qwen)  │
│             │   Layout-aware        │  Domain detection     │
│             │   Struct metadata     │  Stored in Actian     │
├─────────────┴───────────────────────┴───────────────────────┤
│              ACTIAN VECTORAI DB (Central Brain)             │
│                                                             │
│  Named Vectors:  text_vector (384d) + image_vector (512d)  │
│  Metadata:  page, section, chapter, category, persona       │
│  Collections:  chunks + audit_log                           │
├─────────────────────────────────────────────────────────────┤
│              TRIPLE ENGINE QUERY PIPELINE                   │
│                                                             │
│  Engine 1: Semantic text search + safety boost             │
│  Engine 2: Zero-shot visual search (CLIP)                  │
│  Engine 3: Structural parent hierarchy retrieval            │
│  Fusion:   Reciprocal Rank Fusion (RRF)                    │
├─────────────────────────────────────────────────────────────┤
│              SELF-HEALING AGENT LOOP                        │
│                                                             │
│  Retrieve → Critique → Retry (if score < 6.5) → Generate   │
│  Max 3 retries, full reasoning trace → Actian audit log     │
└─────────────────────────────────────────────────────────────┘
```

---

## 🔑 Five Innovations

| Innovation | Description |
|---|---|
| **Auto-Configuring Persona** | Qwen2.5-VL reads your doc, generates a domain expert system prompt, stores it in Actian |
| **Hierarchical Indexing** | Section/chapter/parent metadata — not random chunks. Structural sibling retrieval |
| **Named Vector Multimodal** | Text + image embeddings in same Actian collection. Zero-shot visual troubleshooting |
| **Self-Healing Agent** | Critique → rewrite → retry loop. The system knows when it's wrong and fixes itself |
| **Actian Audit Trail** | Every query, retry, and reasoning trace stored back into Actian as searchable records |

---

## 📋 Requirements

### Required
- Python 3.9+

### For full functionality
- **Actian VectorAI DB** (or Docker) — vector storage
- **LM Studio** with Qwen2.5-VL loaded — AI inference
- **MinerU** (`pip install magic-pdf`) — advanced PDF parsing

### Optional
- Docker (for Actian VectorAI DB auto-start)

---

## 🛠️ Manual Setup

```bash
# 1. Start Actian VectorAI DB
docker run -d -p 6333:6333 -p 6334:6334 \
  -v $(pwd)/actian_data:/qdrant/storage \
  qdrant/qdrant

# 2. Install dependencies
cd backend
pip install -r requirements.txt

# 3. Start backend
uvicorn main:app --port 8000 --reload

# 4. Open frontend
open frontend/index.html
```

---

## 🧩 Tech Stack

| Component | Technology |
|---|---|
| PDF Parsing | MinerU (layout-aware) / PyPDF fallback |
| Text Embeddings | sentence-transformers all-MiniLM-L6-v2 (384d) |
| Image Embeddings | CLIP ViT-B/32 (512d) |
| Vector DB | **Actian VectorAI DB** (Named Vectors) |
| AI Inference | Qwen2.5-VL via LM Studio |
| Critique Model | Qwen 1.5B (lightweight, fast) |
| Fusion | Reciprocal Rank Fusion (RRF) |
| Backend | FastAPI + WebSockets |
| Frontend | Vanilla JS, dark industrial UI |
| Deployment | Docker (ARM64 ready) |

---

## 🏆 Hackathon Submission — Actian VectorAI DB Build Challenge

**Judging Criteria Coverage:**

- **Use of Actian VectorAI DB (30%)**: Named vectors, hybrid search, metadata filtering, dual collections (chunks + audit)
- **Real-world impact (25%)**: Air-gapped industrial safety, GDPR-compliant offline operation
- **Technical execution (25%)**: 5 coherent innovations, clean architecture, no LangChain bloat
- **Demo & presentation (20%)**: Live self-healing visible in terminal, theatrical demo sequence

**Bonus points**: Runs 100% offline ✓ | ARM Docker ✓ | No cloud dependency ✓

---

## 📁 Project Structure

```
docsentinel/
├── start.bat              # Windows launcher
├── start.sh               # Mac/Linux launcher
├── README.md
├── backend/
│   ├── main.py            # FastAPI app + WebSocket logs
│   ├── ingestion.py       # MinerU pipeline + persona generation
│   ├── vector_store.py    # Actian VectorAI DB (named vectors, RRF)
│   ├── agent.py           # Self-healing agent loop
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/
│   └── index.html         # Dark industrial UI
└── docker/
    └── docker-compose.yml
```

---

## 🎬 Demo Script (for judges)

1. **Unplug ethernet** — "Everything you see runs locally. No API keys. No cloud."
2. Upload a 300-page PDF — watch MinerU parse, persona appear
3. Ask a normal question — get answer with page/section citation
4. Upload a photo of a component — watch visual retrieval find matching diagrams
5. Ask an ambiguous question — watch the agent retry with rewritten query (live in terminal)
6. Open Audit tab — search the reasoning history semantically in Actian
7. "This is DocSentinel. Self-configuring. Self-healing. Multimodal. Auditable."

---

Built for the **Actian VectorAI DB Build Challenge** | April 2026
