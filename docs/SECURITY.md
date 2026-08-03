# Security

Byte-MCP V1 is a local data-access boundary, not a general remote-control service.

## Default-denied material

The implementation blocks common secret-bearing names and locations, including:

- `.env`
- `.git`
- `.ssh`
- `.gnupg`
- `AppData`
- credential or secret directories
- private-key and password-vault file formats

The policy is intentionally conservative and can be extended.

## Prompt injection

Text found inside a retrieved file must be treated as untrusted content. It must never override Nolan's request, Byte-MCP's tool contract, or higher-level safety rules.

## Network boundary

The V1 server binds through the MCP SDK's local Streamable HTTP development defaults. Do not expose the port directly to the public internet. The later ChatGPT integration phase should use the supported secure connection mechanism and authentication controls.

## Audit

Allowed calls are appended to `data/audit.jsonl`. File contents are never written to the audit ledger.
