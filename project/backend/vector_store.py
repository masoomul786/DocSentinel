"""
DocSentinel — Actian VectorAI DB Integration
Named vectors, hybrid search, metadata filtering, audit storage

IMAGE ENCODER — Design decision:
  We use jinaai/jina-clip-v1 as the image encoder, which embeds BOTH text and
  images into the SAME 512-dimensional vector space. This means:
    - Searching for "burnt thermal fuse" (text) finds the same diagram as
      uploading a photo of a burnt thermal fuse (image).
  This is the core multimodal innovation described in the project summary.

  Fallback chain:
    1. jinaai/jina-clip-v1 via transformers + Pillow  (preferred, offline)
    2. openai/clip-vit-base-patch32 via open_clip      (alternative)
    3. MockEncoder — deterministic hash-based vectors   (no ML deps required)

TEXT ENCODER:
    sentence-transformers/all-MiniLM-L6-v2 → 384-dim
    Fallback: MockEncoder
"""

import os
import uuid
import json
import logging
from pathlib import Path
import asyncio
from datetime import datetime
from typing import List, Dict, Any, Optional

log = logging.getLogger("docsentinel.vectorstore")

# ── Actian VectorAI DB Connection ─────────────────────────────────────────────
ACTIAN_HOST = os.getenv("ACTIAN_HOST", "localhost")
ACTIAN_PORT = int(os.getenv("ACTIAN_PORT", "6333"))
ACTIAN_URL = f"http://{ACTIAN_HOST}:{ACTIAN_PORT}"

COLLECTION_DOCS  = "docsentinel_chunks"
COLLECTION_AUDIT = "docsentinel_audit"

TEXT_DIM  = 384   # sentence-transformers/all-MiniLM-L6-v2
IMAGE_DIM = 512   # jinaai/jina-clip-v1  (text + image same space)


def get_client():
    """Get Actian VectorAI DB client (Qdrant-compatible REST API)"""
    try:
        from qdrant_client import QdrantClient
        return QdrantClient(host=ACTIAN_HOST, port=ACTIAN_PORT)
    except ImportError:
        log.warning("qdrant_client not installed — using mock store")
        return MockVectorStore()


