import pytest

from byte_mcp.errors import OXBundleError, OXFindingValidationError
from tests.ox.test_natural_review_architecture import derived_finding, make_natural_service
from tests.ox.test_review_service import RecordingClient, prepare


def establish_natural_review(tmp_path):
    client = RecordingClient()
    service, store, _, base, target, _ = make_natural_service(tmp_path, client)
    proposal = prepare(service, base, target)
    service.transmit_review(proposal["review_id"])
    return service, store, client, proposal["review_id"]


def test_record_findings_rejects_configured_credential_before_local_persistence(tmp_path) -> None:
    service, store, client, review_id = establish_natural_review(tmp_path)
    calls_before = len(client.calls)
    finding = derived_finding()
    finding["evidence"] = f"accidental credential copy: {service._settings.api_key}"

    with pytest.raises(OXBundleError):
        service.record_findings(review_id, [finding])

    assert len(client.calls) == calls_before
    assert store.read_findings(review_id)["findings"] == []


def test_record_findings_rejects_nonfinite_confidence_as_controlled_validation_error(
    tmp_path,
) -> None:
    service, store, client, review_id = establish_natural_review(tmp_path)
    calls_before = len(client.calls)
    finding = derived_finding()
    finding["confidence"] = float("nan")

    with pytest.raises(OXFindingValidationError):
        service.record_findings(review_id, [finding])

    assert len(client.calls) == calls_before
    assert store.read_findings(review_id)["findings"] == []
