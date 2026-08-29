# OX Validator Context Ledger Design

## Status

Approved in conversation; consolidated and self-reviewed design specification. Pending Nolan's written-spec acceptance before implementation planning.

## Date

2026-08-29

## Scope

This document is the architectural authority for adding OX external validation and the Validator Context Ledger (VCL) as a bounded subsystem inside Byte-MCP.

The design has two purposes:

1. establish a rigorous external validation loop in which Byte remains the engineering owner and OX remains an independent external validator; and
2. later evaluate whether controlled access to historical engineering evidence improves OX validation without destroying the value of a memoryless reviewer.

The system must preserve a permanent COLD review path even if historical context later proves useful.

No production implementation begins from the conversational design alone. Implementation planning begins only after this written specification is reviewed and accepted.

---

# 1. Architectural decision

The OX integration and VCL are implemented as a **native bounded subsystem inside Byte-MCP**.

Rejected alternatives:

- a separate OX/VCL service, because it would duplicate lifecycle, authentication, deployment, logging, tunnel, and failure semantics;
- generalizing Byte-MCP into a generic persistence platform, because it would introduce unnecessary scope and authority.

Conceptual package structure:

```text
src/byte_mcp/
├── existing filesystem/security/audit modules
└── ox/
    ├── review/
    │   ├── domain
    │   ├── bundle
    │   ├── findings
    │   ├── adjudication
    │   ├── remediation
    │   └── revalidation
    └── vcl/
        ├── repository
        ├── policy
        ├── context
        ├── validity
        ├── provenance
        ├── scheduler
        ├── meta
        └── recovery
```

SQLite is owned exclusively by the VCL subsystem. Other Byte-MCP modules do not execute arbitrary SQL against the VCL database and use typed domain interfaces only.

## Storage location

The authoritative VCL database and immutable artifacts must live outside every approved Byte-MCP filesystem root.

Recommended Windows application-state layout:

```text
%LOCALAPPDATA%\Byte-MCP\
├── state\
│   └── vcl.sqlite3
├── artifacts\
│   ├── bundles\
│   ├── findings\
│   ├── reproduction\
│   ├── verification\
│   └── exports\
├── runtime\
└── protected\
```

Configuration should follow Byte-MCP's existing `Settings` pattern through explicit state/database environment settings. A relative repository-local default is not acceptable for VCL authoritative state.

SQLite is the authoritative structured validation ledger. The existing JSONL audit remains a separate operational/security evidence stream.

Initial persistence uses Python's standard-library `sqlite3`; no new database dependency is required for V1.

Semantic/vector indexes, if later introduced, are derived indexes only and can never become authoritative state.

---

# 2. Authority and threat model

## Actors

The system models five internal authority principals:

```text
BYTE_ENGINEERING
OX_VALIDATOR
META_EVALUATOR
NOLAN_OPERATOR
VCL_SYSTEM
```

Principals represent execution authority classes, not usernames.

### Nolan

Nolan remains human project authority for:

- what is built;
- intended behavior;
- product/architectural trade-offs;
- protocol phase activation;
- final stage acceptance.

Nolan is not required to compile review bundles, reproduce findings, adjudicate code defects, score twins, or inspect raw database/audit state.

### Byte

Byte owns the technical engineering process end-to-end:

- subsystem scope;
- implementation;
- deterministic verification;
- review initiation;
- evidence-based adjudication;
- reproduction;
- remediation;
- revalidation;
- final technical recommendation.

Byte is denied protected validator-behavior information such as aggregate OX calibration, category-specific weakness profiles, active probe ground truth, future probe selection, and blinded twin-mode mappings.

### OX

OX is the independent external validator. OX may:

- inspect a frozen review bundle;
- use review-scoped read-only repository/history tools where permitted;
- retrieve allowed historical engineering context in ASSISTED/INFORMED mode;
- submit structured immutable findings;
- propose future context candidates.

OX may not:

- mutate repository state;
- execute arbitrary VCL writes;
- modify review mode;
- modify Byte adjudications;
- access validator-behavior META data;
- access active probe identity or ground truth.

### META

META evaluates the validator system rather than the code. META may handle:

- COLD-vs-ASSISTED comparisons;
- blinded finding matching;
- canary/probe scoring;
- confidence calibration;
- aggregate validator behavior.

META does not adjudicate or alter engineering conclusions.

### VCL system

`VCL_SYSTEM` is deterministic internal machinery for:

- migrations;
- bundle freezing;
- mode scheduling;
- validity checks;
- dependency propagation;
- backups;
- protected-state transitions.

It is never a model-facing caller.

## Threats addressed

The design explicitly addresses:

1. reviewer anchoring from stale historical context;
2. Byte profiling OX and optimizing toward its blind spots;
3. OX self-calibration contamination;
4. evidence starvation through manual review-bundle curation;
5. historical record rewriting;
6. hidden review-mode switching;
7. probe/canary leakage;
8. VCL becoming a general conversational memory channel;
9. VCL database/artifact exposure through ordinary Byte-MCP filesystem tools;
10. prompt injection from repository content;
11. runtime self-modification bypassing VCL protections;
12. future broader shell/process/computer authority bypassing the supported-tool model.

The V1 threat model does not claim Byzantine protection against a malicious local OS administrator able to rewrite the runtime, database, audit, secrets, and backups simultaneously.

---

# 3. Core domain model

The VCL models durable validation events rather than conversational transcripts.

```text
Review
 ├── ReviewBundle
 ├── ModeAssignment
 ├── Finding*
 │    ├── Evidence*
 │    ├── ReproductionArtifact*
 │    └── Adjudication
 │         └── Remediation*
 │              └── Revalidation*
 ├── ContextExposure*
 ├── ProtocolEvent*
 └── Probe?            [protected]

ContextRecord*
 ├── ValidityAnchor*
 └── ProvenanceEdge*

MetaEvaluation*        [protected]
```

## Review lifecycle

