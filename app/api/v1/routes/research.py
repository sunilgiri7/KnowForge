from typing import Annotated, List, Optional
from fastapi import APIRouter, Depends, Body
from sqlalchemy.orm import Session
from sqlalchemy import func
import json

from app.api.deps import get_current_user, get_active_workspace_dep
from app.db.models import User, Workspace, ResearchPaper, ResearchPaperSection, ResearchMethod, ResearchClaim, ResearchPaperEdge, ResearchInsight, ResearchAnalysisJob
from app.db.session import get_db
from app.services.llm_factory import build_user_llm
from app.llmwiki.text import safe_format
from app.core.errors import KnowForgeError

router = APIRouter(prefix="/research", tags=["research"])


def _load_json_list(value: str | None) -> list:
    if not value:
        return []
    try:
        data = json.loads(value)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _paper_status(db: Session, paper_id: str) -> tuple[str, str | None]:
    job = db.query(ResearchAnalysisJob).filter_by(paper_id=paper_id).first()
    return (job.status if job else "pending", job.error_message if job else None)


def _paper_card(db: Session, paper: ResearchPaper) -> dict:
    status, error_message = _paper_status(db, paper.id)
    method_count = db.query(func.count(ResearchMethod.id)).filter_by(paper_id=paper.id).scalar() or 0
    claim_count = db.query(func.count(ResearchClaim.id)).filter_by(paper_id=paper.id).scalar() or 0
    section_count = db.query(func.count(ResearchPaperSection.id)).filter_by(paper_id=paper.id).scalar() or 0
    return {
        "id": paper.id,
        "title": paper.title,
        "authors": _load_json_list(paper.authors),
        "venue": paper.venue,
        "doi": paper.doi,
        "publication_year": paper.publication_year,
        "slug": paper.slug,
        "created_at": paper.created_at.isoformat(),
        "status": status,
        "error_message": error_message,
        "method_count": method_count,
        "claim_count": claim_count,
        "section_count": section_count,
    }


def _methods_and_claims(db: Session, paper: ResearchPaper) -> tuple[list[ResearchMethod], list[ResearchClaim]]:
    methods = db.query(ResearchMethod).filter_by(paper_id=paper.id).all()
    claims = db.query(ResearchClaim).filter_by(paper_id=paper.id).all()
    return methods, claims


def _fallback_comparison(db: Session, papers: list[ResearchPaper]) -> dict:
    rows = []
    for paper in papers:
        methods, claims = _methods_and_claims(db, paper)
        method_text = "; ".join([f"{m.name}: {m.description}" for m in methods[:4]]) or "No method extracted yet"
        datasets = ", ".join(sorted({m.dataset_used for m in methods if m.dataset_used})) or "No dataset extracted"
        findings = "; ".join([c.claim_text for c in claims if (c.category or "finding") == "finding"][:3]) or "; ".join([c.claim_text for c in claims[:3]]) or "No claims extracted yet"
        limits = "; ".join([c.claim_text for c in claims if c.category in {"limitation", "gap"}][:3]) or "No explicit limitations extracted"
        rows.append([paper.title, method_text, datasets, findings, limits])
    return {
        "headers": ["Paper", "Methodologies/Models", "Datasets Evaluated", "Key Findings/Metrics", "Limitations"],
        "rows": rows,
        "fallback": True,
        "note": "Generated from extracted entities because the AI synthesis call was unavailable."
    }


