"""
Search API endpoints.
"""
from typing import List
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from database import get_db

router = APIRouter(prefix="/search", tags=["Search"])


class DomainSearchRequest(BaseModel):
    keyword: str
    region: str = "Global"
    num_results: int = 100


class DomainSearchResponse(BaseModel):
    domains: List[str]
    total_count: int
    metadata: dict


@router.post("/domains", response_model=DomainSearchResponse)
def search_domains(request: DomainSearchRequest, db=None):
    """Search for company domains based on keyword."""
    try:
        from services.search_orchestration import search_domains, search_domains_dual
        
        domains, metadata = search_domains_dual(
            base_query=request.keyword,
            region=request.region,
            target_results=request.num_results
        )
        
        return DomainSearchResponse(
            domains=domains,
            total_count=len(domains),
            metadata=metadata
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