```text
CREATED
  ↓
BUNDLE_FROZEN
  ↓
SUBMITTED
  ↓
UNDER_REVIEW
  ↓
FINDINGS_RECEIVED
  ↓
ADJUDICATING
  ↓
REMEDIATING          [if required]
  ↓
REVALIDATING         [if required]
  ↓
CLOSED
```

Exceptional terminal states:

```text
CANCELLED
FAILED
DEFERRED
```

Once a review reaches `BUNDLE_FROZEN`, its mode, candidate identity, target revision, and frozen bundle identity are immutable.

## Review bundle

A bundle is exactly the engineering material OX was allowed to see.

Each bundle records:

- `bundle_id`;
- `review_id`;
- manifest hash;
- packager version;
- bundle-entry roles;
- relative paths;
- content hashes;
- byte sizes;
- source revision/candidate identity;
- raw deterministic verification artifacts.

Large immutable payloads may live in the private artifact store; SQLite stores authoritative identity, metadata, and hashes.

## Finding

OX findings are immutable technical claims and require:

- finding ID;
- review ID;
- category;
- severity;
- calibrated confidence in `[0,1]`;
- falsifiable claim;
- affected scope;
- evidence references;
- concrete reproduction recipe;
- disproof condition;
- creation time;
- source validator;
- material VCL context dependencies when applicable.

Corrections create superseding findings rather than edits in place.

## Adjudication

Adjudication records Byte's technical determination without modifying OX's original finding.

**Final model:** technical correctness and engineering disposition are separate.

`technical_outcome`:

```text
CONFIRMED
DISPROVED
DEFERRED
DUPLICATE
```

`disposition`:

```text
REMEDIATE
ACCEPT_RISK
NO_ACTION
DEFER
```

`DISPROVED` requires counter-evidence that addresses the finding's disproof condition. Failure to reproduce alone is insufficient and normally results in `DEFERRED`.

## Remediation

A remediation records an engineering change claimed to address a confirmed finding:

- remediation ID;
- finding ID;
- implementation revision/candidate identity;
- changed paths;
- verification artifacts.

A remediation does not itself prove closure.

## Revalidation

Revalidation stages:

```text
BLIND
TARGETED
```

Results:

```text
PASS
FAIL
INCONCLUSIVE
```

Blind revalidation receives the remediated engineering candidate without the original finding/adjudication/remediation narrative. Targeted revalidation intentionally receives the prior finding and repair evidence.

## Context records

Permitted context types:

```text
PROTOCOL
CODEBASE
ADJUDICATION
PROCESS
```

Prohibited concepts include generic conversational memory, relationship memory, and unrestricted notes.

A context record has independent ingestion and substantive validity states.

Ingestion:

```text
PROPOSED
VALIDATING
ACCEPTED
REJECTED
```

Substantive status:

```text
CURRENT
STALE
SUPERSEDED
INVALID
UNKNOWN
```

Classification:

```text
ENGINEERING
META
```

---

# 4. SQLite persistence model

## Infrastructure tables

Minimum infrastructure includes:

```text
schema_migrations
  migration_id TEXT PRIMARY KEY
  applied_at_utc TEXT NOT NULL
  migration_hash TEXT NOT NULL

database_metadata
  key TEXT PRIMARY KEY
  value TEXT NOT NULL
  updated_at_utc TEXT NOT NULL
```

Migration files are immutable once released. A historical migration hash mismatch fails startup closed.

## Core engineering tables

The implementation should provide strongly constrained equivalents of:

```text
reviews
review_bundles
bundle_entries
findings
finding_evidence
reproduction_artifacts
adjudications
adjudication_artifacts
remediations
remediation_paths
remediation_artifacts
revalidations
context_records
context_sources
validity_anchors
validity_anchor_files
provenance_edges
context_retrievals
context_retrieval_results
mode_assignments
protocol_events
validator_executions
operation_journal
```

Protected META storage includes equivalents of:

```text
validator_probes
protected_probe_ground_truth
meta_evaluations
meta_evaluation_inputs
protected_unblinding
validator calibration / protected research records
```

Exact physical table names may change during implementation if the resulting schema preserves this domain model and invariants.

## Identifiers

Domain identifiers are opaque, application-generated, non-sequential public IDs, preferably time-sortable random identifiers with readable type prefixes.

SQLite `rowid` is never the public protocol identity.

## Timestamps

Authoritative timestamps are UTC, ISO-8601, timezone-explicit.

## Transaction rules

Every meaningful lifecycle transition spanning multiple records occurs inside one SQLite transaction.

SQLite connection defaults for authoritative operation:

```text
PRAGMA foreign_keys = ON
PRAGMA journal_mode = WAL
PRAGMA synchronous = FULL
bounded busy_timeout
```

V1 permits one authoritative Byte-MCP writer process per VCL database. Application-level domain mutations are serialized conservatively.

## Deletion

Review, finding, adjudication, remediation, revalidation, context, and protocol-history records are never hard-deleted through normal VCL operation.

Corrections use supersession, invalidation, cancellation, or new linked records.

---

# 5. Review modes

Every review has exactly one immutable mode:

```text
COLD
ASSISTED
INFORMED
META
```

A review never transitions between modes. A follow-up under a different mode is a new linked review.

## COLD

COLD receives only:

- active protocol instructions;
- the current frozen review material;
- no codebase history;
- no previous findings;
- no adjudication history;
- no validator behavioral data.

Historical retrieval calls in COLD are denied and audited.

COLD remains a permanent reference/control instrument and may never be deprecated by later VCL capability.

## ASSISTED

ASSISTED receives the current bundle plus explicit, validity-controlled access to eligible historical **engineering** context.

Past findings are not automatically injected by default. OX explicitly recalls or looks up context through structured tools.

ASSISTED never receives validator-behavior META data.

## INFORMED

INFORMED intentionally exposes selected engineering history for tasks such as:

- targeted revalidation;
- disputed-finding follow-up;
- completeness review;
- historical recurrence investigation.

Its assignment reason is a defined protocol category, not free text such as `NEEDS_MORE_CONTEXT`.

## META

