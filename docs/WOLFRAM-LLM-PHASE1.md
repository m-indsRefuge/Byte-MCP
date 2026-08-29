# Wolfram LLM Phase 1

## Status

```text
Capability:          Wolfram|Alpha LLM API
Implementation:      implementation_in_validation
Public MCP surface:  wolfram_query only
Broad co-engineer:   not yet qualified
Live campaign:       pending local AppID gate
```

This capability is a separately governed next-version expansion. It does not rewrite the accepted Byte-MCP V1.1 closeout or weaken the four existing filesystem tools.

## Operator setup

Store the Wolfram|Alpha LLM API AppID through the Windows user-bound DPAPI prompt:

```powershell
.\scripts\Setup-Wolfram.ps1
```

Then start Byte-MCP normally:

```powershell
.\scripts\Start-ByteMCP.ps1
```

The AppID is stored at:

```text
%USERPROFILE%\.byte-mcp\credentials\wolfram-appid.dpapi
```

Local conservative usage accounting is stored at:

```text
%USERPROFILE%\.byte-mcp\wolfram\usage.json
```

`Setup-Wolfram.ps1` is optional. Without a dedicated Wolfram credential, Byte-MCP core still starts and the Wolfram capability reports unavailable when invoked.

## Phase 1 tool

```text
wolfram_query(
    input,
    max_chars=None,
    purpose="COENGINEERING",
    route_reason="OTHER_BOUNDED_REASON",
    source_finding_id=None
)
```

The caller cannot supply an AppID, URL, HTTP method, authorization header, arbitrary endpoint, or unrestricted Wolfram API parameter.

The service uses the fixed Wolfram|Alpha LLM API endpoint with bearer authentication. Input is normalized, bounded to 8,000 characters, screened for secret-like material, and stripped of machine-specific absolute Windows paths before transmission. Output defaults to and is bounded by 6,800 characters. Each invocation performs at most one external request; there are no automatic retries.

## OX separation

OX and Wolfram never communicate directly. No OX prompt, response, thread, provider context, or hidden review state is automatically forwarded to Wolfram.

When Byte deliberately uses Wolfram for an unresolved OX issue, the query is marked `FALLBACK_VALIDATION` with route reason `OX_FALLBACK` and may include only a local opaque `source_finding_id` for provenance. Byte reformulates the technical question independently.

## Persistence and audit

The local quota ledger stores only schema version, UTC month, and attempt count. It never stores query text, response text, result URLs, AppID, headers, or provider errors.

Operational audit records metadata and SHA-256 input fingerprints, not raw Wolfram request or response content. A transmission-intent audit event is written before the provider call. Audit failure therefore prevents an unaudited outbound request.

Provider responses are not cached. Current-call response text exists only long enough to return and use the result.

## Qualification gate

The fixed campaign is:

```text
qualification/wolfram/llm-api-v1.json
```

It contains exactly 30 primary tasks: three each across WA-01 through WA-10. The campaign covers computation, symbolic reasoning, algorithms, code comprehension, debugging, test generation, test oracles, state machines, architecture constraints, and adversarial claim checking.

Freeze and inspect its hash before live qualification:

```powershell
.\.venv\Scripts\python.exe scripts\wolfram_qualification.py list `
    --campaign qualification\wolfram\llm-api-v1.json
```

The score ledger stores only task IDs, fixture hash, numeric scores, bounded Byte-authored notes, and coding diagnostic booleans. Raw Wolfram responses are not persisted by the harness.

Broad co-engineer status requires all of:

```text
overall average >= 14/20
WA-04/WA-05 root-cause correctness >= 70%
unsupported/invented claim rate <= 10%
Byte + Wolfram materially improves >= 1 meaningful task family
```

Even if that threshold is met, no broader MCP tools are registered automatically. `wolfram_review`, `wolfram_continue`, `wolfram_revalidate`, and `wolfram_get_review` require a separate approved implementation cycle.

## Current provider constraints

Before live use, re-check the current Wolfram|Alpha LLM API documentation and API Terms of Use. Phase 1 is designed around the documented GET endpoint, bearer AppID support, result-link attribution, and a no-cache operating model. Wolfram API results must not be accumulated into a training or fine-tuning dataset.

## Live acceptance sequence

After deterministic CI is green:

1. Run `Setup-Wolfram.ps1` locally and paste the existing AppID only into its secure prompt.
2. Start Byte-MCP and confirm MCP discovery contains `wolfram_query` plus the existing filesystem tools.
3. Run a single non-sensitive `2^100` canary through the actual MCP tool.
4. Confirm exactly one quota increment and metadata-only audit.
5. Exercise one controlled uninterpretable input without retrying to force an error.
6. Freeze the campaign hash and execute the 30 primary calls in fixture order.
7. Record scores without storing raw provider results.
8. Use at most five deliberate clarification follow-ups.
9. Generate the summary and assign one evidence-based capability profile.
10. Only then decide whether broader Wolfram lifecycle tooling is justified.