def _fallback_gaps(db: Session, papers: list[ResearchPaper]) -> dict:
    method_items = []
    dataset_items = []
    open_challenges = []
    contradictions = []
    for paper in papers:
        methods, claims = _methods_and_claims(db, paper)
        for method in methods:
            method_items.append((paper, method))
            if method.dataset_used:
                dataset_items.append((paper, method.dataset_used))
        for claim in claims:
            text = claim.claim_text.strip()
            if claim.category in {"limitation", "gap"}:
                open_challenges.append({
                    "challenge": text,
                    "implication": f"Consider a follow-up study that directly addresses this limitation from {paper.title}."
                })
    for i, paper_a in enumerate(papers):
        claims_a = db.query(ResearchClaim).filter_by(paper_id=paper_a.id).all()
        for paper_b in papers[i + 1:]:
            claims_b = db.query(ResearchClaim).filter_by(paper_id=paper_b.id).all()
            for ca in claims_a[:8]:
                for cb in claims_b[:8]:
                    a = ca.claim_text.lower()
                    b = cb.claim_text.lower()
                    if any(w in a for w in ["outperform", "improve", "higher", "better"]) and any(w in b for w in ["underperform", "fail", "lower", "worse", "limitation"]):
                        contradictions.append({
                            "claim_a": ca.claim_text,
                            "paper_a": paper_a.title,
                            "claim_b": cb.claim_text,
                            "paper_b": paper_b.title,
                            "explanation": "Heuristic check found positive-performance language in one paper and negative/limitation language in another. Review the evidence before treating it as a true contradiction."
                        })
                        break
                if contradictions:
                    break
    untested = []
    for paper, method in method_items[:8]:
        for dataset_paper, dataset in dataset_items[:8]:
            if dataset_paper.id != paper.id:
                untested.append({
                    "method": method.name,
                    "paper": paper.title,
                    "dataset": dataset,
                    "dataset_paper": dataset_paper.title,
                    "potential_benefit": "Cross-evaluating this method on another paper's dataset can reveal robustness and generalization gaps."
                })
                break
    if not open_challenges and not untested and papers:
        open_challenges.append({
            "challenge": "The selected papers do not expose enough extracted limitations or datasets for a strong automated gap analysis.",
            "implication": "Open paper details, verify extraction quality, or select papers with richer methods and limitations."
        })
    return {
        "contradictions": contradictions[:5],
        "untested_combinations": untested[:8],
        "open_challenges": open_challenges[:8],
        "fallback": True
    }


@router.get("/papers")
def list_papers(
    workspace: Annotated[Workspace, Depends(get_active_workspace_dep)],
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)]
):
    """
    List all analyzed research papers in the active workspace.
    """
    papers = db.query(ResearchPaper).filter(
        ResearchPaper.workspace_id == workspace.id
    ).order_by(ResearchPaper.created_at.desc()).all()

    return [_paper_card(db, paper) for paper in papers]


@router.get("/summary")
def research_summary(
    workspace: Annotated[Workspace, Depends(get_active_workspace_dep)],
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)]
):
    papers = db.query(ResearchPaper).filter(ResearchPaper.workspace_id == workspace.id).all()
    status_counts = {"pending": 0, "processing": 0, "done": 0, "completed": 0, "failed": 0}
    for paper in papers:
        status, _ = _paper_status(db, paper.id)
        status_counts[status] = status_counts.get(status, 0) + 1
    method_count = db.query(func.count(ResearchMethod.id)).filter(ResearchMethod.workspace_id == workspace.id).scalar() or 0
    claim_count = db.query(func.count(ResearchClaim.id)).filter(ResearchClaim.workspace_id == workspace.id).scalar() or 0
    edge_count = db.query(func.count(ResearchPaperEdge.id)).filter(ResearchPaperEdge.workspace_id == workspace.id).scalar() or 0
    limitation_count = db.query(func.count(ResearchClaim.id)).filter(
        ResearchClaim.workspace_id == workspace.id,
        ResearchClaim.category.in_(["limitation", "gap"])
    ).scalar() or 0
    return {
        "total_papers": len(papers),
        "analyzed_papers": status_counts.get("done", 0) + status_counts.get("completed", 0),
        "processing_papers": status_counts.get("pending", 0) + status_counts.get("processing", 0),
        "failed_papers": status_counts.get("failed", 0),
        "method_count": method_count,
        "claim_count": claim_count,
        "edge_count": edge_count,
        "limitation_count": limitation_count,
        "status_counts": status_counts,
    }