META evaluates validator behavior and experiments. It is not an ordinary engineering-review mode and cannot mutate production engineering conclusions.

---

# 6. Context ingestion

The VCL stores structured engineering evidence, not conversational memory.

## Allowed sources

Context may derive only from structured authoritative sources such as:

- finalized reviews;
- immutable findings;
- adjudications;
- reproduction artifacts;
- remediation;
- revalidation;
- mechanically established repository facts;
- versioned protocol definitions;
- validation-system process records.

No generic `memory_add(text)` / `context_write(text)` / `remember_this(text)` interface exists.

OX may submit a typed **proposal**, but cannot persist a `CURRENT` context record directly.

Every candidate must pass:

1. schema validation;
2. source/provenance validation;
3. subject classification;
4. validity-anchor construction where applicable;
5. duplicate/conflict analysis;
6. policy decision.

## Engineering vs META classification

The primary subject determines classification.

ENGINEERING includes code, repository behavior, concrete defects, invariants, interfaces, review events, case-level adjudications, remediations, and protocol rules.

META includes OX tendencies, category-level performance, aggregate false positives/negatives, confidence calibration, retrieval behavior, and cross-review validator patterns.

If removing OX's identity/history would materially change a record's meaning, it is validator-behavior data.

Ambiguous ENGINEERING-vs-META candidates fail conservatively into META.

## Basic Memory boundary

Basic Memory Cloud may store design documentation *about* VCL, but Basic Memory content must never be directly ingested, retrieved, or injected as VCL validator context.

There is no Basic Memory note-ID, URL, Markdown dump, or free-prose ingestion route into VCL.

---

# 7. Retrieval policy

Retrieval is **policy-first, relevance-second**.

The processing order is:

```text
principal authorization
→ review-mode authorization
→ classification filter
→ repository scope
→ subsystem/boundary scope
→ validity/applicability
→ context-type filter
→ exact/structured match
→ semantic/text relevance
→ bounded result set
→ exposure provenance
```

Semantic similarity may never restore a record rejected by any preceding policy stage.

## OX-facing context operations

Conceptual operations:

```text
context_recall(review_id, query, subsystem?, type?, max_results?)
context_lookup(review_id, context_id)
context_validate(review_id, context_id)
context_propose(...)
```

The active repository is inherited from the frozen review and is not a caller-controlled widening parameter.

## Applicability states

```text
VERIFIED_CURRENT
COMPATIBLE
STALE
CONFLICTED
UNKNOWN
HISTORICAL_ONLY
```

`VERIFIED_CURRENT` requires exact valid anchors or explicit new validation evidence.

Semantic/LLM similarity cannot establish current applicability.

ASSISTED ordinary recall favors valid current/compatible context and may return historical-only evidence with explicit labels. Stale, unknown, or conflicted records cannot masquerade as current facts.

Explicit lookup may return inspectable stale history when authorized, clearly labelled.

## Exposure provenance

The system distinguishes:

```text
record existed
record was eligible
record was retrieved
record was exposed
record materially informed a finding
```

Every context record exposed to OX is provenance-bearing.

Findings that materially rely on VCL context declare the relevant context IDs and dependency strength.

---

# 8. Git validity and staleness

Historical validity and current applicability are separate.

A codebase proposition established against revision A remains a valid historical statement even after revision B makes it stale.

## Anchors

Supported anchor concepts include:

```text
REVISION
FILE_HASH
SCOPE_SET
```

A codebase fact uses the smallest defensible set of material source/boundary files needed to establish the proposition.

Applicability is evaluated against the **frozen review target revision/candidate**, never mutable current HEAD.

Possible mechanical checks:

```text
EXACT_MATCH
CHANGED
MISSING
UNAVAILABLE
```

These produce the higher-level applicability states.

Changed anchors make a proposition stale unless it is explicitly revalidated. Similar-looking new code does not automatically refresh validity.

Formal review candidates must have immutable identities. Uncommitted work must be frozen through an artifact/candidate identity such as base revision + normalized diff + file hashes rather than treated as a mutable directory state.

Git validity access is read-only: resolve commit, read file at commit, list changed paths, diff revisions, inspect history. It does not require checkout/reset/merge/push.

---

# 9. Context conflicts and dependency invalidation

Conflicting accepted context records over compatible scopes create explicit conflict state rather than retrieval ranking deciding which one is true.

Conflict resolution states may include:

```text
NOT_A_CONFLICT
OLDER_RECORD_SUPERSEDED
NEW_RECORD_INVALID
BOTH_VALID_DIFFERENT_SCOPES
UNRESOLVED
```

Until resolved, conflicting context is not presented as unquestioned current truth.

## Dependency graph

Provenance relationships are typed, e.g.:

```text
REVIEW_USES_BUNDLE
BUNDLE_CONTAINS_ENTRY
REVIEW_EXPOSED_CONTEXT
FINDING_RAISED_IN_REVIEW
FINDING_SUPPORTED_BY
FINDING_MATERIALLY_INFORMED_BY_CONTEXT
FINDING_BACKGROUND_CONTEXT
ADJUDICATION_OF_FINDING
ADJUDICATION_SUPPORTED_BY
REMEDIATION_ADDRESSES_FINDING
REVALIDATION_TESTS_REMEDIATION
CONTEXT_DERIVED_FROM
CONTEXT_SUPERSEDES
REVIEW_FOLLOWS_REVIEW
PROTOCOL_EVENT_AFFECTS_REVIEW
```

Dependency strengths:

```text
MATERIAL
SUPPORTING
BACKGROUND
```

If a material upstream context record becomes invalid/conflicted, downstream conclusions are **flagged for review**, not silently rewritten.

Examples:

```text
Finding → DEPENDENCY_REVIEW_REQUIRED
Adjudication → BASIS_REVIEW_REQUIRED
Remediation → HISTORICAL_BASIS_REVIEW_REQUIRED
```

The graph expresses dependence, not automatic logical falsity.

---

# 10. Actor-facing tools and API contracts

The system exposes domain actions, never raw storage primitives.

