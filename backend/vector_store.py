"""
DocSentinel — Actian VectorAI DB Integration
Named vectors, hybrid search, metadata filtering, audit storage
"""

import os
import uuid
import json
import logging
import asyncio
from datetime import datetime
from typing import List, Dict, Any, Optional

log = logging.getLogger("docsentinel.vectorstore")

# ── Actian VectorAI DB Connection ─────────────────────────────────────────────
ACTIAN_HOST = os.getenv("ACTIAN_HOST", "localhost")
ACTIAN_PORT = int(os.getenv("ACTIAN_PORT", "6333"))
ACTIAN_URL = f"http://{ACTIAN_HOST}:{ACTIAN_PORT}"

COLLECTION_DOCS = "docsentinel_chunks"
COLLECTION_AUDIT = "docsentinel_audit"

TEXT_DIM = 384    # sentence-transformers/all-MiniLM-L6-v2
IMAGE_DIM = 512   # jinaai/jina-clip-v1


def get_client():
    """Get Actian VectorAI DB client (Qdrant-compatible API)"""
    try:
        from qdrant_client import QdrantClient
        return QdrantClient(host=ACTIAN_HOST, port=ACTIAN_PORT)
    except ImportError:
        log.warning("qdrant_client not installed — using mock store")
        return MockVectorStore()


