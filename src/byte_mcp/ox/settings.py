import os
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True, repr=False)
class OXSettings:
    api_key: str | None
    repositories_file: Path
    evidence_root: Path
    max_bundle_bytes: int = 4_000_000
    max_output_tokens: int = 65_536
    gateway_url: str = "https://ai-gateway.vercel.sh/v1/chat/completions"
    model: str = "zai/glm-5.3-flash"
    provider_slug: str = "zai"

    def __repr__(self) -> str:
        return f"OXSettings(api_key_configured={self.api_key is not None})"

    @classmethod
    def load(cls, repo_root: Path) -> "OXSettings":
        def bounded(name: str, default: int, low: int, high: int) -> int:
            value = int(os.getenv(name, str(default)))
            if not low <= value <= high:
                raise ValueError(f"{name} must be between {low} and {high}")
            return value

        repositories = Path(
            os.getenv("BYTE_MCP_OX_REPOSITORIES_FILE", "config/ox-repositories.local.json")
        )
        if not repositories.is_absolute():
            repositories = repo_root / repositories
        evidence = os.getenv("BYTE_MCP_OX_EVIDENCE_DIR")
        if evidence:
            evidence_root = Path(evidence)
        elif sys.platform == "win32":
            evidence_root = (
                Path(os.getenv("LOCALAPPDATA", Path.home() / "AppData/Local")) / "Byte-MCP" / "ox"
            )
        else:
            evidence_root = (
                Path(os.getenv("XDG_DATA_HOME", Path.home() / ".local/share")) / "byte-mcp" / "ox"
            )
        key = os.getenv("AI_GATEWAY_API_KEY", "").strip() or None
        return cls(
            key,
            repositories,
            evidence_root,
            bounded("BYTE_MCP_OX_MAX_BUNDLE_BYTES", 4_000_000, 16_384, 16_000_000),
            bounded("BYTE_MCP_OX_MAX_OUTPUT_TOKENS", 65_536, 1_024, 131_072),
        )