There is no generic SQL, unrestricted ledger export, arbitrary history browse, or generic write-memory tool.

## Byte-facing engineering operations

Conceptual operations include:

```text
ox_review_create
ox_review_status
ox_review_get_bundle_manifest
ox_findings_list
ox_finding_get
ox_finding_adjudicate
ox_adjudication_get
ox_remediation_record
ox_revalidation_request
ox_revalidation_status
vcl_integrity_status
vcl_review_audit_summary
```

Byte supplies engineering intent and candidate scope. Byte does not arbitrarily choose an ordinary review's COLD/ASSISTED mode.

## OX-facing review operations

Conceptual callbacks include:

```text
review_get_current
review_bundle_entry_get
review_repo_search
review_repo_symbol_lookup
review_git_diff
review_git_history
context_recall
context_lookup
context_validate
context_propose
finding_submit
finding_supersede
review_complete
```

OX repository operations are review-scoped and read-only.

A clean review must explicitly complete with `NO_FINDINGS`; silence is never interpreted as a clean review.

## META operations

META operations are not registered in the normal Byte-facing MCP catalog. Protected operations may include:

```text
meta_twin_create
meta_blinded_inputs_get
meta_match_submit
meta_unblind
meta_probe_score
meta_evaluation_finalize
```

## Identity and scope

Actor/principal is never a caller-supplied tool field.

Opaque IDs do not confer authority. Every operation checks:

- authenticated/system-assigned principal;
- capability;
- resource class;
- review/evaluation scope;
- mode;
- classification;
- lifecycle state.

Effectful operations support idempotent retry through request/idempotency identifiers. Same key + same payload returns the original committed result; same key + different payload is an idempotency conflict.

---

# 11. Authentication, authorization, secrets, and trusted runtime

The current Byte-MCP public MCP surface is Byte-facing. OX and META capability surfaces should not simply be added to that same globally visible tool catalog.

Recommended topology:

```text
                     TRUSTED BYTE-MCP RUNTIME
                              |
          +-------------------+-------------------+
          |                   |                   |
      Byte MCP           OX API adapter      META evaluator
          |                   |                   |
 BYTE_ENGINEERING         OX_VALIDATOR        META_EVALUATOR
          |                   |                   |
          +-------------------+-------------------+
                              |
                         VCL policy layer
                              |
                    scoped SQLite connections
```

OX API tool callbacks close over a server-created review execution context containing review ID, repository, target revision, mode, protocol version, allowed capabilities, and expiry.

META evaluation callbacks similarly close over evaluation/stage context.

## Database defense in depth

The VCL connection factory conceptually exposes:

```text
engineering()
validator(review_context)
meta(evaluation_context)
system()
```

Engineering and validator connections deny protected META tables below the service layer where practical using SQLite connection authorization hooks/policies.

Row-level review scope remains enforced in the application/service layer.

## Secrets

Secrets never become VCL records and never live beneath approved Byte-MCP filesystem roots.

Protected material includes:

- OX API credential;
- scheduler HMAC secret;
- protected-payload encryption/key material;
- session/signing secrets if introduced.

Secrets must be retrievable only by the trusted Byte-MCP runtime identity and must never be logged.

## Trusted runtime boundary

Byte may develop the Byte-MCP source repository but must not silently replace the active runtime responsible for enforcing VCL protections.

Future deployment should separate development source from the accepted running runtime, e.g.:

```text
AIProjects\Byte-MCP
    → verified build/acceptance
    → %LOCALAPPDATA%\Byte-MCP\runtime\
```

The active runtime carries an integrity manifest including version, build commit, package hash, protocol version, and deployment identity.

Runtime-integrity failure blocks protected VCL/META mutation.

If Byte later gains unrestricted shell, process-control, computer-use, or comparable authority, the VCL threat model must be formally revisited before those capabilities coexist with protected validator data.

---

# 12. Deterministic COLD scheduling

Review-mode assignment is policy-owned.

Operational phases:

```text
PHASE_1_BASELINE
PHASE_2_ASSISTED_PILOT
PHASE_3_OPERATIONAL
```

Phase 1 ordinary independent reviews use `ALL_COLD`.

Later fractional scheduling uses deterministic-but-unpredictable assignment:

```text
HMAC-SHA256(scheduler_secret, canonical immutable candidate inputs)
```

Canonical inputs include policy version, repository ID, subsystem ID, review candidate identity, target revision, and review type.

The secret prevents Byte or OX from predicting future control assignments while the stored canonical input, key epoch, bucket, decision, and policy version support later verification.

Equivalent retries of the same candidate do **not** resample mode.

## COLD debt

A required COLD observation that becomes invalid after review execution creates a persistent `cold_debt_pending` obligation.

The next eligible independent review is forced COLD until a valid COLD observation completes.

A deliberately abandoned candidate before review execution does not automatically create meaningless debt.

A later policy may also set a maximum permitted gap between valid COLD observations; its empirical value is not fixed in this design.

---

# 13. Twin-review experiments

Formal twins are scheduler-generated, not manually assembled by Byte.

A twin pair shares:

- repository;
- target revision/candidate;
- subsystem;
- objective;
- protocol version;
- **identical frozen bundle manifest**.

The intended difference is historical-context availability.

The two arms run in separate OX sessions with no conversational continuity.

Execution order may be scheduler-controlled to reduce first/second-run bias.

Mode mapping is hidden from the meta-evaluator and from Byte during formal engineering adjudication until the pre-unblind result is frozen.

---

# 14. Canary/probe framework

Canaries measure the validator system without becoming training material for either side.

Three protected concepts:

```text
ProbeTemplate
ProbeInstance
ProbeExecution
```

The public repository may contain probe-framework interfaces, schemas, and explicitly non-scored fixtures.

The active scored template corpus, mutation operators, instances, ground truth, usage history, and adaptive selection state remain protected META material outside approved roots.

## Probe construction

Preferred execution:

