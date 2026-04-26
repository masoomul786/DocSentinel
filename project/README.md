# 🛡️ DocSentinel

> **Self-healing, multimodal, agentic document intelligence — running 100% offline, on local hardware, with zero cloud dependency.**

---

## 🧠 What Is DocSentinel?

DocSentinel is not another RAG chatbot. It is a **five-layer agentic document intelligence system** that understands your documents the way a human expert would — reading structure, reasoning about context, self-correcting when it's wrong, and logging every decision it makes.

Built for the **Actian VectorAI DB Hackathon**, DocSentinel uses Actian VectorAI DB as its central brain — storing not just knowledge, but **AI behavior profiles** and **full reasoning audit trails**, all in the same vector database.

---

## 🎯 The Problem It Solves

Industrial teams, legal teams, and compliance officers work with massive, complex documents — safety manuals, contracts, technical specs — where a wrong answer is worse than no answer.

Existing tools fail them because:
- They are cloud-dependent (your confidential data leaves your machine)
- They treat documents as flat text (losing all structure and hierarchy)
- They don't know when they are wrong (no self-correction)
- They leave no audit trail (no accountability)

DocSentinel solves all four problems simultaneously.

---

## ✨ The Five Core Innovations

### 1. 🧬 Auto-Configuring Domain Persona
After ingestion, DocSentinel sends the first 3,000 words of your document to a local vision-language model and asks it to **generate its own expert system prompt**. For a CNC machine manual, it generates:

```
"You are a certified CNC machinery safety expert.
Always cite the specific page and section number.
Prioritize safety warnings above all else.
Never guess — if information is not in the manual, say so explicitly."
```

This generated persona is stored **inside Actian VectorAI DB** as metadata alongside document chunks. When a user queries, Actian retrieves both the relevant content **and** the behavior profile simultaneously. The AI doesn't just know what the document says — it knows **how to act** with that knowledge.

---

### 2. 🏗️ Hierarchical Structural Indexing
Most RAG systems chunk documents blindly. DocSentinel uses **MinerU** for layout-aware PDF parsing, which understands that "Section 3.2 — Pressure Valve Specifications" is a child of "Chapter 3 — Safety Components."

Every chunk stored in Actian carries rich structural metadata:

```json
{
  "page": 67,
  "chapter": 4,
  "section": "3.2",
  "parent_heading": "Safety Components",
  "category": "safety_warning"
}
```

When a query matches section 3.2, Actian automatically pulls **all sibling chunks** under the same `parent_heading` — so the answer always arrives with full context, not an isolated paragraph.

---

### 3. 🖼️ True Multimodal Named Vectors
DocSentinel stores **text and images in the same vector space** using two named vector spaces inside a single Actian collection:

| Vector Space | Dimensions | Model | Stores |
|---|---|---|---|
| `text_vector` | 384 | `all-MiniLM-L6-v2` | Text chunks |
| `image_vector` | 512 | `Jina-CLIP-v1` | Diagrams and figures |

When a user uploads a **photo of a broken component**, Qwen2.5-VL describes it in text first. That description and the raw image are both embedded with Jina-CLIP — which puts text and images in the same mathematical space — and searched against Actian's `image_vector` space. The system finds the matching diagram **without any training**. Zero-shot visual troubleshooting.

---

### 4. 🔁 Self-Healing Agentic Retry Loop
Standard RAG retrieves once and hopes for the best. DocSentinel **knows when it retrieved the wrong thing** and fixes itself.

```
[AGENT] User query: "How to fix valve-X pressure issue?"
[RETRIEVE] Searching Actian... found 5 chunks, relevance score: 4/10
[CRITIQUE] Low relevance. Suggested rewrite: "pressure regulation valve maintenance procedure"
[RETRY 1] Searching Actian with new query...
[RETRIEVE] Found 5 new chunks, relevance score: 8/10
[GENERATE] Composing answer with CNC Safety Expert persona...
[ANSWER] "According to Section 3.2 (Page 67): The pressure regulation valve..."
[AUDIT] Storing reasoning trace to Actian...
```

