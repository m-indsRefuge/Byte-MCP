from .approval_replay import InitialApprovalReplayMixin
from .natural_service import OXReviewService as NaturalOXReviewService


class OXReviewService(InitialApprovalReplayMixin, NaturalOXReviewService):
    """Live OX service composed from replay governance and natural review behavior."""