```text
accepted engineering candidate
→ protected isolated copy/worktree
→ deterministic protected mutation
→ mechanical ground-truth verification
→ frozen ordinary-looking review bundle
→ OX review
→ destroy mutable probe workspace
```

Known-bad probe code is never deployed merely for calibration.

Positive probes require mechanical ground truth established before OX reviews them.

Negative controls use the same protected construction path but contain no planted target defect.

Review-visible metadata must not leak positive/negative status, probe/template IDs, canary terminology, mutation descriptions, or ground-truth paths.

Probe identity and ground truth remain sealed throughout OX review and Byte adjudication. Only after protocol-defined engineering closure may META unblind and score the observation.

Experimental contamination invalidates the calibration observation but does not automatically invalidate legitimate engineering findings produced during that review.

Incidental real findings are adjudicated normally and are not false positives merely because they differ from the planted target.

Canary scoring distinguishes validator detection from Byte adjudication correctness.

---

# 15. Blinded meta-evaluation

Formal twin scoring follows:

```text
TWIN_CREATED
→ ARMS_EXECUTED
→ FINDINGS_FROZEN
→ BLINDED_MATCHING
→ MATCHES_FROZEN
→ BLINDED_ENGINEERING_ADJUDICATION_COMPLETE
→ PRE_UNBLIND_METRICS_FROZEN
→ UNBLIND
→ MODE_COMPARISON_GENERATED
→ META_EVALUATION_CLOSED
```

## Finding matching

The scoring unit is an underlying **defect cluster**, not raw prose finding count.

Findings are matched using:

- defect mechanism;
- affected-scope compatibility;
- reproduction compatibility;
- disproof compatibility;
- supporting structured signals.

Outcomes:

```text
EXACT_MATCH
PROBABLE_MATCH
DISTINCT
AMBIGUOUS
```

One-to-many and many-to-one clusters are permitted when sessions decompose one underlying mechanism differently.

Ambiguity remains explicit rather than being forced into whichever classification favors a mode.

## Metrics

Primary dimensions include:

- confirmed defect recall;
- false-positive burden;
- deferred burden;
- evidence/reproduction quality;
- novel confirmed finding yield;
- COLD-only versus ASSISTED-only confirmed defects.

Secondary operational metrics may include review latency, cost, finding count, confidence distribution, retrieval count, and context usage.

Confidence calibration, OX weakness profiles, and retrieval behavior analytics remain META-only.

Phase 1/2 should not collapse performance into a single composite score.

A formal comparison may eventually be summarized as `COLD superior`, `ASSISTED superior`, `NO MATERIAL DIFFERENCE`, `MIXED`, or `INCONCLUSIVE`, but only from pre-registered multidimensional rules.

Adjudication inconsistencies across findings already matched as the same defect must be reconciled or explicitly remain unresolved **before** unblinding.

---

# 16. Failure, recovery, and degraded operation

Failure classes:

```text
TRANSIENT
EXTERNAL
INTEGRITY
PERSISTENCE
SECURITY
```

Retry is appropriate for bounded availability failures such as temporary SQLite lock or OX transport failure.

Retry is not a permissive response to trust failures such as artifact mismatch, runtime-manifest failure, migration-history tampering, authorization ambiguity, or provenance corruption.

## Transport and idempotency

If a mutation commits but the response is lost, retry with the same request ID returns the original authoritative result and does not create a duplicate.

If OX submits findings and transport then fails before `review_complete`, committed findings remain evidence but the review is `INCOMPLETE_VALIDATOR_RESPONSE` and cannot count as a valid completed COLD/twin observation.

No silence is interpreted as `NO_FINDINGS`.

## Runtime restart

Non-terminal review/execution state survives Byte-MCP restart.

Recovery classifies interrupted reviews/executions as resumable, waiting external, recovery-required, or failed. It never blindly replays remote calls without checking durable execution state.

## Artifact failure

Missing or corrupt frozen artifacts are never regenerated under the same artifact/bundle identity.

Exact restoration is allowed only when the restored hash matches the original recorded hash bit-for-bit. Otherwise a new identity/review is required.

## Database health

VCL runtime health modes:

```text
NORMAL
READ_ONLY_DEGRADED
UNAVAILABLE
```

Integrity corruption stops VCL mutation. The damaged database is preserved; automatic delete-and-recreate is forbidden.

Formal validation requires authoritative VCL persistence even for COLD reviews because provenance, mode, findings, and completion state must remain trustworthy.

## Backup

Backups use SQLite's supported online backup approach rather than copying a live WAL database casually.

A recoverable checkpoint includes:

- database snapshot;
- artifact manifest/content availability;
- hashes;
- schema version;
- runtime/protocol version;
- checkpoint identity.

Protected META backup data remains separately encrypted/protected from ordinary engineering recovery material.

Restore always occurs into a new recovery location, verifies database/artifact/runtime compatibility, produces a recovery report, and requires explicit activation.

Recovery never overwrites the only damaged state first.

Any unreconstructable post-backup data becomes a permanent `RECOVERY_GAP` / `PROVENANCE_GAP`, not silently omitted history.

---

# 17. Audit, observability, and privacy

The independent JSONL audit remains separate from SQLite VCL provenance.

```text
VCL provenance = engineering/epistemic evidence
JSONL audit    = operational/security evidence
telemetry      = current operational measurements
reports         = derived human-readable interpretation
```

## Audit event envelope

Conceptual safe fields:

```text
timestamp_utc
event_id
action
outcome
principal
request_id
review_id
resource_class
opaque resource_id
reason_code
runtime_version
protocol_version
safe operational counts/timing
```

Actions are stable and namespaced, e.g. `vcl.review.create`, `vcl.finding.submit`, `vcl.authorization.deny`, `ox.execution.start`.

Outcomes use a bounded vocabulary such as:

```text
SUCCESS
DENIED
FAILED
ABORTED
RETRY
DEGRADED
```

## Audit minimization

Ordinary audit logs must never contain:

- API credentials;
- scheduler secrets;
- encryption keys;
- session tokens;
- active probe ground truth/template content;
- protected mode mappings before unblinding;
- full source payloads;
- unnecessary raw prompts/transcripts;
- protected validator analytics.

