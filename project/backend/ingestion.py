"""
DocSentinel — Document Ingestion Pipeline
Uses MinerU for intelligent PDF parsing with layout preservation
"""

import os
import json
import uuid
import asyncio
import logging
from pathlib import Path
from typing import Callable, Optional, List, Dict, Any

log = logging.getLogger("docsentinel.ingestion")

IMAGES_DIR = Path("extracted_images")
IMAGES_DIR.mkdir(exist_ok=True)


class DocumentIngestionPipeline:
    def __init__(self, broadcast_fn: Optional[Callable] = None):
        self.broadcast = broadcast_fn or (lambda x: None)

    async def _log(self, msg: str, level: str = "info", phase: str = ""):
        log.info(msg)
        await self.broadcast({
            "type": "log",
            "level": level,
            "phase": phase,
            "message": msg,
            "timestamp": __import__("datetime").datetime.utcnow().isoformat(),
        })

    async def process(self, file_path: str, doc_id: str, filename: str) -> Dict:
        await self._log(f"📄 Starting ingestion for: {filename}", phase="INGEST")

        # Step 1: Parse PDF
        await self._log("🔍 Running MinerU PDF parser...", phase="PARSE")
        chunks, images = await self._parse_pdf(file_path, doc_id)
        await self._log(f"✅ Extracted {len(chunks)} text chunks, {len(images)} images", phase="PARSE")

        # Step 2: Generate domain persona
        await self._log("🧠 Analyzing document domain with Qwen2.5-VL...", phase="PERSONA")
        persona_data = await self._generate_persona(chunks[:5], doc_id)
        await self._log(f"✅ Domain: {persona_data.get('domain', 'General')}", phase="PERSONA")
        await self.broadcast({"type": "persona", "data": persona_data})

        # Step 3: Embed and store in Actian
        await self._log("💾 Embedding chunks and storing in Actian VectorAI DB...", phase="EMBED")
        from vector_store import ActianVectorStore
        vs = ActianVectorStore()
        stored = await vs.store_document(doc_id, filename, chunks, images, persona_data)
        await self._log(f"✅ Stored {stored} records in Actian VectorAI DB", phase="EMBED")

        await self._log(f"🎉 Ingestion complete for {filename}", level="success", phase="DONE")
        await self.broadcast({
            "type": "ingestion_complete",
            "doc_id": doc_id,
            "filename": filename,
            "chunks": len(chunks),
            "images": len(images),
            "persona": persona_data,
        })

        return {
            "doc_id": doc_id,
            "chunks": len(chunks),
            "images": len(images),
            "persona": persona_data,
        }

    async def _parse_pdf(self, file_path: str, doc_id: str) -> tuple:
        """Parse PDF using MinerU (or fallback to PyPDF2 if MinerU not available)"""
        try:
            return await self._parse_with_mineru(file_path, doc_id)
        except Exception as e:
            log.warning(f"MinerU unavailable ({e}), falling back to PyPDF2")
            return await self._parse_with_pypdf2(file_path, doc_id)

    async def _parse_with_mineru(self, file_path: str, doc_id: str) -> tuple:
        """Use MinerU for intelligent layout-aware parsing"""
        import subprocess
        import tempfile

        output_dir = Path(f"mineru_output/{doc_id}")
        output_dir.mkdir(parents=True, exist_ok=True)

        # Run MinerU
        proc = await asyncio.create_subprocess_exec(
            "magic-pdf", "-p", file_path, "-o", str(output_dir), "-m", "auto",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        # Parse MinerU markdown output
        md_files = list(output_dir.rglob("*.md"))
        if not md_files:
            raise RuntimeError("MinerU produced no markdown output")

        md_content = md_files[0].read_text(encoding="utf-8")
        chunks = self._structure_markdown_chunks(md_content, doc_id)

        # Collect extracted images
        images = []
        for img_path in output_dir.rglob("*.png"):
            images.append({
                "image_id": str(uuid.uuid4())[:8],
                "path": str(img_path),
                "label": img_path.stem,
                "doc_id": doc_id,
            })

        return chunks, images

    async def _parse_with_pypdf2(self, file_path: str, doc_id: str) -> tuple:
        """Fallback: pypdf parser with structural heuristics"""
        try:
            import pypdf
            reader = pypdf.PdfReader(file_path)
        except ImportError:
            try:
                import PyPDF2 as pypdf
                reader = pypdf.PdfReader(file_path)
            except ImportError:
                log.error("No PDF parser available — install pypdf: pip install pypdf")
                raise RuntimeError("No PDF parser available. Run: pip install pypdf")

        chunks = []
        current_chapter = "Introduction"
        current_section = "1.0"
        chunk_size = 500

        for page_num, page in enumerate(reader.pages):
            text = page.extract_text() or ""
            if not text.strip():
                continue

            lines = text.split("\n")
            buffer = []

            for line in lines:
                stripped = line.strip()
                if not stripped:
                    continue

                # Heuristic heading detection
                if len(stripped) < 80 and (
                    stripped.isupper() or
                    stripped.startswith("Chapter") or
                    stripped.startswith("Section") or
                    any(stripped.startswith(f"{i}.") for i in range(1, 20))
                ):
                    if buffer:
                        chunk_text = " ".join(buffer).strip()
                        if len(chunk_text) > 50:
                            chunks.append(self._make_chunk(
                                chunk_text, page_num + 1, current_chapter,
                                current_section, doc_id, len(chunks)
                            ))
                        buffer = []
                    current_chapter = stripped[:80]
                else:
                    buffer.append(stripped)

                # Flush buffer when large enough
                if len(" ".join(buffer)) > chunk_size:
                    chunk_text = " ".join(buffer).strip()
                    chunks.append(self._make_chunk(
                        chunk_text, page_num + 1, current_chapter,
                        current_section, doc_id, len(chunks)
                    ))
                    buffer = []

            if buffer:
                chunk_text = " ".join(buffer).strip()
                if len(chunk_text) > 50:
                    chunks.append(self._make_chunk(
                        chunk_text, page_num + 1, current_chapter,
                        current_section, doc_id, len(chunks)
                    ))

        return chunks, []

    def _make_chunk(self, text: str, page: int, chapter: str, section: str,
                    doc_id: str, idx: int) -> Dict:
        return {
            "chunk_id": f"{doc_id}_chunk_{idx}",
            "content": text,
            "page": page,
            "chapter": chapter,
            "section": section,
            "parent_heading": chapter,
            "category": self._classify_content(text),
            "doc_id": doc_id,
        }

    def _structure_markdown_chunks(self, md_content: str, doc_id: str) -> List[Dict]:
        """Parse MinerU markdown into hierarchical chunks"""
        import re
        chunks = []
        lines = md_content.split("\n")

        current_h1 = "Document"
        current_h2 = ""
        current_h3 = ""
        buffer = []
        page = 1

        def flush_buffer():
            if buffer:
                text = " ".join(buffer).strip()
                if len(text) > 30:
                    heading = current_h3 or current_h2 or current_h1
                    chunks.append(self._make_chunk(
                        text, page, current_h1,
                        current_h2 or "1.0", doc_id, len(chunks)
                    ))
                buffer.clear()

        for line in lines:
            if line.startswith("# "):
                flush_buffer()
                current_h1 = line[2:].strip()
                current_h2 = ""
                current_h3 = ""
            elif line.startswith("## "):
                flush_buffer()
                current_h2 = line[3:].strip()
                current_h3 = ""
            elif line.startswith("### "):
                flush_buffer()
                current_h3 = line[4:].strip()
            elif line.strip():
                buffer.append(line.strip())
                if len(" ".join(buffer)) > 600:
                    flush_buffer()

        flush_buffer()
        return chunks

    def _classify_content(self, text: str) -> str:
        """Classify chunk content type"""
        text_lower = text.lower()
        if any(w in text_lower for w in ["warning", "danger", "caution", "critical", "hazard"]):
            return "safety_warning"
        if any(w in text_lower for w in ["figure", "diagram", "illustration", "table"]):
            return "figure_reference"
        if any(w in text_lower for w in ["procedure", "step", "instruction", "how to"]):
            return "procedure"
        if any(w in text_lower for w in ["specification", "parameter", "value", "range"]):
            return "specification"
        return "general"

    async def _generate_persona(self, sample_chunks: List[Dict], doc_id: str) -> Dict:
        """Generate domain persona using Qwen2.5-VL via LM Studio"""
        sample_text = "\n\n".join(c["content"] for c in sample_chunks[:3])[:3000]

        prompt = f"""Analyze this document excerpt and return ONLY a valid JSON object with these exact keys:
{{
  "domain": "specific domain name",
  "tone": "technical/casual/academic/safety-critical/etc",
  "key_topics": ["topic1", "topic2", "topic3"],
  "safety_level": "high/medium/low",
  "generated_system_prompt": "You are an expert in [domain]... (2-3 sentences defining expert behavior)"
}}

Document excerpt:
{sample_text}

Return ONLY the JSON, no other text."""

        try:
            import httpx
            # Respect LM_STUDIO_URL env var (same as agent.py) instead of hardcoding localhost
            lm_url = os.getenv("LM_STUDIO_URL", "http://localhost:1234")
            model_name = "local-model"
            try:
                async with httpx.AsyncClient(timeout=5) as mc:
                    mr = await mc.get(f"{lm_url}/v1/models")
                    if mr.status_code == 200:
                        models = mr.json().get("data", [])
                        if models:
                            model_name = models[0]["id"]
            except Exception:
                pass

            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    f"{lm_url}/v1/chat/completions",
                    json={
                        "model": model_name,
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": 0.1,
                        "max_tokens": 500,
                    }
                )
                if resp.status_code == 200:
                    content = resp.json()["choices"][0]["message"]["content"]
                    # Extract JSON
                    import re
                    json_match = re.search(r'\{.*\}', content, re.DOTALL)
                    if json_match:
                        return json.loads(json_match.group())
        except Exception as e:
            log.warning(f"LM Studio persona generation failed: {e}")

        # Fallback persona
        return {
            "domain": "General Document",
            "tone": "professional",
            "key_topics": ["document analysis", "information retrieval"],
            "safety_level": "low",
            "generated_system_prompt": (
                "You are a helpful document analysis expert. "
                "Always cite specific page and section numbers when referencing content. "
                "If information is not in the document, say so explicitly."
            ),
        }
