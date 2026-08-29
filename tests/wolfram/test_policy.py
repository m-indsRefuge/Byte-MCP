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
        "pwd=hunter2",
        "postgresql://user:secret@localhost/db?password=secret",
        "sk-proj-fake-but-secret-shaped-token",
        "ghp_abcdefghijklmnopqrstuvwxyz1234567890",
    ],
)
def test_secret_like_payload_is_denied(payload: str) -> None:
    with pytest.raises(WolframPolicyError, match="sensitive"):
        WolframOutboundPolicy(max_input_chars=8000).prepare(payload)


def test_windows_absolute_paths_are_replaced() -> None:
    prepared = WolframOutboundPolicy(
        max_input_chars=8000,
        user_profile=Path(r"C:\Users\test-user"),
    ).prepare(r"Failure in C:\Users\test-user\AIProjects\tidy\src\tidy\core.py line 12")
    assert r"C:\Users\test-user" not in prepared.text
    assert "<local-path>" in prepared.text
    assert prepared.paths_sanitized == 1


def test_unc_absolute_paths_are_replaced() -> None:
    prepared = WolframOutboundPolicy(max_input_chars=8000).prepare(
        r"Failure at \\server\share\project\secretless.txt line 4"
    )
    assert "<local-path>" in prepared.text
    assert prepared.paths_sanitized == 1


def test_repository_relative_path_is_preserved() -> None:
    prepared = WolframOutboundPolicy(max_input_chars=8000).prepare("Failure in src/tidy/core.py")
    assert "src/tidy/core.py" in prepared.text
    assert prepared.paths_sanitized == 0


def test_input_is_stripped_and_crlf_normalized() -> None:
    prepared = WolframOutboundPolicy(max_input_chars=8000).prepare("  first\r\nsecond  ")
    assert prepared.text == "first\nsecond"
    assert prepared.original_chars == len("  first\r\nsecond  ")
    assert prepared.transmitted_chars == len("first\nsecond")
    assert len(prepared.sha256) == 64


def test_nul_is_rejected() -> None:
    with pytest.raises(WolframPolicyError, match="NUL"):
        WolframOutboundPolicy(max_input_chars=8000).prepare("abc\x00def")


def test_oversize_normalized_input_is_rejected() -> None:
    with pytest.raises(WolframPolicyError, match="8000"):
        WolframOutboundPolicy(max_input_chars=8000).prepare("x" * 8001)