@router.get("/papers/{paper_id}")
def get_paper_details(
    paper_id: str,
    workspace: Annotated[Workspace, Depends(get_active_workspace_dep)],
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)]
):
    """
    Retrieve details of a specific research paper, including sections, methodologies, and claims.
    """
    paper = db.query(ResearchPaper).filter(
        ResearchPaper.id == paper_id,
        ResearchPaper.workspace_id == workspace.id
    ).first()
    if not paper:
        raise KnowForgeError("Paper not found.", status_code=404, code="paper_not_found")

    sections = db.query(ResearchPaperSection).filter_by(paper_id=paper.id).all()
    methods = db.query(ResearchMethod).filter_by(paper_id=paper.id).all()
    claims = db.query(ResearchClaim).filter_by(paper_id=paper.id).all()
    job = db.query(ResearchAnalysisJob).filter_by(paper_id=paper.id).first()

    return {
        "id": paper.id,
        "title": paper.title,
        "authors": _load_json_list(paper.authors),
        "venue": paper.venue,
        "doi": paper.doi,
        "publication_year": paper.publication_year,
        "abstract": paper.abstract,
        "slug": paper.slug,
        "file_path": paper.file_path,
        "status": job.status if job else "pending",
        "error_message": job.error_message if job else None,
        "sections": [
            {
                "heading": s.heading,
                "content": s.content,
                "section_type": s.section_type
            } for s in sections
        ],
        "methods": [
            {
                "name": m.name,
                "description": m.description,
                "dataset_used": m.dataset_used
            } for m in methods
        ],
        "claims": [
            {
                "claim_text": c.claim_text,
                "category": c.category,
                "evidence": c.evidence,
                "grounding_level": c.grounding_level
            } for c in claims
        ]
    }


@router.get("/graph")
def get_research_graph(
    workspace: Annotated[Workspace, Depends(get_active_workspace_dep)],
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)]
):
    """
    Build citation/contradiction graph mapping connections between papers in the workspace.
    """
    papers = db.query(ResearchPaper).filter(
        ResearchPaper.workspace_id == workspace.id
    ).all()
    edges = db.query(ResearchPaperEdge).filter(
        ResearchPaperEdge.workspace_id == workspace.id
    ).all()

    nodes = [
        {
            "id": p.id,
            "label": p.title,
            "venue": p.venue or "Unknown Venue",
            "year": p.publication_year or "N/A"
        } for p in papers
    ]
    links = [
        {
            "source": e.source_paper_id,
            "target": e.target_paper_id,
            "relation_type": e.relation_type
        } for e in edges
    ]

    return {"nodes": nodes, "links": links}


COMPARE_PAPERS_PROMPT = """You are an expert scientific synthesist. Analyze the following information extracted from several research papers and construct a comprehensive methodology comparison matrix in JSON format.

{papers_data}

If a specific query is provided, focus the comparison on that aspect:
Query: {query}

Output a JSON object with the following structure:
{{
  "headers": ["Paper", "Methodologies/Models", "Datasets Evaluated", "Key Findings/Metrics", "Limitations"],
  "rows": [
    ["Paper Title 1", "Proposed model detail", "Dataset names", "Performance metrics / BLEU / Accuracy", "Limitations noted"],
    ["Paper Title 2", "Proposed model detail", "Dataset names", "Performance metrics / BLEU / Accuracy", "Limitations noted"]
  ]
}}
"""


@router.post("/compare")
async def generate_comparison(
    workspace: Annotated[Workspace, Depends(get_active_workspace_dep)],
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    paper_ids: List[str] = Body(..., embed=True),
    query: Optional[str] = Body(None, embed=True)
):
    """
    Synthesize comparison matrix across selected papers.
    """
    papers = db.query(ResearchPaper).filter(
        ResearchPaper.id.in_(paper_ids),
        ResearchPaper.workspace_id == workspace.id
    ).all()

    if not papers:
        return {"headers": [], "rows": []}

    # Package information
    papers_data = []
    for paper in papers:
        methods = db.query(ResearchMethod).filter_by(paper_id=paper.id).all()
        claims = db.query(ResearchClaim).filter_by(paper_id=paper.id).all()
        
        methods_str = ", ".join([f"{m.name} ({m.description or ''})" for m in methods])
        claims_str = " | ".join([f"{c.claim_text} ({c.category})" for c in claims])
        
        papers_data.append(
            f"Paper: {paper.title}\n"
            f"Methods: {methods_str}\n"
            f"Claims & Limitations: {claims_str}\n"
        )
    
    papers_payload = "\n---\n".join(papers_data)
    
    llm = build_user_llm(db, user)
    try:
        comparison_res = await llm.generate_json(
            safe_format(COMPARE_PAPERS_PROMPT, papers_data=papers_payload, query=query or "General comparison"),
            temperature=0.1
        )
    except Exception:
        # Fallback empty structure on rate limit / api errors
        comparison_res = _fallback_comparison(db, papers)

    # Save to insights table
    insight = ResearchInsight(
        workspace_id=workspace.id,
        insight_type="comparison_matrix",
        title=f"Methodology Comparison ({len(papers)} papers)",
        content_json=json.dumps(comparison_res)
    )
    db.add(insight)
    db.commit()

    return comparison_res


