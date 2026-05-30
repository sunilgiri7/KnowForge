from typing import Annotated, List, Optional
from fastapi import APIRouter, Depends, Body
from sqlalchemy.orm import Session
import json

from app.api.deps import get_current_user, get_active_workspace_dep
from app.db.models import User, Workspace, ResearchPaper, ResearchPaperSection, ResearchMethod, ResearchClaim, ResearchPaperEdge, ResearchInsight, ResearchAnalysisJob
from app.db.session import get_db
from app.services.llm_factory import build_user_llm
from app.llmwiki.text import safe_format

router = APIRouter(prefix="/research", tags=["research"])


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

    results = []
    for paper in papers:
        # Get job status
        job = db.query(ResearchAnalysisJob).filter_by(paper_id=paper.id).first()
        results.append({
            "id": paper.id,
            "title": paper.title,
            "authors": json.loads(paper.authors) if paper.authors else [],
            "venue": paper.venue,
            "doi": paper.doi,
            "publication_year": paper.publication_year,
            "slug": paper.slug,
            "created_at": paper.created_at.isoformat(),
            "status": job.status if job else "pending",
            "error_message": job.error_message if job else None
        })
    return results


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
        return {"error": "Paper not found"}

    sections = db.query(ResearchPaperSection).filter_by(paper_id=paper.id).all()
    methods = db.query(ResearchMethod).filter_by(paper_id=paper.id).all()
    claims = db.query(ResearchClaim).filter_by(paper_id=paper.id).all()
    job = db.query(ResearchAnalysisJob).filter_by(paper_id=paper.id).first()

    return {
        "id": paper.id,
        "title": paper.title,
        "authors": json.loads(paper.authors) if paper.authors else [],
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
        comparison_res = {
            "headers": ["Paper", "Methodologies/Models", "Datasets Evaluated", "Key Findings/Metrics", "Limitations"],
            "rows": [[p.title, "LLM Extraction Offline", "N/A", "N/A", "N/A"] for p in papers]
        }

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
        # Fallback structure on error
        gaps_res = {
            "contradictions": [],
            "untested_combinations": [],
            "open_challenges": [
                {
                    "challenge": "LLM Synthesis Offline. Could not check research gaps automatically.",
                    "implication": str(exc)
                }
            ]
        }

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
        return {"error": "Paper not found"}

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
