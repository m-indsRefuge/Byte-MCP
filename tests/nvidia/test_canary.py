import pytest

EXPECTED_MODEL_ID = "nvidia/nemotron-3.5-lightning-30b-a3b"
EXPECTED_PROMPT = "Reply with exactly: BYTE_NVIDIA_CANARY_OK"
EXPECTED_TEXT = "BYTE_NVIDIA_CANARY_OK"
QUALIFIED_PREDECESSOR = "29daea6ef68ebb3d46031ce302b0108617bd1221"
FIXED_NOW_TEXT = "2026-09-09T18:00:00+00:00"
AUTH_NOW_TEXT = "2026-09-09T18:01:00+00:00"
START_NOW_TEXT = "2026-09-09T18:02:00+00:00"
FINISH_NOW_TEXT = "2026-09-09T18:02:01+00:00"
TERMINAL_KEYS = {
    "event_type",
    "canary_id",
    "request_sha256",
    "provider_id",
    "model_id",
    "provider_started_at",
    "provider_finished_at",
    "attempt_outcome",
    "nvidia_failure_kind",
    "transport_failure_kind",
    "http_status_code",
    "response_headers_received",
    "response_body_started",
    "decoded_body_bytes_received",
    "elapsed_ms",
    "finish_reason",
    "response_id",
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
    "semantic_probe_match",
    "recorded_at",
}


def _module(name: str):
    return __import__(name, fromlist=["*"])


def _canary_module():
    return _module("byte_mcp.nvidia.canary")


def _evidence_module():
    return _module("byte_mcp.nvidia.canary_evidence")


def _evidence_store_class():
    return _evidence_module().NvidiaCanaryEvidenceStore


def _settings_class():
    return _module("byte_mcp.nvidia.settings").NvidiaHostedSettings


def _fixed_now():
    return _module("datetime").datetime.fromisoformat(FIXED_NOW_TEXT)


def _clock(*values: str):
    moments = iter(_module("datetime").datetime.fromisoformat(value) for value in values)
    return lambda: next(moments)


def _valid_settings():
    return _settings_class()(api_key="configured")


def _transport_observation(
    *,
    provider_started_at: str = START_NOW_TEXT,
    provider_finished_at: str = FINISH_NOW_TEXT,
    http_status_code: int | None = 200,
    response_headers_received: bool = True,
    response_body_started: bool = True,
    decoded_body_bytes_received: int = 42,
    elapsed_ms: int = 125,
    transport_failure_kind=None,
):
    providers = _module("byte_mcp.providers")
    return providers.ProviderTransportObservation(
        response_headers_received=response_headers_received,
        response_headers_at=(provider_finished_at if response_headers_received else None),
        response_headers_elapsed_ms=(10 if response_headers_received else None),
        http_status_code=http_status_code,
        response_body_started=response_body_started,
        first_body_at=(provider_finished_at if response_body_started else None),
        first_body_elapsed_ms=(20 if response_body_started else None),
        last_body_at=(provider_finished_at if response_body_started else None),
        last_body_elapsed_ms=(elapsed_ms if response_body_started else None),
        decoded_body_bytes_received=decoded_body_bytes_received,
        provider_started_at=provider_started_at,
        provider_finished_at=provider_finished_at,
        elapsed_ms=elapsed_ms,
        transport_failure_kind=transport_failure_kind,
        trust_env_enabled=True,
        proxy_environment_present=False,
    )


def _successful_executor_result(content: str = EXPECTED_TEXT):
    chat = _module("byte_mcp.nvidia.chat")
    return _module("types").SimpleNamespace(
        model_id=EXPECTED_MODEL_ID,
        content=content,
        finish_reason="stop",
        response_id="chatcmpl-n02-test",
        usage=chat.NvidiaChatUsage(prompt_tokens=3, completion_tokens=4, total_tokens=7),
        transport_observation=_transport_observation(),
    )


def _forbid_http_client(*args: object, **kwargs: object) -> None:
    raise AssertionError("Task 3 must not construct an HTTP client")


def _forbid_settings_load(*args: object, **kwargs: object):
    raise AssertionError("Task 3 must not load NVIDIA hosted settings")


def _evidence_bytes(root) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _prepared_canary(tmp_path):
    canary = _canary_module()
    store = _evidence_store_class()(tmp_path / "evidence")
    receipt = canary.prepare_lightning_canary(store, now=_fixed_now)
    return canary, store, receipt


