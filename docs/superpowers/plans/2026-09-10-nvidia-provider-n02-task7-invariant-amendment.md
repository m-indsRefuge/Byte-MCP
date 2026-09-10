# NVIDIA-02 Task 7 Security-Invariant Amendment

Date: 2026-09-10

This amendment is authoritative for Task 7 of `2026-09-09-nvidia-provider-n02-lightning-canary-implementation-plan.md`.

## Trigger

The initial Task 7 security-invariant test correctly found the literal hosted-key prefix sentinel in the implementation-plan documentation itself. The occurrence was descriptive documentation, not a credential or runtime secret, and no production/runtime invariant failed.

## Clarification

The Task 7 bullet:

> tracked NVIDIA-02 files contain no hosted NVIDIA API-key prefix sentinel

is clarified to mean:

> tracked NVIDIA-02 executable and test artifacts under `src/byte_mcp/nvidia`, `scripts/nvidia_lightning_canary.py`, and `tests/nvidia` contain no literal hosted NVIDIA API-key prefix sentinel. Design/specification/implementation-plan documentation may mention the prefix descriptively and is excluded from this sentinel scan.

This preserves the intended security property: no key-shaped sentinel or credential material is embedded in runtime code, tests, scripts, durable evidence, logs, hashes, or operator outputs.

## Scope

- Documentation-only clarification.
- No production modification is authorized or implied.
- All other Task 7 invariants remain unchanged.
- The known replay-protection trust boundary remains unchanged: the selected local evidence root is authoritative, but rollback-resistant storage is out of NVIDIA-02 scope.
