# NVIDIA-03 Routine Code Review Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a bounded NVIDIA routine code-review MCP capability that prepares immutable review packets, requires exact-hash approval, performs at most one hosted NVIDIA request per review identity, and exposes only validated bounded findings.

**Architecture:** NVIDIA-03 remains NVIDIA-owned and does not import OX or Wolfram. It adds a local allow-listed repository registry, deterministic Git-object packet builder, strict JSON result parser, durable append-only review evidence, a narrow prepare/transmit/read service, and two MCP tools. Network execution must reuse `execute_prepared_nvidia_chat()`; no alternate HTTP client, retry, fallback, model discovery call, continuation, or automatic provider routing is introduced.

**Tech Stack:** Python 3.12, stdlib JSON/hashlib/pathlib, Dulwich, existing Byte-MCP provider runtime and NVIDIA hosted chat adapter, FastMCP, pytest, Ruff.

**Spec:** `docs/superpowers/specs/2026-09-10-nvidia-provider-n03-routine-code-review-design.md`

## Global Constraints

- Fixed model: `nvidia/nemotron-3.5-lightning-30b-a3b`.
- Fixed endpoint: `POST https://integrate.api.nvidia.com/v1/chat/completions` through the existing prepared-request transport.
- Fixed request controls: `temperature=0.2`, `top_p=0.95`, `max_tokens=4096`, `n=1`, `stream=false`, `chat_template_kwargs.enable_thinking=false`, no reasoning budget.
- Objective maximum: 4,096 UTF-8 bytes.
- Verification maximum: 32 records; `stdout` and `stderr` each maximum 16,384 characters per record.
- Changed target files maximum: 200; individual changed target text file maximum: 524,288 bytes.
- Serialized review packet maximum: 3,145,728 bytes.
- Findings maximum: 50; summary maximum: 4,000 characters; finding path 512; title 200; explanation 4,000; recommendation 4,000; line is null or 1..2,147,483,647.
- Exact 40-hex base and target Git commit SHAs only.
- Review evidence is outside Git under the NVIDIA evidence root in a `reviews/NVR-XXXXXX` namespace.
- Credentials never enter manifests, request hashes, result hashes, reprs, logs, MCP outputs, or Git-tracked files.
- Prepare and read paths must not load `NVIDIA_API_KEY`.
- Once durable `PROVIDER_START` exists, that review identity is permanently consumed.
- No retry flag, retry path, fallback, replay, continuation, revalidation, model substitution, `/v1/models` call, OX call, Wolfram call, or other provider call.
- No live provider/model requests are permitted during Tasks 1-9 offline implementation and qualification.

---

### Task 1: NVIDIA Review Repository Registry and Exact Git Access

**Files:**
- Create: `src/byte_mcp/nvidia/review_registry.py`
- Create: `tests/nvidia/test_review_registry.py`

**Interfaces:**
- Produces `NvidiaReviewSubsystemDefinition`, `NvidiaReviewRepositoryDefinition`, `NvidiaReviewRepositoryRegistry.load(path: Path)`, and `NvidiaReviewGitRepository`.
- `NvidiaReviewGitRepository` exposes `resolve_commit(sha: str)`, `diff(base, target) -> bytes`, `changed_paths(base, target) -> tuple[str, ...]`, and `read_target_text(commit, path) -> bytes`.
- Registry JSON is version 1 and maps safe aliases to an absolute existing Git repository plus subsystem `source_roots`, `test_roots`, `boundary_files`, and `context_files`.

- [ ] **Step 1: Write RED tests for registry and Git boundaries.**

```python
def test_registry_requires_exact_absolute_git_repository(tmp_path):
    path = tmp_path / "repos.json"
    path.write_text('{"version":1,"repositories":{}}', encoding="utf-8")
    with pytest.raises(ValueError):
        NvidiaReviewRepositoryRegistry.load(path)


def test_resolve_commit_requires_exact_40_hex(repo_fixture):
    repository = NvidiaReviewGitRepository.open(repo_fixture.definition)
    with pytest.raises(ValueError):
        repository.resolve_commit("HEAD")
```