class _NoopLock:
    def __enter__(self):
        return None

    def __exit__(self, exc_type, exc, traceback):
        return False


class _SnapshotStore:
    def __init__(self, snapshot) -> None:
        self.snapshot = snapshot
        self.authorized_appends = 0
        self.provider_start_appends = 0

    def transmit_lock(self, canary_id: str):
        return _NoopLock()

    def load(self, canary_id: str):
        return self.snapshot

    def append_authorized(self, *args: object, **kwargs: object) -> None:
        self.authorized_appends += 1

    def append_provider_start(self, *args: object, **kwargs: object) -> None:
        self.provider_start_appends += 1


def _replace_manifest_field(snapshot, field_name: str, value: object):
    manifest = snapshot.manifest
    fields = {
        name: getattr(manifest, name)
        for name in (
            "schema",
            "canary_id",
            "provider_id",
            "model_id",
            "method",
            "target_origin",
            "endpoint_path",
            "payload_sha256",
            "request_sha256",
            "body_bytes",
            "prepared_at",
            "probe_expected_text",
            "qualified_predecessor_sha",
        )
    }
    fields[field_name] = value
    fake_manifest = _module("types").SimpleNamespace(**fields)
    return _module("types").SimpleNamespace(
        manifest=fake_manifest,
        request_body=snapshot.request_body,
        events=snapshot.events,
        authorized_at=snapshot.authorized_at,
        provider_started_at=snapshot.provider_started_at,
        terminal_event=snapshot.terminal_event,
    )


def test_task3_api_exports_exact_frozen_constants() -> None:
    canary = _canary_module()

    assert canary.NVIDIA_LIGHTNING_CANARY_MODEL_ID == EXPECTED_MODEL_ID
    assert canary.NVIDIA_LIGHTNING_CANARY_PROMPT == EXPECTED_PROMPT
    assert canary.NVIDIA_LIGHTNING_CANARY_EXPECTED_TEXT == EXPECTED_TEXT
    assert canary.NVIDIA_01_QUALIFIED_SHA == QUALIFIED_PREDECESSOR


