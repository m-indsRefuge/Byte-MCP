# NVIDIA N05 Failure Map

This document is the living failure-engineering map for the governed NVIDIA platform in Byte-MCP.

## Scope and invariants

The NVIDIA platform has two deliberately different execution surfaces:

- `nvidia_query`: routine governed inference through friendly model aliases.
- `nvidia_review`: evidence-heavy formal review with PREPARE, exact request identity, human approval, one provider request, and append-only evidence.
- `nvidia_get_review`: provider-free local evidence retrieval.

Global invariants:

- No automatic retry.
- No automatic fallback.
- No dynamic `/v1/models` discovery in governed query or review execution.
- No arbitrary provider model IDs on public MCP surfaces.
- No provider substitution.
- Credentials are acquired only at the settings/transmit boundary.
- Prompt text, response text, credentials, authorization headers, and raw provider bodies are excluded from routine query audit records.
- A provider-started review without a trustworthy terminal event is never retransmitted automatically.
- A failure never authorizes a second provider request.

## Failure matrix

| ID | Failure boundary | Observable state | First diagnostics | Safe recovery | Do not | Coverage |
| --- | --- | --- | --- | --- | --- | --- |
| F01 | `CREDENTIAL_UNAVAILABLE` | Local failure before provider execution; `provider_started=false`. | Confirm hosted NVIDIA credential configuration through the settings boundary. | Configure/correct the hosted credential, then make a new explicit invocation. | Do not use `NGC_API_KEY` as a hosted fallback. Do not persist the credential. | `tests/nvidia/test_settings.py`, `tests/nvidia/test_query_service.py`, `tests/nvidia/test_n02_security_invariants.py` |
| F02 | `AUTHENTICATION_FAILED` | Provider rejects authentication/permission; request is rejected. | Check credential validity and account/model entitlement. | Correct authentication or entitlement, then explicitly invoke again. | Do not retry automatically. Do not expose provider prose or headers. | `tests/nvidia/test_chat_execution.py`, `tests/nvidia/test_errors_platform.py` |
| F03 | `RATE_LIMITED` | Typed rate-limit failure after one request attempt. | Confirm provider rate-limit status and request timing outside the harness. | Wait or resolve quota/rate conditions, then make a fresh explicit invocation. | Do not back off and retry inside Byte-MCP. | `tests/nvidia/test_chat_execution.py`, `tests/nvidia/test_errors_platform.py` |
| F04 | `PROVIDER_REJECTED` | Provider rejection that is not safely classified as a local validation failure. | Inspect safe status/error classification; keep raw provider prose out of logs. | Correct the request/account condition and explicitly invoke again. | Do not silently substitute a model or endpoint. | `tests/nvidia/test_chat_execution.py`, `tests/nvidia/test_chat_response.py` |
| F05 | `TRANSPORT_FAILED` / NOT_SENT | Connect or pool failure where transmission is classified `NOT_SENT`. | Inspect safe transport failure kind and network reachability. | Correct transport conditions, then start a fresh explicit invocation. | Do not auto-retry. | `tests/nvidia/test_chat_execution.py`, `tests/nvidia/test_n01_security_invariants.py` |
| F06 | `TRANSPORT_FAILED` / OUTCOME_UNKNOWN | Failure after transmission may have begun; provider outcome is ambiguous. | Inspect `ProviderAttemptOutcome` and transport observation metadata. | Query calls require a fresh explicit invocation. Formal review remains blocked by evidence/replay rules when provider start is recorded without a terminal event. | Do not replay the same formal review attempt. | `tests/nvidia/test_chat_execution.py`, `tests/nvidia/test_n02_security_invariants.py`, `tests/nvidia/test_review_service_transmit.py` |
| F07 | `RESPONSE_INVALID` | Provider started, but response structure, identity, or required content is invalid. | Check model identity, request SHA binding, payload SHA binding, and bounded response parser. | Treat result as unusable; investigate parser/provider behavior before a fresh explicit call. | Do not return partially trusted content. | `tests/nvidia/test_chat_response.py`, `tests/nvidia/test_query_service.py` |
| F08 | `RESPONSE_TOO_LARGE` | Provider response exceeds the governed query bound. | Compare response size with `MAX_QUERY_RESPONSE_CHARS`. | Tighten the request or model output expectation, then explicitly invoke again. | Do not bypass the bound or persist the oversized body in audit. | `tests/nvidia/test_query_service.py`, `tests/nvidia/test_chat_response.py` |
| F09 | `MODEL_NOT_ALLOWED` | Unknown alias or raw provider model ID rejected locally. | Check the frozen friendly-alias registry. | Use an allowed friendly alias. | Do not accept arbitrary provider IDs. | `tests/nvidia/test_models.py`, `tests/nvidia/test_query_protocol.py`, `tests/nvidia/test_n04_governed_model_selection.py` |
| F10 | `MODEL_NOT_ENABLED` | Known model is disabled for the requested surface. | Inspect governed model definition and per-surface enablement. | Enable only through a reviewed registry change and qualification cycle. | Do not override enablement from the MCP request. | `tests/nvidia/test_models.py`, `tests/nvidia/test_errors_platform.py` |
| F11 | Registry mismatch | Model registry validation or qualification fails closed. | Run registry validation and offline qualification. | Correct the frozen registry definition, then rerun offline qualification. | Do not continue with a partially valid registry. | `tests/nvidia/test_models.py`, `tests/nvidia/test_qualification.py` |
| F12 | Dynamic discovery regression | Governed execution starts consulting `/v1/models` or catalog discovery. | Run N01/platform structural invariants and N05 offline qualification. | Remove discovery from governed execution and restore the frozen registry boundary. | Do not dynamically choose production model identity. | `tests/nvidia/test_n01_security_invariants.py`, `tests/nvidia/test_platform_security_invariants.py`, `tests/nvidia/test_query_service.py` |
| F13 | Retry/fallback regression | Loop, retry, fallback, or substitution machinery appears in governed query/transport code. | Run AST-based security invariants and N05 offline qualification. | Remove the machinery; preserve one explicit attempt per invocation. | Do not mask failures with a second provider request. | `tests/nvidia/test_n01_security_invariants.py`, `tests/nvidia/test_query_service.py`, `tests/nvidia/test_platform_security_invariants.py` |
| F14 | Audit persistence failure | Query result cannot be safely audited; executor has already run at most once. | Inspect local audit path/permissions and the query audit recorder. | Repair audit persistence before the next explicit invocation. | Do not reinvoke the provider to repair an audit failure. | `tests/nvidia/test_query_audit.py`, `tests/test_audit.py` |
| F15 | Audit privacy regression | Prompt, system prompt, response, credential, or authorization material appears in audit. | Inspect raw audit JSONL and metadata schema. | Remove unsafe fields and rotate any compromised secret if applicable. | Do not store raw query/response content in routine query audit. | `tests/nvidia/test_query_audit.py`, `tests/nvidia/test_n02_security_invariants.py` |
| F16 | Review evidence corruption | Manifest/event/evidence content is malformed, missing, or hash-inconsistent. | Load review evidence locally and verify immutable identities/hashes. | Repair only through a new governed review lifecycle when necessary; preserve original evidence. | Do not rewrite append-only evidence to make it pass. | `tests/nvidia/test_review_evidence.py`, `tests/nvidia/test_review_service_prepare.py` |
| F17 | Ambiguous review provider start | Provider start exists without a trustworthy terminal event. | Inspect review events for `provider_started_at` and terminal outcome. | Investigate manually; create a new review only under a new explicit lifecycle if justified. | Do not retransmit the same review attempt. | `tests/nvidia/test_n02_security_invariants.py`, `tests/nvidia/test_review_service_transmit.py` |
| F18 | Review request/manifest mismatch | Approval hash, manifest identity, request body, model identity, or packet hash does not match immutable evidence. | Compare expected request SHA-256 and persisted manifest/request identities. | Prepare a new correct review if the intended request changed. | Do not mutate or approve around a hash mismatch. | `tests/nvidia/test_review_protocol.py`, `tests/nvidia/test_review_service_transmit.py`, `tests/nvidia/test_n04_immutable_model_identity.py` |
| F19 | Credential-boundary regression | Code outside settings/transmit starts naming or loading the hosted credential. | Run N02 credential-access invariant. | Move credential acquisition back to the settings/transmit boundary. | Do not inspect the credential in readiness, PREPARE, retrieval, or qualification paths. | `tests/nvidia/test_n02_security_invariants.py`, `tests/nvidia/test_qualification.py` |
| F20 | MCP surface regression | Extra NVIDIA tools, provider controls, static NVIDIA imports, or raw provider IDs appear publicly. | Inspect exact MCP tool set/signatures and server import AST. | Restore the three-tool governed surface and lazy import boundary. | Do not expose endpoint, API key, retry, fallback, temperature, token, seed, or raw model-ID controls. | `tests/nvidia/test_query_mcp.py`, `tests/nvidia/test_review_mcp.py`, `tests/nvidia/test_platform_security_invariants.py`, `tests/test_nvidia_runtime_integration.py` |

