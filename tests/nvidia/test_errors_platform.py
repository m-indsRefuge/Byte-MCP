import importlib

import pytest


def _errors():
    return importlib.import_module("byte_mcp.nvidia.errors")


def test_platform_error_vocabulary_is_exact() -> None:
    errors = _errors()
    code = errors.NvidiaErrorCode

    assert {member.value for member in code} == {
        "INVALID_REQUEST",
        "MODEL_NOT_ALLOWED",
        "MODEL_NOT_ENABLED",
        "CREDENTIAL_UNAVAILABLE",
        "AUTHENTICATION_FAILED",
        "RATE_LIMITED",
        "PROVIDER_REJECTED",
        "TRANSPORT_FAILED",
        "RESPONSE_INVALID",
        "RESPONSE_TOO_LARGE",
    }


def test_platform_error_serializes_only_safe_operational_metadata() -> None:
    errors = _errors()

    error = errors.NvidiaPlatformError(
        code=errors.NvidiaErrorCode.MODEL_NOT_ALLOWED,
        message="model is not allowed",
        provider_started=False,
        safe_to_invoke_fresh=True,
    )

    assert error.to_dict() == {
        "code": "MODEL_NOT_ALLOWED",
        "message": "model is not allowed",
        "provider_started": False,
        "safe_to_invoke_fresh": True,
        "status_code": None,
        "automatic_retry": False,
    }


@pytest.mark.parametrize("status", [401, 403])
def test_authentication_statuses_are_classified(status: int) -> None:
    errors = _errors()

    assert (
        errors.classify_nvidia_http_status(status) is errors.NvidiaErrorCode.AUTHENTICATION_FAILED
    )


def test_rate_limit_status_is_classified() -> None:
    errors = _errors()

    assert errors.classify_nvidia_http_status(429) is errors.NvidiaErrorCode.RATE_LIMITED


@pytest.mark.parametrize("status", [400, 404, 500, 503])
def test_other_provider_errors_are_classified(status: int) -> None:
    errors = _errors()

    assert errors.classify_nvidia_http_status(status) is errors.NvidiaErrorCode.PROVIDER_REJECTED


def test_non_error_http_status_is_rejected() -> None:
    errors = _errors()

    with pytest.raises(ValueError, match="status_code is not a provider error"):
        errors.classify_nvidia_http_status(200)


def test_platform_error_never_advertises_automatic_retry() -> None:
    errors = _errors()

    error = errors.NvidiaPlatformError(
        code=errors.NvidiaErrorCode.TRANSPORT_FAILED,
        message="transport failed",
        provider_started=True,
        safe_to_invoke_fresh=True,
        status_code=None,
    )

    assert error.automatic_retry is False
    assert error.to_dict()["automatic_retry"] is False
