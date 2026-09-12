from byte_mcp import server


def test_v1_ox_tools_are_not_registered() -> None:
    registered = server.mcp._tool_manager._tools
    assert "ox_review" not in registered
    assert "ox_continue" not in registered
    assert "ox_revalidate" not in registered
    assert "ox_get_review" not in registered
    assert set(registered) == {
        "list_roots",
        "list_directory",
        "search",
        "fetch",
        "wolfram_query",
        "ox_v2_lifetime_probe",
    }


def test_q03h_ac18_attempts_view_is_bounded_local_and_secret_free(
    tmp_path
) -> None:
    import json
    from datetime import datetime, timedelta

    from byte_mcp.errors import OXTransportFailureKind
    from byte_mcp.ox.evidence import EvidenceStore
    from byte_mcp.ox.models import AttemptOutcome
    from byte_mcp.ox.service import OXReviewService
    from byte_mcp.ox.settings import OXSettings

    manifest_sha256 = "a" * 64
    runtime_session_id = "b" * 32

    class ProjectionEvidenceStore(EvidenceStore):
        def get_review(self, review_id: str) -> dict[str, object]:
            review = super().get_review(review_id)
            for attempt in review["attempts"]:
                attempt.update(
                    {
                        "raw_body": "RAW-BODY-SENTINEL",
                        "authorization_header": "HEADER-SENTINEL",
                        "cookie": "COOKIE-SENTINEL",
                        "exception_text": "EXCEPTION-SENTINEL",
                        "stack": "STACK-SENTINEL",
                    }
                )
            return review

    class FailIfCalledClient:
        def complete(self, *args, **kwargs):
            raise AssertionError("retrieval must not call the provider")

    class Audit:
        def record(self, *args, **kwargs) -> None:
            return None

    store = ProjectionEvidenceStore(tmp_path / "evidence")
    review_id = store.persist_prepared_review(
        identity={
            "repository": "fixture",
            "subsystem": "validation",
            "objective": "review",
        },
        manifest={"manifest_sha256": manifest_sha256},
        bundle={"packet": "prepared"},
    )
    events_path = store._root / "reviews" / review_id / "events.jsonl"
    legacy_attempt_id = f"{review_id}-A001"
    legacy_events = [
        {
            "attempt_id": legacy_attempt_id,
            "event_type": "TRANSMISSION_INTENT",
            "manifest_sha256": manifest_sha256,
            "recorded_at": "2026-09-01T00:00:00+00:00",
        },
        {
            "attempt_id": legacy_attempt_id,
            "event_type": "ATTEMPT_OUTCOME",
            "outcome": AttemptOutcome.NOT_SENT.value,
        },
    ]
    with events_path.open("ab") as handle:
        for event in legacy_events:
            handle.write(
                json.dumps(event, separators=(",", ":"), sort_keys=True).encode("utf-8")
                + b"\n"
            )

    owned = store.claim_retry_transmission(
        review_id,
        manifest_sha256,
        renewed_approval=True,
        runtime_session_id=runtime_session_id,
    )
    store.record_provider_request_started(
        review_id,
        owned["attempt_id"],
        runtime_session_id=runtime_session_id,
        phase="initial",
    )
    started_at = store.get_review(review_id)["attempts"][-1]["provider_started_at"]
    assert isinstance(started_at, str)
    finished_at = (datetime.fromisoformat(started_at) + timedelta(milliseconds=25)).isoformat()
    store.record_attempt_outcome(
        review_id,
        owned["attempt_id"],
        AttemptOutcome.OUTCOME_UNKNOWN,
    )
    store.record_provider_transport_metadata(
        review_id,
        owned["attempt_id"],
        runtime_session_id=runtime_session_id,
        provider_finished_at=finished_at,
        elapsed_ms=25,
        transport_failure_kind=OXTransportFailureKind.READ_ERROR,
    )

    settings = OXSettings(
        "FAKE-TEST-KEY",
        tmp_path / "repositories.json",
        store._root,
    )
    service = OXReviewService(settings, store, FailIfCalledClient(), Audit())

    result = service.get_review(review_id, view="attempts")

    assert result == {
        "review_id": review_id,
        "attempts": [
            {
                "attempt_id": legacy_attempt_id,
                "manifest_sha256": manifest_sha256,
                "outcome": AttemptOutcome.NOT_SENT.value,
            },
            {
                "attempt_id": owned["attempt_id"],
                "manifest_sha256": manifest_sha256,
                "runtime_session_id": runtime_session_id,
                "provider_request_started": True,
                "outcome": AttemptOutcome.OUTCOME_UNKNOWN.value,
                "provider_started_at": started_at,
                "provider_finished_at": finished_at,
                "elapsed_ms": 25,
                "transport_failure_kind": OXTransportFailureKind.READ_ERROR.value,
            },
        ],
    }