Also cover traversal, absolute/drive paths, symlink/submodule/unsafe entry rejection, changed-path calculation, deleted-path representation, and target-side regular-file reads.

- [ ] **Step 2: Run the focused RED.**

Run: `python -m pytest tests/nvidia/test_review_registry.py -q`
Expected: FAIL because `byte_mcp.nvidia.review_registry` does not exist.

- [ ] **Step 3: Implement the minimal isolated registry and Git reader.**

Use Dulwich directly. Do not import `byte_mcp.ox.*`. Validate aliases with `^[a-z][a-z0-9_-]{0,63}$`, commits with `^[0-9a-f]{40}$`, reject backslashes/absolute paths/drive prefixes/dot segments, and accept only regular Git file modes `100644`/`100755` for target artifacts.

- [ ] **Step 4: Run GREEN and static checks.**

Run: `python -m pytest tests/nvidia/test_review_registry.py -q && python -m ruff check src/byte_mcp/nvidia/review_registry.py tests/nvidia/test_review_registry.py`
Expected: PASS.

- [ ] **Step 5: Commit.**

```bash
git add src/byte_mcp/nvidia/review_registry.py tests/nvidia/test_review_registry.py
git commit -m "feat: add NVIDIA review repository registry"
```

---

### Task 2: Deterministic Review Packet and Manifest

**Files:**
- Create: `src/byte_mcp/nvidia/review_packet.py`
- Create: `tests/nvidia/test_review_packet.py`

**Interfaces:**
- Consumes `NvidiaReviewGitRepository` and `NvidiaReviewSubsystemDefinition` from Task 1.
- Produces immutable `NvidiaReviewArtifact`, `NvidiaReviewManifestEntry`, `NvidiaReviewManifest`, and `PreparedNvidiaReviewPacket`.
- Produces `prepare_review_packet(repository, subsystem, base_commit, target_commit, objective, verification) -> PreparedNvidiaReviewPacket`.

- [ ] **Step 1: Write RED tests for deterministic packet identity.**

```python
def test_packet_is_deterministic(review_repo, subsystem, verification):
    first = prepare_review_packet(review_repo, subsystem, BASE, TARGET, "Review regression risk", verification)
    second = prepare_review_packet(review_repo, subsystem, BASE, TARGET, "Review regression risk", verification)
    assert first.serialized_packet == second.serialized_packet
    assert first.manifest.manifest_sha256 == second.manifest.manifest_sha256
```

Cover exact base/target binding, objective byte limit, 32-record verification limit, stdout/stderr bounds, changed-file limit, 524,288-byte file limit, deleted files omitted from target artifacts, UTF-8-only target text, 3,145,728-byte packet limit, per-artifact hashes, and changed files constrained to configured subsystem scope.

- [ ] **Step 2: Run RED.**

Run: `python -m pytest tests/nvidia/test_review_packet.py -q`
Expected: FAIL because packet types/functions do not exist.

- [ ] **Step 3: Implement canonical packet construction.**

Canonical JSON must use `sort_keys=True`, `separators=(",", ":")`, `ensure_ascii=False`, `allow_nan=False`. Verification records must require exactly `id`, `kind`, `command`, `exit_code`, `stdout`, `stderr`, `recorded_at`, and `provenance`; add each record's SHA-256 to the packet. Manifest entries bind logical path, category, byte length, and SHA-256. Include diff plus target-side changed text artifacts only.

- [ ] **Step 4: Run GREEN and static checks.**

Run: `python -m pytest tests/nvidia/test_review_packet.py -q && python -m ruff check src/byte_mcp/nvidia/review_packet.py tests/nvidia/test_review_packet.py`
Expected: PASS.

- [ ] **Step 5: Commit.**

```bash
git add src/byte_mcp/nvidia/review_packet.py tests/nvidia/test_review_packet.py
git commit -m "feat: build deterministic NVIDIA review packets"
```

---

### Task 3: Versioned Prompt, Fixed Request, and Strict Result Parser

