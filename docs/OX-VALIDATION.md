# OX Validation Operations

This document defines the operator procedure for Byte-MCP's optional OX external-validation capability.

OX is an independent reviewer. Byte remains the technical process owner and evidence adjudicator. Nolan, as the human operator, remains the final authority over outbound review approval and final acceptance.

## Status

The OX integration candidate has passed its automated unit, integration, lifecycle, recovery, and adversarial security gates on Windows and Ubuntu.

The real Vercel AI Gateway → Z.AI → GLM-5.3-Flash route is **not accepted merely because automated tests pass**. A live canary remains a separate, explicitly approved gate.

## Architecture

```text
ChatGPT / Byte
    |
    v
Byte-MCP
    |
    +-- OXReviewService
          +-- allowlisted Git repository reader
          +-- deterministic bundle builder
          +-- append-only evidence store
          +-- finding/adjudication lifecycle
          +-- OXClient
                |
                v
          https://ai-gateway.vercel.sh/v1/chat/completions
                |
                +-- pinned provider: zai
                +-- fixed model: zai/glm-5.3-flash
```

The OX client is not a generic provider abstraction. V1 has no caller-selected URL, model, provider, or fallback route.

Vercel and Z.AI are external processors for any approved OX transmission. An approved review packet leaves the local Byte-MCP trust boundary and is sent through Vercel AI Gateway to Z.AI. Review their current data-handling terms before transmitting private repository material; the first live canary remains deliberately non-sensitive regardless.

## MCP tool surface

OX exposes exactly four high-level tools:

- `ox_review`
- `ox_continue`
- `ox_revalidate`
- `ox_get_review`

`ox_review`, `ox_continue`, and `ox_revalidate` can cause external provider requests and append local evidence, so they are not classified as read-only/idempotent at the MCP system level. `ox_get_review` is local/read-only.

The reviewed repository remains read-only through all four tools.

## Configuration

### API credential

OX reads the Vercel AI Gateway credential only from:

```text
AI_GATEWAY_API_KEY
```

Do not paste this value into chat, source code, documentation, repository configuration, review objectives, verification output, or evidence.

If the variable is absent, OX initializes as `DISABLED`. The four original Byte-MCP local tools continue to work.

After setting or changing `AI_GATEWAY_API_KEY`, restart Byte-MCP so the new server process inherits the environment value. Never print the key as part of a verification command.

### Repository registry

Machine-specific OX authorization defaults to:

```text
config/ox-repositories.local.json
```

This path is Git-ignored. Copy the shape from:

```text
config/ox-repositories.example.json
```

Use an absolute local Git repository path in each machine-local repository entry. Each entry declares one or more versioned subsystem definitions. A subsystem explicitly declares:

- `source_roots`
- `test_roots`
- `boundary_files`
- `context_files`

The runtime does not infer scope from imports, symbols, embeddings, or model suggestions.

Override the registry path with:

```text
BYTE_MCP_OX_REPOSITORIES_FILE
```

### Evidence directory

Default detailed evidence locations are:

```text
Windows: %LOCALAPPDATA%\Byte-MCP\ox
Linux:   ${XDG_DATA_HOME:-~/.local/share}/byte-mcp/ox
```

Override with:

```text
BYTE_MCP_OX_EVIDENCE_DIR
```

The evidence directory must remain outside the reviewed repository. Configuration that overlaps the evidence root with a reviewed repository fails closed.

The V1 evidence store is intentionally single-process. Its locks coordinate concurrent calls within one Byte-MCP process; multiple Byte-MCP processes must not share the same OX evidence root.

### Limits

Optional limits are:

```text
BYTE_MCP_OX_MAX_BUNDLE_BYTES
BYTE_MCP_OX_MAX_OUTPUT_TOKENS
```

Defaults:

```text
max bundle / outbound-message bytes: 4,000,000
max output tokens:                   16,384
```

Bounds enforced by settings:

```text
BYTE_MCP_OX_MAX_BUNDLE_BYTES: 16,384 .. 16,000,000
BYTE_MCP_OX_MAX_OUTPUT_TOKENS: 1,024 .. 65,536
```