A lightweight local model (Qwen 1.5B) acts as a **critic** after each retrieval. If relevance scores below 7/10, it rewrites the query and searches again. Maximum 3 loops. Every retry is logged.

---

### 5. 📋 Full Audit Trail Stored in Actian
Every query, every retry, every agent decision is written back to a dedicated `audit_log` collection in Actian VectorAI DB:

```json
{
  "query_id": "uuid-1234",
  "original_query": "How to fix valve-X?",
  "rewrites": ["pressure regulation valve maintenance"],
  "retrieval_scores": [4, 8],
  "retries": 1,
  "final_answer": "According to Section 3.2...",
  "answer_confidence": 8,
  "timestamp": "2026-04-17T14:23:11",
  "document_id": "cnc_manual_v2"
}
```

The audit log is **semantically searchable**. You can ask: *"Show me all questions the system was not confident about"* — and Actian will retrieve them by meaning, not just keyword. This is Actian being used for **knowledge storage, behavioral intelligence storage, and reasoning accountability** simultaneously.

---

## ⚙️ Architecture Overview

```
PDF Upload
    │
    ▼
MinerU (Layout-Aware Parsing)
├── Text chunks with structural metadata
└── Diagram/figure images with position labels
    │
    ▼
Qwen2.5-VL (Local, LM Studio)
└── Auto-generates domain expert persona
    │
    ▼
Actian VectorAI DB (Central Brain)
├── Collection: document_chunks
│   ├── text_vector (384d, sentence-transformers)
│   └── image_vector (512d, Jina-CLIP)
└── Collection: audit_log
    │
    ▼
Query Pipeline — Triple Engine
├── Engine 1: Semantic text search + metadata filter (category priority boost)
├── Engine 2: Jina-CLIP image search (text description + raw image simultaneously)
└── Engine 3: Structural parent retrieval (sibling chunks from same heading)
    │
    ▼
Reciprocal Rank Fusion (merge ranked results from all 3 engines)
    │
    ▼
Self-Healing Agent Loop
├── Critique: relevance scored by Qwen 1.5B
├── If score < 7 → rewrite query → retry (max 3 loops)
└── If score ≥ 7 → proceed to generation
    │
    ▼
Qwen2.5-VL (Answer Generation with Domain Persona)
    │
    ▼
Chainlit UI (Answer + Citations + Reasoning Trace)
    │
    ▼
Audit Record → Actian VectorAI DB
```

---

## 🗄️ Actian VectorAI DB — The Central Role

Actian VectorAI DB is not a peripheral component. It is the system's brain.

It handles **five distinct responsibilities** no other component can:

1. **Named vector search** — dual vector spaces (text + image) in a single collection
2. **Hybrid retrieval** — semantic similarity + metadata filtering in one query
3. **Structural context** — parent-heading filters for hierarchical chunk retrieval
4. **Persona storage** — AI behavior profiles stored and retrieved as payload metadata
5. **Audit intelligence** — reasoning history stored as a searchable semantic collection

Actian returns merged multi-engine results in **under 15ms locally**.

---

## 🛠️ Tech Stack

| Component | Technology |
|---|---|
| PDF Parsing | MinerU (layout-aware, image extraction) |
| Text Embeddings | `sentence-transformers/all-MiniLM-L6-v2` (384d) |
| Image + Text Embeddings | `Jina-CLIP-v1` (512d, unified space) |
| Vector Database | **Actian VectorAI DB** (named vectors, hybrid search, metadata filters) |
| Vision-Language Model | Qwen2.5-VL via LM Studio (local, offline) |
| Critique Model | Qwen 1.5B via LM Studio (lightweight, fast) |
| Multi-Engine Fusion | Reciprocal Rank Fusion (custom Python) |
| UI | Chainlit (dark mode, native image upload) |
| Agent Loop | Pure Python (no LangChain, no LangGraph) |
| Deployment | Docker (ARM-ready) |