Use opaque IDs and fingerprints where correlation is sufficient.

Original findings live in VCL, not duplicated into audit logs.

## Reconciliation

Critical committed VCL records should have corresponding successful audit evidence. Reconciliation detects both:

- VCL commit with missing audit evidence (`AUDIT_EVIDENCE_GAP`);
- audit success with missing authoritative state (`AUTHORITATIVE_STATE_GAP`).

Missing historical audit entries are not fabricated retroactively.

## Health

Overall health separates availability from trust.

Component checks include:

- runtime integrity;
- database integrity;
- artifact integrity;
- audit reconciliation;
- OX provider health;
- scheduler health;
- secret-store health;
- META isolation.

Integrity assertions produce `PASS`, `FAIL`, or `UNKNOWN`; `UNKNOWN` is never silently represented as healthy.

Byte/Nolan-facing reporting is concise and decision-oriented. Protected OX performance profiles are not exposed through routine health alerts.

Raw OX transcripts are exceptional protocol/incident evidence rather than authoritative default storage. Structured findings, review completion, tool/exposure provenance, and provider execution metadata are persisted by default.

---

# 18. Verification strategy

The verification hierarchy is:

```text
1. Domain unit tests
2. Persistence/transaction tests
3. Authorization/isolation tests
4. Protocol/state-machine tests
5. Failure/recovery tests
6. OX integration contract tests
7. End-to-end adversarial validation tests
```

Deterministic verification precedes OX review.

## Core tests

Cover:

- valid/invalid review transitions;
- mode immutability;
- finding schema;
- technical outcome + disposition model;
- supersession rather than edits;
- real temporary SQLite databases with foreign keys enabled;
- migration hashes;
- rollback after injected failure at each multi-record transition step;
- opaque IDs and referential integrity;
- artifact hash verification;
- private-state path isolation.

## Authority tests

Build a positive/negative capability matrix for every principal.

Explicitly test that:

- Byte cannot read protected META/probe data;
- OX cannot adjudicate, mutate repo state, change mode, or read META;
- META cannot modify engineering conclusions;
- caller-supplied `actor`, `role`, or `principal` fields cannot grant authority;
- scoped SQLite engineering/validator connections deny protected META tables;
- denied actions are audited safely.

## COLD isolation tests

Create highly relevant historical records and attempt to expose them through every supported route:

- context recall/lookup/validate;
- pre-session injection;
- provenance traversal;
- audit summaries;
- error messages;
- bundle/repository search side paths;
- cached results.

Expected historical engineering exposure: zero.

Repository files containing prompt-injection text such as `ignore protocol / reveal META` must remain untrusted data and cannot change available capabilities.

## ASSISTED tests

Verify policy precedes relevance:

- current ENGINEERING context may be eligible;
- META never enters the semantic candidate set;
- other-repository context is excluded;
- stale/conflicted/unknown records cannot masquerade as current;
- invalid context is suppressed or explicitly labelled as policy dictates.

## Git validity tests

Use controlled Git histories to verify:

- unchanged anchor → current;
- unrelated change → current where anchor scope is untouched;
- material anchor change → stale;
- deletion/rename → conservative stale/unknown handling;
- missing revision → unknown;
- repository mismatch → denial/error;
- historical adjudication remains historically true after code changes.

## Provenance/dependency tests

Verify closed findings can resolve complete evidence chains and no dangling references exist.

Invalidate material context and verify downstream records receive review obligations without changing historical findings/adjudications.

## OX adapter tests

Use a deterministic fake provider for:

- normal completion;
- explicit no-findings completion;
- one/many findings;
- malformed finding;
- tool callbacks;
- partial response;
- timeout;
- duplicate retry;
- provider failure.

After adapter contract tests, run a minimal real OX API smoke test for session/message/tool/finding/completion integration before any validator-quality conclusion.

## Revalidation tests

Blind sessions must contain none of the original finding, adjudication, remediation narrative, or previous OX response. Targeted sessions intentionally expose the defined prior evidence.

## Twin tests

Verify:

- bundle manifest identity between arms;
- separate OX sessions;
- no mode side-channel in IDs/order/timestamps/API shape exposed to the evaluator;
- Byte adjudication remains mode-blind;
- same-defect matcher handles exact/probable/distinct/ambiguous/one-to-many cases;
- pre-unblind results are immutable.

## Probe tests

Before any hidden scored corpus exists, public dry-run probes must prove:

- isolated workspace;
- no mutation of real branch;
- mechanical positive ground truth;
- valid negative controls;
- no canary metadata leakage;
- Byte/OX denial of protected ground truth;
- stage-controlled META unblinding;
- contamination detection;
- deterministic cleanup and frozen-bundle reproducibility.

## Failure/recovery tests

Inject failure into:

- SQLite writes;
- artifact writes/reads;
- audit append;
- OX request/response;
- Git validation;
- migrations;
- secret retrieval;
- runtime integrity.

Test crash after DB commit but before response and prove idempotent retry returns the original result.

Test verified backup/restore, corrupt backup rejection, second-writer detection, audit reconciliation, and recovery gaps.

## Leakage tests

Seed known fake secrets/ground truth and assert zero occurrence in generated audit logs, normal error responses, integrity reports, and ordinary manifests.

## Verification gates

Named gates:

```text
A Core
B Authority
C Protocol
D Resilience
E OX Integration
F Experimental Integrity
G Full Subsystem
```

Existing Byte-MCP regression tests and repository linting remain mandatory.

Every confirmed authority/integrity defect discovered during development becomes a permanent deterministic regression test where feasible.

OX external review supplements deterministic verification; it never replaces executable evidence.

---

# 19. Phased activation

## Phase 1 — Formal COLD baseline

Phase 1 operational loop:

```text
Byte implementation
→ deterministic verification
→ freeze review candidate
→ COLD OX review
→ structured findings
→ Byte evidence adjudication
→ remediation
→ blind revalidation
→ targeted revalidation where required
→ Byte technical recommendation
→ Nolan acceptance
```

