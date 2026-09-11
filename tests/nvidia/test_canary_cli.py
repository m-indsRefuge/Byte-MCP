from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import scripts.nvidia_lightning_canary as cli
from byte_mcp.nvidia.settings import NvidiaHostedSettings
from byte_mcp.providers import ProviderAttemptOutcome

CANARY_ID = "NVC-000001"
REQUEST_SHA256 = "b" * 64
PAYLOAD_SHA256 = "a" * 64
MODEL_ID = "nvidia/nemotron-3.5-lightning-30b-a3b"
PREPARED_AT = "2026-09-10T07:00:00+00:00"


def _install_fake_store(monkeypatch: pytest.MonkeyPatch):
    store = object()
    monkeypatch.setattr(
        cli.NvidiaCanaryEvidenceStore,
        "from_environment",
        classmethod(lambda cls: store),
    )
    return store


def _compact_json(value: dict[str, object]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n"


def test_prepare_emits_only_bounded_sorted_json(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    store = _install_fake_store(monkeypatch)
    receipt = SimpleNamespace(
        canary_id=CANARY_ID,
        provider_id="nvidia-api-catalog",
        model_id=MODEL_ID,
        payload_sha256=PAYLOAD_SHA256,
        request_sha256=REQUEST_SHA256,
        body_bytes=224,
        prepared_at=PREPARED_AT,
        evidence_root="C:/bounded/evidence",
        secret_extra="must-not-render",
    )
    monkeypatch.setattr(cli, "prepare_lightning_canary", lambda actual_store: receipt)

    assert cli.main(["prepare"]) == 0

    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out == _compact_json(
        {
            "body_bytes": 224,
            "canary_id": CANARY_ID,
            "evidence_root": "C:/bounded/evidence",
            "model_id": MODEL_ID,
            "payload_sha256": PAYLOAD_SHA256,
            "prepared_at": PREPARED_AT,
            "provider_id": "nvidia-api-catalog",
            "request_sha256": REQUEST_SHA256,
        }
    )
    assert "must-not-render" not in captured.out
    assert store is not None


def test_inspect_emits_only_bounded_sorted_json(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    store = _install_fake_store(monkeypatch)
    inspection = SimpleNamespace(
        canary_id=CANARY_ID,
        provider_id="nvidia-api-catalog",
        model_id=MODEL_ID,
        payload_sha256=PAYLOAD_SHA256,
        request_sha256=REQUEST_SHA256,
        body_bytes=224,
        prepared_at=PREPARED_AT,
        probe_text="BYTE_NVIDIA_CANARY_OK",
        provider_started_at=None,
        has_terminal_event=False,
        secret_extra="must-not-render",
    )
    monkeypatch.setattr(
        cli,
        "inspect_lightning_canary",
        lambda actual_store, canary_id: inspection,
    )

    assert cli.main(["inspect", "--canary-id", CANARY_ID]) == 0

    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out == _compact_json(
        {
            "body_bytes": 224,
            "canary_id": CANARY_ID,
            "has_terminal_event": False,
            "model_id": MODEL_ID,
            "payload_sha256": PAYLOAD_SHA256,
            "prepared_at": PREPARED_AT,
            "probe_text": "BYTE_NVIDIA_CANARY_OK",
            "provider_id": "nvidia-api-catalog",
            "provider_started_at": None,
            "request_sha256": REQUEST_SHA256,
        }
    )
    assert "must-not-render" not in captured.out
    assert store is not None


def test_transmit_requires_exact_bound_identity_and_emits_no_response_body(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    store = _install_fake_store(monkeypatch)
    calls: list[dict[str, object]] = []

    async def transmit(actual_store, **kwargs: object):
        calls.append({"store": actual_store, **kwargs})
        return SimpleNamespace(
            canary_id=CANARY_ID,
            request_sha256=REQUEST_SHA256,
            attempt_outcome=ProviderAttemptOutcome.COMPLETED,
            model_id=MODEL_ID,
            semantic_probe_match=True,
            response_content="provider-response-must-not-render",
        )

    monkeypatch.setattr(cli, "transmit_lightning_canary", transmit)

    assert (
        cli.main(
            [
                "transmit",
                "--canary-id",
                CANARY_ID,
                "--expected-request-sha256",
                REQUEST_SHA256,
                "--approve",
            ]
        )
        == 0
    )

    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out == _compact_json(
        {
            "attempt_outcome": "COMPLETED",
            "canary_id": CANARY_ID,
            "model_id": MODEL_ID,
            "request_sha256": REQUEST_SHA256,
            "semantic_probe_match": True,
        }
    )
    assert "provider-response-must-not-render" not in captured.out
    assert calls == [
        {
            "store": store,
            "canary_id": CANARY_ID,
            "expected_request_sha256": REQUEST_SHA256,
            "approve": True,
        }
    ]


@pytest.mark.parametrize(
    "argv",
    [
        ["transmit", "--expected-request-sha256", REQUEST_SHA256, "--approve"],
        ["transmit", "--canary-id", CANARY_ID, "--approve"],
        ["transmit", "--canary-id", CANARY_ID, "--expected-request-sha256", REQUEST_SHA256],
    ],
)
def test_transmit_requires_id_hash_and_explicit_approval(argv: list[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        cli.main(argv)
    assert exc_info.value.code == 2


@pytest.mark.parametrize(
    "invalid_hash",
    ["0" * 63, "A" * 64, "g" * 64],
)
def test_transmit_rejects_non_lowercase_sha256(invalid_hash: str) -> None:
    with pytest.raises(SystemExit) as exc_info:
        cli.main(
            [
                "transmit",
                "--canary-id",
                CANARY_ID,
                "--expected-request-sha256",
                invalid_hash,
                "--approve",
            ]
        )
    assert exc_info.value.code == 2


@pytest.mark.parametrize(
    "argv",
    [
        ["prepare", "--api-key", "secret"],
        ["prepare", "--token", "secret"],
        ["prepare", "--credential", "secret"],
        ["prepare", "--model", "other/model"],
        ["prepare", "--endpoint", "/v1/other"],
        ["prepare", "--prompt", "other prompt"],
        [
            "transmit",
            "--canary-id",
            CANARY_ID,
            "--expected-request-sha256",
            REQUEST_SHA256,
            "--approve",
            "--retry",
        ],
        [
            "transmit",
            "--canary-id",
            CANARY_ID,
            "--expected-request-sha256",
            REQUEST_SHA256,
            "--approve",
            "--fallback",
        ],
        [
            "transmit",
            "--canary-id",
            CANARY_ID,
            "--expected-request-sha256",
            REQUEST_SHA256,
            "--yes",
        ],
        ["status"],
    ],
)
def test_cli_rejects_unapproved_commands_and_override_flags(argv: list[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        cli.main(argv)
    assert exc_info.value.code == 2


def test_prepare_and_inspect_are_credential_blind(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    evidence_root = tmp_path / "evidence"
    secret = "nv" + "api-secret-must-never-be-read-or-persisted"
    monkeypatch.setenv("BYTE_MCP_NVIDIA_EVIDENCE_DIR", str(evidence_root))
    monkeypatch.setenv("NVIDIA_API_KEY", secret)

    def forbidden_settings_load(cls):
        raise AssertionError("prepare/inspect must not load NVIDIA hosted settings")

    monkeypatch.setattr(NvidiaHostedSettings, "load", classmethod(forbidden_settings_load))

    assert cli.main(["prepare"]) == 0
    prepared = json.loads(capsys.readouterr().out)
    assert prepared["canary_id"] == CANARY_ID

    assert cli.main(["inspect", "--canary-id", CANARY_ID]) == 0
    inspected = json.loads(capsys.readouterr().out)
    assert inspected["canary_id"] == CANARY_ID
    assert inspected["provider_started_at"] is None
    assert inspected["has_terminal_event"] is False

    for path in evidence_root.rglob("*"):
        if path.is_file():
            assert secret.encode("utf-8") not in path.read_bytes()


def test_runtime_failure_output_is_bounded_and_secret_safe(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _install_fake_store(monkeypatch)
    secret = "raw-secret-error-detail"

    def fail(_store):
        raise RuntimeError(secret)

    monkeypatch.setattr(cli, "prepare_lightning_canary", fail)

    assert cli.main(["prepare"]) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == _compact_json({"error_type": "RuntimeError"})
    assert secret not in captured.err