## Failure propagation rules

Local validation failures must terminate before credential loading and before any provider attempt. Provider and transport failures must retain the safest available attempt classification without inventing certainty. Routine query audit records only safe operational metadata. Formal review failures are additionally constrained by immutable evidence and replay protection.

A query failure never causes a second provider call inside the same invocation. A review failure never consumes a second provider request unless a completely new, explicitly authorized review lifecycle is created under the review contract.

## First-response diagnostic order

1. Confirm whether failure was local or provider-started.
2. Confirm friendly model alias and governed model maturity.
3. Confirm request identity/hash when available.
4. Check typed failure code.
5. Check safe transport attempt outcome when applicable.
6. Check audit/evidence persistence.
7. For formal review, inspect provider-start and terminal evidence before considering any further action.
8. Run `scripts/nvidia_n05_offline_qualification.py` after code changes affecting NVIDIA governance.

## Recovery principles

- Prefer local correction over provider experimentation.
- Treat `OUTCOME_UNKNOWN` as ambiguous, not as a failed request that can safely be replayed.
- Preserve append-only evidence.
- Never solve a failure by weakening model governance, credential isolation, response bounds, audit privacy, or exact request identity.
- Any future automatic retry, fallback, model routing, or discovery feature requires a new design and explicit approval; it is not a repair.
