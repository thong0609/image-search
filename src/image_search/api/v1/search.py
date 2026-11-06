"""HTTP routes for search; implemented in a later phase."""

from fastapi import APIRouter

router = APIRouter(prefix="/search", tags=["search"])
