# OX Historical Archive

OX V1 and the abandoned OX V2 implementation are historical only. They are not runtime compatibility targets for the clean-room rebuild, and no legacy runtime state or evidence is migrated into the new OX generation.

## Current contract boundary

Current clean-room operating guidance lives in `docs/OX.md`. The current OX failure-engineering map lives in `docs/FAILURE_MAP.md`.

The former top-level operator manual `docs/OX-VALIDATION.md` and OX plans/specifications dated before the 2026-09-17 clean-room design are historical only. The operator manual has been removed from the active documentation tree so it cannot be mistaken for current guidance; its exact content remains recoverable through Git history and the archived V1 lineage. Older dated plans/specifications remain in the repository as clearly historical engineering records and are not current execution instructions.

## Implementation campaign base

- clean-room implementation branch: `feat/ox-clean-room-rebuild`
- freshly verified converged base: `61c77ed1bcaa2a1aeac2bfe3ca3f0aab8ee680c9`
- original design baseline: `fb87e39d24ee2e74f648da0495059f147f30fb89`
- relationship: the implementation base is 17 commits ahead of the original design baseline

## OX V1

- immutable archive branch: `archive/ox-v1-final`
- final/quiesced active identity: `6603a8a5f22c32483d81ff8d932adab4de7f099a`
- frozen V1 baseline: `94ff28810a06b7af2207196ac98c1152cc65b4b1`
- final evidence inventory: `qualification/ox-v1/final-evidence.json` at the archived lineage
- final recorded V1 review: `OX-000013`

## Abandoned OX V2

- immutable probe archive branch: `archive/ox-v2-probe`
- probe identity: `09e67969197aee5883e9111eb94d116245d0bd53`
- immutable design archive branch: `archive/ox-v2-design`
- amended design/plan identity: `cb4aebfa344d74279bff245773c68a1d5a57aea6`
- frozen historical probe blob: `59802c4a24fdc90a02c68a69e003462713ee3d7b`
- frozen historical probe-test blob: `fe3dd4a0bbe5e0b0a09f2ad004337cf870edea18`

The old V2 lifetime probe was never successfully deployed/run from the Web UI and is not continued by the clean-room rebuild.

## Harness adaptation

The approved implementation plan names non-head `refs/archive/*` refs. This ChatGPT/GitHub connector exposes branch creation but not arbitrary Git ref creation, so the same immutable historical identities are preserved as dedicated `archive/...` branches. No source commit was rewritten or rebased to make this adaptation.

## Active-tree policy

The clean-room implementation has removed V1/V2 execution code, execution-only tests, runtime registrations, continuation/revalidation/retry/background machinery, the superseded top-level V1 operator manual, and current README/security links to obsolete OX execution guidance. Historical source, evidence, designs, qualification artifacts, and superseded documentation remain recoverable through archive branches and Git history.
