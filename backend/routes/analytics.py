"""
routes/analytics.py
"""

from fastapi import APIRouter
from services.analytics_service import get_analytics

router = APIRouter()


@router.get("/")
def analytics():
    return get_analytics()
