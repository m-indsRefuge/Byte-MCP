from .approval_replay import InitialApprovalReplayMixin
from .audit_reliability import SafeAttemptAuditMixin
from .natural_service import OXReviewService as NaturalOXReviewService
from .provider_reliability import ProviderReliabilityMixin


class OXReviewService(
    InitialApprovalReplayMixin,
    SafeAttemptAuditMixin,
    ProviderReliabilityMixin,
    NaturalOXReviewService,
):
    """Live OX service composed from replay and provider reliability governance."""
