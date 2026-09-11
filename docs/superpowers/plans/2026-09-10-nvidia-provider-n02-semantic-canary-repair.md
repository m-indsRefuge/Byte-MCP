# NVIDIA-02 Semantic Canary Repair Record

Date: 2026-09-10

## Scope

This record freezes the post-live-canary diagnosis and the bounded offline repair for the NVIDIA-02 Lightning semantic canary. It does not authorize another provider request.

Pre-repair qualified checkpoint:

`de38dbce83a38f44aa36a4cfb4c9275a37fbd7f3`

Model:

`nvidia/nemotron-3.5-lightning-30b-a3b`

## NVC-000001 immutable live outcome

Canary ID:

`NVC-000001`

Request SHA-256:

`7a435b127a5a0347c15714badf1627351f18562532f4ea4374813fde9e293bdc`

Bounded terminal observations:

- attempt outcome: `COMPLETED`
- HTTP status: `200`
- NVIDIA failure kind: `null`
- transport failure kind: `null`
- completion tokens: `64`
- finish reason: `length`
- semantic probe match: `false`
- elapsed time: `31734 ms`

Disposition:

`COMPLETED / SEMANTIC_MISMATCH / LENGTH_LIMIT`

`NVC-000001` is consumed. Retransmission or retry is forbidden.

## Diagnosis

The request reached NVIDIA successfully and returned a valid response that the qualified adapter parsed and terminalized. The model consumed the full fixed 64-token completion budget and terminated with `finish_reason=length` before satisfying the exact sentinel comparison.

Official NVIDIA hosted-model documentation verified on 2026-09-10 documents that Nemotron 3.5 Lightning supports an explicit chat-template control, `chat_template_kwargs.enable_thinking`, and that thinking is enabled by default. For this trivial semantic health probe, reasoning is not part of the capability being tested.

## Approved offline repair

The fixed Lightning canary request is amended to persist this additional request field:

```json
{"chat_template_kwargs":{"enable_thinking":false}}
```

All other fixed canary inputs remain unchanged:

- endpoint: `POST /v1/chat/completions`
- prompt: `Reply with exactly: BYTE_NVIDIA_CANARY_OK`
- expected text: `BYTE_NVIDIA_CANARY_OK`
- `temperature=1.0`
- `top_p=0.95`
- `max_tokens=64`
- `n=1`
- `stream=false`

The generic NVIDIA-01 chat request builder remains unchanged. The thinking control is canary-specific so the previously qualified provider-neutral and generic NVIDIA chat contracts are not broadened.

## Authorization boundary

This repair is offline only. It authorizes no NVIDIA, OX, Wolfram, or other provider/model request.

A future provider-free preparation may allocate `NVC-000002` from the real local evidence root. Any live transmission for `NVC-000002` requires a new explicit authorization bound to that exact canary ID and its exact newly prepared request SHA-256.
