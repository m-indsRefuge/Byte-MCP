# Byte-MCP V2 Chess Capability Contract

## Purpose

Provide Byte with one narrowly governed command channel into B87 Chess Arena without changing the V1.1 read-only file server.

## Process isolation

The chess capability runs as a separate MCP process:

```text
Byte-MCP Files  http://127.0.0.1:8000/mcp
Byte-MCP Chess  http://127.0.0.1:8001/mcp
```

The file server does not register chess tools. The chess server does not register file tools.

## Startup binding

The chess server is bound at startup to:

- one loopback Arena API base URL;
- one Arena match UUID;
- one Byte actor identity;
- one local audit ledger;
- one persistent idempotency receipt store.

Required environment variable:

```text
BYTE_MCP_CHESS_MATCH_ID=<arena-match-uuid>
```

Default actor:

```text
BYTE_MCP_CHESS_ACTOR=byte
```

## Tool contract

### `chess_get_turn`

Returns the bound match identity, authoritative FEN, state version, position hash, actor to move, and whether it is Byte's turn.

### `chess_get_match`

Returns the complete authoritative Arena match snapshot.

### `chess_get_events`

Returns a bounded slice of immutable Arena events after one sequence number.

### `chess_submit_move`

Submits exactly one UCI move with:

- expected state version;
- expected position hash;
- UCI move;
- idempotency key.

The server inserts the configured Byte actor and configured match identity. They are not caller-selectable.

## Authority boundary

Byte-MCP never changes chess state directly. It forwards one proposal to B87 Chess Arena. The Arena deterministic referee remains the sole authority that can accept a move and advance the board.

## Idempotency

Every submission requires an idempotency key. The chess server stores a persistent fingerprint and response receipt locally.

- repeating the same key with the same submission returns the stored response without a second Arena call;
- repeating the same key with different inputs is denied;
- receipts survive a chess-server restart.

## Network boundary

Both the MCP listener and Arena API target must remain loopback-only. Arbitrary URLs, HTTPS targets, remote hosts, redirects configured by callers, shell access, filesystem access, and unrestricted HTTP requests are not exposed.

## Audit

The append-only local chess audit records:

- action;
- outcome;
- match identity;
- actor;
- expected state version;
- proposed UCI move;
- accepted/rejected result;
- rejection code;
- SHA-256 idempotency-key fingerprint.

The raw idempotency key is not written to audit.

## Deferred

- multiple simultaneous match bindings;
- autonomous turn scheduling;
- legal-move disclosure;
- engine evaluation;
- match creation or deletion through MCP;
- file-system tools in the chess process;
- Byte mentorship or candidate memory.
