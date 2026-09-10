# NVIDIA-02 Live Qualification Receipt

Date: 2026-09-10

Qualified implementation checkpoint:

`8ce92056cdfe8412cd9856eca32fb2ddacf52147`

Model:

`nvidia/nemotron-3.5-lightning-30b-a3b`

## NVC-000001

Request SHA-256:

`7a435b127a5a0347c15714badf1627351f18562532f4ea4374813fde9e293bdc`

Disposition:

`COMPLETED / SEMANTIC_MISMATCH / LENGTH_LIMIT`

Observed: HTTP 200, 64 completion tokens, finish reason `length`, semantic probe match `false`, no NVIDIA or transport failure, elapsed 31734 ms.

NVC-000001 is consumed and must not be retransmitted.

## NVC-000002

Request SHA-256:

`8a8cd3654018a92c91ca37e86e69e6470be3faa27cb400fb42c52b64553e3161`

Payload SHA-256:

`ee395e1fae6dc05980c9eacf0e49c8ea82eca3fc1965037cf7ad8fa47d0bc493`

Prepared body: 249 bytes with `chat_template_kwargs.enable_thinking=false`, `max_tokens=64`, `n=1`, and `stream=false`.

Provider start:

`2026-09-10T15:13:49.950666+00:00`

Disposition:

`COMPLETED / SEMANTIC_MATCH / STOP`

Observed: HTTP 200, 10 completion tokens, 30 prompt tokens, 40 total tokens, finish reason `stop`, semantic probe match `true`, response headers and body received, 419 decoded body bytes, no NVIDIA or transport failure, elapsed 1938 ms.

NVC-000002 is consumed and must not be retransmitted.

## Qualification conclusion

At the checkpoint above, the NVIDIA hosted path is live-qualified for immutable prepared-request identity, exactly-once transport execution, NVIDIA chat response parsing, bounded response metadata, durable provider-start and terminal evidence, and exact semantic final-content comparison for the fixed Lightning probe.

The first canary proved transport but exhausted the reasoning-enabled completion budget. The repaired second canary explicitly disabled thinking and completed the semantic probe successfully.

This receipt does not enable a general code-review MCP tool or automatic routing. Those belong to the next bounded phase, NVIDIA-03.