Oversized mandatory evidence fails closed. Byte-MCP does not silently trim the approved review packet.

## Startup behavior

OX startup is local-only and never contacts the provider.

Conceptual states:

- `AVAILABLE`: key present and local OX configuration validates.
- `DISABLED`: `AI_GATEWAY_API_KEY` is absent.
- `MISCONFIGURED`: optional OX settings/registry/evidence configuration is invalid.

OX is fail-isolated. `DISABLED` or `MISCONFIGURED` must not prevent the core Byte-MCP server from starting.

## Review scope and bundle rules

Every review targets:

- one approved repository alias;
- one predeclared subsystem;
- one exact target commit;
- an explicit base commit when a diff is required;
- one objective;
- explicit Byte-supplied verification evidence.

The target/base commit identifiers must resolve to committed Git objects. Working-tree changes are not substituted for the approved committed state.

A deterministic review bundle includes the mandatory subsystem evidence, bounded repository tree context, exact base-to-target diff when applicable, verification evidence, and a hash-verifiable manifest. Missing mandatory categories fail preparation.

Repository content is represented by repository-relative logical paths. Machine-specific absolute filesystem paths are not part of the outbound review contract.

## Initial review: two-phase approval

### Phase 1 — prepare

Call `ox_review` with repository, subsystem, commits, objective, and verification evidence.

Preparation:

1. validates repository and subsystem authority;
2. resolves immutable Git commits;
3. deterministically builds the mandatory bundle;
4. rejects the operation if the configured gateway credential appears in review material;
5. computes the complete manifest and canonical outbound payload;
6. persists the prepared evidence;
7. returns the proposal with `review_id`, artifact/size information, `manifest_sha256`, and `payload_sha256`;
8. performs **zero provider calls**.

Nolan must inspect and approve the exact proposal before transmission. The approval must cover the repository, subsystem, commits, objective/purpose, artifact count/bytes, `manifest_sha256`, and `payload_sha256` shown by preparation.

### Phase 2 — approve/transmit

After explicit approval of that exact prepared proposal, call `ox_review` in approval mode for the `review_id`.

Before any provider request, Byte-MCP rebuilds the bundle from the committed state and verifies:

- the complete persisted manifest equals the deterministic rebuild;
- `manifest_sha256` is therefore bound to the rebuilt scope;
- exact canonical `payload_sha256` matches the prepared approval;
- total outbound bytes match;
- artifact count matches;
- the configured gateway credential is absent.

Any mismatch fails before the provider boundary.

Only after those checks does Byte-MCP claim a transmission attempt, persist attempt identity, append the native request messages, and invoke the fixed OX client.

## Continuation

`ox_continue` adds one bounded user message to an already transmitted/reviewed OX thread.

Continuation cannot add repository files or change the approved subsystem/commit scope.

Before the attempt is claimed, Byte-MCP:

- reconstructs the existing native message history;
- appends the new message;
- rejects the request if the configured credential appears anywhere in the assembled history;
- enforces the outbound message-size ceiling.

One continuation operation produces at most one provider response. There is no hidden self-continuation loop.

## Findings and Byte adjudication

Formal OX findings are parsed against the versioned finding contract. Malformed provider output remains an explicit protocol/finding-validation failure; Byte-MCP does not silently repair the raw response and pretend it was valid.

OX findings and Byte conclusions are separate evidence. A finding can move through explicit states such as:

- `RAISED`
- `REPRODUCED`
- `CONFIRMED`
- `DISPROVED`
- `DEFERRED`
- `UNRESOLVED`
- `REMEDIATED`
- `REVALIDATED`

Adjudication events are append-only and attributable. OX's original claim is never overwritten by Byte's conclusion.

Configured gateway credentials are rejected from adjudication evidence before persistence.

## Revalidation

A new remediation commit requires a new prepared revalidation boundary.

### Blind revalidation

`ox_revalidate` first prepares the new exact committed state with verification evidence. Preparation performs no provider call and returns a new digest-bound proposal.

Nolan must inspect and approve that new exact proposal before the blind provider request.

