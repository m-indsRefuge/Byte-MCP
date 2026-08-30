# Wolfram LLM Phase 1

## Status

```text
Capability:          Wolfram|Alpha LLM API
Implementation:      implementation_in_validation
Public MCP surface:  wolfram_query only
Broad co-engineer:   not yet qualified
Live transport:      canary_and_failure_path_validated
Native dialect:      calibration_runner_pending_local_acceptance
Formal campaign:     pending qualification conformance repair
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
.\.venv\Scripts\python.exe scripts\wolfram_native_calibration.py
```

The runner:

- discovers `wolfram_query` over MCP before use;
- performs the six fixed calls once each and in fixed order;
- never talks directly to the provider;
- has no AppID, authorization-header, or direct HTTP handling;
- performs no automatic retries;
- validates bounded expected evidence in memory;
- prints only calibration names, pass status, local quota counts, and run metadata in its final success summary;
- does not persist raw provider result text.

The raw 30-task qualification campaign and this mediated calibration measure different things and must remain separate evidence sets:

```text
RAW        = Wolfram receives the frozen engineering prompt unchanged.
MEDIATED   = Byte extracts a formal/computational model and sends Wolfram-native input.
```

A strong mediated calibration does not erase raw `UNINTERPRETABLE` results and does not by itself unlock broad co-engineer status. It measures whether Byte + Wolfram can use the actual intended orchestration pattern effectively.

## OX separation

OX and Wolfram never communicate directly. No OX prompt, response, thread, provider context, or hidden review state is automatically forwarded to Wolfram.

When Byte deliberately uses Wolfram for an unresolved OX issue, the query is marked `FALLBACK_VALIDATION` with route reason `OX_FALLBACK` and may include only a local opaque `source_finding_id` for provenance. Byte reformulates the technical question independently.

## Persistence and audit

The local quota ledger stores only schema version, UTC month, and attempt count. It never stores query text, response text, result URLs, AppID, headers, or provider errors.

Operational audit records metadata and SHA-256 input fingerprints, not raw Wolfram request or response content. A transmission-intent audit event is written before the provider call. Audit failure therefore prevents an unaudited outbound request.

Provider responses are not cached. Current-call response text exists only long enough to return and use the result.

## Qualification gate

The fixed raw campaign is:

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
6. Run `scripts/wolfram_native_calibration.py` and require all six mediated cases to pass through the MCP boundary.
7. Preserve the raw and mediated evidence separately.
8. Repair and freeze the formal qualification fixture before executing the remaining primary campaign.
9. Record scores without storing raw provider results and use at most five deliberate clarification follow-ups.
10. Generate the summary and assign one evidence-based capability profile.
11. Only then decide whether broader Wolfram lifecycle tooling is justified.