### Phase 1 production capability

The first bounded implementation subsystem is **OX Validation Core / Phase 1**, containing:

- domain contracts;
- SQLite repository + migrations;
- private state/artifact layout;
- review lifecycle;
- deterministic bundle freeze/manifest;
- OX execution adapter abstraction and real integration;
- structured immutable findings;
- technical outcome + engineering disposition adjudication;
- remediation;
- blind/targeted revalidation;
- core provenance;
- audit integration;
- COLD enforcement;
- essential recovery;
- Phase 1 verification.

### Explicit Phase 1 non-goals

Do not activate production:

- ASSISTED retrieval;
- semantic/vector index;
- formal twin scoring;
- adaptive scheduler fractions;
- hidden scored probe corpus before its own gate;
- broad META analytics;
- complex audit hash chaining;
- multi-process authoritative writers;
- Postgres.

Phase 1 may accumulate accepted/anchored future engineering context records, but OX cannot retrieve them.

### Legacy vs formal COLD

Historic pre-VCL reviews may be recorded as `LEGACY_COLD` where evidence can be reconstructed. They are useful observations but do not automatically meet formal experimental standards.

`FORMAL_COLD` requires frozen candidate/bundle identity, protocol version, explicit completion, structured findings/no-findings record, zero historical exposure, audit reconciliation, and review-integrity evidence.

### First milestone

**OX-V1 — Formal COLD External Validation** is accepted when Byte can independently prepare and run the complete deterministic review/adjudication/remediation/revalidation loop and present Nolan a technically grounded closeout without Nolan acting as senior code reviewer.

## Phase 2 — ASSISTED pilot

ASSISTED remains disabled until:

1. sufficient valid formal COLD baseline exists;
2. context records demonstrate sound provenance/classification/validity/conflict handling;
3. retrieval isolation proves no META/cross-repo/stale masquerading/COLD leakage;
4. twin dry-run infrastructure passes identical-bundle, isolation, blinding, adjudication, and pre-unblind gates;
5. no unresolved critical authorization, artifact, runtime, audit, or provenance integrity failures remain.

The protected system may then recommend Phase 2 readiness, but Nolan explicitly approves activation.

Phase 2 begins with selected **COLD/ASSISTED twins**, not broad ordinary ASSISTED rollout.

Initial ASSISTED uses explicit structured/text recall and lookup. Embeddings are deferred until evidence demonstrates a need.

## Phase 3 — Operational

Only after Phase 2 evidence supports historical-context value may ordinary scheduling use an empirically selected mixture of mandatory COLD and ASSISTED reviews, with INFORMED used by protocol and META isolated.

COLD remains permanent regardless of ASSISTED success.

---

# 20. Empirical parameters deliberately unset

These values are not architectural defaults and must be set only through versioned policy after evidence exists:

```text
COLD review fraction
maximum COLD gap / final control cadence
exact deterministic bundle-expansion thresholds/rules
formal twin finding-match numeric thresholds
retrieval ranking weights/parameters
probe frequency/cooldown values
minimum formal COLD count for Phase 2 readiness
```

When a phase requires one of these values, `NULL`/unset causes `POLICY_CONFIGURATION_INCOMPLETE`; the system must not silently invent a convenient default.

---

# 21. Implementation decomposition

After this written design is accepted, implementation planning should use bounded subsystem chunks rather than component-by-component human approvals.

Recommended sequence:

## Subsystem 1 — OX Validation Core / Phase 1

Build the formal COLD loop end-to-end.

## Subsystem 2 — VCL Historical Context Core

Implement:

- context records;
- typed ingestion;
- ENGINEERING/META classification;
- validity anchors;
- Git applicability;
- conflict handling;
- context/provenance dependencies;
- structured recall/lookup;
- ASSISTED isolation verification.

ASSISTED remains disabled until its activation gate passes.

## Subsystem 3 — Validator Evaluation Core

Implement:

- twin pairing;
- blinding;
- defect clustering;
- pre-unblind freezing;
- protected probe framework/corpus boundary;
- META evaluation;
- experimental scheduler controls.

Hidden scored probes activate only after their own gate.

---

# 22. Security and protocol invariants

The following invariants are architectural requirements. Implementation names may vary, but behavior may not weaken them without an explicitly approved design revision.