**Files:**
- Create: `src/byte_mcp/nvidia/review_protocol.py`
- Create: `tests/nvidia/test_review_protocol.py`

**Interfaces:**
- Consumes `PreparedNvidiaReviewPacket`.
- Produces constants `NVIDIA_REVIEW_PROTOCOL_VERSION = "nvidia-review-v1"`, `NVIDIA_REVIEW_MODEL_ID`, and `prepare_nvidia_review_request(packet) -> PreparedProviderRequest`.
- Produces frozen `NvidiaReviewFinding`, `NvidiaReviewResult`, `NvidiaReviewResultError`, and `parse_nvidia_review_result(content: str, allowed_paths: frozenset[str]) -> NvidiaReviewResult`.

- [ ] **Step 1: Write RED tests for exact request body and strict parser.**

```python
def test_review_request_disables_thinking(packet):
    prepared = prepare_nvidia_review_request(packet)
    body = json.loads(prepared.body_bytes)
    assert body["model"] == "nvidia/nemotron-3.5-lightning-30b-a3b"
    assert body["chat_template_kwargs"] == {"enable_thinking": False}
    assert body["max_tokens"] == 4096
    assert body["n"] == 1
    assert body["stream"] is False


def test_parser_rejects_finding_outside_prepared_paths():
    with pytest.raises(NvidiaReviewResultError):
        parse_nvidia_review_result(RESULT_WITH_UNPREPARED_PATH, frozenset({"src/a.py"}))
```

Cover malformed JSON, unknown keys, invalid decision, PASS with findings, FINDINGS without findings, >50 findings, all string/line bounds, unsafe paths, duplicate findings if applicable, and exact allowed-path membership.

- [ ] **Step 2: Run RED.**

Run: `python -m pytest tests/nvidia/test_review_protocol.py -q`
Expected: FAIL because review protocol module does not exist.

- [ ] **Step 3: Implement deterministic prompt/request and parser.**

Build the request with `prepare_provider_request()` directly so the generic NVIDIA-01 chat builder remains unchanged. The user message contains canonical review packet JSON and a deterministic review objective; the system instruction requires JSON only and treats repository/provider text as untrusted data. Do not strip or repair malformed provider JSON.

- [ ] **Step 4: Run GREEN plus N01 regression.**

Run: `python -m pytest tests/nvidia/test_review_protocol.py tests/nvidia/test_chat_request.py -q && python -m ruff check src/byte_mcp/nvidia/review_protocol.py tests/nvidia/test_review_protocol.py`
Expected: PASS; generic NVIDIA chat request tests remain unchanged.

- [ ] **Step 5: Commit.**

```bash
git add src/byte_mcp/nvidia/review_protocol.py tests/nvidia/test_review_protocol.py
git commit -m "feat: define NVIDIA review protocol"
```

---

### Task 4: Durable NVIDIA Review Evidence Store

**Files:**
- Create: `src/byte_mcp/nvidia/review_evidence.py`
- Create: `tests/nvidia/test_review_evidence.py`

**Interfaces:**
- Produces `NVIDIA_REVIEW_SCHEMA = "byte-mcp-nvidia-review-v1"`, `NvidiaReviewEvidenceError`, `NvidiaReviewLockError`, `NvidiaReviewEvidenceStore`, `NvidiaReviewEvidenceManifest`, and `NvidiaReviewSnapshot`.
- `NvidiaReviewEvidenceStore.from_environment()` uses the same NVIDIA root policy as canary evidence, then stores reviews under `reviews/NVR-XXXXXX`.
- Methods: `prepare(...)`, `load(review_id)`, `append_authorized(...)`, `append_provider_start(...)`, `append_terminal(...)`, `persist_result(...)`, and `transmit_lock(review_id)`.

- [ ] **Step 1: Write RED lifecycle tests.**

