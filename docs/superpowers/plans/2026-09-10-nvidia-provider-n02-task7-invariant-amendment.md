# NVIDIA-02 Task 7 Security-Invariant Amendment

Date: 2026-09-10

This amendment is authoritative for Task 7 of `2026-09-09-nvidia-provider-n02-lightning-canary-implementation-plan.md`.

## Trigger 1 — documentation scope

The initial Task 7 security-invariant test correctly found the literal hosted-key prefix sentinel in the implementation-plan documentation itself. The occurrence was descriptive documentation, not a credential or runtime secret, and no production/runtime invariant failed.

## Clarification

The Task 7 bullet:

> tracked NVIDIA-02 files contain no hosted NVIDIA API-key prefix sentinel

is clarified to mean:

> tracked NVIDIA-02 executable and test artifacts under `src/byte_mcp/nvidia`, `scripts/nvidia_lightning_canary.py`, and `tests/nvidia` contain no literal hosted NVIDIA API-key prefix sentinel. Design/specification/implementation-plan documentation may mention the prefix descriptively and is excluded from this sentinel scan.

This preserves the intended security property: no key-shaped sentinel or credential material is embedded in runtime code, tests, scripts, durable evidence, logs, hashes, or operator outputs.

## Trigger 2 — previously qualified synthetic test fixture

After applying the documentation-scope clarification, the Task 7 freeze found exactly one remaining literal hosted-key prefix in the executable/test scope:

`tests/nvidia/test_canary_cli.py`

The occurrence is a synthetic Task 6 credential-blindness fixture, not a real credential. A diagnostic scan confirmed it is the only remaining literal occurrence in `src/byte_mcp/nvidia`, `tests/nvidia`, and `scripts/nvidia_lightning_canary.py`.

## Authorized minimal repair

Task 7 is authorized to make one test-only, behavior-preserving sanitation change in `tests/nvidia/test_canary_cli.py`: construct the synthetic hosted-key-shaped test value from adjacent string fragments so the literal hosted-key prefix is not embedded in the tracked file.

No production source may change.

The Task 7 final governed commit scope is therefore amended from only:

- `tests/nvidia/test_n02_security_invariants.py`

to exactly these two test files:

- `tests/nvidia/test_n02_security_invariants.py`
- `tests/nvidia/test_canary_cli.py`

The required final commit message remains:

`test: freeze NVIDIA-02 canary security invariants`

## Scope

- Documentation clarification plus the single authorized test-fixture sanitation above.
- No production modification is authorized or implied.
- All other Task 7 invariants remain unchanged.
- The known replay-protection trust boundary remains unchanged: the selected local evidence root is authoritative, but rollback-resistant storage is out of NVIDIA-02 scope.