---

## 🔒 Privacy & Offline Operation

DocSentinel runs entirely on local hardware. There is no internet connection required, no cloud API, no external service. Documents never leave the machine.

This makes DocSentinel suitable for:
- Air-gapped industrial facilities
- Legal and compliance teams handling confidential documents
- Healthcare environments with patient data
- Defense and government deployments

---

## 🚀 Getting Started

### Prerequisites
- [LM Studio](https://lmstudio.ai/) with Qwen2.5-VL and Qwen 1.5B loaded locally
- Actian VectorAI DB running (local instance)
- Python 3.10+
- Docker (optional, for containerized deployment)

### Installation

```bash
git clone https://github.com/your-username/docsentinel
cd docsentinel
pip install -r requirements.txt
```

### Configuration

```bash
cp .env.example .env
# Set ACTIAN_HOST, ACTIAN_PORT, LMSTUDIO_URL in .env
```

### Run

```bash
# Initialize Actian collections and schema
python db/actian_schema.py

# Launch the UI
chainlit run ui/app.py
```

Open `http://localhost:8000`, upload a PDF, and start querying.

---

## 💡 Example Interaction

**User uploads:** 300-page CNC machine safety manual

**Persona auto-generated:** *"You are a certified CNC machinery safety expert. Always cite the specific page and section number. Prioritize safety warnings above all else."*

**User asks:** *"How do I fix the valve-X pressure issue?"*

**Agent output:**
```
[RETRIEVE] Relevance: 4/10 — retrying with rewritten query
[RETRY 1]  Relevance: 8/10 — proceeding to generation
[ANSWER]   According to Section 3.2 (Page 67, Chapter 4 — Safety Components):
           The pressure regulation valve must be recalibrated every 500 operating
           hours. Step 1: Depressurize the line using the manual bypass at Panel B...
```

**User uploads:** photo of a burnt component

**Agent output:**
```
[VISION]   Detected: burnt thermal fuse, cylindrical, ~2cm, heat damage on casing
[IMAGE SEARCH] Matched Figure 4.2 — Thermal Fuse Assembly (Page 82)
[ANSWER]   The component is the primary thermal fuse (Part No. TF-2200).
           Replacement procedure begins on Page 83, Section 4.3...
```

---

## 🏆 Hackathon Alignment

| Judging Criterion | DocSentinel's Answer |
|---|---|
| **Actian VectorAI DB Usage** | Central role: named vectors, hybrid search, persona storage, audit log — not a peripheral add-on |
| **Real-World Impact** | Air-gapped document intelligence for industrial safety, legal, healthcare, and defense |
| **Technical Innovation** | Five systems assembled together for the first time: persona generation, hierarchical indexing, multimodal named vectors, self-healing agent, semantic audit log |
| **Offline / ARM Bonus** | Designed offline-first from the ground up; Docker container is ARM-ready |
| **Demo Quality** | Terminal shows live agent reasoning — judges see the system catching its own mistakes and fixing them in real time |

---

## 🔮 What Makes This Different

Most hackathon RAG projects follow the same pattern: upload PDF → chunk text → store vectors → ask question → get answer. DocSentinel goes further in every dimension:

- **Not just retrieval** — it critiques its own retrieval and improves it
- **Not just text** — it searches diagrams using both images and text descriptions simultaneously  
- **Not just answers** — it stores every decision it made and makes that history searchable
- **Not just a model** — it auto-configures its own expert persona per document domain
- **Not just a tool** — it is an accountable, auditable reasoning system

---

## 📄 License

MIT License — see [LICENSE](LICENSE) for details.

---

*Built for the Actian VectorAI DB Hackathon. Every component intentional. Every innovation purposeful.*