```python
def test_review_ids_are_monotonic(tmp_path, prepared_packet, prepared_request):
    store = NvidiaReviewEvidenceStore(tmp_path)
    first = store.prepare(prepared_packet, prepared_request, prepared_at=TS)
    second = store.prepare(prepared_packet, prepared_request, prepared_at=TS2)
    assert first.review_id == "NVR-000001"
    assert second.review_id == "NVR-000002"


def test_provider_start_requires_prior_authorization(store, prepared_review):
    with pytest.raises(NvidiaReviewEvidenceError):
        store.append_provider_start(prepared_review.review_id, request_sha256=prepared_review.request_sha256, recorded_at=TS)
```

Cover immutable request/packet/manifest files, newline-terminated JSONL, malformed/truncated event rejection, exact request and packet hash reconstruction, event ordering, duplicate authorization/start/terminal rejection, event-after-terminal rejection, concurrent lock exclusion, result written once only, and no credential material in repr/evidence.

- [ ] **Step 2: Run RED.**

Run: `python -m pytest tests/nvidia/test_review_evidence.py -q`
Expected: FAIL because review evidence module does not exist.

- [ ] **Step 3: Implement append-only review evidence.**

Persist `review-packet.json`, `request-body.bin`, `manifest.json`, `events.jsonl`, and optional bounded `result.json`. Use exclusive file creation and fsync patterns already proven by canary evidence, but do not import the canary module as a service dependency. Validate request integrity with `validate_prepared_provider_request_integrity()`.

- [ ] **Step 4: Run GREEN and static checks.**

Run: `python -m pytest tests/nvidia/test_review_evidence.py -q && python -m ruff check src/byte_mcp/nvidia/review_evidence.py tests/nvidia/test_review_evidence.py`
Expected: PASS.

- [ ] **Step 5: Commit.**

```bash
git add src/byte_mcp/nvidia/review_evidence.py tests/nvidia/test_review_evidence.py
git commit -m "feat: add durable NVIDIA review evidence"
```

---

### Task 5: Provider-Free Prepare and Read Service

**Files:**
- Create: `src/byte_mcp/nvidia/review_service.py`
- Create: `src/byte_mcp/nvidia/review_settings.py`
- Create: `tests/nvidia/test_review_service_prepare.py`

**Interfaces:**
- `NvidiaReviewSettings.load(repo_root: Path)` resolves `BYTE_MCP_NVIDIA_REVIEW_REPOSITORIES_FILE`; when unset, default to `<NVIDIA evidence root>/review-repositories.json`. It contains no API key field.
- `NvidiaReviewService.initialize(repo_root: Path, evidence_store=None)` validates local review configuration only.
- `prepare_review(repository, subsystem, target_commit, base_commit, objective, verification) -> dict[str, object]`.
- `get_review(review_id, view="summary") -> dict[str, object]` with `summary`, `findings`, `attempt`, `manifest`.

- [ ] **Step 1: Write RED tests proving prepare/read are credential-blind.**

```python
def test_prepare_does_not_load_hosted_settings(monkeypatch, service):
    monkeypatch.setattr(NvidiaHostedSettings, "load", lambda: (_ for _ in ()).throw(AssertionError()))
    receipt = service.prepare_review(...)
    assert receipt["review_id"] == "NVR-000001"


def test_get_review_is_provider_free(monkeypatch, service, prepared_review):
    monkeypatch.setattr("byte_mcp.nvidia.review_service.execute_prepared_nvidia_chat", lambda *a, **k: (_ for _ in ()).throw(AssertionError()))
    assert service.get_review(prepared_review.review_id)["review_id"] == prepared_review.review_id
```

Cover allow-list failures, exact commit failures, invalid mode, bounded identity-only prepare output, no raw request/provider result leakage, and manifest/findings views.

- [ ] **Step 2: Run RED.**

Run: `python -m pytest tests/nvidia/test_review_service_prepare.py -q`
Expected: FAIL because service/settings do not exist.

- [ ] **Step 3: Implement provider-free service paths.**

Prepare loads only local registry/evidence, builds packet/request, persists it, and returns bounded identity metadata. `findings` is empty before a valid terminal result. `attempt` exposes bounded lifecycle/transport state only.

- [ ] **Step 4: Run GREEN and static checks.**

