from __future__ import annotations

import json
import re
from datetime import datetime, UTC
from sqlalchemy.orm import Session
from app.db.models import (
    ResearchPaper,
    ResearchPaperSection,
    ResearchMethod,
    ResearchClaim,
    ResearchPaperEdge,
    ResearchAnalysisJob
)
from app.llmwiki.groq import GroqClient
from app.llmwiki.text import safe_format, trim_to_chars

MAX_RESEARCH_SECTIONS = 32
MAX_SECTION_CONTENT_CHARS = 12_000
MAX_SECTION_HEADING_CHARS = 180
MAX_RESEARCH_TEXT_FIELD_CHARS = 8_000


def _db_text(value: object, *, max_chars: int = MAX_RESEARCH_TEXT_FIELD_CHARS) -> str:
    text = "" if value is None else str(value)
    # PostgreSQL rejects NUL bytes; other invisible control chars make PDF
    # extraction noisy and can break downstream rendering. Keep normal
    # whitespace and printable unicode.
    text = text.replace("\x00", "")
    text = re.sub(r"[\x01-\x08\x0b\x0c\x0e-\x1f\x7f]", " ", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n{4,}", "\n\n\n", text)
    return trim_to_chars(text.strip(), max_chars)


def _json_list(value: object, *, max_items: int = 12, item_chars: int = 120) -> str:
    if not isinstance(value, list):
        return json.dumps([])
    cleaned = [_db_text(item, max_chars=item_chars) for item in value if _db_text(item, max_chars=item_chars)]
    return json.dumps(cleaned[:max_items])

# Prompt to classify and extract academic metadata from the first 2-3 pages of a document
CLASSIFY_PAPER_PROMPT = """You are an expert academic metadata extractor. Analyze the following document excerpt (from the first few pages) and determine if it is a scientific research paper, journal article, conference proceeding, preprint, or thesis.

Document Excerpt:
{excerpt}

Output a JSON object with the following fields:
- is_research_paper (boolean): True if this is a research paper/article, False otherwise.
- title (string): The title of the paper.
- authors (array of strings): List of author names.
- venue (string or null): The conference, journal, or publisher name if present (e.g., "arXiv", "CVPR", "Nature").
- doi (string or null): The digital object identifier if present (e.g., "10.1145/3477495").
- publication_year (integer or null): The year of publication.
- abstract (string or null): The extracted abstract of the paper.
"""

# Prompt to extract methodology details and claims/findings from the paper content
EXTRACT_RESEARCH_DETAILS_PROMPT = """You are an expert scientific researcher. Analyze the following research paper content and extract:
1. The key methodologies, models, algorithms, or frameworks proposed/used.
2. The datasets used for evaluation.
3. The main findings or claims made by the authors.
4. The limitations, untested dataset-methodology pairs, or research gaps acknowledged or implied.

Paper Content:
{content}

Output a JSON object with the following structure:
{{
  "methods": [
    {{
      "name": "Method/Model name (e.g., LLaMA-3)",
      "description": "Short explanation of how it works or is used",
      "dataset_used": "Name of the dataset it was evaluated on, or null"
    }}
  ],
  "claims": [
    {{
      "claim_text": "The specific finding or claim made (e.g., 'Proposed model outperforms baseline by 4.2%')",
      "category": "finding" | "limitation" | "hypothesis" | "gap",
      "evidence": "Brief textual proof or quote from the paper supporting this claim",
      "grounding_level": "fully_supported" | "partially_supported" | "unsupported"
    }}
  ]
}}
"""


def _publication_year(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value if 1800 <= value <= 2200 else None
    match = re.search(r"\b(18\d{2}|19\d{2}|20\d{2}|21\d{2}|2200)\b", str(value))
    if not match:
        return None
    year = int(match.group(1))
    return year if 1800 <= year <= 2200 else None


def _normalize_claim_category(value: object) -> str:
    category = _db_text(value, max_chars=40).lower() or "finding"
    return category if category in {"finding", "limitation", "hypothesis", "gap"} else "finding"


def _normalize_grounding(value: object, *, default: str = "fully_supported") -> str:
    grounding = _db_text(value, max_chars=40).lower() or default
    allowed = {"fully_supported", "partially_supported", "unsupported"}
    return grounding if grounding in allowed else default


class ResearchPaperAnalyzer:
    def __init__(self, db: Session, llm: GroqClient | None = None):
        self.db = db
        self.llm = llm or GroqClient()

    async def run_pipeline(
        self,
        *,
        workspace_id: str,
        filename: str,
        text: str,
        slug: str,
        file_path: str | None = None,
        force_research: bool = False,
        paper_id: str | None = None,
    ) -> bool:
        """
        Orchestrates classification, section parsing, methodology extraction, claim identification,
        and citation relationship mapping for a research document.
        """
        # 1. Grab first 6000 characters for metadata extraction and classification
        excerpt = trim_to_chars(text, 6000)
        
        is_research = force_research
        title = filename.rsplit(".", 1)[0].replace("_", " ").replace("-", " ").title()
        authors = []
        venue = None
        doi = None
        pub_year = None
        abstract = None

        # Even if force_research is True, try to extract metadata/abstract, but don't fail if metadata check says is_research is False
        try:
            metadata = await self.llm.generate_json(
                safe_format(CLASSIFY_PAPER_PROMPT, excerpt=excerpt),
                temperature=0.1
            )
            is_research_detected = metadata.get("is_research_paper", False)
            if force_research or is_research_detected:
                is_research = True
                title = _db_text((metadata.get("title") or "").strip() or title, max_chars=240)
                authors = metadata.get("authors") or []
                venue = _db_text(metadata.get("venue"), max_chars=240) or None
                doi = _db_text(metadata.get("doi"), max_chars=100) or None
                pub_year = _publication_year(metadata.get("publication_year"))
                abstract = _db_text(metadata.get("abstract"), max_chars=4000) or None
        except Exception as exc:
            print(f"[Research Intelligence] LLM metadata extraction failed: {exc}. Falling back to heuristics.")
            # Heuristic checks for academic paper properties
            excerpt_lower = excerpt.lower()
            academic_indicators = ["abstract", "introduction", "methodology", "results", "references", "conclusions"]
            indicator_matches = sum(1 for ind in academic_indicators if ind in excerpt_lower)
            if force_research or indicator_matches >= 3:
                is_research = True
                abstract_match = re.search(r"abstract\s*(.*?)\s*(?:1\.?\s*Introduction|introduction|introduction\b)", excerpt, re.IGNORECASE | re.DOTALL)
                if abstract_match:
                    abstract = abstract_match.group(1).strip()
                else:
                    abstract = "Academic document processed via heuristic fallback."

        if not is_research:
            print(f"[Research Intelligence] File {filename} classified as non-research.")
            if paper_id:
                job = self.db.query(ResearchAnalysisJob).filter_by(paper_id=paper_id).first()
                if job:
                    job.status = "failed"
                    job.error_message = "Document was not classified as a research paper."
                    job.completed_at = datetime.now(UTC)
                    self.db.commit()
            return False

        # Create or update the paper record. Research-tab uploads create a
        # pending shell immediately so the UI can show progress while analysis runs.
        paper = self.db.get(ResearchPaper, paper_id) if paper_id else None
        if not paper:
            paper = self.db.query(ResearchPaper).filter_by(workspace_id=workspace_id, slug=slug).first()
        if paper:
            paper.title = _db_text(title, max_chars=240)
            paper.authors = _json_list(authors)
            paper.venue = _db_text(venue, max_chars=240) or None
            paper.doi = _db_text(doi, max_chars=100) or None
            paper.publication_year = _publication_year(pub_year)
            paper.abstract = _db_text(abstract, max_chars=4000) or None
            paper.slug = _db_text(slug, max_chars=240)
            paper.file_path = file_path or paper.file_path
        else:
            paper = ResearchPaper(
                workspace_id=workspace_id,
                title=_db_text(title, max_chars=240),
                authors=_json_list(authors),
                venue=_db_text(venue, max_chars=240) or None,
                doi=_db_text(doi, max_chars=100) or None,
                publication_year=_publication_year(pub_year),
                abstract=_db_text(abstract, max_chars=4000) or None,
                slug=_db_text(slug, max_chars=240),
                file_path=file_path
            )
            self.db.add(paper)
        self.db.commit()
        self.db.refresh(paper)

        # Create or update tracking job
        job = self.db.query(ResearchAnalysisJob).filter_by(paper_id=paper.id).first()
        if job:
            job.status = "processing"
            job.error_message = None
            job.completed_at = None
        else:
            job = ResearchAnalysisJob(
                workspace_id=workspace_id,
                paper_id=paper.id,
                status="processing"
            )
            self.db.add(job)
        self.db.commit()
        self.db.refresh(job)

        self.db.query(ResearchPaperSection).filter_by(paper_id=paper.id).delete()
        self.db.query(ResearchMethod).filter_by(paper_id=paper.id).delete()
        self.db.query(ResearchClaim).filter_by(paper_id=paper.id).delete()
        self.db.query(ResearchPaperEdge).filter(
            (ResearchPaperEdge.source_paper_id == paper.id) |
            (ResearchPaperEdge.target_paper_id == paper.id)
        ).delete()
        self.db.commit()

        # 2. Parse sections heuristically. This must never poison the session:
        # large/noisy PDFs can contain NUL bytes, huge references, or repeated
        # benchmark tables that exceed practical DB/rendering limits.
        try:
            sections = self.parse_sections_heuristically(text)[:MAX_RESEARCH_SECTIONS]
            for sec in sections:
                db_sec = ResearchPaperSection(
                    paper_id=paper.id,
                    heading=_db_text(sec.get("heading") or "Section", max_chars=MAX_SECTION_HEADING_CHARS) or "Section",
                    content=_db_text(sec.get("content") or "", max_chars=MAX_SECTION_CONTENT_CHARS),
                    section_type=_db_text(sec.get("section_type") or "other", max_chars=40) or "other",
                )
                if db_sec.content:
                    self.db.add(db_sec)
            self.db.commit()
        except Exception as sec_exc:
            self.db.rollback()
            print(f"[Research Intelligence] Section parsing failed: {sec_exc}")

        try:
            # 3. Extract methodology and claims using LLM
            content_summary = trim_to_chars(text, 25000)  # Use representative core of the text
            details = await self.llm.generate_json(
                safe_format(EXTRACT_RESEARCH_DETAILS_PROMPT, content=content_summary),
                temperature=0.1
            )

            # Persist methods
            methods_list = details.get("methods") or []
            for item in methods_list:
                method_name = _db_text(item.get("name"), max_chars=120)
                if not method_name:
                    continue
                db_method = ResearchMethod(
                    workspace_id=workspace_id,
                    paper_id=paper.id,
                    name=method_name,
                    description=_db_text(item.get("description"), max_chars=1200) or "No description extracted.",
                    dataset_used=_db_text(item.get("dataset_used"), max_chars=240) or None
                )
                self.db.add(db_method)

            # Persist claims
            claims_list = details.get("claims") or []
            for claim in claims_list:
                claim_text = _db_text(claim.get("claim_text"), max_chars=1800)
                if not claim_text:
                    continue
                db_claim = ResearchClaim(
                    workspace_id=workspace_id,
                    paper_id=paper.id,
                    claim_text=claim_text,
                    category=_normalize_claim_category(claim.get("category")),
                    evidence=_db_text(claim.get("evidence"), max_chars=1600) or None,
                    grounding_level=_normalize_grounding(claim.get("grounding_level"))
                )
                self.db.add(db_claim)
            self.db.commit()

            # 4. Citation linking across current workspace
            self.link_citation_edges(workspace_id, paper, text)

            # Done
            job.status = "done"
            job.completed_at = datetime.now(UTC)
            self.db.commit()
            print(f"[Research Intelligence] Successfully analyzed research paper: {title}")
            return True

        except Exception as exc:
            self.db.rollback()
            print(f"[Research Intelligence] LLM details extraction failed: {exc}. Using heuristic fallback.")
            try:
                fallback = self.extract_details_heuristically(text)
                for item in fallback.get("methods", []):
                    method_name = _db_text(item.get("name"), max_chars=120)
                    if not method_name:
                        continue
                    self.db.add(ResearchMethod(
                        workspace_id=workspace_id,
                        paper_id=paper.id,
                        name=method_name,
                        description=_db_text(item.get("description") or "Extracted from methodology-like section.", max_chars=1200),
                        dataset_used=_db_text(item.get("dataset_used"), max_chars=240) or None
                    ))
                for claim in fallback.get("claims", []):
                    claim_text = _db_text(claim.get("claim_text"), max_chars=1800)
                    if not claim_text:
                        continue
                    self.db.add(ResearchClaim(
                        workspace_id=workspace_id,
                        paper_id=paper.id,
                        claim_text=claim_text,
                        category=_normalize_claim_category(claim.get("category")),
                        evidence=_db_text(claim.get("evidence"), max_chars=1600) or None,
                        grounding_level=_normalize_grounding(claim.get("grounding_level"), default="partially_supported")
                    ))
                self.db.commit()
                self.link_citation_edges(workspace_id, paper, text)
                job.status = "done"
                job.error_message = f"AI extraction unavailable; heuristic extraction used. {str(exc)[:300]}"
                job.completed_at = datetime.now(UTC)
                self.db.commit()
            except Exception as fallback_exc:
                self.db.rollback()
                job.status = "failed"
                job.error_message = _db_text(f"AI and heuristic extraction failed: {fallback_exc}", max_chars=1000)
                job.completed_at = datetime.now(UTC)
                self.db.commit()
                return False
            return True

    @staticmethod
    def extract_details_heuristically(text: str) -> dict:
        sections = ResearchPaperAnalyzer.parse_sections_heuristically(text)
        methods = []
        claims = []
        dataset_pattern = re.compile(r"\b([A-Z][A-Za-z0-9_-]*(?:\s+[A-Z][A-Za-z0-9_-]*){0,3})\s+(?:dataset|benchmark|corpus|data set)\b", re.IGNORECASE)
        method_keywords = ["method", "model", "framework", "algorithm", "architecture", "approach", "pipeline", "system"]
        finding_keywords = ["outperform", "improve", "achieve", "show", "demonstrate", "result", "accuracy", "performance", "effective"]
        limitation_keywords = ["limitation", "future work", "fail", "cannot", "challenge", "gap", "underperform", "constraint"]

        for section in sections:
            content = re.sub(r"\s+", " ", section.get("content", "")).strip()
            if not content:
                continue
            sentences = re.split(r"(?<=[.!?])\s+", content)
            section_type = section.get("section_type", "other")
            if section_type == "methodology" or any(k in section.get("heading", "").lower() for k in method_keywords):
                excerpt = " ".join(sentences[:3]).strip()
                dataset_match = dataset_pattern.search(content)
                methods.append({
                    "name": section.get("heading") or "Extracted Method",
                    "description": trim_to_chars(excerpt or content, 700),
                    "dataset_used": dataset_match.group(1).strip() if dataset_match else None
                })
            for sentence in sentences:
                low = sentence.lower()
                clean = sentence.strip()
                if len(clean) < 45 or len(clean) > 450:
                    continue
                if any(k in low for k in limitation_keywords):
                    claims.append({
                        "claim_text": clean,
                        "category": "limitation" if "limitation" in low or "future work" in low else "gap",
                        "evidence": clean,
                        "grounding_level": "partially_supported"
                    })
                elif any(k in low for k in finding_keywords):
                    claims.append({
                        "claim_text": clean,
                        "category": "finding",
                        "evidence": clean,
                        "grounding_level": "partially_supported"
                    })
                if len(claims) >= 12:
                    break
            if len(claims) >= 12:
                break

        if not methods:
            introduction = next((s for s in sections if s.get("section_type") in {"methodology", "introduction"}), None)
            if introduction:
                methods.append({
                    "name": introduction.get("heading") or "Paper Approach",
                    "description": trim_to_chars(re.sub(r"\s+", " ", introduction.get("content", "")), 700),
                    "dataset_used": None
                })
        return {"methods": methods[:6], "claims": claims[:12]}

    @staticmethod
    def parse_sections_heuristically(text: str) -> list[dict]:
        """
        Splits paper text into sections based on typical academic headings.
        """
        lines = text.splitlines()
        sections = []
        current_heading = "Abstract"
        current_content = []

        # Matches standard section names like "1. Introduction", "Abstract", "References", "Methodology"
        heading_pattern = re.compile(
            r"^(?:\d+(?:\.\d+)*\s+)?(Abstract|Introduction|Related\s+Work|Literature\s+Review|Background|Methodology|Method|Proposed\s+Method|Experiments?|Evaluations?|Results?|Discussions?|Limitations?|Future\s+Work|Conclusions?|References|Bibliography)$",
            re.IGNORECASE
        )

        for line in lines:
            stripped = line.strip()
            match = heading_pattern.match(stripped)
            if match:
                if current_content:
                    sections.append({
                        "heading": current_heading,
                        "content": "\n".join(current_content).strip()
                    })
                current_heading = match.group(1).title()
                current_content = []
            else:
                current_content.append(line)

        if current_content:
            sections.append({
                "heading": current_heading,
                "content": "\n".join(current_content).strip()
            })

        # Refine and map headings to database types
        refined = []
        for sec in sections:
            h = sec["heading"].lower()
            content = sec["content"]
            if not content.strip():
                continue

            sec_type = "other"
            if "abstract" in h:
                sec_type = "abstract"
            elif "introduction" in h:
                sec_type = "introduction"
            elif any(w in h for w in ["methodology", "method", "approach", "architecture", "model"]):
                sec_type = "methodology"
            elif any(w in h for w in ["result", "experiment", "evaluation", "performance"]):
                sec_type = "results"
            elif "limitation" in h:
                sec_type = "limitations"
            elif "discussion" in h:
                sec_type = "discussion"

            refined.append({
                "heading": _db_text(sec["heading"], max_chars=MAX_SECTION_HEADING_CHARS) or "Section",
                "content": _db_text(content, max_chars=MAX_SECTION_CONTENT_CHARS),
                "section_type": sec_type
            })
            if len(refined) >= MAX_RESEARCH_SECTIONS:
                break

        return refined

    def link_citation_edges(self, workspace_id: str, new_paper: ResearchPaper, text: str):
        """
        Scans the text of the new paper for citations and contradictions matching existing papers
        in the current workspace.
        """
        text_lower = text.lower()
        # Fetch other papers in the workspace
        existing_papers = self.db.query(ResearchPaper).filter(
            ResearchPaper.workspace_id == workspace_id,
            ResearchPaper.id != new_paper.id
        ).all()

        for paper in existing_papers:
            is_linked = False
            relation_type = "cites"

            # Parse title keywords
            title_words = [w for w in re.findall(r"\w+", paper.title.lower()) if len(w) > 4]
            # Parse authors
            authors = []
            if paper.authors:
                try:
                    authors = json.loads(paper.authors)
                except Exception:
                    pass

            # Method 1: Check if authors and year appear in the text (e.g. "Vaswani" and "2017")
            author_match = False
            if authors and paper.publication_year:
                for author in authors:
                    if author.lower() in text_lower:
                        author_match = True
                        break
                if author_match and str(paper.publication_year) in text_lower:
                    is_linked = True

            # Method 2: Check title keywords (at least 3 keywords match, or all keywords if less than 3)
            if not is_linked and title_words:
                match_count = sum(1 for word in title_words if word in text_lower)
                if match_count >= min(3, len(title_words)):
                    is_linked = True

            if is_linked:
                # Detect if the citation has a contradiction or limitation context
                # Look for contradiction words around the author or title keywords in the text
                contradiction_words = ["contradict", "oppose", "unlike", "differ", "limit", "fail", "underperform", "disagree"]
                for cw in contradiction_words:
                    if cw in text_lower:
                        # Simple proximity heuristic: if a contradiction word is present, label as contradicts
                        relation_type = "contradicts"
                        break

                # Create edge
                edge = ResearchPaperEdge(
                    workspace_id=workspace_id,
                    source_paper_id=new_paper.id,
                    target_paper_id=paper.id,
                    relation_type=relation_type
                )
                self.db.add(edge)
        self.db.commit()
