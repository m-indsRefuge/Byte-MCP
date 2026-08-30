# Wolfram LLM Phase 1

## Status

```text
Capability:          Wolfram|Alpha LLM API
Implementation:      implementation_in_validation
Public MCP surface:  wolfram_query only
Broad co-engineer:   not yet qualified
Live transport:      web_ui_end_to_end_validated
Native dialect:      six_case_calibration_validated
Formal campaign:     v2_frozen_pending_live_execution
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

When the MCP tool surface changes, refresh the Byte-MCP server connection in the ChatGPT Web UI so ChatGPT re-discovers the current tool schema. A connected session may otherwise continue exposing a previously scanned tool set.

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

## Byte-mediated native query protocol

The server does not translate ordinary engineering prose or source code into Wolfram queries. Semantic translation remains Byte-owned. Byte first understands the engineering problem, extracts the smallest computational or formal model that can answer it, and then sends only that compact model through `wolfram_query`.

Preferred Wolfram-native query properties are:

- remove conversational framing when the computation itself is sufficient;
- extract the mathematical, logical, combinatorial, numerical, or state-space object;
- use explicit operators such as `expand`, `factor`, `solve`, `integrate`, `maximize`, `minimize`, or `table`;
- encode constraints directly beside the expression;
- prefer compact symbols and single-line expressions over explanatory prose;
- decompose compound engineering questions into separate governed calls when independent computations are required;
- send only the minimum non-secret model needed for the computation rather than an entire repository or review transcript.

Examples:

```text
engineering intent                      Wolfram-native query
-------------------------------------   ------------------------------------------
verify binomial identity                expand (a+b)^2-a^2-2*a*b-b^2
constrained product maximum             maximize x*y, x+y=10, x>=0, y>=0
analyze divide-and-conquer recurrence   f(n)=2*f(n/2)+n, f(1)=1
enumerate capped retry delays           table min(2*2^n,60), n=0 to 6
count 8 booleans x 5 modes              2^8*5
model falsey-cache hit condition        P && V
```

A provider `501` suggestion is reformulation guidance, not permission for an automatic retry. Phase 1 still performs exactly one provider request per MCP invocation. If Byte decides that the suggested interpretation justifies a reformulation, that reformulation is a new deliberate `wolfram_query` call with its own policy check, quota reservation, and audit events.

Byte remains responsible for mapping Wolfram's computational evidence back to repository facts and for the final engineering conclusion. A Wolfram result is evidence, not independent authority to modify code.

## Native dialect calibration

The fixed mediated calibration corpus lives in:

```text
src/byte_mcp/wolfram/native_calibration.py
```

It contains six Byte-authored Wolfram-native cases covering identity verification, constrained optimization, recurrence analysis, bounded sequence generation, state counting, and a Boolean model of the falsey-cache defect.

Run the live calibration only against a running Byte-MCP instance:

```powershell
.\.venv\Scripts\python.exe .\scripts\wolfram_native_calibration.py
```

The accepted local MCP calibration completed all six cases successfully with exactly six quota increments. A separate ChatGPT Web UI acceptance call then invoked `wolfram_query` through the secure tunnel and returned the expected result, validating the complete Web UI -> Byte-MCP -> Wolfram -> Web UI transport path.

The runner:

- discovers `wolfram_query` over MCP before use;
- performs the six fixed calls once each and in fixed order;
- never talks directly to the provider;
- has no AppID, authorization-header, or direct HTTP handling;
- performs no automatic retries;
- validates bounded expected evidence in memory;
- prints only calibration names, pass status, local quota counts, and run metadata in its final success summary;
- does not persist raw provider result text.

## Qualification V2 freeze

The original V1 campaign remains unchanged as provenance for the early exploratory RAW calls:

```text
qualification/wolfram/llm-api-v1.json
```

Those exploratory results are not relabeled as formal V2 evidence.

The formal qualification campaign is now:

```text
qualification/wolfram/llm-api-v2.json
```

V2 contains exactly 30 primary tasks, three each across WA-01 through WA-10. It covers computation, symbolic reasoning, algorithms, code comprehension, debugging, test generation, test oracles, state machines, architecture constraints, and adversarial claim checking. The coding fixtures include a clean control and five ground-truth defect cases so root-cause scoring is derived from the campaign contract rather than from score-field presence.

Each V2 task freezes both qualification conditions before any new live campaign answers are observed:

```text
RAW             = transmit the exact engineering prompt unchanged.
BYTE_MEDIATED   = transmit the task's exact pre-authored Wolfram-native query.
```

For both conditions the fixture also freezes the route reason. `BYTE_MEDIATED` uses dialect version `wolfram-native-v0.1`. The mediation note records Byte's local semantic mapping and is not sent to Wolfram.

The two modes are independent evidence sets. A primary task may therefore have one RAW score and one BYTE_MEDIATED score. Duplicate primaries are rejected within a mode, while the same task ID in the other mode is valid. Each mode receives its own maximum of five deliberate follow-up calls.

Inspect the frozen campaign and hash before live execution:

```powershell
.\.venv\Scripts\python.exe .\scripts\wolfram_qualification.py list
```

The score ledger stores only derived qualification evidence: task ID, fixture hash, mode, transmitted-query SHA-256, route reason, dialect version where applicable, numeric scores, bounded Byte-authored notes, and coding diagnostic booleans. Raw Wolfram response text is not persisted by the harness.

Record and summarize RAW and BYTE_MEDIATED independently:

```powershell
.\.venv\Scripts\python.exe .\scripts\wolfram_qualification.py summary --mode RAW
.\.venv\Scripts\python.exe .\scripts\wolfram_qualification.py summary --mode BYTE_MEDIATED
```

An incomplete mode reports `INCOMPLETE` plus its missing primary task IDs and does not assign a capability profile. A complete mode receives one of:

```text
A_BROAD_COENGINEER
B_COMPUTATIONAL_COENGINEER
C_SPECIALIST_CALCULATOR
D_NOT_WORTH_BROAD_INTEGRATION
```

Broad co-engineer status requires all of:

```text
overall average >= 14/20
ground-truth coding defect root-cause correctness >= 70%
unsupported/invented claim rate <= 10%
Byte + Wolfram materially improves >= 1 meaningful task family
```

The final production question is not whether Wolfram can consume arbitrary engineering prose. It is whether the Byte-mediated system solves engineering problems more reliably or usefully than Byte alone and whether that improvement is broad enough to justify a co-engineer profile.

Even if the threshold is met, no broader MCP tools are registered automatically. `wolfram_review`, `wolfram_continue`, `wolfram_revalidate`, and `wolfram_get_review` require a separate approved implementation cycle.

## OX separation

OX and Wolfram never communicate directly. No OX prompt, response, thread, provider context, or hidden review state is automatically forwarded to Wolfram.

When Byte deliberately uses Wolfram for an unresolved OX issue, the query is marked `FALLBACK_VALIDATION` with route reason `OX_FALLBACK` and may include only a local opaque `source_finding_id` for provenance. Byte reformulates the technical question independently.

## Persistence and audit

The local quota ledger stores only schema version, UTC month, and attempt count. It never stores query text, response text, result URLs, AppID, headers, or provider errors.

Operational audit records metadata and SHA-256 input fingerprints, not raw Wolfram request or response content. A transmission-intent audit event is written before the provider call. Audit failure therefore prevents an unaudited outbound request.

Provider responses are not cached. Current-call response text exists only long enough to return and use the result.

## Current provider constraints

Before live use, re-check the current Wolfram|Alpha LLM API documentation and API Terms of Use. Phase 1 is designed around the documented GET endpoint, bearer AppID support, result-link attribution, and a no-cache operating model. Wolfram API results must not be accumulated into a training or fine-tuning dataset.

## Formal benchmark execution sequence

After deterministic CI is green:

1. Update the local Wolfram worktree to the exact accepted branch head and run `scripts/Check.ps1`.
2. Run `scripts/wolfram_qualification.py list` and preserve the V2 fixture SHA-256 in the run evidence.
3. Confirm Byte-MCP is READY and ChatGPT's refreshed server connection exposes `wolfram_query`.
4. Execute all 30 V2 RAW primaries through `wolfram_query` using the exact frozen prompts and route reasons. No silent reformulation is allowed in RAW mode.
5. Score the RAW answers without persisting raw provider result text. Use at most five deliberate RAW follow-ups.
6. Execute all 30 V2 BYTE_MEDIATED primaries through `wolfram_query` using the exact frozen mediated queries and route reasons. Do not edit the mediated fixture in response to RAW outcomes.
7. Score the BYTE_MEDIATED answers without persisting raw provider result text. Use at most five deliberate mediated follow-ups.
8. Generate independent summaries for both modes and compare family-level performance.
9. Determine whether Byte + Wolfram materially improves at least one meaningful family and assign the evidence-based capability profile.
10. Preserve V1 exploratory evidence, V2 RAW evidence, and V2 BYTE_MEDIATED evidence as separate provenance classes.
11. Only then decide whether broader Wolfram lifecycle tooling is justified.