Run: `python -m pytest tests/nvidia/test_review_service_prepare.py -q && python -m ruff check src/byte_mcp/nvidia/review_service.py src/byte_mcp/nvidia/review_settings.py tests/nvidia/test_review_service_prepare.py`
Expected: PASS.

- [ ] **Step 5: Commit.**

```bash
git add src/byte_mcp/nvidia/review_service.py src/byte_mcp/nvidia/review_settings.py tests/nvidia/test_review_service_prepare.py
git commit -m "feat: prepare NVIDIA reviews provider-free"
```

---

### Task 6: Exactly-Once Approval, Transmission, and Terminalization

**Files:**
- Modify: `src/byte_mcp/nvidia/review_service.py`
- Create: `tests/nvidia/test_review_service_transmit.py`

**Interfaces:**
- Adds async `transmit_review(review_id: str, expected_request_sha256: str, approve: bool, settings_loader=NvidiaHostedSettings.load, executor=execute_prepared_nvidia_chat, now=...) -> dict[str, object]`.
- Executor is invoked at most once after durable authorization and provider-start evidence.

- [ ] **Step 1: Write RED exactly-once tests with a fake executor.**

```python
@pytest.mark.asyncio
async def test_provider_start_is_durable_before_executor(service, store, prepared_review):
    async def fake_executor(prepared, context, settings):
        assert store.load(prepared_review.review_id).provider_started_at == context.provider_started_at
        return synthetic_chat_result(prepared, context)
    result = await service.transmit_review(prepared_review.review_id, prepared_review.request_sha256, True, executor=fake_executor, settings_loader=fake_settings)
    assert result["attempt_outcome"] == "COMPLETED"
```

Cover approve must be exactly true, wrong hash zero executor, absent key zero provider-start, malformed bearer credential zero provider-start, concurrent transmit exclusion, provider-start blocks all retransmission, NVIDIA errors and provider transport errors terminalize once, arbitrary post-start exception leaves start-only ambiguity, valid JSON persists bounded result, invalid JSON terminalizes `COMPLETED` with `review_result_status="INVALID"`, and no retry/fallback invocation exists.

- [ ] **Step 2: Run RED.**

Run: `python -m pytest tests/nvidia/test_review_service_transmit.py -q`
Expected: FAIL because transmit path does not exist.

- [ ] **Step 3: Implement minimal transmission path.**

Inside `transmit_lock`: load immutable snapshot; validate approval/hash/unconsumed state; load `NvidiaHostedSettings`; validate bearer credential before appending authorization/start; reconstruct and integrity-check exact prepared request bytes; append authorization if absent; append `PROVIDER_START`; call `execute_prepared_nvidia_chat()` exactly once. Terminalize only bounded known NVIDIA/transport outcomes. Parse successful content with the strict parser and persist only bounded validated result or safe invalid-result classification.

- [ ] **Step 4: Run GREEN plus canary transport regression.**

Run: `python -m pytest tests/nvidia/test_review_service_transmit.py tests/nvidia/test_canary.py tests/nvidia/test_chat_execution.py -q && python -m ruff check src/byte_mcp/nvidia/review_service.py tests/nvidia/test_review_service_transmit.py`
Expected: PASS.

- [ ] **Step 5: Commit.**

```bash
git add src/byte_mcp/nvidia/review_service.py tests/nvidia/test_review_service_transmit.py
git commit -m "feat: transmit NVIDIA reviews exactly once"
```

---

### Task 7: MCP Tool Surface and Lazy NVIDIA Review Runtime

**Files:**
- Create: `src/byte_mcp/nvidia/review_runtime.py`
- Modify: `src/byte_mcp/server.py`
- Modify: `src/byte_mcp/nvidia/__init__.py`
- Create: `tests/nvidia/test_review_mcp.py`
- Modify: `tests/test_server.py`

