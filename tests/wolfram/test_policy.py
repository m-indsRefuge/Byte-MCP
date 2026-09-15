from pathlib import Path

import pytest

from byte_mcp.errors import WolframPolicyError
from byte_mcp.wolfram.policy import WolframOutboundPolicy


@pytest.mark.parametrize(
    "payload",
    [
        "OPENAI_API_KEY=sk-test-secret",
        "AI_GATEWAY_API_KEY=ox-secret",
        "WOLFRAM_APP_ID=APP-SECRET",
        "CONTROL_PLANE_API_KEY=tunnel-secret",
        "Authorization: Bearer secret-token",
        "-----BEGIN PRIVATE KEY-----",
        "password=hunter2",
        "postgresql://user:password@db.example/test",
        "ghp_abcdefghijklmno",
    ],
)
def test_secret_like_payload_is_denied(payload: str) -> None:
    with pytest.raises(WolframPolicyError, match="sensitive"):
        WolframOutboundPolicy().prepare(payload)


def test_windows_absolute_paths_are_replaced() -> None:
    prepared = WolframOutboundPolicy(Path(r"C:\Users\nolan")).prepare(
        r"Failure in C:\Users\nolan\AIProjects\tidy\src\tidy\core.py line 12"
    )
    assert r"C:\Users\nolan" not in prepared.text
    assert "<local-path>" in prepared.text
    assert prepared.paths_sanitized == 1


def test_relative_paths_remain_intact() -> None:
    prepared = WolframOutboundPolicy().prepare("Failure in src/tidy/core.py line 12")
    assert "src/tidy/core.py" in prepared.text
    assert prepared.paths_sanitized == 0


def test_input_normalization_and_limits() -> None:
    prepared = WolframOutboundPolicy(max_input_chars=20).prepare("  a\r\nb  ")
    assert prepared.text == "a\nb"
    assert len(prepared.sha256) == 64

    with pytest.raises(WolframPolicyError, match="NUL"):
        WolframOutboundPolicy().prepare("a\x00b")
    with pytest.raises(WolframPolicyError, match="exceeds"):
        WolframOutboundPolicy(max_input_chars=3).prepare("abcd")
