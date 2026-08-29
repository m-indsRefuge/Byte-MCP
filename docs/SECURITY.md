# Security

Byte-MCP contains two separately governed capability boundaries:

1. the accepted V1/V1.1 local read-only filesystem boundary; and
2. the optional OX external-validation boundary on the `build/byte-mcp-ox-validation-v1` branch.

The OX capability does **not** change the filesystem authority of the original four core tools. It adds a narrowly fixed outbound review path and append-only local review evidence under its own contract.

## Default-denied material

The core implementation blocks common secret-bearing names and locations, including:

- `.env`
- `.git`
- `.ssh`
- `.gnupg`
- `AppData`
- credential or secret directories
- files whose stem is `secret`, `secrets`, `credential`, or `credentials`
- private-key and password-vault suffixes, including when they occur inside a multi-suffix filename

Examples such as `secrets.json`, `credentials.yaml`, and `database.key.bak` are denied. Similar non-secret names such as `secretary.txt` are not denied merely because they contain a denied word as a substring.

The policy is intentionally conservative and can be extended only through a new-version security review.

The per-component link/junction checks are defense-in-depth. The authoritative containment boundary remains strict path resolution followed by `relative_to()` against the canonical approved root.

An approved root itself is resolved to its canonical target when configuration is loaded. Links or junctions encountered beneath that root are not traversed.

## Prompt injection and untrusted content

Text found inside a retrieved file or OX review bundle must be treated as untrusted content. It must never override the operator's request, Byte-MCP's tool contract, the OX protocol boundary, or higher-level safety rules.

OX provider output is also untrusted data. Provider responses may be recorded and parsed as review evidence, but they do not become executable instructions. The OX provider is not given tools, shell access, filesystem access, or function-calling authority through Byte-MCP.

## Core network boundary

Byte-MCP explicitly binds to a loopback host. Supported core host values are:

- `127.0.0.1`
- `localhost`
- `::1`

The default endpoint is:

```text
http://127.0.0.1:8000/mcp
```

The core server rejects non-loopback values such as `0.0.0.0`. Do not expose the port through a router, public firewall rule, or unauthenticated generic tunnel.

The resumed ChatGPT validation uses OpenAI Secure MCP Tunnel while retaining the loopback-only Byte-MCP listener. The tunnel client is an outbound transport layer; it does not expand Byte-MCP's filesystem authority.

Core runtime configuration environment variables:

```text
BYTE_MCP_HOST
BYTE_MCP_PORT
BYTE_MCP_TRANSPORT
BYTE_MCP_ROOTS_FILE
BYTE_MCP_AUDIT_FILE
BYTE_MCP_MAX_FILE_BYTES
BYTE_MCP_MAX_RESPONSE_CHARS
BYTE_MCP_MAX_SEARCH_FILES
BYTE_MCP_CONTENT_SEARCH_MAX_BYTES
```

The core server supports only the `streamable-http` transport.

## MCP response boundary

Core MCP-facing responses must not expose the backing local absolute filesystem path.

The public addressing contract is:

- approved root alias;
- relative path within that approved root;
- opaque fetch reference where applicable.

`list_roots` returns aliases only. Search and fetch metadata return relative paths and do not include `absolute_path`.

Opaque references are identifiers, not authentication tokens and not a security boundary. They are deliberately decodable. Every decoded root/path pair is passed back through the approved-root and containment checks before a file is accessed.

This prevents a remote MCP caller from learning Windows user-profile or machine-specific path details that are unnecessary to use the service while ensuring a forged reference cannot bypass filesystem authority.

## File and extraction limits

`fetch` enforces `BYTE_MCP_MAX_FILE_BYTES` before extraction and raises a `LimitExceededError` when the configured ceiling is exceeded.

Content search separately enforces `BYTE_MCP_CONTENT_SEARCH_MAX_BYTES` before extracting a candidate file. The extractor also has its own hard input ceiling as defense-in-depth so direct internal use cannot accidentally perform unbounded reads.

Response text remains bounded by the configured response-character limit. When a client requests fewer than the V1 minimum, `fetch` reports the actual `max_chars_applied` value in its response.

Malformed or encrypted document-library failures are normalized at the service boundary. A corrupt candidate encountered during content search is treated as a per-file miss so one bad document does not abort the entire search. A corrupt file requested directly through `fetch` returns a Byte-MCP domain error rather than a raw third-party exception.

## Core audit

Allowed, denied, and unexpected-error outcomes are appended to the configured audit ledger.

