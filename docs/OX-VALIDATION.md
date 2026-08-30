# OX Validation Operations

This document defines the operator procedure for Byte-MCP's optional OX external-validation capability.

OX is an independent reviewer. Byte remains the technical process owner and evidence adjudicator. Nolan, as the human operator, remains the final authority over outbound review approval and final acceptance.

## Status

The OX integration candidate has passed its automated unit, integration, lifecycle, recovery, and adversarial security gates on Windows and Ubuntu.

The real Vercel AI Gateway → Z.AI → GLM-5.3-Flash route has also completed non-sensitive live transport checks outside CI. Live-route success does **not** waive the separate privacy/data-handling gate for private repository material.

The review architecture now deliberately separates two evidence classes:

1. **OX-authored evidence:** the exact natural-language provider response and raw provider response object; and
2. **Byte-authored interpretation:** optional structured findings derived locally from that OX response and explicitly provenance-bound to it.

Byte-MCP does not require OX to emit a rigid findings JSON object. This avoids conflating provider formatting compliance with review quality while preserving deterministic local evidence for adjudication and revalidation.

## Architecture

```text
ChatGPT / Byte
    |
    v
Byte-MCP
    |
    +-- Natural OXReviewService
          +-- allowlisted Git repository reader
          +-- deterministic bundle builder
          +-- append-only evidence store
          +-- Byte-derived finding/adjudication lifecycle
          +-- OXClient
                |
                v
          https://ai-gateway.vercel.sh/v1/chat/completions
                |
                +-- pinned provider: zai
                +-- fixed model: zai/glm-5.3-flash
```

The OX client is not a generic provider abstraction. V1 has no caller-selected URL, model, provider, or fallback route.

Vercel and Z.AI are external processors for any approved OX transmission. An approved review packet leaves the local Byte-MCP trust boundary and is sent through Vercel AI Gateway to Z.AI. Review their current data-handling terms before transmitting private repository material.

### Private-repository privacy gate

Before any private repository content is transmitted, review the then-current Vercel and Z.AI data-handling terms and the active Vercel account/data settings again.

Model-training opt-out and zero-data-retention are separate controls. Disabling Vercel Model Training does **not** by itself prove that the selected provider route is operating under zero-data-retention. Provider logs and current provider terms must therefore be considered separately.

The current hard provider pin remains `zai`; Byte-MCP must not silently switch providers merely to obtain a different retention policy. If a future retention control would make the pinned Z.AI route unavailable, that is an explicit product/privacy decision rather than a reason to fall back automatically.

No further private-source dogfood review should be transmitted until this privacy/ZDR assessment is explicitly accepted. Non-sensitive synthetic transport checks do not waive this gate.

## MCP tool surface

OX exposes exactly four high-level tools:

- `ox_review`
- `ox_continue`
- `ox_revalidate`
- `ox_get_review`

`ox_review` and `ox_revalidate` can cause external provider requests and append local evidence. `ox_continue` can either send one bounded continuation message externally or perform the local-only `record_findings` operation. These tools are therefore not classified as globally read-only/idempotent at the MCP system level. `ox_get_review` is local/read-only.

The reviewed repository remains read-only through all four tools.

## Configuration

### API credential

OX reads the Vercel AI Gateway credential only from:

```text
AI_GATEWAY_API_KEY
```