class ActianVectorStore:
    def __init__(self):
        self.client = get_client()
        self._text_encoder = None
        self._image_encoder = None
        self._mock_docs: List[Dict] = []
        self._mock_audit: List[Dict] = []
        self._ensure_collections()

    def _ensure_collections(self):
        """Create collections with named vectors if they don't exist"""
        try:
            from qdrant_client.models import (
                VectorParams, Distance, NamedVector
            )
            existing = [c.name for c in self.client.get_collections().collections]

            if COLLECTION_DOCS not in existing:
                self.client.create_collection(
                    collection_name=COLLECTION_DOCS,
                    vectors_config={
                        "text_vector": VectorParams(size=TEXT_DIM, distance=Distance.COSINE),
                        "image_vector": VectorParams(size=IMAGE_DIM, distance=Distance.COSINE),
                    },
                )
                log.info(f"Created collection: {COLLECTION_DOCS} with named vectors")

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

    @property
    def text_encoder(self):
        if self._text_encoder is None:
            try:
                from sentence_transformers import SentenceTransformer
                self._text_encoder = SentenceTransformer("all-MiniLM-L6-v2")
                log.info("Loaded sentence-transformers encoder")
            except Exception as e:
                log.warning(f"SentenceTransformer unavailable: {e}")
                self._text_encoder = MockEncoder(TEXT_DIM)
        return self._text_encoder

    @property
    def image_encoder(self):
        if self._image_encoder is None:
            try:
                import open_clip
                model, _, preprocess = open_clip.create_model_and_transforms(
                    "ViT-B-32", pretrained="openai"
                )
                self._image_encoder = (model, preprocess)
                log.info("Loaded CLIP image encoder")
            except Exception as e:
                log.warning(f"CLIP unavailable: {e}")
                self._image_encoder = MockEncoder(IMAGE_DIM)
        return self._image_encoder

    def embed_text(self, text: str) -> List[float]:
        """Embed text using sentence-transformers"""
        enc = self.text_encoder
        if isinstance(enc, MockEncoder):
            return enc.encode(text)
        return enc.encode(text, convert_to_tensor=False).tolist()

    def embed_image(self, image_path: str) -> List[float]:
        """Embed image using CLIP vision encoder"""
        enc = self.image_encoder
        if isinstance(enc, MockEncoder):
            return enc.encode(image_path)
        try:
            import torch
            from PIL import Image
            model, preprocess = enc
            img = preprocess(Image.open(image_path)).unsqueeze(0)
            with torch.no_grad():
                feat = model.encode_image(img)
            return feat[0].tolist()
        except Exception as e:
            log.warning(f"Image embedding failed: {e}")
            return [0.0] * IMAGE_DIM

    async def store_document(
        self,
        doc_id: str,
        filename: str,
        chunks: List[Dict],
        images: List[Dict],
        persona_data: Dict,
    ) -> int:
        """Store all document chunks with named vectors in Actian VectorAI DB"""
        stored = 0

        for chunk in chunks:
            try:
                text_vec = self.embed_text(chunk["content"])
                # For text chunks, image vector is same dimension but zeros
                image_vec = [0.0] * IMAGE_DIM

                point = {
                    "id": str(uuid.uuid4()),
                    "vectors": {
                        "text_vector": text_vec,
                        "image_vector": image_vec,
                    },
                    "payload": {
                        **chunk,
                        "doc_id": doc_id,
                        "filename": filename,
                        "content_type": "text",
                        "domain_persona": persona_data.get("generated_system_prompt", ""),
                        "domain": persona_data.get("domain", ""),
                        "safety_level": persona_data.get("safety_level", "low"),
                    },
                }

                self._upsert_point(COLLECTION_DOCS, point)
                stored += 1
            except Exception as e:
                log.error(f"Failed to store chunk: {e}")

        for img in images:
            try:
                image_vec = self.embed_image(img["path"])
                # Generate text description vector too
                text_vec = self.embed_text(img.get("label", "diagram figure"))

                point = {
                    "id": str(uuid.uuid4()),
                    "vectors": {
                        "text_vector": text_vec,
                        "image_vector": image_vec,
                    },
                    "payload": {
                        **img,
                        "doc_id": doc_id,
                        "filename": filename,
                        "content_type": "image",
                        "category": "figure",
                        "domain_persona": persona_data.get("generated_system_prompt", ""),
                    },
                }

                self._upsert_point(COLLECTION_DOCS, point)
                stored += 1
            except Exception as e:
                log.error(f"Failed to store image: {e}")

        log.info(f"Stored {stored} records for doc {doc_id}")
        return stored

    def _upsert_point(self, collection: str, point: Dict):
        """Upsert a single point into Actian VectorAI DB"""
        try:
            from qdrant_client.models import PointStruct, NamedVector
            self.client.upsert(
                collection_name=collection,
                points=[PointStruct(
                    id=point["id"],
                    vector=point["vectors"],
                    payload=point["payload"],
                )],
            )
        except Exception as e:
            # Fallback to mock store
            self._mock_docs.append(point)

    def search_text(
        self,
        query: str,
        doc_id: Optional[str] = None,
        limit: int = 5,
        priority_safety: bool = True,
    ) -> List[Dict]:
        """Semantic text search with optional metadata filtering"""
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
                limit=limit * 2,  # Get extra for re-ranking
                with_payload=True,
            )

            hits = []
            for r in results:
                payload = r.payload
                score = r.score
                # Boost safety warnings
                if priority_safety and payload.get("category") == "safety_warning":
                    score += 0.15
                hits.append({**payload, "score": score})

            # Sort by boosted score and return top N
            hits.sort(key=lambda x: x["score"], reverse=True)
            return hits[:limit]

        except Exception as e:
            log.warning(f"Actian search failed, using mock: {e}")
            return self._mock_search(query, doc_id, limit)

    def search_by_parent(self, parent_heading: str, doc_id: Optional[str] = None) -> List[Dict]:
        """Structural retrieval: fetch all chunks under same parent heading"""
        try:
            from qdrant_client.models import Filter, FieldCondition, MatchValue

            must_conditions = [
                FieldCondition(key="parent_heading", match=MatchValue(value=parent_heading))
            ]
            if doc_id:
                must_conditions.append(
                    FieldCondition(key="doc_id", match=MatchValue(value=doc_id))
                )

            results = self.client.scroll(
                collection_name=COLLECTION_DOCS,
                scroll_filter=Filter(must=must_conditions),
                limit=10,
                with_payload=True,
            )
            return [r.payload for r in results[0]]
        except Exception:
            return []

    def search_image(self, query: str, limit: int = 3) -> List[Dict]:
        """Search image vectors using text query (zero-shot visual retrieval)"""
        query_vec = self.embed_text(query)
        try:
            from qdrant_client.models import Filter, FieldCondition, MatchValue

            results = self.client.search(
                collection_name=COLLECTION_DOCS,
                query_vector=("image_vector", query_vec + [0.0] * (IMAGE_DIM - TEXT_DIM)),
                query_filter=Filter(
                    must=[FieldCondition(key="content_type", match=MatchValue(value="image"))]
                ),
                limit=limit,
                with_payload=True,
            )
            return [r.payload for r in results]
        except Exception:
            return []

    def reciprocal_rank_fusion(
        self, result_lists: List[List[Dict]], k: int = 60
    ) -> List[Dict]:
        """Merge multiple ranked result lists using RRF"""
        scores: Dict[str, float] = {}
        items: Dict[str, Dict] = {}

        for result_list in result_lists:
            for rank, item in enumerate(result_list):
                item_id = item.get("chunk_id") or item.get("image_id") or str(rank)
                scores[item_id] = scores.get(item_id, 0) + 1.0 / (k + rank + 1)
                items[item_id] = item

        sorted_ids = sorted(scores, key=lambda x: scores[x], reverse=True)
        return [items[i] for i in sorted_ids]

    def store_audit(self, audit_record: Dict):
        """Store query reasoning trace in Actian audit collection"""
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
        """Retrieve recent audit records"""
        try:
            results = self.client.scroll(
                collection_name=COLLECTION_AUDIT,
                limit=limit,
                with_payload=True,
                order_by="timestamp",
            )
            return [r.payload for r in results[0]]
        except Exception:
            return [r["payload"] for r in self._mock_audit[-limit:]]

    def search_audit(self, query: str) -> List[Dict]:
        """Semantic search over audit history"""
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

    def list_documents(self) -> List[Dict]:
        """List unique ingested documents"""
        try:
            results = self.client.scroll(
                collection_name=COLLECTION_DOCS,
                limit=1000,
                with_payload=True,
            )
            seen = {}
            for r in results[0]:
                p = r.payload
                did = p.get("doc_id")
                if did and did not in seen:
                    seen[did] = {
                        "doc_id": did,
                        "filename": p.get("filename", "Unknown"),
                        "domain": p.get("domain", ""),
                        "safety_level": p.get("safety_level", ""),
                        "persona": p.get("domain_persona", ""),
                    }
            return list(seen.values())
        except Exception:
            seen = {}
            for item in self._mock_docs:
                p = item.get("payload", {})
                did = p.get("doc_id")
                if did and did not in seen:
                    seen[did] = {
                        "doc_id": did,
                        "filename": p.get("filename", "Unknown"),
                        "domain": p.get("domain", ""),
                        "safety_level": p.get("safety_level", ""),
                        "persona": p.get("domain_persona", ""),
                    }
            return list(seen.values())

    def reset_all(self) -> Dict:
        """Delete all collections and uploaded files — full reset"""
        deleted_collections = []
        try:
            for col in [COLLECTION_DOCS, COLLECTION_AUDIT]:
                try:
                    self.client.delete_collection(col)
                    deleted_collections.append(col)
                    log.info(f"Deleted collection: {col}")
                except Exception as e:
                    log.warning(f"Could not delete collection {col}: {e}")
            # Recreate empty collections
            self._ensure_collections()
        except Exception as e:
            log.warning(f"Reset partial (mock mode): {e}")

        # Clear mock stores
        self._mock_docs.clear()
        self._mock_audit.clear()

        # Delete uploaded files
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
            "files_cleared": deleted_files,
            "status": "reset_complete"
        }

    def health_check(self) -> str:
        try:
            self.client.get_collections()
            return "connected"
        except Exception:
            return "mock_mode"

    def _mock_search(self, query: str, doc_id: Optional[str], limit: int) -> List[Dict]:
        """Simple mock search for demo without Actian running"""
        results = []
        for item in self._mock_docs:
            p = item.get("payload", {})
            if doc_id and p.get("doc_id") != doc_id:
                continue
            content = p.get("content", "").lower()
            q_words = query.lower().split()
            score = sum(1 for w in q_words if w in content) / max(len(q_words), 1)
            if score > 0:
                results.append({**p, "score": score})
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:limit]


class MockEncoder:
    """Deterministic mock encoder for when ML libraries aren't available"""
    def __init__(self, dim: int):
        self.dim = dim

    def encode(self, text: str) -> List[float]:
        import hashlib
        import math
        h = hashlib.sha256(str(text).encode()).digest()
        vec = []
        for i in range(self.dim):
            byte = h[i % 32]
            vec.append(math.sin(byte + i * 0.1) * 0.5)
        # Normalize
        magnitude = sum(x**2 for x in vec) ** 0.5
        if magnitude > 0:
            vec = [x / magnitude for x in vec]
        return vec


class MockVectorStore:
    """Mock Actian client for demo without running Actian instance"""
    def get_collections(self):
        class R:
            collections = []
        return R()

    def create_collection(self, **kwargs):
        pass

    def delete_collection(self, collection_name, **kwargs):
        pass

    def upsert(self, **kwargs):
        pass

    def search(self, **kwargs):
        return []

    def scroll(self, **kwargs):
        return [], None