class ActianVectorStore:
    def __init__(self):
        self.client = get_client()
        self._text_encoder  = None
        self._image_encoder = None   # will be JinaClipEncoder or MockEncoder
        self._mock_docs:  List[Dict] = []
        self._mock_audit: List[Dict] = []
        self._ensure_collections()

    # ── Collection bootstrap ───────────────────────────────────────────────────
    def _ensure_collections(self):
        """Create named-vector collections if they don't exist."""
        try:
            from qdrant_client.models import VectorParams, Distance
            existing = [c.name for c in self.client.get_collections().collections]

            if COLLECTION_DOCS not in existing:
                self.client.create_collection(
                    collection_name=COLLECTION_DOCS,
                    vectors_config={
                        "text_vector":  VectorParams(size=TEXT_DIM,  distance=Distance.COSINE),
                        "image_vector": VectorParams(size=IMAGE_DIM, distance=Distance.COSINE),
                    },
                )
                log.info(f"Created collection: {COLLECTION_DOCS} (named vectors: text + image)")

            if COLLECTION_AUDIT not in existing:
                self.client.create_collection(
                    collection_name=COLLECTION_AUDIT,
                    vectors_config={
                        "query_vector": VectorParams(size=TEXT_DIM, distance=Distance.COSINE),
                    },
                )
                log.info(f"Created collection: {COLLECTION_AUDIT}")

        except Exception as e:
            log.warning(f"Collection setup skipped (mock mode): {e}")

    # ── Encoder properties (lazy-load) ─────────────────────────────────────────
    @property
    def text_encoder(self):
        if self._text_encoder is None:
            try:
                from sentence_transformers import SentenceTransformer
                self._text_encoder = SentenceTransformer("all-MiniLM-L6-v2")
                log.info("Loaded text encoder: sentence-transformers/all-MiniLM-L6-v2")
            except Exception as e:
                log.warning(f"SentenceTransformer unavailable ({e}) — using mock encoder")
                self._text_encoder = MockEncoder(TEXT_DIM)
        return self._text_encoder

    @property
    def image_encoder(self):
        """
        Returns a JinaClipEncoder if jinaai/jina-clip-v1 can be loaded,
        otherwise falls back to open_clip ViT-B-32, then MockEncoder.

        JinaClipEncoder exposes:
            .encode_text(str)  → List[float]  (512-dim)
            .encode_image(path_or_pil) → List[float]  (512-dim)

        Both outputs live in the SAME vector space — this is what enables
        zero-shot visual search: "burnt fuse" text query finds fuse diagram.
        """
        if self._image_encoder is None:
            self._image_encoder = self._load_image_encoder()
        return self._image_encoder

    def _load_image_encoder(self):
        # ── Option 1: Jina CLIP (preferred) ──────────────────────────────────
        try:
            from transformers import AutoModel, AutoProcessor
            from PIL import Image
            import torch

            log.info("Loading jinaai/jina-clip-v1 …")
            model     = AutoModel.from_pretrained("jinaai/jina-clip-v1", trust_remote_code=True)
            processor = AutoProcessor.from_pretrained("jinaai/jina-clip-v1", trust_remote_code=True)
            model.eval()

            encoder = JinaClipEncoder(model, processor)
            log.info("✓ Loaded jinaai/jina-clip-v1 — text+image share same 512-dim space")
            return encoder
        except Exception as e:
            log.warning(f"jina-clip-v1 unavailable ({e}), trying open_clip …")

        # ── Option 2: open_clip ViT-B-32 ──────────────────────────────────────
        try:
            import open_clip
            import torch
            model, _, preprocess = open_clip.create_model_and_transforms(
                "ViT-B-32", pretrained="openai"
            )
            model.eval()
            log.info("✓ Loaded open_clip ViT-B-32 as image encoder (512-dim)")
            return OpenClipEncoder(model, preprocess)
        except Exception as e:
            log.warning(f"open_clip unavailable ({e}) — using mock image encoder")

        return MockEncoder(IMAGE_DIM)

    # ── Embedding methods ──────────────────────────────────────────────────────
    def embed_text(self, text: str) -> List[float]:
        """384-dim embedding for text chunks (sentence-transformers)."""
        enc = self.text_encoder
        if isinstance(enc, MockEncoder):
            return enc.encode(text)
        return enc.encode(text, convert_to_tensor=False).tolist()

    def embed_image(self, image_path: str) -> List[float]:
        """
        512-dim embedding for a diagram/figure image (Jina CLIP vision encoder).
        Falls back to MockEncoder silently.
        """
        enc = self.image_encoder
        if isinstance(enc, MockEncoder):
            return enc.encode(image_path)
        try:
            return enc.encode_image(image_path)
        except Exception as e:
            log.warning(f"Image embedding failed for {image_path}: {e}")
            return [0.0] * IMAGE_DIM

    def embed_image_text(self, text: str) -> List[float]:
        """
        512-dim embedding for a TEXT QUERY against the image vector space.
        Uses Jina CLIP text encoder so queries land in same space as images.
        This is what makes "burnt fuse" text find fuse diagrams visually.
        """
        enc = self.image_encoder
        if isinstance(enc, MockEncoder):
            return enc.encode(text)
        if isinstance(enc, JinaClipEncoder):
            try:
                return enc.encode_text(text)
            except Exception as e:
                log.warning(f"Jina text-for-image embedding failed: {e}")
                return enc.encode(text) if hasattr(enc, 'encode') else [0.0] * IMAGE_DIM
        # open_clip fallback: tokenize and encode text
        if isinstance(enc, OpenClipEncoder):
            try:
                return enc.encode_text(text)
            except Exception as e:
                log.warning(f"OpenClip text embedding failed: {e}")
        # Final fallback: use text encoder (different space, but better than zeros)
        txt = self.text_encoder
        if isinstance(txt, MockEncoder):
            v = txt.encode(text)
        else:
            v = txt.encode(text, convert_to_tensor=False).tolist()
        # Pad/truncate to IMAGE_DIM
        if len(v) < IMAGE_DIM:
            v = v + [0.0] * (IMAGE_DIM - len(v))
        return v[:IMAGE_DIM]

    # ── Storage ────────────────────────────────────────────────────────────────
    async def store_document(
        self,
        doc_id:       str,
        filename:     str,
        chunks:       List[Dict],
        images:       List[Dict],
        persona_data: Dict,
    ) -> int:
        """Store all document chunks with named vectors in Actian VectorAI DB."""
        stored = 0

        # ── Text chunks ────────────────────────────────────────────────────────
        for chunk in chunks:
            try:
                text_vec  = self.embed_text(chunk["content"])
                image_vec = [0.0] * IMAGE_DIM  # text chunks have no image embedding

                point = {
                    "id": str(uuid.uuid4()),
                    "vectors": {
                        "text_vector":  text_vec,
                        "image_vector": image_vec,
                    },
                    "payload": {
                        **chunk,
                        "doc_id":        doc_id,
                        "filename":      filename,
                        "content_type":  "text",
                        "domain_persona": persona_data.get("generated_system_prompt", ""),
                        "domain":        persona_data.get("domain", ""),
                        "safety_level":  persona_data.get("safety_level", "low"),
                    },
                }
                self._upsert_point(COLLECTION_DOCS, point)
                stored += 1
            except Exception as e:
                log.error(f"Failed to store text chunk: {e}")

        # ── Image chunks ───────────────────────────────────────────────────────
        for img in images:
            try:
                image_vec = self.embed_image(img["path"])
                # Also embed the label as text in the IMAGE vector space
                # so text queries like "thermal fuse diagram" find this image
                text_in_image_space = self.embed_image_text(img.get("label", "diagram figure"))

                point = {
                    "id": str(uuid.uuid4()),
                    "vectors": {
                        "text_vector":  text_in_image_space,  # Jina text → 512-dim
                        "image_vector": image_vec,            # Jina vision → 512-dim
                    },
                    "payload": {
                        **img,
                        "doc_id":        doc_id,
                        "filename":      filename,
                        "content_type":  "image",
                        "category":      "figure",
                        "domain_persona": persona_data.get("generated_system_prompt", ""),
                    },
                }
                self._upsert_point(COLLECTION_DOCS, point)
                stored += 1
            except Exception as e:
                log.error(f"Failed to store image: {e}")

        log.info(f"Stored {stored} records for doc_id={doc_id}")
        return stored

    def _upsert_point(self, collection: str, point: Dict):
        """Upsert a single point into Actian VectorAI DB."""
        try:
            from qdrant_client.models import PointStruct
            self.client.upsert(
                collection_name=collection,
                points=[PointStruct(
                    id=point["id"],
                    vector=point["vectors"],
                    payload=point["payload"],
                )],
            )
        except Exception as e:
            log.debug(f"Upsert fell back to mock store: {e}")
            self._mock_docs.append(point)

    # ── Search ─────────────────────────────────────────────────────────────────
    def search_text(
        self,
        query: str,
        doc_id: Optional[str] = None,
        limit: int = 5,
        priority_safety: bool = True,
    ) -> List[Dict]:
        """Semantic text search with optional metadata filter + safety boost."""
        query_vec = self.embed_text(query)
        try:
            from qdrant_client.models import Filter, FieldCondition, MatchValue

            query_filter = None
            if doc_id:
                query_filter = Filter(
                    must=[FieldCondition(key="doc_id", match=MatchValue(value=doc_id))]
                )

            results = self.client.search(
                collection_name=COLLECTION_DOCS,
                query_vector=("text_vector", query_vec),
                query_filter=query_filter,
                limit=limit * 2,
                with_payload=True,
            )

            hits = []
            for r in results:
                payload = r.payload
                score   = r.score
                if priority_safety and payload.get("category") == "safety_warning":
                    score += 0.15
                hits.append({**payload, "score": score})

            hits.sort(key=lambda x: x["score"], reverse=True)
            return hits[:limit]

        except Exception as e:
            log.warning(f"Actian text search failed ({e}) — using mock search")
            return self._mock_search(query, doc_id, limit)

    def search_image(self, query_text: str, limit: int = 3) -> List[Dict]:
        """
        Search for images using a TEXT query against the image_vector space.
        Uses embed_image_text() so the query lands in the same Jina CLIP space
        as the stored image embeddings — enabling zero-shot visual retrieval.
        """
        query_vec = self.embed_image_text(query_text)
        try:
            from qdrant_client.models import Filter, FieldCondition, MatchValue

            results = self.client.search(
                collection_name=COLLECTION_DOCS,
                query_vector=("image_vector", query_vec),
                query_filter=Filter(
                    must=[FieldCondition(key="content_type", match=MatchValue(value="image"))]
                ),
                limit=limit,
                with_payload=True,
            )
            return [r.payload for r in results]
        except Exception:
            return []

    def search_by_parent(self, parent_heading: str, doc_id: Optional[str] = None) -> List[Dict]:
        """Structural retrieval: all chunks under the same parent heading."""
        try:
            from qdrant_client.models import Filter, FieldCondition, MatchValue

            must = [FieldCondition(key="parent_heading", match=MatchValue(value=parent_heading))]
            if doc_id:
                must.append(FieldCondition(key="doc_id", match=MatchValue(value=doc_id)))

            results = self.client.scroll(
                collection_name=COLLECTION_DOCS,
                scroll_filter=Filter(must=must),
                limit=10,
                with_payload=True,
            )
            return [r.payload for r in results[0]]
        except Exception:
            return []

    def reciprocal_rank_fusion(
        self, result_lists: List[List[Dict]], k: int = 60
    ) -> List[Dict]:
        """Merge multiple ranked lists using Reciprocal Rank Fusion."""
        scores: Dict[str, float] = {}
        items:  Dict[str, Dict]  = {}

        for result_list in result_lists:
            for rank, item in enumerate(result_list):
                item_id = item.get("chunk_id") or item.get("image_id") or str(id(item))
                scores[item_id] = scores.get(item_id, 0) + 1.0 / (k + rank + 1)
                items[item_id]  = item

        sorted_ids = sorted(scores, key=lambda x: scores[x], reverse=True)
        return [items[i] for i in sorted_ids]

    # ── Audit ──────────────────────────────────────────────────────────────────
    def store_audit(self, audit_record: Dict):
        """Store the full agent reasoning trace in Actian audit collection."""
        query_vec = self.embed_text(audit_record.get("original_query", ""))
        point = {
            "id": str(uuid.uuid4()),
            "vectors": {"query_vector": query_vec},
            "payload": {
                **audit_record,
                "timestamp": datetime.utcnow().isoformat(),
            },
        }
        try:
            from qdrant_client.models import PointStruct
            self.client.upsert(
                collection_name=COLLECTION_AUDIT,
                points=[PointStruct(
                    id=point["id"],
                    vector=point["vectors"],
                    payload=point["payload"],
                )],
            )
        except Exception:
            self._mock_audit.append(point)

    def get_audit_log(self, limit: int = 20) -> List[Dict]:
        """
        Retrieve recent audit records, sorted newest-first.
        We scroll without order_by (qdrant-client ≥1.7 only) and sort client-side.
        """
        try:
            results = self.client.scroll(
                collection_name=COLLECTION_AUDIT,
                limit=limit,
                with_payload=True,
            )
            records = [r.payload for r in results[0]]
            records.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
            return records
        except Exception:
            records = [r["payload"] for r in self._mock_audit[-limit:]]
            records.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
            return records

    def search_audit(self, query: str) -> List[Dict]:
        """Semantic search over audit history."""
        vec = self.embed_text(query)
        try:
            results = self.client.search(
                collection_name=COLLECTION_AUDIT,
                query_vector=("query_vector", vec),
                limit=10,
                with_payload=True,
            )
            return [r.payload for r in results]
        except Exception:
            return [r["payload"] for r in self._mock_audit]

    # ── Document listing ───────────────────────────────────────────────────────
    def list_documents(self) -> List[Dict]:
        """List unique ingested documents (one entry per doc_id)."""
        try:
            results = self.client.scroll(
                collection_name=COLLECTION_DOCS,
                limit=1000,
                with_payload=True,
            )
            seen: Dict[str, Dict] = {}
            for r in results[0]:
                p   = r.payload
                did = p.get("doc_id")
                if did and did not in seen:
                    seen[did] = {
                        "doc_id":       did,
                        "filename":     p.get("filename", "Unknown"),
                        "domain":       p.get("domain", ""),
                        "safety_level": p.get("safety_level", ""),
                        "persona":      p.get("domain_persona", ""),
                    }
            return list(seen.values())
        except Exception:
            seen = {}
            for item in self._mock_docs:
                p   = item.get("payload", {})
                did = p.get("doc_id")
                if did and did not in seen:
                    seen[did] = {
                        "doc_id":       did,
                        "filename":     p.get("filename", "Unknown"),
                        "domain":       p.get("domain", ""),
                        "safety_level": p.get("safety_level", ""),
                        "persona":      p.get("domain_persona", ""),
                    }
            return list(seen.values())

    # ── Reset ──────────────────────────────────────────────────────────────────
    def reset_all(self) -> Dict:
        """Delete all collections and uploaded files — full wipe."""
        deleted_collections = []
        try:
            for col in [COLLECTION_DOCS, COLLECTION_AUDIT]:
                try:
                    self.client.delete_collection(col)
                    deleted_collections.append(col)
                    log.info(f"Deleted collection: {col}")
                except Exception as e:
                    log.warning(f"Could not delete {col}: {e}")
            self._ensure_collections()
        except Exception as e:
            log.warning(f"Reset partial (mock mode): {e}")

        self._mock_docs.clear()
        self._mock_audit.clear()

        import shutil
        deleted_files = 0
        for folder in ["uploads", "extracted_images", "mineru_output"]:
            p = Path(folder)
            if p.exists():
                shutil.rmtree(p)
                p.mkdir(exist_ok=True)
                deleted_files += 1

        return {
            "collections_reset": deleted_collections,
            "files_cleared":     deleted_files,
            "status":            "reset_complete",
        }

    def health_check(self) -> str:
        try:
            self.client.get_collections()
            return "connected"
        except Exception:
            return "mock_mode"

    # ── Mock fallback search ───────────────────────────────────────────────────
    def _mock_search(self, query: str, doc_id: Optional[str], limit: int) -> List[Dict]:
        """Keyword-based mock search used when Actian is unreachable."""
        results = []
        for item in self._mock_docs:
            p       = item.get("payload", {})
            if doc_id and p.get("doc_id") != doc_id:
                continue
            content = p.get("content", "").lower()
            q_words = query.lower().split()
            score   = sum(1 for w in q_words if w in content) / max(len(q_words), 1)
            if score > 0:
                results.append({**p, "score": score})
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:limit]