Do not paste this value into chat, source code, documentation, repository configuration, review objectives, verification output, findings, adjudication, or evidence.

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
max generated tokens:                65,536
```

Bounds enforced by settings:

```text
BYTE_MCP_OX_MAX_BUNDLE_BYTES: 16,384 .. 16,000,000
BYTE_MCP_OX_MAX_OUTPUT_TOKENS: 1,024 .. 131,072
```

The provider request also sets reasoning effort to `medium`. Reasoning tokens consume generated-token budget, which is why the previous 16,384-token default was retired after live-route evidence showed it could be exhausted by reasoning before a useful visible answer was produced.

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

A successful initial provider call uses natural text mode. The exact raw provider response is persisted before the review is treated as successfully evidenced. The assistant response text is stored in the native review thread and returned as `response`; OX is not required to satisfy a local findings schema.

## Continuation

`ox_continue` has two distinct modes.

### Message mode

Message mode adds one bounded user message to an already transmitted/reviewed OX thread.

Continuation cannot add repository files or change the approved subsystem/commit scope.

Before the attempt is claimed, Byte-MCP:

- reconstructs the existing native message history;
- appends the new message;
- rejects the request if the configured credential appears anywhere in the assembled history;
- enforces the outbound message-size ceiling.

One continuation operation produces at most one provider response. There is no hidden self-continuation loop.

### `record_findings` mode

`record_findings` is **local-only**. It performs no provider request.

Byte may use it after reviewing the exact natural OX response to persist a structured engineering interpretation for downstream adjudication. The resulting object uses:

```text
protocol_version: byte-derived-findings-v1
derivation_authority: byte
derivation_provenance: derived-from-ox-natural-review
```

The record also binds to:

- the exact completed initial OX `source_attempt_id`; and
- `source_response_sha256`, the SHA-256 of the exact natural OX response text used as the derivation source.

Each local finding is still validated against the strict finding-field contract before persistence. Invalid severity/confidence/fields, non-finite numeric values, malformed values, or configured credentials fail closed before findings evidence is written.

This distinction is important: the structured finding is **Byte's evidence-based interpretation of OX**, not a claim that OX emitted the same JSON object verbatim.

## Findings and Byte adjudication

The canonical external review evidence is the persisted natural OX response. Structured findings are optional Byte-derived local evidence bound to that response.

A Byte-derived finding can move through explicit states such as:

- `RAISED`
- `REPRODUCED`
- `CONFIRMED`
- `DISPROVED`
- `DEFERRED`
- `UNRESOLVED`
- `REMEDIATED`
- `REVALIDATED`

Adjudication events are append-only and attributable. OX's original natural response is never overwritten by Byte's interpretation or conclusion.

Configured gateway credentials are rejected from both Byte-derived findings and adjudication evidence before persistence.

Failure to reproduce is not automatically disproof. Byte remains responsible for checking claims against repository evidence before changing code.

## Revalidation

A new remediation commit requires a new prepared revalidation boundary.

### Blind revalidation

`ox_revalidate` first prepares the new exact committed state with verification evidence. Preparation performs no provider call and returns a new digest-bound proposal.

Nolan must inspect and approve that new exact proposal before the blind provider request.

After explicit approval, blind revalidation is sent in fresh OX context. Original Byte-derived findings and Byte remediation/adjudication are not disclosed during the blind pass.

The blind response is natural OX text. Successful blind state is backed by durable provider-response evidence and the exact assistant message in the blind thread; there is no requirement for OX to emit findings JSON.

### Targeted revalidation

Only after a valid blind natural response may the targeted pass disclose selected prior Byte-derived findings and relevant Byte adjudication evidence for completeness checking.

Targeted context explicitly identifies those findings as Byte-derived local interpretation and carries their source provenance. It must not present them as verbatim OX output.

The fully assembled targeted context is checked for the configured gateway credential before any targeted attempt is claimed or sent.

The targeted response is also natural OX text and is evidenced through the exact persisted provider response plus targeted assistant-thread message.

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
-> persist exact raw provider response
-> persist exact natural assistant message
-> mark attempt/review phase complete
-> optionally derive structured Byte findings locally
-> adjudicate separately
```

If provider success cannot be durably evidenced, Byte-MCP does not report a clean evidenced review merely because an HTTP response existed transiently.

Raw provider responses, native messages, Byte-derived findings, adjudication, attempts, and revalidation evidence are retained as separate artifacts so provenance remains inspectable.

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

The `findings` view reflects local findings evidence when Byte has explicitly recorded it; it must not be read as a verbatim rendering of natural OX output.

## Provider boundary

The V1 client uses:

```text
Gateway URL:       https://ai-gateway.vercel.sh/v1/chat/completions
Provider:          zai
Model:             zai/glm-5.3-flash
Streaming:         disabled
Reasoning effort:  medium
Read timeout:      900 seconds
Redirects:         disabled
Automatic retries: none
```

There is no automatic model/provider fallback.

The request does not expose tool/function-calling authority to OX. OX cannot request Byte-MCP to execute a command or access an undeclared file merely by writing such an instruction in its response.

The authorization header is formed in memory from `AI_GATEWAY_API_KEY`. Safe provider status/error classifications may be retained; sensitive request diagnostics and credentials must not be persisted.

## Live route checks

Live provider checks must never run casually as part of startup or CI.

The route has been exercised with deliberately non-sensitive payloads outside CI, including a minimal transport handshake. Those checks established that the configured Vercel gateway credential, fixed Z.AI provider route, GLM-5.3-Flash model, HTTP client, and basic response parsing can complete an end-to-end round trip.

Live experiments also exposed two important engineering facts that are now reflected in the implementation:

- long reasoning can consume the generated-token budget, so the default output budget was raised to 65,536 with an explicit `medium` reasoning effort; and
- long provider operations require a longer read timeout than the earlier 300-second value, so the client read timeout is now 900 seconds.

These checks prove transport behavior only. They do not waive approval, privacy, provenance, or private-source gates.

No live API key or live provider call belongs in CI.

## Private dogfood acceptance

Before the next private dogfood review, satisfy and record the private-repository privacy/ZDR gate above.

The serious dogfood sequence is then:

1. prepare the exact committed OX subsystem review with genuine verification evidence;
2. inspect and explicitly approve the digest-bound outbound proposal;
3. transmit one natural initial OX review;
4. preserve the exact OX response unchanged;
5. let Byte independently derive any actionable findings and persist them locally through `record_findings`;
6. reproduce/adjudicate each finding against repository evidence;
7. remediate confirmed defects under TDD and full regression verification;
8. prepare and approve a fresh remediation revalidation boundary;
9. run blind natural OX revalidation first;
10. run targeted natural completeness review only when Byte-derived findings warrant it;
11. complete final regression verification and Nolan's human acceptance.

No OX finding is self-executing, and no provider response authorizes repository mutation by itself.