def test_prepare_lightning_canary_persists_exact_fixed_request_without_key(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    canary = _canary_module()
    store_class = _evidence_store_class()
    settings_class = _settings_class()
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    monkeypatch.setattr(_module("httpx"), "AsyncClient", _forbid_http_client)
    monkeypatch.setattr(settings_class, "load", classmethod(_forbid_settings_load))
    store = store_class(tmp_path / "evidence")

    receipt = canary.prepare_lightning_canary(store, now=_fixed_now)
    snapshot = store.load(receipt.canary_id)
    body = _module("json").loads(snapshot.request_body)

    assert body == {
        "max_tokens": 64,
        "messages": [{"content": EXPECTED_PROMPT, "role": "user"}],
        "model": EXPECTED_MODEL_ID,
        "n": 1,
        "stream": False,
        "temperature": 1.0,
        "top_p": 0.95,
    }
    assert snapshot.manifest.probe_expected_text == EXPECTED_TEXT
    assert snapshot.manifest.qualified_predecessor_sha == QUALIFIED_PREDECESSOR
    assert receipt.canary_id == "NVC-000001"
    assert receipt.provider_id == "nvidia-api-catalog"
    assert receipt.model_id == EXPECTED_MODEL_ID
    assert receipt.payload_sha256 == snapshot.manifest.payload_sha256
    assert receipt.request_sha256 == snapshot.manifest.request_sha256
    assert receipt.body_bytes == len(snapshot.request_body)
    assert receipt.prepared_at == FIXED_NOW_TEXT
    assert receipt.evidence_root == str(store.root)


def test_inspect_lightning_canary_is_read_only_and_credential_blind(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    canary = _canary_module()
    store_class = _evidence_store_class()
    settings_class = _settings_class()
    store = store_class(tmp_path / "evidence")
    receipt = canary.prepare_lightning_canary(store, now=_fixed_now)
    before = _evidence_bytes(store.root)

    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    monkeypatch.setattr(_module("httpx"), "AsyncClient", _forbid_http_client)
    monkeypatch.setattr(settings_class, "load", classmethod(_forbid_settings_load))

    inspection = canary.inspect_lightning_canary(store, receipt.canary_id)
    after = _evidence_bytes(store.root)

    assert inspection.canary_id == receipt.canary_id
    assert inspection.provider_id == "nvidia-api-catalog"
    assert inspection.model_id == EXPECTED_MODEL_ID
    assert inspection.payload_sha256 == receipt.payload_sha256
    assert inspection.request_sha256 == receipt.request_sha256
    assert inspection.body_bytes == receipt.body_bytes
    assert inspection.prepared_at == FIXED_NOW_TEXT
    assert inspection.probe_text == EXPECTED_TEXT
    assert inspection.provider_started_at is None
    assert inspection.has_terminal_event is False
    assert after == before


def test_task3_api_is_reexported_from_nvidia_package() -> None:
    package = _module("byte_mcp.nvidia")

    assert package.NVIDIA_LIGHTNING_CANARY_MODEL_ID == EXPECTED_MODEL_ID
    assert package.NVIDIA_LIGHTNING_CANARY_PROMPT == EXPECTED_PROMPT
    assert package.NVIDIA_LIGHTNING_CANARY_EXPECTED_TEXT == EXPECTED_TEXT
    assert package.NVIDIA_01_QUALIFIED_SHA == QUALIFIED_PREDECESSOR
    assert callable(package.prepare_lightning_canary)
    assert callable(package.inspect_lightning_canary)


def test_transmit_result_contract_hides_response_content_from_repr() -> None:
    canary = _canary_module()
    outcome = _module("byte_mcp.providers").ProviderAttemptOutcome.COMPLETED

    result = canary.NvidiaCanaryTransmissionResult(
        canary_id="NVC-000001",
        request_sha256="a" * 64,
        attempt_outcome=outcome,
        model_id=EXPECTED_MODEL_ID,
        semantic_probe_match=True,
        response_content="sensitive-response-content",
    )

    assert "sensitive-response-content" not in repr(result)


def test_transmit_rejects_approval_false_without_settings_or_executor(tmp_path) -> None:
    canary, store, receipt = _prepared_canary(tmp_path)
    calls = {"settings": 0, "executor": 0}

    def settings_loader():
        calls["settings"] += 1
        return _valid_settings()

    async def executor(*args: object, **kwargs: object):
        calls["executor"] += 1
        return _successful_executor_result()

    with pytest.raises(ValueError, match="approval"):
        _module("asyncio").run(
            canary.transmit_lightning_canary(
                store,
                canary_id=receipt.canary_id,
                expected_request_sha256=receipt.request_sha256,
                approve=False,
                settings_loader=settings_loader,
                executor=executor,
                now=_clock(AUTH_NOW_TEXT, START_NOW_TEXT),
            )
        )

    snapshot = store.load(receipt.canary_id)
    assert calls == {"settings": 0, "executor": 0}
    assert snapshot.authorized_at is None
    assert snapshot.provider_started_at is None


def test_transmit_rejects_wrong_hash_without_settings_or_executor(tmp_path) -> None:
    canary, store, receipt = _prepared_canary(tmp_path)
    calls = {"settings": 0, "executor": 0}

    def settings_loader():
        calls["settings"] += 1
        return _valid_settings()

    async def executor(*args: object, **kwargs: object):
        calls["executor"] += 1
        return _successful_executor_result()

    with pytest.raises(ValueError, match="request"):
        _module("asyncio").run(
            canary.transmit_lightning_canary(
                store,
                canary_id=receipt.canary_id,
                expected_request_sha256="0" * 64,
                approve=True,
                settings_loader=settings_loader,
                executor=executor,
                now=_clock(AUTH_NOW_TEXT, START_NOW_TEXT),
            )
        )

    snapshot = store.load(receipt.canary_id)
    assert calls == {"settings": 0, "executor": 0}
    assert snapshot.authorized_at is None
    assert snapshot.provider_started_at is None


def test_transmit_missing_canary_makes_zero_settings_or_executor_calls(tmp_path) -> None:
    canary = _canary_module()
    store = _evidence_store_class()(tmp_path / "evidence")
    calls = {"settings": 0, "executor": 0}

    def settings_loader():
        calls["settings"] += 1
        return _valid_settings()

    async def executor(*args: object, **kwargs: object):
        calls["executor"] += 1
        return _successful_executor_result()

    with pytest.raises(_evidence_module().NvidiaCanaryEvidenceError):
        _module("asyncio").run(
            canary.transmit_lightning_canary(
                store,
                canary_id="NVC-999999",
                expected_request_sha256="a" * 64,
                approve=True,
                settings_loader=settings_loader,
                executor=executor,
                now=_clock(AUTH_NOW_TEXT, START_NOW_TEXT),
            )
        )

    assert calls == {"settings": 0, "executor": 0}


def test_transmit_tampered_evidence_makes_zero_settings_or_executor_calls(tmp_path) -> None:
    canary, store, receipt = _prepared_canary(tmp_path)
    request_path = store.root / "canaries" / receipt.canary_id / "request-body.bin"
    request_path.write_bytes(request_path.read_bytes() + b"x")
    calls = {"settings": 0, "executor": 0}

    def settings_loader():
        calls["settings"] += 1
        return _valid_settings()

    async def executor(*args: object, **kwargs: object):
        calls["executor"] += 1
        return _successful_executor_result()

    with pytest.raises(_evidence_module().NvidiaCanaryEvidenceError):
        _module("asyncio").run(
            canary.transmit_lightning_canary(
                store,
                canary_id=receipt.canary_id,
                expected_request_sha256=receipt.request_sha256,
                approve=True,
                settings_loader=settings_loader,
                executor=executor,
                now=_clock(AUTH_NOW_TEXT, START_NOW_TEXT),
            )
        )

    assert calls == {"settings": 0, "executor": 0}


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    [
        ("provider_id", "other-provider"),
        ("model_id", "nvidia/other-model"),
        ("method", "PUT"),
        ("target_origin", "https://example.com"),
        ("endpoint_path", "/v1/other"),
    ],
)
def test_transmit_rejects_wrong_frozen_target_before_executor(
    tmp_path,
    field_name: str,
    invalid_value: str,
) -> None:
    canary, real_store, receipt = _prepared_canary(tmp_path)
    fake_snapshot = _replace_manifest_field(
        real_store.load(receipt.canary_id), field_name, invalid_value
    )
    store = _SnapshotStore(fake_snapshot)
    executor_calls = 0

    async def executor(*args: object, **kwargs: object):
        nonlocal executor_calls
        executor_calls += 1
        return _successful_executor_result()

    with pytest.raises(ValueError):
        _module("asyncio").run(
            canary.transmit_lightning_canary(
                store,
                canary_id=receipt.canary_id,
                expected_request_sha256=receipt.request_sha256,
                approve=True,
                settings_loader=_valid_settings,
                executor=executor,
                now=_clock(AUTH_NOW_TEXT, START_NOW_TEXT),
            )
        )

    assert executor_calls == 0
    assert store.authorized_appends == 0
    assert store.provider_start_appends == 0


def test_transmit_missing_key_stops_before_authorization_and_start(tmp_path) -> None:
    canary, store, receipt = _prepared_canary(tmp_path)
    executor_calls = 0

    async def executor(*args: object, **kwargs: object):
        nonlocal executor_calls
        executor_calls += 1
        return _successful_executor_result()

    with pytest.raises(ValueError, match="key"):
        _module("asyncio").run(
            canary.transmit_lightning_canary(
                store,
                canary_id=receipt.canary_id,
                expected_request_sha256=receipt.request_sha256,
                approve=True,
                settings_loader=lambda: _settings_class()(api_key=None),
                executor=executor,
                now=_clock(AUTH_NOW_TEXT, START_NOW_TEXT),
            )
        )

    snapshot = store.load(receipt.canary_id)
    assert executor_calls == 0
    assert snapshot.authorized_at is None
    assert snapshot.provider_started_at is None


def test_transmit_invalid_timeout_config_stops_before_authorization_and_start(tmp_path) -> None:
    canary, store, receipt = _prepared_canary(tmp_path)
    executor_calls = 0

    def invalid_settings_loader():
        return _settings_class()(api_key="configured", chat_read_timeout_seconds=0)

    async def executor(*args: object, **kwargs: object):
        nonlocal executor_calls
        executor_calls += 1
        return _successful_executor_result()

    with pytest.raises(ValueError, match="chat_read_timeout_seconds"):
        _module("asyncio").run(
            canary.transmit_lightning_canary(
                store,
                canary_id=receipt.canary_id,
                expected_request_sha256=receipt.request_sha256,
                approve=True,
                settings_loader=invalid_settings_loader,
                executor=executor,
                now=_clock(AUTH_NOW_TEXT, START_NOW_TEXT),
            )
        )

    snapshot = store.load(receipt.canary_id)
    assert executor_calls == 0
    assert snapshot.authorized_at is None
    assert snapshot.provider_started_at is None


def test_transmit_prior_provider_start_stops_before_settings_or_executor(tmp_path) -> None:
    canary, store, receipt = _prepared_canary(tmp_path)
    store.append_authorized(
        receipt.canary_id,
        request_sha256=receipt.request_sha256,
        recorded_at=AUTH_NOW_TEXT,
    )
    store.append_provider_start(
        receipt.canary_id,
        request_sha256=receipt.request_sha256,
        recorded_at=START_NOW_TEXT,
    )
    calls = {"settings": 0, "executor": 0}

    def settings_loader():
        calls["settings"] += 1
        return _valid_settings()

    async def executor(*args: object, **kwargs: object):
        calls["executor"] += 1
        return _successful_executor_result()

    with pytest.raises(ValueError, match="provider-start"):
        _module("asyncio").run(
            canary.transmit_lightning_canary(
                store,
                canary_id=receipt.canary_id,
                expected_request_sha256=receipt.request_sha256,
                approve=True,
                settings_loader=settings_loader,
                executor=executor,
                now=_fixed_now,
            )
        )

    assert calls == {"settings": 0, "executor": 0}


def test_transmit_lock_contention_makes_zero_settings_or_executor_calls(tmp_path) -> None:
    canary, store, receipt = _prepared_canary(tmp_path)
    calls = {"settings": 0, "executor": 0}

    def settings_loader():
        calls["settings"] += 1
        return _valid_settings()

    async def executor(*args: object, **kwargs: object):
        calls["executor"] += 1
        return _successful_executor_result()

    with (
        store.transmit_lock(receipt.canary_id),
        pytest.raises(_evidence_module().NvidiaCanaryLockError),
    ):
        _module("asyncio").run(
            canary.transmit_lightning_canary(
                store,
                canary_id=receipt.canary_id,
                expected_request_sha256=receipt.request_sha256,
                approve=True,
                settings_loader=settings_loader,
                executor=executor,
                now=_clock(AUTH_NOW_TEXT, START_NOW_TEXT),
            )
        )

    assert calls == {"settings": 0, "executor": 0}


def test_transmit_persists_exact_provider_start_before_single_executor_call(tmp_path) -> None:
    canary, store, receipt = _prepared_canary(tmp_path)
    executor_calls = 0

    async def executor(prepared_request, context, settings):
        nonlocal executor_calls
        executor_calls += 1
        snapshot = store.load(receipt.canary_id)
        assert snapshot.provider_started_at == START_NOW_TEXT
        assert context.provider_started_at == START_NOW_TEXT
        assert context.expected_request_sha256 == receipt.request_sha256
        assert prepared_request.body_bytes == snapshot.request_body
        assert prepared_request.request_sha256 == receipt.request_sha256
        assert settings.api_key is not None
        return _successful_executor_result()

    result = _module("asyncio").run(
        canary.transmit_lightning_canary(
            store,
            canary_id=receipt.canary_id,
            expected_request_sha256=receipt.request_sha256,
            approve=True,
            settings_loader=_valid_settings,
            executor=executor,
            now=_clock(AUTH_NOW_TEXT, START_NOW_TEXT),
        )
    )

    snapshot = store.load(receipt.canary_id)
    event_types = [event["event_type"] for event in snapshot.events]
    assert executor_calls == 1
    assert event_types[:3] == ["CANARY_PREPARED", "CANARY_AUTHORIZED", "PROVIDER_START"]
    assert snapshot.authorized_at == AUTH_NOW_TEXT
    assert snapshot.provider_started_at == START_NOW_TEXT
    assert result.canary_id == receipt.canary_id
    assert result.request_sha256 == receipt.request_sha256
    assert result.attempt_outcome is _module("byte_mcp.providers").ProviderAttemptOutcome.COMPLETED
    assert result.model_id == EXPECTED_MODEL_ID
    assert result.semantic_probe_match is True
    assert result.response_content == EXPECTED_TEXT


def test_transmit_existing_matching_authorization_is_not_duplicated(tmp_path) -> None:
    canary, store, receipt = _prepared_canary(tmp_path)
    store.append_authorized(
        receipt.canary_id,
        request_sha256=receipt.request_sha256,
        recorded_at=AUTH_NOW_TEXT,
    )
    executor_calls = 0

    async def executor(*args: object, **kwargs: object):
        nonlocal executor_calls
        executor_calls += 1
        return _successful_executor_result()

    _module("asyncio").run(
        canary.transmit_lightning_canary(
            store,
            canary_id=receipt.canary_id,
            expected_request_sha256=receipt.request_sha256,
            approve=True,
            settings_loader=_valid_settings,
            executor=executor,
            now=_clock(START_NOW_TEXT),
        )
    )

    snapshot = store.load(receipt.canary_id)
    event_types = [event["event_type"] for event in snapshot.events]
    assert executor_calls == 1
    assert event_types.count("CANARY_AUTHORIZED") == 1
    assert snapshot.authorized_at == AUTH_NOW_TEXT
    assert snapshot.provider_started_at == START_NOW_TEXT


def test_concurrent_duplicate_transmit_allows_at_most_one_executor_and_start(tmp_path) -> None:
    canary, store, receipt = _prepared_canary(tmp_path)
    lock_error = _evidence_module().NvidiaCanaryLockError

    async def scenario() -> None:
        entered = _module("asyncio").Event()
        release = _module("asyncio").Event()
        executor_calls = 0
        settings_calls = 0

        def settings_loader():
            nonlocal settings_calls
            settings_calls += 1
            return _valid_settings()

        async def executor(*args: object, **kwargs: object):
            nonlocal executor_calls
            executor_calls += 1
            entered.set()
            await release.wait()
            return _successful_executor_result()

        first = _module("asyncio").create_task(
            canary.transmit_lightning_canary(
                store,
                canary_id=receipt.canary_id,
                expected_request_sha256=receipt.request_sha256,
                approve=True,
                settings_loader=settings_loader,
                executor=executor,
                now=_clock(AUTH_NOW_TEXT, START_NOW_TEXT),
            )
        )
        await entered.wait()

        with pytest.raises(lock_error):
            await canary.transmit_lightning_canary(
                store,
                canary_id=receipt.canary_id,
                expected_request_sha256=receipt.request_sha256,
                approve=True,
                settings_loader=settings_loader,
                executor=executor,
                now=_fixed_now,
            )

        release.set()
        await first

        snapshot = store.load(receipt.canary_id)
        event_types = [event["event_type"] for event in snapshot.events]
        assert executor_calls == 1
        assert settings_calls == 1
        assert event_types.count("PROVIDER_START") == 1
        assert event_types.count("CANARY_AUTHORIZED") == 1

    _module("asyncio").run(scenario())


@pytest.mark.parametrize(
    ("content", "expected_match"),
    [(EXPECTED_TEXT, True), ("different wording", False)],
)
def test_transmit_success_persists_fixed_terminal_event(
    tmp_path,
    content: str,
    expected_match: bool,
) -> None:
    canary, store, receipt = _prepared_canary(tmp_path)
    secret = "configured-secret-not-for-evidence"

    async def executor(*args: object, **kwargs: object):
        return _successful_executor_result(content)

    result = _module("asyncio").run(
        canary.transmit_lightning_canary(
            store,
            canary_id=receipt.canary_id,
            expected_request_sha256=receipt.request_sha256,
            approve=True,
            settings_loader=lambda: _settings_class()(api_key=secret),
            executor=executor,
            now=_clock(AUTH_NOW_TEXT, START_NOW_TEXT),
        )
    )

    snapshot = store.load(receipt.canary_id)
    terminal = snapshot.terminal_event
    assert terminal is not None
    assert set(terminal) == TERMINAL_KEYS
    assert terminal["event_type"] == "CANARY_TERMINAL"
    assert terminal["canary_id"] == receipt.canary_id
    assert terminal["request_sha256"] == receipt.request_sha256
    assert terminal["provider_id"] == "nvidia-api-catalog"
    assert terminal["model_id"] == EXPECTED_MODEL_ID
    assert terminal["provider_started_at"] == START_NOW_TEXT
    assert terminal["provider_finished_at"] == FINISH_NOW_TEXT
    assert terminal["attempt_outcome"] == "COMPLETED"
    assert terminal["nvidia_failure_kind"] is None
    assert terminal["transport_failure_kind"] is None
    assert terminal["http_status_code"] == 200
    assert terminal["response_headers_received"] is True
    assert terminal["response_body_started"] is True
    assert terminal["decoded_body_bytes_received"] == 42
    assert terminal["elapsed_ms"] == 125
    assert terminal["finish_reason"] == "stop"
    assert terminal["response_id"] == "chatcmpl-n02-test"
    assert terminal["prompt_tokens"] == 3
    assert terminal["completion_tokens"] == 4
    assert terminal["total_tokens"] == 7
    assert terminal["semantic_probe_match"] is expected_match
    assert terminal["recorded_at"] == FINISH_NOW_TEXT
    assert result.semantic_probe_match is expected_match

    raw_events = (
        store.root / "canaries" / receipt.canary_id / "events.jsonl"
    ).read_text(encoding="utf-8")
    assert content not in raw_events
    assert secret not in raw_events
    assert "Authorization" not in raw_events


@pytest.mark.parametrize(
    ("kind_name", "outcome_name", "status_code"),
    [("RATE_LIMIT", "REJECTED", 429), ("PROTOCOL", "COMPLETED", 200)],
)
def test_transmit_terminalizes_nvidia_chat_error_and_reraises_same_error(
    tmp_path,
    kind_name: str,
    outcome_name: str,
    status_code: int,
) -> None:
    canary, store, receipt = _prepared_canary(tmp_path)
    errors = _module("byte_mcp.nvidia.errors")
    providers = _module("byte_mcp.providers")
    error = errors.NvidiaChatError(
        kind=errors.NvidiaChatFailureKind[kind_name],
        attempt_outcome=providers.ProviderAttemptOutcome[outcome_name],
        transport_observation=_transport_observation(http_status_code=status_code),
        request_sha256=receipt.request_sha256,
    )

    async def executor(*args: object, **kwargs: object):
        raise error

    with pytest.raises(errors.NvidiaChatError) as caught:
        _module("asyncio").run(
            canary.transmit_lightning_canary(
                store,
                canary_id=receipt.canary_id,
                expected_request_sha256=receipt.request_sha256,
                approve=True,
                settings_loader=_valid_settings,
                executor=executor,
                now=_clock(AUTH_NOW_TEXT, START_NOW_TEXT),
            )
        )

    assert caught.value is error
    terminal = store.load(receipt.canary_id).terminal_event
    assert terminal is not None
    assert terminal["attempt_outcome"] == outcome_name
    assert terminal["nvidia_failure_kind"] == kind_name
    assert terminal["transport_failure_kind"] is None
    assert terminal["http_status_code"] == status_code
    assert terminal["semantic_probe_match"] is None
    assert terminal["finish_reason"] is None
    assert terminal["response_id"] is None


@pytest.mark.parametrize(
    ("outcome_name", "failure_name", "status_code", "headers", "body_started"),
    [
        ("NOT_SENT", "CONNECT_ERROR", None, False, False),
        ("OUTCOME_UNKNOWN", "READ_TIMEOUT", 200, True, True),
    ],
)
def test_transmit_terminalizes_provider_transport_error_and_reraises_same_error(
    tmp_path,
    outcome_name: str,
    failure_name: str,
    status_code: int | None,
    headers: bool,
    body_started: bool,
) -> None:
    canary, store, receipt = _prepared_canary(tmp_path)
    providers = _module("byte_mcp.providers")
    failure_kind = providers.ProviderTransportFailureKind[failure_name]
    observation = _transport_observation(
        http_status_code=status_code,
        response_headers_received=headers,
        response_body_started=body_started,
        decoded_body_bytes_received=(11 if body_started else 0),
        transport_failure_kind=failure_kind,
    )
    error = providers.ProviderTransportError(
        attempt_outcome=providers.ProviderAttemptOutcome[outcome_name],
        transport_failure_kind=failure_kind,
        transport_observation=observation,
    )

    async def executor(*args: object, **kwargs: object):
        raise error

    with pytest.raises(providers.ProviderTransportError) as caught:
        _module("asyncio").run(
            canary.transmit_lightning_canary(
                store,
                canary_id=receipt.canary_id,
                expected_request_sha256=receipt.request_sha256,
                approve=True,
                settings_loader=_valid_settings,
                executor=executor,
                now=_clock(AUTH_NOW_TEXT, START_NOW_TEXT),
            )
        )

    assert caught.value is error
    terminal = store.load(receipt.canary_id).terminal_event
    assert terminal is not None
    assert terminal["attempt_outcome"] == outcome_name
    assert terminal["nvidia_failure_kind"] is None
    assert terminal["transport_failure_kind"] == failure_name
    assert terminal["http_status_code"] == status_code
    assert terminal["semantic_probe_match"] is None


def test_prior_terminal_blocks_settings_and_executor(tmp_path) -> None:
    canary, store, receipt = _prepared_canary(tmp_path)
    store.append_authorized(
        receipt.canary_id,
        request_sha256=receipt.request_sha256,
        recorded_at=AUTH_NOW_TEXT,
    )
    store.append_provider_start(
        receipt.canary_id,
        request_sha256=receipt.request_sha256,
        recorded_at=START_NOW_TEXT,
    )
    store.append_terminal(
        receipt.canary_id,
        {
            "event_type": "CANARY_TERMINAL",
            "canary_id": receipt.canary_id,
            "request_sha256": receipt.request_sha256,
            "provider_id": "nvidia-api-catalog",
            "model_id": EXPECTED_MODEL_ID,
            "provider_started_at": START_NOW_TEXT,
            "provider_finished_at": FINISH_NOW_TEXT,
            "attempt_outcome": "COMPLETED",
            "nvidia_failure_kind": None,
            "transport_failure_kind": None,
            "http_status_code": 200,
            "response_headers_received": True,
            "response_body_started": True,
            "decoded_body_bytes_received": 1,
            "elapsed_ms": 10,
            "finish_reason": "stop",
            "response_id": "bounded-id",
            "prompt_tokens": 1,
            "completion_tokens": 1,
            "total_tokens": 2,
            "semantic_probe_match": True,
            "recorded_at": FINISH_NOW_TEXT,
        },
    )
    calls = {"settings": 0, "executor": 0}

    def settings_loader():
        calls["settings"] += 1
        return _valid_settings()

    async def executor(*args: object, **kwargs: object):
        calls["executor"] += 1
        return _successful_executor_result()

    with pytest.raises(ValueError):
        _module("asyncio").run(
            canary.transmit_lightning_canary(
                store,
                canary_id=receipt.canary_id,
                expected_request_sha256=receipt.request_sha256,
                approve=True,
                settings_loader=settings_loader,
                executor=executor,
                now=_fixed_now,
            )
        )

    assert calls == {"settings": 0, "executor": 0}


def test_unexpected_post_start_exception_leaves_ambiguous_start_and_blocks_retransmission(
    tmp_path,
) -> None:
    canary, store, receipt = _prepared_canary(tmp_path)
    executor_calls = 0

    async def exploding_executor(*args: object, **kwargs: object):
        nonlocal executor_calls
        executor_calls += 1
        raise RuntimeError("raw-provider-detail-must-not-be-persisted")

    with pytest.raises(RuntimeError):
        _module("asyncio").run(
            canary.transmit_lightning_canary(
                store,
                canary_id=receipt.canary_id,
                expected_request_sha256=receipt.request_sha256,
                approve=True,
                settings_loader=_valid_settings,
                executor=exploding_executor,
                now=_clock(AUTH_NOW_TEXT, START_NOW_TEXT),
            )
        )

    snapshot = store.load(receipt.canary_id)
    assert executor_calls == 1
    assert snapshot.provider_started_at == START_NOW_TEXT
    assert snapshot.terminal_event is None

    calls = {"settings": 0, "executor": 0}

    def settings_loader():
        calls["settings"] += 1
        return _valid_settings()

    async def second_executor(*args: object, **kwargs: object):
        calls["executor"] += 1
        return _successful_executor_result()

    with pytest.raises(ValueError, match="provider-start"):
        _module("asyncio").run(
            canary.transmit_lightning_canary(
                store,
                canary_id=receipt.canary_id,
                expected_request_sha256=receipt.request_sha256,
                approve=True,
                settings_loader=settings_loader,
                executor=second_executor,
                now=_fixed_now,
            )
        )

    raw_events = (
        store.root / "canaries" / receipt.canary_id / "events.jsonl"
    ).read_text(encoding="utf-8")
    assert calls == {"settings": 0, "executor": 0}
    assert "raw-provider-detail-must-not-be-persisted" not in raw_events