**Interfaces:**
- `NvidiaReviewRuntime.load(repo_root: Path)` fail-isolates local review misconfiguration from server startup.
- Server tools: `nvidia_review(...)` and `nvidia_get_review(review_id, view="summary")`.
- `nvidia_review` prepare mode accepts only the six scoped prepare fields; approval mode accepts only `review_id`, `expected_request_sha256`, and `approve=True`.

- [ ] **Step 1: Write RED tool-mode tests.**

```python
@pytest.mark.asyncio
async def test_nvidia_review_prepare_mode_rejects_approval_fields(monkeypatch):
    with pytest.raises(ValueError):
        await server.nvidia_review(repository="byte-mcp", subsystem="nvidia", target_commit=TARGET, base_commit=BASE, objective="x", verification=[], approve=True)


def test_nvidia_get_review_rejects_unknown_view():
    with pytest.raises(ValueError):
        server.nvidia_get_review("NVR-000001", view="raw")
```

Also prove main startup does not require an NVIDIA key or review registry, `nvidia_get_review` is read-only, and tool signatures contain no retry/model/endpoint/prompt/key override.

- [ ] **Step 2: Run RED.**

Run: `python -m pytest tests/nvidia/test_review_mcp.py tests/test_server.py -q`
Expected: FAIL because MCP tools/runtime do not exist.

- [ ] **Step 3: Implement lazy runtime and two tools.**

Add `NVIDIA_EXTERNAL` tool annotations (`readOnlyHint=False`, `destructiveHint=False`, `idempotentHint=False`, `openWorldHint=True`) and use `READ_ONLY` for `nvidia_get_review`. Do not initialize NVIDIA review runtime in `main()`; load lazily on first NVIDIA review tool use so configuration cannot block core/OX/Wolfram startup.

- [ ] **Step 4: Run GREEN and static checks.**

Run: `python -m pytest tests/nvidia/test_review_mcp.py tests/test_server.py -q && python -m ruff check src/byte_mcp/server.py src/byte_mcp/nvidia/review_runtime.py src/byte_mcp/nvidia/__init__.py tests/nvidia/test_review_mcp.py tests/test_server.py`
Expected: PASS.

- [ ] **Step 5: Commit.**

```bash
git add src/byte_mcp/server.py src/byte_mcp/nvidia/__init__.py src/byte_mcp/nvidia/review_runtime.py tests/nvidia/test_review_mcp.py tests/test_server.py
git commit -m "feat: expose NVIDIA routine review tools"
```

---

### Task 8: Model Qualification State and Security/Isolation Freeze

**Files:**
- Modify: `src/byte_mcp/nvidia/registry.py`
- Modify: `tests/nvidia/test_registry.py`
- Create: `tests/nvidia/test_n03_security_invariants.py`

**Interfaces:**
- Lightning candidate becomes `ModelLifecycleState.QUALIFIED` for the already proven hosted-chat path; no model becomes `ENABLED` in N03 offline implementation.
- Security test file statically and behaviorally freezes isolation and no-retry/no-fallback properties.

- [ ] **Step 1: Write RED lifecycle/security tests.**

```python
def test_lightning_is_qualified_but_not_enabled():
    candidate = next(c for c in initial_qualification_candidates() if c.profile.model_id == NVIDIA_REVIEW_MODEL_ID)
    assert candidate.profile.qualification_state is ModelLifecycleState.QUALIFIED
    assert candidate.profile.qualification_state is not ModelLifecycleState.ENABLED
```

Security invariants must inspect NVIDIA review modules and assert no `byte_mcp.ox`, `byte_mcp.wolfram`, retry/backoff/sleep/fallback/replay/catalog calls, `/v1/models`, dynamic model override, or credential access outside the transmit path. Also prove OX/Wolfram modules do not import NVIDIA review modules.

- [ ] **Step 2: Run RED.**

Run: `python -m pytest tests/nvidia/test_registry.py tests/nvidia/test_n03_security_invariants.py -q`
Expected: registry lifecycle assertion fails until Lightning is promoted to QUALIFIED; all security assertions must then pass without weakening earlier N01/N02 invariants.

- [ ] **Step 3: Apply the minimal lifecycle change and satisfy invariant tests.**

