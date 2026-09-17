# Security

Byte-MCP contains several deliberately separate capability boundaries:

1. the accepted V1/V1.1 local read-only filesystem boundary;
2. the governed Wolfram query capability;
3. the governed NVIDIA provider capability; and
4. the clean-room OX adversarial code-review capability.

The external capabilities do not expand the filesystem authority of the original core tools. Each has its own explicit contract and tests.

## Default-denied material

The core filesystem implementation blocks common secret-bearing names and locations, including `.env`, `.git`, `.ssh`, `.gnupg`, credential/secret directories, credential/secret filenames, private-key material, and password-vault formats.

The policy is intentionally conservative and can be expanded only through a reviewed capability change.

Per-component link/junction checks are defense-in-depth. Core filesystem containment remains strict canonical resolution beneath an approved root. OX separately refuses to follow links/junctions during review snapshotting.

## Prompt injection and untrusted content

Text found inside retrieved files, frozen OX source material, provider responses, or external-tool output is untrusted content. It must never override the operator's request, Byte-MCP tool contracts, or higher-level safety/authority rules.

OX provider output is review evidence, not executable instruction. The OX provider receives no Byte-MCP tools, shell access, filesystem access, function-calling authority, continuation channel, or interactive tool loop.

## Core network boundary

Byte-MCP binds to loopback only. Supported core host values are:

- `127.0.0.1`
- `localhost`
- `::1`

The default endpoint is:

```text
http://127.0.0.1:8000/mcp
```

The server rejects non-loopback values such as `0.0.0.0`. OpenAI Secure MCP Tunnel is an outbound transport layer and does not broaden Byte-MCP filesystem authority.

Core runtime configuration environment variables include:

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

## Core response and root boundary

Core MCP-facing responses do not expose backing absolute filesystem paths. The public addressing contract is approved root alias plus relative path/opaque reference where applicable.

The accepted ChatGPT deployment is deliberately restricted to approved roots rather than a drive root or whole user profile. The `projects` root does not grant arbitrary absolute-path access.

Opaque references are identifiers, not authentication tokens. Decoded root/path pairs are passed back through approved-root containment checks before access.

## Core limits and extraction

`fetch` enforces `BYTE_MCP_MAX_FILE_BYTES` before extraction. Content search has its own bounded extraction ceiling. Response text is bounded by the configured response-character limit.

Malformed/encrypted document-library failures are normalized at service boundaries. A corrupt search candidate is a per-file miss; a corrupt file requested directly through `fetch` returns a Byte-MCP domain error rather than a raw third-party exception.

## Core audit

Allowed, denied, and unexpected core outcomes are appended to the configured audit ledger. Fetched content is not written to that ledger. Search terms and opaque references are fingerprinted rather than stored raw.

Audit persistence is fail-closed. If Byte-MCP cannot persist the audit entry, the operation result is not returned as accepted.

`AuditLog` is single-process by contract. Separate Byte-MCP processes must use distinct audit files.

## Secure tunnel boundary

OpenAI Secure MCP Tunnel is the selected ChatGPT transport. Required properties remain:

- Byte-MCP listens only on loopback;
- the tunnel client connects outbound;
- no router port forwarding is required;
- no public inbound Windows Firewall rule is added;
- tunnel runtime credentials are not stored in Git or pasted into chat;
- the tunnel points only to the reviewed local MCP endpoint.

Tunnel transport permission does not authorize filesystem writes or additional MCP capabilities.

## Current MCP surface

The currently qualified surface is exactly:

```text
list_roots
list_directory
search
fetch
wolfram_query
nvidia_query
nvidia_review
nvidia_get_review
ox_review
ox_get_review
```

For OX, only `ox_review` can cross the provider boundary. `ox_get_review` is local/read-only and performs zero provider networking.

## OX clean-room authority

The current governing OX contract is `docs/OX.md`. Historical V1/V2 operator/design material is not current authority; see `archive/OX-ARCHIVE.md`.

### Repository and scope boundary

OX reuses Byte-MCP's existing `projects` root. The caller supplies a direct-child repository name, not an arbitrary filesystem path.

Supported modes are:

- `FULL_REPOSITORY` — all material eligible under the versioned snapshot policy;
- `BOUNDED` — one or more explicitly selected normalized relative paths.

Bounded scope is never silently widened. Absolute paths, traversal, unsafe/non-normalized paths, and link/junction components fail closed.

### Current-filesystem snapshot boundary

OX freezes current filesystem bytes, including eligible staged, unstaged, and untracked text material. The packet is built only from the frozen snapshot; OX does not reread the repository after freeze.