The core audit ledger records operation metadata but does not record fetched file contents. Search terms and opaque file references are represented by SHA-256 fingerprints and lengths rather than raw values. Denied operations include a bounded error type and message so the security boundary can be reviewed without storing requested file content.

Audit persistence is fail-closed. If Byte-MCP cannot serialize, create, open, or append the configured audit ledger, the operation result is not returned to the client and a Byte-MCP `AuditError` is raised. This is deliberate: an access that cannot be durably recorded is not treated as an accepted access.

`AuditLog` uses an in-process lock and is therefore single-process by contract. Multiple Byte-MCP processes must use distinct audit files. Audit rotation and a dedicated audit reader are deferred capabilities; operators should monitor ledger size. A future reader must tolerate and count malformed or torn JSONL lines rather than failing the whole ledger.

## Runtime layout

The core default configuration paths are derived from the source/repository layout. The supported deployment model is therefore the reviewed repository/editable-install launcher. A standalone wheel installation with unrelated filesystem layout is not yet a supported deployment contract and would require explicit configuration-path design and validation.

## Remote root boundary

The accepted ChatGPT tunnel deployment is deliberately restricted to approved roots rather than a drive root, entire user profile, or arbitrary absolute paths.

The `projects` profile does not grant arbitrary absolute-path access. All requests remain constrained beneath the configured project directory and are still subject to secret-name, traversal, symlink, junction, file-type, size, and response limits.

## Secure tunnel boundary

OpenAI Secure MCP Tunnel is the selected transport for the ChatGPT integration.

Required tunnel properties:

- Byte-MCP remains on loopback;
- the tunnel client connects outbound;
- no router port forwarding is used;
- no public inbound Windows Firewall rule is added;
- the tunnel runtime uses a restricted Runtime API key with Tunnels **Read** + **Use** only;
- runtime credentials are never stored in Git or pasted into chat;
- the tunnel runtime points only to the reviewed local MCP endpoint.

Tunnel runtime permissions are transport permissions. They do not authorize filesystem writes or additional Byte-MCP capabilities.

The earlier Cloudflare Quick Tunnel experiment is historical evidence only and is not an accepted final transport.

## ChatGPT deployment boundary

The original core profile exposes exactly the four accepted read-only filesystem tools:

- `list_roots`
- `list_directory`
- `search`
- `fetch`

The integrated OX branch additionally exposes four separately annotated OX tools:

- `ox_review`
- `ox_continue`
- `ox_revalidate`
- `ox_get_review`

The three OX tools capable of external action are intentionally **not** classified as read-only or idempotent at the MCP system level. `ox_get_review` is local/read-only. The reviewed repository itself remains read-only throughout all four OX operations.

## OX external-validation boundary

OX is an optional, fixed-purpose validation capability. It is not a general HTTP client and does not grant OX filesystem or execution authority.

The only supported outbound provider route is:

```text
Byte-MCP
  -> OXReviewService
  -> OXClient
  -> https://ai-gateway.vercel.sh/v1/chat/completions
  -> provider pin: zai
  -> model: zai/glm-5.3-flash
```

The V1 OX client uses non-streaming HTTPS, certificate verification, disabled redirects, a fixed gateway URL, a fixed model, and a fixed Z.AI provider pin. There is no caller-supplied base URL, model selection, arbitrary provider routing, or automatic fallback.

No provider call is made during server startup. OX startup validates only local configuration. If `AI_GATEWAY_API_KEY` is absent, OX is `DISABLED`. If optional OX configuration is invalid, OX is `MISCONFIGURED`. Either condition is fail-isolated: the core Byte-MCP tools can still start and operate.

## OX credential boundary

The Vercel AI Gateway credential is read only from:

```text
AI_GATEWAY_API_KEY
```

It must never be committed, written to machine-local repository configuration, stored in OX evidence, copied into audit records, pasted into review material, or returned through MCP.

The configured key is held in memory and used only to form the outbound authorization header at request time. `OXSettings.__repr__` reports only whether a key is configured, not its value.

The OX service also fails closed if the exact configured credential appears anywhere in material that would be persisted, transmitted, replayed, or returned through the supported OX lifecycle. This guard covers:

- initial review objective, verification, and committed bundle content;
- blind revalidation preparation;
- continuation messages and replayed continuation retries;
- adjudication events;
- targeted revalidation context and replayed targeted retries;
- all bounded `ox_get_review` response views.

Byte-MCP does not silently redact source code or verification evidence because doing so would corrupt the review artifact. It rejects the operation instead.

## OX repository and scope authority

OX reads only repositories named in the machine-local registry:

```text
config/ox-repositories.local.json
```

That file is Git-ignored. Each repository entry contains predeclared, versioned subsystem definitions with deterministic source, test, boundary, and context paths.

