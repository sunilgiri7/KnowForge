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
        force_research: bool = False
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
                title = (metadata.get("title") or "").strip() or title
                authors = metadata.get("authors") or []
                venue = metadata.get("venue")
                doi = metadata.get("doi")
                pub_year = metadata.get("publication_year")
                abstract = metadata.get("abstract")
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
            return False

        # Create paper record
        paper = ResearchPaper(
            workspace_id=workspace_id,
            title=title,
            authors=json.dumps(authors),
            venue=venue,
            doi=doi,
            publication_year=pub_year,
            abstract=abstract,
            slug=slug,
            file_path=file_path
        )
        self.db.add(paper)
        self.db.commit()
        self.db.refresh(paper)

        # Create tracking job
        job = ResearchAnalysisJob(
            workspace_id=workspace_id,
            paper_id=paper.id,
            status="processing"
        )
        self.db.add(job)
        self.db.commit()
        self.db.refresh(job)

        # 2. Parse sections heuristically
        try:
            sections = self.parse_sections_heuristically(text)
            for idx, sec in enumerate(sections):
                db_sec = ResearchPaperSection(
                    paper_id=paper.id,
                    heading=sec["heading"],
                    content=sec["content"],
                    section_type=sec["section_type"]
                )
                self.db.add(db_sec)
            self.db.commit()
        except Exception as sec_exc:
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
                method_name = (item.get("name") or "").strip()
                if not method_name:
                    continue
                db_method = ResearchMethod(
                    workspace_id=workspace_id,
                    paper_id=paper.id,
                    name=method_name,
                    description=(item.get("description") or "").strip(),
                    dataset_used=item.get("dataset_used")
                )
                self.db.add(db_method)

            # Persist claims
            claims_list = details.get("claims") or []
            for claim in claims_list:
                claim_text = (claim.get("claim_text") or "").strip()
                if not claim_text:
                    continue
                db_claim = ResearchClaim(
                    workspace_id=workspace_id,
                    paper_id=paper.id,
                    claim_text=claim_text,
                    category=claim.get("category", "finding"),
                    evidence=claim.get("evidence"),
                    grounding_level=claim.get("grounding_level", "fully_supported")
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
            job.status = "failed"
            job.error_message = str(exc)
            job.completed_at = datetime.now(UTC)
            self.db.commit()
            print(f"[Research Intelligence] Paper pipeline details extraction failed: {exc}")
            return True

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
                "heading": sec["heading"],
                "content": content,
                "section_type": sec_type
            })

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