The snapshot excludes known secret/env/key material, `.git`, dependency/virtualenv directories, caches, generated/build/coverage output, databases, archives, binary/media material, invalid text, nested repositories, and OX/evidence directories. Symlinks/junctions are never followed.

A per-artifact size ceiling determines snapshot eligibility. Included content is additionally subject to hard artifact-count, aggregate-content, packet, and prepared-request limits. Hard included-material overflow fails locally with no truncation, summarization, split request, or provider call.

### OX provider boundary

The outbound route is fixed:

```text
Byte-MCP
  -> https://ai-gateway.vercel.sh/v1/chat/completions
  -> provider allow-list: zai
  -> model: zai/glm-5.3-flash
```

OX has no caller-selected URL/provider/model, provider fallback, dynamic discovery, provider tool loop, redirect following, retry, continuation, revalidation, queue, worker, or recovery resend.

One explicit `ox_review` invocation authorizes exactly one synchronous review lifecycle and at most one provider request.

### OX credential boundary

The Vercel AI Gateway credential is read lazily from:

```text
AI_GATEWAY_API_KEY
```

It is not required for server import or OX runtime construction. Missing credential stops the individual review before `send.claim` and before networking.

The key must never be committed, stored in OX evidence, copied into audit logs, pasted into review objectives, or returned through MCP. `OXSettings.__repr__` reports only whether a key is configured.

Before send authority is consumed, OX checks the exact active credential and strong private-key markers against provider-bound packet/request bytes. Detection fails closed; OX does not silently redact and continue.

### OX send and replay boundary

Prepared snapshot/packet/request evidence is persisted before transmission preflight. The canonical request identity is revalidated before send authority is consumed.

`send.claim` is created atomically and is irreversible. Once present, it is never deleted/reset to restore send authority. Concurrent/duplicate execution can therefore produce at most one transport winner for a review identity.

Transport outcomes preserve certainty:

- definite connect/pool `NOT_SENT` -> `FAILED`;
- write/read/deadline/remote ambiguity -> `OUTCOME_UNKNOWN`;
- complete non-2xx response -> `FAILED/REJECTED`;
- complete 2xx malformed/empty assistant envelope -> `FAILED` with attempt outcome `COMPLETED`;
- post-claim evidence-persistence uncertainty -> `OUTCOME_UNKNOWN`.

`OUTCOME_UNKNOWN` never grants retry authority.

### Raw response and evidence boundary

The exact provider response body is persisted to `response.bin` before Byte-MCP decodes the envelope or extracts assistant text.

Per-review evidence can include:

```text
review.json
snapshot.json
packet.bin
request.bin
send.claim
response.bin
review.txt
```

`packet.bin`, `request.bin`, `response.bin`, and `snapshot.json` are restricted forensic material. Routine MCP results/logs must not expose raw request bodies, raw provider envelopes, absolute local paths, credentials, authorization headers, proxy/environment values, or arbitrary exception text.

`ox_get_review` returns a safe local projection and never performs provider networking.

### OX runtime isolation

OX runtime construction is lazy and fail-isolated. Missing/invalid OX local configuration must not prevent core, Wolfram, or NVIDIA startup.

OX and NVIDIA do not import each other's provider-specific packages. OX does not invoke Wolfram. Shared code is limited to provider-neutral primitives under `byte_mcp.providers`.

## Frozen authority

The accepted core filesystem capability contains no write, rename, move, delete, shell, execute, process-control, registry, application-control, or arbitrary HTTP tool.

Wolfram, NVIDIA, and OX are separately governed exceptions. OX specifically authorizes only fixed-purpose outbound code review through the fixed route above.

Adding broader filesystem authority, arbitrary HTTP, OX retry/continuation/revalidation, provider tool access, alternate provider/model routing, background execution, or materially different authentication requires a new capability contract, threat review, tests, and explicit approval.

## Current OX qualification status

The clean-room OX feature branch has completed provider-free implementation/security qualification on Windows and Ubuntu. That qualification does not authorize live runtime promotion or a real OX provider request.

Runtime promotion and the first live clean-room OX review are separate explicit authorization boundaries. See `docs/OX.md` for the operator contract and `docs/FAILURE_MAP.md` for failure diagnostics.

## Known V1/core limitations

The following remain intentionally deferred:

- extraction and SHA-256 calculation read a fetched file in separate passes, so concurrent modification can create a content/hash TOCTOU mismatch;
- PDF extraction is byte-bounded but has no separate page-count ceiling;
- PPTX extraction does not guarantee complete traversal of grouped shapes/tables;
- core audit logging has no built-in rotation and is not multi-process safe;
- the default runtime layout assumes the reviewed source/repository deployment model.

These limitations do not expand authority; changing them requires tests/review appropriate to the affected boundary.