Review-time callers cannot attach arbitrary files or heuristically expand scope. Bundle construction reads immutable committed Git objects rather than substituting the working tree. Mandatory evidence categories, repository tree context, verification records, and the exact base-to-target diff are hash-bound into the prepared review artifact. Oversized or incomplete bundles fail closed rather than being silently truncated.

OX does not execute repository code, tests, builds, package managers, shells, or subprocesses. Verification evidence is supplied by Byte and provenance-labelled.

## OX human approval and integrity binding

A new review and a blind revalidation use a two-phase protocol:

1. **Prepare:** deterministically build and persist the proposal. This phase performs zero provider calls.
2. **Approve/transmit:** after explicit human approval, rebuild the artifact from the committed state and verify that it exactly matches the approved evidence before crossing the provider boundary.

The approval check binds to the complete deterministic manifest and the canonical outbound `payload_sha256`, not merely to byte length or a self-reported digest. Artifact count and message-size limits are also rechecked. A changed objective, verification record, manifest field, subsystem definition, commit, or payload invalidates the approval before any provider request.

Continuation cannot add repository files or expand the prepared scope. Revalidation of a new commit requires a separately prepared approval boundary.

## OX attempts, failures, and retries

Every outbound attempt receives an identity and durable local intent/evidence before the provider boundary is crossed. If pre-request evidence persistence fails, the provider is not called.

V1 performs no automatic retries. Transport/provider outcomes distinguish successful completion from failures and from `OUTCOME_UNKNOWN`, where a timeout or connection failure may have occurred after request upload. Byte-MCP never assumes an ambiguous attempt was not received.

A retry is explicit, receives a new attempt identity, and requires renewed approval where defined by the OX lifecycle. Persisted continuation/revalidation histories are hash-checked before replay and are rechecked for the configured credential before a new retry attempt can be claimed.

## OX evidence boundary

Detailed OX evidence is separate from the reviewed repository and from the compact core operation audit. Default locations are user-local data directories:

- Windows: `%LOCALAPPDATA%\Byte-MCP\ox`
- Linux: `${XDG_DATA_HOME:-~/.local/share}/byte-mcp/ox`

The location may be overridden with `BYTE_MCP_OX_EVIDENCE_DIR`.

OX evidence records prepared review identity, manifest, bundle, attempt identity, native conversation messages, provider responses, validated findings, adjudication events, and revalidation evidence. OX statements are never rewritten into Byte conclusions; adjudication is stored separately so provenance remains explicit.

The public retrieval surface is bounded to seven views: `summary`, `findings`, `thread`, `manifest`, `adjudication`, `attempts`, and `revalidation`. Returned material passes through the configured-credential guard before crossing the MCP boundary.

## Frozen authority

The accepted **core filesystem** capability contains no write, rename, move, delete, shell, execute, process-control, registry, application-control, or arbitrary HTTP tool.

The OX branch introduces one separately reviewed exception: a fixed-purpose outbound validation client to the fixed Vercel AI Gateway route described above. It does not authorize arbitrary HTTP destinations, caller-selected providers/models, repository mutation, or command execution.

Adding any broader authority requires:

1. a new version or separately governed capability increment;
2. a capability contract;
3. threat modelling and adversarial tests;
4. explicit confirmation and rollback design where mutation is possible;
5. a new release and deployment review.

The separate chess-capability branch is not part of this integration and must not be merged merely to complete OX connectivity.

## Current OX acceptance status

Automated unit, integration, lifecycle, failure-recovery, and adversarial security tests are green on Windows and Ubuntu for the OX integration candidate. This does **not** by itself prove the real external provider route.

A live Vercel AI Gateway → Z.AI → GLM-5.3-Flash canary remains a separate acceptance gate and must not occur until the exact repository, commit, subsystem, objective, manifest/payload digests, and outbound purpose have been explicitly approved by the human operator.

See [OX Validation Operations](OX-VALIDATION.md) for the operational procedure.

## Known V1/core limitations

The following are intentionally deferred rather than silently assumed to be solved:

- extraction and SHA-256 calculation read a fetched file in separate passes, so a concurrently modified file can create a content/hash TOCTOU mismatch;
- PDF extraction is byte-bounded but does not yet apply a separate page-count ceiling;
- PPTX extraction does not guarantee complete traversal of grouped shapes or tables;
- audit logging has no built-in rotation and is not multi-process safe;
- the default runtime layout assumes the reviewed source/repository deployment model.

These limitations do not expand filesystem authority, but changing any of them should receive tests and review appropriate to the affected boundary.
