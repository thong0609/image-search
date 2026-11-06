"""HTTP routes for auth; implemented in a later phase."""

from fastapi import APIRouter

router = APIRouter(prefix="/auth", tags=["auth"])