LITERATURE_GAPS_PROMPT = """You are an expert academic advisor. Analyze the following list of research papers, their methodologies, and their extracted claims/limitations. Identify significant literature gaps, contradictions, or untested dataset-methodology combinations across these papers.

{papers_data}

Output a JSON object with the following structure:
{{
  "contradictions": [
    {{
      "claim_a": "Claim text from paper A",
      "paper_a": "Title of paper A",
      "claim_b": "Claim text from paper B",
      "paper_b": "Title of paper B",
      "explanation": "Why these claims contradict or diverge"
    }}
  ],
  "untested_combinations": [
    {{
      "method": "Name of method/model from paper A",
      "paper": "Title of paper A",
      "dataset": "Name of dataset from paper B",
      "dataset_paper": "Title of paper B",
      "potential_benefit": "Why testing this method on this dataset would be valuable"
    }}
  ],
  "open_challenges": [
    {{
      "challenge": "Description of the open research challenge or gap identified",
      "implication": "What this means for future work"
    }}
  ]
}}
"""


@router.post("/gaps")
async def generate_literature_gaps(
    workspace: Annotated[Workspace, Depends(get_active_workspace_dep)],
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    paper_ids: List[str] = Body(..., embed=True)
):
    """
    Detect gaps and contradictions across research papers.
    """
    papers = db.query(ResearchPaper).filter(
        ResearchPaper.id.in_(paper_ids),
        ResearchPaper.workspace_id == workspace.id
    ).all()

    if not papers:
        return {"contradictions": [], "untested_combinations": [], "open_challenges": []}

    # Package information
    papers_data = []
    for paper in papers:
        methods = db.query(ResearchMethod).filter_by(paper_id=paper.id).all()
        claims = db.query(ResearchClaim).filter_by(paper_id=paper.id).all()
        
        methods_str = ", ".join([f"{m.name} ({m.description or ''})" for m in methods])
        claims_str = " | ".join([f"{c.claim_text} ({c.category})" for c in claims])
        
        papers_data.append(
            f"Paper: {paper.title}\n"
            f"Methods: {methods_str}\n"
            f"Claims & Limitations: {claims_str}\n"
        )
    
    papers_payload = "\n---\n".join(papers_data)
    
    llm = build_user_llm(db, user)
    try:
        gaps_res = await llm.generate_json(
            safe_format(LITERATURE_GAPS_PROMPT, papers_data=papers_payload),
            temperature=0.15
        )
    except Exception as exc:
        gaps_res = _fallback_gaps(db, papers)

    # Save to insights
    insight = ResearchInsight(
        workspace_id=workspace.id,
        insight_type="literature_gap",
        title=f"Literature Gap Analysis ({len(papers)} papers)",
        content_json=json.dumps(gaps_res)
    )
    db.add(insight)
    db.commit()

    return gaps_res


@router.delete("/papers/{paper_id}")
def delete_paper(
    paper_id: str,
    workspace: Annotated[Workspace, Depends(get_active_workspace_dep)],
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)]
):
    """
    Deletes a specific research paper and all related sections, methods, claims, and edges.
    """
    paper = db.query(ResearchPaper).filter(
        ResearchPaper.id == paper_id,
        ResearchPaper.workspace_id == workspace.id
    ).first()
    
    if not paper:
        raise KnowForgeError("Paper not found.", status_code=404, code="paper_not_found")

    # Delete related records
    db.query(ResearchPaperSection).filter_by(paper_id=paper.id).delete()
    db.query(ResearchMethod).filter_by(paper_id=paper.id).delete()
    db.query(ResearchClaim).filter_by(paper_id=paper.id).delete()
    db.query(ResearchAnalysisJob).filter_by(paper_id=paper.id).delete()
    db.query(ResearchPaperEdge).filter(
        (ResearchPaperEdge.source_paper_id == paper.id) | 
        (ResearchPaperEdge.target_paper_id == paper.id)
    ).delete()

    db.delete(paper)
    db.commit()

    return {"success": True, "message": "Paper deleted successfully"}
