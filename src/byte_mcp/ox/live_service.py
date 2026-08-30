from .approval_replay import InitialApprovalReplayMixin
from .natural_service import OXReviewService as NaturalOXReviewService
from .provider_reliability import ProviderReliabilityMixin


class OXReviewService(
    InitialApprovalReplayMixin,
    ProviderReliabilityMixin,
    NaturalOXReviewService,
):
    """Live OX service composed from replay and provider reliability governance."""