1. **Validator state isolation:** no supported Byte-MCP filesystem capability may resolve, search, fetch, or expose the VCL DB, WAL/SHM, backups, protected artifacts, or live-data migrations/exports.
2. **Authorization ambiguity fails closed.**
3. **Historical evidentiary meaning is not edited in place; corrections create linked records.**
4. **Frozen input identity:** frozen bundle, mode, target revision/candidate, and manifest cannot change.
5. **Claims and conclusions are separate records.**
6. **Evidentiary history is append-oriented.**
7. **Transactional state transitions commit completely or not at all.**
8. **No ordinary hard deletion of validation history.**
9. **External authoritative artifacts are hashed and verified before use.**
10. **Single-writer authority for VCL V1.**
11. **Protected META is structurally separated from ordinary engineering access.**
12. **Review mode is immutable after freeze.**
13. **COLD means zero historical engineering exposure.**
14. **Missed required COLD observations create scheduler debt.**
15. **Twin reviews share identical frozen engineering material/protocol.**
16. **Mode selection is policy-owned, not caller-selected.**
17. **No provenance-free context.**
18. **No generic memory ingestion.**
19. **ENGINEERING-vs-META ambiguity routes to META.**
20. **CODEBASE current status requires revision validity evidence.**
21. **Basic Memory content is never directly VCL validator context.**
22. **Context conflicts fail safe and cannot be ranked away silently.**
23. **Policy precedes relevance.**
24. **COLD exposure is protocol-only.**
25. **Historical exposure is provenance-bearing.**
26. **Invalid/stale history cannot masquerade as current.**
27. **Context-dependent findings declare material dependencies.**
28. **Retrieval frequency/rank does not confer authority.**
29. **Historical truth and current applicability are distinct.**
30. **Current applicability requires exact anchors or explicit new validation.**
31. **Semantic similarity cannot establish validity.**
32. **Review validity targets frozen revision/candidate, not mutable HEAD.**
33. **Context invalidation propagates review obligations, not automatic rewritten conclusions.**
34. **Unresolved contradictions remain visible.**
35. **Every authoritative conclusion is traceable.**
36. **Exposure is distinct from mere record existence.**
37. **Later invalidation never erases prior exposure/reliance history.**
38. **Dependency propagation creates obligations, not rewritten truth.**
39. **Artifact provenance references remain hash-valid.**
40. **Protocol version is part of provenance.**
41. **Only domain actions are exposed; no arbitrary SQL/ledger primitives.**
42. **Identity is execution-context-derived, not caller-declared.**
43. **Tool availability is capability-scoped.**
44. **Lifecycle-invalid actions are rejected.**
45. **Mutations are retry-safe/idempotent.**
46. **Blindness is enforced by context construction, not model instruction.**
47. **OX never receives unrestricted ledger browsing.**
48. **Principals are system-assigned.**
49. **Protected capability surfaces are not globally exposed.**
50. **Engineering/validator DB access has defense-in-depth META denial.**
51. **Secrets are external to the ledger and approved roots.**
52. **Active probe ground truth remains sealed.**
53. **Source modification does not imply trusted-runtime modification.**
54. **Broader shell/process/computer authority requires re-threat-modeling.**
55. **Authorization/integrity failure has no permissive fallback.**
56. **Future reference/probe assignment is unpredictable to participating models.**
57. **Equivalent retries do not resample mode.**
58. **COLD debt is mechanically enforced.**
59. **Twin arms are isolated sessions.**
60. **Probe identity is protected during the engineering cycle.**
61. **Probe ground truth precedes review.**
62. **Known defects are never deployed merely for calibration.**
63. **Formal experimental scoring is pre-registered.**
64. **Public probe framework and protected scored corpus are separate.**
65. **Positive probes/negative controls do not leak experimental status through construction metadata.**
66. **Every positive probe has mechanical ground truth.**
67. **Experimental contamination is explicit and does not automatically erase legitimate engineering findings.**
68. **Validator misses and Byte adjudication errors are scored separately.**
69. **Non-target findings are adjudicated normally.**
70. **META results do not become silent validator training.**
71. **Engineering correctness/release safety outranks preserving an experiment.**
72. **Twin finding matching is frozen before mode disclosure.**
73. **Underlying defect clusters, not prose units, are the scoring unit.**
74. **Mode comparison uses adjudicated technical truth, not raw finding count.**
75. **Byte adjudicates formal twins while mode-blind.**
76. **Ambiguity remains explicit.**
77. **Pre-unblind results are immutable.**
78. **Post-unblind analysis cannot rewrite blinded results.**
79. **Technical correctness and engineering disposition are separate.**
80. **Partial work never becomes partial truth.**
81. **External transport uncertainty remains explicit.**
82. **Frozen artifacts are never regenerated under the same identity.**
83. **Integrity faults disable trust-sensitive mutation.**
84. **Recovery preserves damaged evidence before restore/activation.**
85. **Recovery gaps remain permanently visible.**
86. **Retry does not change candidate/bundle/mode/experimental assignment.**
87. **Security failures never trigger permissive retry/fallback.**
88. **Formal validation requires authoritative VCL persistence.**
89. **Audit and provenance remain independent evidence surfaces.**
90. **Audit minimizes sensitive content.**
91. **Critical audit success and VCL authoritative commits are reconcilable.**
92. **UNKNOWN is not silently treated as healthy.**
93. **Availability and trust are separate health dimensions.**
94. **Observability must not become protected behavioral leakage.**
95. **Raw model transcripts are exceptional, protocol-governed evidence.**
96. **Nolan-facing reports are decision-oriented rather than technical-log burdens.**
97. **Completed formal reviews can produce a derived review-integrity certificate.**
98. **Security boundaries have explicit negative tests.**
99. **Protocol isolation tests cover alternate retrieval/metadata/error paths.**
100. **Failure semantics are executable through fault injection.**
101. **Experimental infrastructure is dry-run verified before hidden scoring.**
102. **Deterministic evidence precedes external validation.**
103. **Capabilities cannot activate before their phase-specific gate passes.**
104. **Existing Byte-MCP behavior remains inside the acceptance regression gate.**
105. **Confirmed authority/integrity defects become permanent regression tests where feasible.**
106. **Verification claims are evidence-bound; required checks must actually complete.**
107. **Capability activation is evidence-gated even if code already exists.**
108. **Phase 1 establishes the memoryless reference baseline first.**
109. **Phase 1 may capture future context but may not expose it to OX.**
110. **ASSISTED begins experimentally through controlled evaluation.**
111. **Empirical parameters have no silent defaults.**
112. **COLD is permanent.**
113. **Negative experimental results are valid and may justify rejecting/reducing ASSISTED.**
114. **Implementation proceeds by bounded activated capability.**
115. **This accepted written specification precedes implementation planning and production coding.**

---

# 23. Acceptance criteria for the written design

Before implementation planning, this specification must be reviewed for:

- consistency between domain model and schema model;
- final corrected `technical_outcome` + `disposition` adjudication semantics;
- no remaining `ACCEPTED_RISK` truth-state usage;
- consistent mode names and lifecycle states;
- clear Phase 1 versus Phase 2/3 boundaries;
- no accidental requirement that Nolan perform technical adjudication;
- no Basic Memory ingestion route;
- no public OX/META capability leak through the ordinary Byte-facing MCP catalog;
- no repository-local authoritative VCL state;
- no hidden assumption that semantic/vector search is required in Phase 1;
- no claim that SQLite provides distributed or Byzantine security;
- explicit empirical parameters remaining unset.

After Nolan accepts the written design, the next action is to produce an implementation plan for **OX Validation Core / Phase 1**. Production code begins only from that approved plan.
