"""Fail-isolated local runtime for the optional OX validation capability."""

from dataclasses import dataclass

from byte_mcp.errors import OXUnavailableError

from .client import OXClient
from .evidence import EvidenceStore
from .models import OXAvailability
from .natural_service import OXReviewService
from .repositories import validate_ox_local_config
from .settings import OXSettings


@dataclass(frozen=True, slots=True)
class OXRuntime:
    """Represent the locally validated availability of the OX subsystem."""

    state: OXAvailability
    _service: OXReviewService | None = None

    @classmethod
    def initialize(cls, settings: OXSettings, audit) -> "OXRuntime":
        """Validate only local OX configuration; never contact the provider."""
        if settings.api_key is None:
            return cls(OXAvailability.DISABLED)

        try:
            validate_ox_local_config(settings)
            service = OXReviewService(
                settings,
                EvidenceStore(settings.evidence_root),
                OXClient(settings),
                audit,
            )
        except (OSError, TypeError, ValueError):
            return cls(OXAvailability.MISCONFIGURED)
        return cls(OXAvailability.AVAILABLE, service)

    @classmethod
    def misconfigured(cls) -> "OXRuntime":
        """Create a fail-isolated state when OX settings cannot be loaded."""
        return cls(OXAvailability.MISCONFIGURED)

    def require_service(self) -> OXReviewService:
        """Return the OX service only when local startup validation succeeded."""
        if self._service is None or self.state is not OXAvailability.AVAILABLE:
            raise OXUnavailableError(f"OX validation is {self.state.value.casefold()}.")
        return self._service