After explicit approval, blind revalidation is sent in fresh OX context. Original findings and Byte remediation/adjudication are not disclosed during the blind pass.

### Targeted revalidation

Only after a valid blind revalidation may the targeted pass disclose selected original findings and relevant Byte adjudication evidence for completeness checking.

The fully assembled targeted context is checked for the configured gateway credential before any targeted attempt is claimed or sent.

## Attempts and retries

Every provider attempt has a unique local attempt identity. Attempt intent/evidence is persisted before the network boundary.

V1 has **no automatic retries**.

Provider/transport outcomes distinguish:

- `NOT_SENT`
- `REJECTED`
- `COMPLETED`
- `OUTCOME_UNKNOWN`

`OUTCOME_UNKNOWN` is important: a timeout after request upload may mean the provider received the request even if Byte-MCP did not receive the response. The system must not relabel this as definitely unsent.

Retry is explicit and uses a new attempt identity. Where the lifecycle requires renewed approval, Nolan must approve the retry before repository context can be resent.

Continuation and revalidation retries replay the exact persisted native history only after verifying its history digest. The replayed history is then checked again for the currently configured gateway credential before a retry attempt can be claimed. This also protects against authentic evidence created by a pre-hardening build.

## Evidence durability

The success ordering is intentionally conservative:

```text
persist prepared state
-> human approval
-> reverify approved scope/payload
-> persist attempt identity
-> send provider request
-> persist exact provider response
-> validate/persist findings or protocol failure
-> update attempt/review state
-> return result
```

If provider success cannot be durably evidenced, Byte-MCP does not report a clean evidenced review merely because an HTTP response existed transiently.

Raw provider responses, native messages, findings, adjudication, attempts, and revalidation evidence are retained as separate artifacts so provenance remains inspectable.

## Retrieval

`ox_get_review` is local-only and exposes seven bounded views:

- `summary`
- `findings`
- `thread`
- `manifest`
- `adjudication`
- `attempts`
- `revalidation`

Unsupported views fail explicitly. Every returned view is checked for the configured gateway credential before it crosses the MCP boundary, including legacy/tampered evidence.

## Provider boundary

The V1 client uses:

```text
Gateway URL: https://ai-gateway.vercel.sh/v1/chat/completions
Provider:    zai
Model:       zai/glm-5.3-flash
Streaming:   disabled
Redirects:   disabled
```

There is no automatic model/provider fallback.

The request does not expose tool/function-calling authority to OX. OX cannot request Byte-MCP to execute a command or access an undeclared file merely by writing such an instruction in its response.

The authorization header is formed in memory from `AI_GATEWAY_API_KEY`. Safe provider status/error classifications may be retained; sensitive request diagnostics and credentials must not be persisted.

## Live canary gate

Do not perform the first real provider request casually as part of startup or CI.

The first live canary should use a deliberately small, non-sensitive approved subsystem. The required sequence is:

1. confirm Vercel AI Gateway account/balance and the intended Z.AI route;
2. review current Vercel/Z.AI data-handling terms;
3. configure `AI_GATEWAY_API_KEY` outside Git and restart Byte-MCP;
4. create/configure the machine-local `ox-canary` repository registry entry;
5. prepare the canary review only;
6. inspect the exact repository, subsystem, base/target commits, objective, artifact count/bytes, `manifest_sha256`, and `payload_sha256`;
7. obtain Nolan's explicit approval for that exact outbound proposal;
8. transmit one initial review;
9. confirm provider/model routing, evidence durability, usage metadata, and absence of credential leakage;
10. optionally perform one explicit continuation and one local adjudication;
11. re-run the core local-tool checks to confirm OX remains fail-isolated from the original Byte-MCP capability.

No live API key or live provider call belongs in CI.

## Acceptance after the canary

The canary proves transport and provider behavior, not the quality of the entire integration. The first serious dogfood review should then review the committed OX subsystem itself, followed by Byte evidence-based adjudication, remediation of confirmed defects, blind OX revalidation, targeted completeness review where appropriate, regression verification, and Nolan's final human acceptance.