# ── Encoder implementations ────────────────────────────────────────────────────

class JinaClipEncoder:
    """
    Wraps jinaai/jina-clip-v1 loaded via HuggingFace transformers.
    Both encode_text() and encode_image() return 512-dim vectors in the SAME
    latent space — enabling zero-shot text-to-image and image-to-image search.
    """
    def __init__(self, model, processor):
        self.model     = model
        self.processor = processor

    def encode_text(self, text: str) -> List[float]:
        import torch
        inputs = self.processor(text=[text], return_tensors="pt", padding=True, truncation=True)
        with torch.no_grad():
            emb = self.model.get_text_features(**inputs)
            emb = emb / emb.norm(dim=-1, keepdim=True)
        return emb[0].tolist()

    def encode_image(self, image_path_or_pil) -> List[float]:
        import torch
        from PIL import Image
        if isinstance(image_path_or_pil, str):
            img = Image.open(image_path_or_pil).convert("RGB")
        else:
            img = image_path_or_pil.convert("RGB")
        inputs = self.processor(images=img, return_tensors="pt")
        with torch.no_grad():
            emb = self.model.get_image_features(**inputs)
            emb = emb / emb.norm(dim=-1, keepdim=True)
        return emb[0].tolist()


class OpenClipEncoder:
    """
    Wraps open_clip ViT-B-32 as a fallback.
    Also encodes text and images in the same 512-dim space.
    """
    def __init__(self, model, preprocess):
        self.model     = model
        self.preprocess = preprocess

    def encode_text(self, text: str) -> List[float]:
        import torch
        import open_clip
        tokens = open_clip.tokenize([text])
        with torch.no_grad():
            emb = self.model.encode_text(tokens)
            emb = emb / emb.norm(dim=-1, keepdim=True)
        return emb[0].tolist()

    def encode_image(self, image_path: str) -> List[float]:
        import torch
        from PIL import Image
        img = self.preprocess(Image.open(image_path).convert("RGB")).unsqueeze(0)
        with torch.no_grad():
            emb = self.model.encode_image(img)
            emb = emb / emb.norm(dim=-1, keepdim=True)
        return emb[0].tolist()


class MockEncoder:
    """
    Deterministic hash-based encoder used when no ML library is available.
    Produces normalized vectors so cosine similarity still works for demo.
    """
    def __init__(self, dim: int):
        self.dim = dim

    def encode(self, text: str) -> List[float]:
        import hashlib, math
        h   = hashlib.sha256(str(text).encode()).digest()
        vec = [math.sin(h[i % 32] + i * 0.1) * 0.5 for i in range(self.dim)]
        mag = sum(x**2 for x in vec) ** 0.5
        return [x / mag for x in vec] if mag > 0 else vec


class MockVectorStore:
    """No-op Actian client used when qdrant_client is not installed."""
    def get_collections(self):
        class R:
            collections = []
        return R()
    def create_collection(self, **kw): pass
    def delete_collection(self, collection_name, **kw): pass
    def upsert(self, **kw): pass
    def search(self, **kw): return []
    def scroll(self, **kw): return [], None
