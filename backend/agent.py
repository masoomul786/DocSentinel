"""
DocSentinel — Self-Healing Agentic Query Loop
The core innovation: retrieve → critique → retry → generate → audit
"""

import json
import uuid
import logging
import asyncio
from datetime import datetime
from typing import Callable, Dict, List, Optional, Any

import httpx

log = logging.getLogger("docsentinel.agent")

LM_STUDIO_URL = "http://localhost:1234/v1/chat/completions"
MAX_RETRIES = 3
RELEVANCE_THRESHOLD = 5.0   # Lowered from 6.5 — technical docs rarely exceed 6 on keyword match


class DocSentinelAgent:
    def __init__(self, vector_store):
        self.vs = vector_store
        self.override_model_name: Optional[str] = None  # set via /api/config
        self.lm_studio_url: str = "http://localhost:1234"

    async def run(
        self,
        question: str,
        document_id: Optional[str] = None,
        image_base64: Optional[str] = None,
        broadcast_fn: Optional[Callable] = None,
    ) -> Dict:
        """Main agentic loop: retrieve → critique → retry → generate → audit"""
        broadcast = broadcast_fn or (lambda x: None)
        query_id = str(uuid.uuid4())[:8]
        reasoning_trace = []
        rewrites = []
        retrieval_scores = []

        async def emit(msg: str, level: str = "agent"):
            reasoning_trace.append(msg)
            log.info(msg)
            await broadcast({
                "type": "agent_log",
                "query_id": query_id,
                "message": msg,
                "level": level,
                "timestamp": datetime.utcnow().isoformat(),
            })

        await emit(f"[AGENT] Query received: \"{question}\"")
        await emit(f"[RETRIEVE] Searching Actian VectorAI DB...")

        current_query = question
        best_chunks = []
        best_score = 0.0
        retries = 0

        # ── Self-Healing Loop ─────────────────────────────────────────────────
        for attempt in range(MAX_RETRIES):
            # Step 1: Triple Engine Retrieval
            chunks = await self._triple_engine_retrieve(
                current_query, document_id, image_base64
            )

            await emit(f"[RETRIEVE] Found {len(chunks)} chunks via triple engine")

            # Step 2: Critique relevance
            score = await self._critique_relevance(question, chunks)
            retrieval_scores.append(score)

            await emit(
                f"[CRITIQUE] Relevance score: {score:.1f}/10 "
                f"(threshold: {RELEVANCE_THRESHOLD})",
                level="critique"
            )

            # Always keep the best-scoring chunks across all attempts
            if score > best_score or not best_chunks:
                best_score = score
                best_chunks = chunks

            if score >= RELEVANCE_THRESHOLD:
                await emit(f"[✓] Sufficient relevance — proceeding to generation")
                break

            if attempt == MAX_RETRIES - 1:
                await emit(f"[!] Max retries reached — using best results (score {best_score:.1f}/10)")
                break

            # Step 3: Rewrite query
            new_query = await self._rewrite_query(question, chunks, score, attempt=retries)
            rewrites.append(new_query)
            retries += 1

            await emit(
                f"[RETRY {retries}] Low relevance. Rewriting query to: \"{new_query}\"",
                level="retry"
            )
            current_query = new_query

        # Step 4: Get domain persona
        persona = self._extract_persona(best_chunks)
        await emit(f"[PERSONA] Using domain persona: {persona[:80]}...")

        # Step 5: Generate answer
        await emit(f"[GENERATE] Composing answer with domain expert persona...")
        answer = await self._generate_answer(question, best_chunks, persona, image_base64)

        # Use best retrieval score (not last), penalise if LM says info wasn't found
        best_retrieval = max(retrieval_scores) if retrieval_scores else 5.0
        not_found_phrases = [
            "cannot be found", "not found in", "not available", "not mentioned",
            "not contain", "no information", "cannot find", "not present",
            "cannot answer", "not in the"
        ]
        found_penalty = 2.5 if any(p in answer.lower() for p in not_found_phrases) else 0.0
        confidence = round(max(best_retrieval - found_penalty, 1.0), 1)
        await emit(f"[ANSWER] Generated — confidence: {confidence:.1f}/10", level="success")

        # Step 6: Store audit trail in Actian
        audit_record = {
            "query_id": query_id,
            "original_query": question,
            "rewrites": rewrites,
            "retrieval_scores": retrieval_scores,
            "retries": retries,
            "final_answer": answer[:500],
            "answer_confidence": confidence,
            "document_id": document_id or "all",
        }
        self.vs.store_audit(audit_record)
        await emit(f"[AUDIT] Reasoning trace stored in Actian audit collection")

        return {
            "answer": answer,
            "sources": self._format_sources(best_chunks),
            "retries": retries,
            "confidence": confidence,
            "persona": persona,
            "query_id": query_id,
            "reasoning_trace": reasoning_trace,
        }

    async def _triple_engine_retrieve(
        self,
        query: str,
        doc_id: Optional[str],
        image_base64: Optional[str],
    ) -> List[Dict]:
        """Run all three retrieval engines and fuse results"""

        # Engine 1: Semantic text search
        text_results = self.vs.search_text(query, doc_id=doc_id, limit=5)

        # Engine 2: Image search (if image provided)
        image_results = []
        if image_base64:
            img_description = await self._describe_image(image_base64)
            if img_description:
                image_results = self.vs.search_image(img_description, limit=3)

        # Engine 3: Structural parent retrieval
        structural_results = []
        if text_results:
            top_parent = text_results[0].get("parent_heading", "")
            if top_parent:
                structural_results = self.vs.search_by_parent(top_parent, doc_id)

        # Fuse with Reciprocal Rank Fusion
        all_lists = [text_results, image_results, structural_results]
        all_lists = [r for r in all_lists if r]

        if len(all_lists) > 1:
            return self.vs.reciprocal_rank_fusion(all_lists)
        elif all_lists:
            return all_lists[0]
        return []

    async def _get_lm_model_name(self) -> str:
        """Return configured model name, or auto-detect from LM Studio"""
        if self.override_model_name:
            return self.override_model_name
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                r = await client.get(f"{self.lm_studio_url}/v1/models")
                if r.status_code == 200:
                    models = r.json().get("data", [])
                    if models:
                        return models[0]["id"]
        except Exception:
            pass
        return "local-model"

    async def _critique_relevance(self, question: str, chunks: List[Dict]) -> float:
        """
        Fast deterministic relevance scorer.
        Handles technical abbreviations, synonyms, and scientific language
        so IPCC/OSHA/legal documents score fairly alongside plain-English queries.
        """
        if not chunks:
            return 0.0

        import re as _re

        all_content = " ".join(c.get("content", "").lower() for c in chunks)

        # ── Synonym / abbreviation expansion ────────────────────────────────
        SYNONYMS: Dict[str, List[str]] = {
            "greenhouse gases": ["ghg", "co2", "carbon dioxide", "methane", "ch4",
                                 "nitrous oxide", "n2o", "emissions"],
            "ghg": ["greenhouse gas", "co2", "emissions", "carbon"],
            "carbon dioxide": ["co2", "carbon", "emissions"],
            "methane": ["ch4", "gas emissions"],
            "temperature": ["warming", "heat", "degrees", "celsius", "°c"],
            "pre-industrial": ["preindustrial", "1850", "historical", "baseline"],
            "climate change": ["global warming", "warming", "climate", "ipcc"],
            "employer": ["employers", "workplace", "company", "business", "organization"],
            "general duty clause": ["section 5", "osha", "hazard", "workplace safety"],
            "osha": ["occupational safety", "workplace", "hazard", "employer"],
            "ppe": ["personal protective equipment", "mask", "respirator", "gloves"],
            "covid": ["coronavirus", "sars-cov-2", "pandemic", "virus"],
            "sources": ["cause", "origin", "emission", "produced by", "generated"],
        }

        q_lower = question.lower()

        # Expand query terms with synonyms
        extra_terms: List[str] = []
        for term, synonyms in SYNONYMS.items():
            if term in q_lower:
                extra_terms.extend(synonyms)

        # ── Build query word list ────────────────────────────────────────────
        stop = {"what", "is", "the", "a", "an", "it", "and", "of", "in",
                "for", "are", "how", "to", "this", "that", "was", "were",
                "be", "by", "on", "at", "or", "do", "does", "with",
                "their", "which", "these", "those", "have", "has", "been"}
        q_words = [w for w in _re.sub(r'[^a-z0-9 ]', '', q_lower).split()
                   if w not in stop and len(w) > 1]
        all_terms = list(dict.fromkeys(q_words + extra_terms))  # dedup, preserve order

        if not all_terms:
            avg_len = sum(len(c.get("content", "")) for c in chunks) / max(len(chunks), 1)
            return min(avg_len / 60, 7.5)

        # ── Signal 1: exact word match (original q_words only) ───────────────
        exact_matches = sum(1 for w in q_words if w in all_content)
        exact_score = (exact_matches / len(q_words)) * 4.5        # up to 4.5

        # ── Signal 2: synonym / expanded term match ───────────────────────────
        synonym_matches = sum(1 for t in extra_terms if t in all_content)
        synonym_score = min((synonym_matches / max(len(extra_terms), 1)) * 2.5, 2.5)

        # ── Signal 3: stemmed match — "employer" ↔ "employers" ──────────────
        unmatched = [w for w in q_words if w not in all_content and len(w) > 4]
        stemmed = sum(1 for w in unmatched if w[:-1] in all_content or w + "s" in all_content)
        stem_score = (stemmed / len(q_words)) * 1.5               # up to 1.5

        # ── Signal 4: chunk richness ─────────────────────────────────────────
        rich_chunks = sum(1 for c in chunks if len(c.get("content", "")) > 150)
        richness_score = min(rich_chunks * 0.25, 1.5)             # up to 1.5

        # ── Signal 5: vector retrieval score from DB ─────────────────────────
        top_vec = max((float(c.get("score", 0)) for c in chunks), default=0)
        retrieval_bonus = min(top_vec * 1.0, 1.0)                 # up to 1.0 (was 1.5)

        total = exact_score + synonym_score + stem_score + richness_score + retrieval_bonus
        return round(min(total, 10.0), 1)

    async def _rewrite_query(
        self, original: str, chunks: List[Dict], score: float, attempt: int = 0
    ) -> str:
        """Rewrite query when relevance is low — each attempt tries a different strategy"""
        context = "\n".join(c.get("content", "")[:100] for c in chunks[:2])

        prompt = f"""The query "{original}" returned irrelevant results (score: {score:.1f}/10).
Available content sample: {context}

Suggest a better, more specific search query to find the answer. 
Reply with ONLY the improved query, nothing else."""

        try:
            model_name = await self._get_lm_model_name()
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    self.lm_studio_url + "/v1/chat/completions",
                    json={
                        "model": model_name,
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": 0.3,
                        "max_tokens": 50,
                    }
                )
                if resp.status_code == 200:
                    return resp.json()["choices"][0]["message"]["content"].strip()
        except Exception:
            pass

        # Fallback: progressively expand query using different strategies per attempt
        import re as _re
        stop = {"what", "is", "the", "a", "an", "it", "and", "of", "in", "for", "are", "how", "to"}
        q_words = [w for w in _re.sub(r'[^a-z0-9 ]', '', original.lower()).split()
                   if w not in stop and len(w) > 2]

        # Pull candidate expansion terms from retrieved chunks
        chunk_text = " ".join(c.get("content", "")[:200] for c in chunks[:3]).lower()
        chunk_words = [w for w in _re.sub(r'[^a-z0-9 ]', '', chunk_text).split()
                       if w not in stop and len(w) > 3 and w not in q_words]
        seen: set = set()
        unique_chunk_words = [w for w in chunk_words if not (w in seen or seen.add(w))]  # type: ignore[func-returns-value]

        # Each attempt uses a different expansion window so rewrites actually differ
        offset = attempt * 3
        expansion = " ".join(unique_chunk_words[offset:offset + 3])
        if expansion:
            return f"{original} {expansion}".strip()
        # Last resort: rephrase the original
        return " ".join(q_words[:6]) if q_words else original

    async def _generate_answer(
        self,
        question: str,
        chunks: List[Dict],
        persona: str,
        image_base64: Optional[str] = None,
    ) -> str:
        """Generate final answer using Qwen2.5-VL with domain persona"""
        if not chunks and not image_base64:
            return ("I could not find relevant information in the uploaded documents "
                    "to answer your question. Please ensure the document has been "
                    "uploaded and processed.")

        context_parts = []
        for i, chunk in enumerate(chunks[:5]):
            page = chunk.get("page", "?")
            section = chunk.get("section", "")
            chapter = chunk.get("chapter", "")
            content = chunk.get("content", "")
            loc = f"[Page {page}"
            if section:
                loc += f", Section {section}"
            if chapter:
                loc += f", {chapter}"
            loc += "]"
            context_parts.append(f"{loc}\n{content}")

        context = "\n\n---\n\n".join(context_parts)

        system_prompt = persona or (
            "You are a helpful document analysis expert. "
            "Always cite specific page and section numbers. "
            "If information is not found, say so explicitly."
        )

        user_content = f"""Based on the following document excerpts, answer the question.

DOCUMENT EXCERPTS:
{context}

QUESTION: {question}

Instructions:
- Cite page numbers and section references
- Be specific and accurate
- If the answer cannot be found in the excerpts, say so clearly
- For safety-critical information, always highlight warnings"""

        try:
            model_name = await self._get_lm_model_name()
            messages = [{"role": "user", "content": user_content}]

            # Add image if provided
            if image_base64:
                messages = [{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_content},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}},
                    ]
                }]

            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(
                    self.lm_studio_url + "/v1/chat/completions",
                    json={
                        "model": model_name,
                        "messages": messages,
                        "temperature": 0.1,
                        "max_tokens": 800,
                        "system": system_prompt,
                    }
                )
                if resp.status_code == 200:
                    return resp.json()["choices"][0]["message"]["content"]
        except Exception as e:
            log.warning(f"Generation failed: {e}")

        # Fallback: return most relevant chunk content
        if chunks:
            top = chunks[0]
            return (
                f"Based on the document (Page {top.get('page', '?')}, "
                f"Section {top.get('section', 'N/A')}):\n\n"
                f"{top.get('content', 'No content available.')}\n\n"
                f"*(Note: AI generation unavailable — showing raw extracted content)*"
            )
        return "Unable to generate answer. Please check LM Studio is running."

    async def _describe_image(self, image_base64: str) -> str:
        """Use vision model to describe uploaded image for visual retrieval"""
        try:
            model_name = await self._get_lm_model_name()
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    self.lm_studio_url + "/v1/chat/completions",
                    json={
                        "model": model_name,
                        "messages": [{
                            "role": "user",
                            "content": [
                                {
                                    "type": "text",
                                    "text": ("Describe this component/object in technical terms "
                                             "for document search. Be specific about shape, color, "
                                             "damage, part type. Max 30 words.")
                                },
                                {
                                    "type": "image_url",
                                    "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}
                                },
                            ]
                        }],
                        "max_tokens": 60,
                    }
                )
                if resp.status_code == 200:
                    return resp.json()["choices"][0]["message"]["content"]
        except Exception:
            pass
        return ""

    def _extract_persona(self, chunks: List[Dict]) -> str:
        """Extract domain persona from chunk metadata"""
        for chunk in chunks:
            persona = chunk.get("domain_persona", "")
            if persona:
                return persona
        return ("You are a helpful document analysis expert. "
                "Always cite page and section numbers in your answers.")

    def _format_sources(self, chunks: List[Dict]) -> List[Dict]:
        """Format source citations for the response"""
        sources = []
        seen = set()
        for chunk in chunks[:5]:
            key = f"{chunk.get('doc_id', '')}_{chunk.get('page', '')}"
            if key not in seen:
                seen.add(key)
                sources.append({
                    "page": chunk.get("page"),
                    "section": chunk.get("section", ""),
                    "chapter": chunk.get("chapter", ""),
                    "category": chunk.get("category", "general"),
                    "content_type": chunk.get("content_type", "text"),
                    "filename": chunk.get("filename", ""),
                    "preview": chunk.get("content", "")[:150] + "...",
                    "score": chunk.get("score", 0),
                })
        return sources