Only Lightning receives `QUALIFIED`; all other provisional candidates remain `DISCOVERED`. Do not add automatic routing or capability enablement.

- [ ] **Step 4: Run NVIDIA security regression.**

Run: `python -m pytest tests/nvidia/test_registry.py tests/nvidia/test_n01_security_invariants.py tests/nvidia/test_n02_security_invariants.py tests/nvidia/test_n03_security_invariants.py -q && python -m ruff check src/byte_mcp/nvidia tests/nvidia`
Expected: PASS.

- [ ] **Step 5: Commit.**

```bash
git add src/byte_mcp/nvidia/registry.py tests/nvidia/test_registry.py tests/nvidia/test_n03_security_invariants.py
git commit -m "test: freeze NVIDIA-03 review invariants"
```

---

### Task 9: Full Offline Qualification and Live-Review Hard Stop

**Files:**
- No production changes expected.
- If a qualification-only document is needed, create `docs/superpowers/plans/2026-09-10-nvidia-provider-n03-offline-qualification.md` containing only exact-head verification evidence and no credentials.

**Interfaces:**
- Produces an exact offline-qualified N03 commit SHA.
- Does not create or transmit a real `NVR` review during repository CI.

- [ ] **Step 1: Run focused compilation and NVIDIA review tests.**

Run: `python -m compileall -q src tests && python -m pytest tests/nvidia/test_review_registry.py tests/nvidia/test_review_packet.py tests/nvidia/test_review_protocol.py tests/nvidia/test_review_evidence.py tests/nvidia/test_review_service_prepare.py tests/nvidia/test_review_service_transmit.py tests/nvidia/test_review_mcp.py tests/nvidia/test_n03_security_invariants.py -q`
Expected: PASS.

- [ ] **Step 2: Run all NVIDIA/provider regressions.**

Run: `python -m pytest tests/nvidia tests/providers -q`
Expected: PASS.

- [ ] **Step 3: Run full repository quality gates.**

Run: `python -m ruff check . && python -m pytest && git diff --check`
Expected: PASS on Linux and Windows CI; existing launcher jobs remain green.

- [ ] **Step 4: Verify provider boundary is sealed.**

Run: `python -c "import os; assert not os.getenv('NVIDIA_API_KEY'); print('NVIDIA_API_KEY=UNSET')"`
Expected: `NVIDIA_API_KEY=UNSET`. Confirm workflow contains zero NVIDIA/OX/Wolfram/other live calls by construction.

- [ ] **Step 5: Record exact qualified identity.**

Capture `git rev-parse HEAD`, branch name, full CI run/job conclusions, test count, and changed-file scope relative to `8ce92056cdfe8412cd9856eca32fb2ddacf52147`. Do not claim `ENABLED`; status is `NVIDIA-03 OFFLINE_QUALIFIED` only.

- [ ] **Step 6: Stop at the live-review boundary.**

After offline qualification, a separate provider-free local operation may create the first real `NVR-000001` using the operator's local allow-list registry and evidence root. That operation must expose the exact `review_id` and `request_sha256` and hard-stop. A live NVIDIA review requires a new explicit authorization bound to both values.

---

## Self-Review

- Spec coverage: Tasks 1-9 cover repository allow-listing, deterministic Git-object packet construction, all frozen limits, fixed Lightning request controls, strict result parsing, durable evidence, exactly-once transmission, MCP mode validation, model lifecycle, provider isolation, cross-platform regression, and the live authorization boundary.
- Placeholder scan: no deferred implementation placeholders remain; every production interface used by a later task is defined in an earlier task or by an existing qualified Byte-MCP interface.
- Type consistency: `NvidiaReviewRepositoryRegistry`, `NvidiaReviewGitRepository`, `PreparedNvidiaReviewPacket`, `NvidiaReviewEvidenceStore`, `NvidiaReviewService`, and `NvidiaReviewRuntime` names are consistent across consuming tasks.
- Scope: OX and Wolfram remain unchanged; automatic routing and provider fallback are intentionally deferred beyond NVIDIA-03.
