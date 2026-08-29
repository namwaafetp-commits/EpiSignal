"""Review queue and resolution API routes."""

from typing import Annotated

from fastapi import APIRouter, Depends

from episignal_api.dependencies import get_review_queue_page, verify_admin_token
from episignal_backend.review.documents import ReviewQueuePage

router = APIRouter(prefix="/api/v1/admin/reviews", tags=["admin-reviews"])


@router.get("", response_model=ReviewQueuePage)
def list_review_queue(
    _admin: Annotated[str, Depends(verify_admin_token)],
    page: Annotated[ReviewQueuePage, Depends(get_review_queue_page)],
) -> ReviewQueuePage:
    """Retrieve filtered review cases awaiting administrator action."""
    return page
