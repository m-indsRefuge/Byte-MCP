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

The policy is intentionally conservative and can be extended only through a new-version security review.

## Prompt injection

Text found inside a retrieved file must be treated as untrusted content. It must never override the operator's request, Byte-MCP's tool contract, or higher-level safety rules.

## Network boundary

Byte-MCP V1.1 explicitly binds to a loopback host. Supported V1 host values are:

- `127.0.0.1`
- `localhost`
- `::1`

The default endpoint is:

```text
http://127.0.0.1:8000/mcp
```

V1 rejects non-loopback values such as `0.0.0.0`. Do not expose the port through a router, public firewall rule, or unauthenticated generic tunnel. Any future ChatGPT integration must use an approved remote connection and retain the local loopback boundary.

Runtime configuration environment variables:

```text
BYTE_MCP_HOST
BYTE_MCP_PORT
BYTE_MCP_TRANSPORT
BYTE_MCP_ROOTS_FILE
BYTE_MCP_AUDIT_FILE
BYTE_MCP_MAX_FILE_BYTES
BYTE_MCP_MAX_RESPONSE_CHARS
BYTE_MCP_MAX_SEARCH_FILES
BYTE_MCP_CONTENT_SEARCH_MAX_BYTES
```

V1 supports only the `streamable-http` transport.

## Audit

Allowed, denied, and unexpected-error outcomes are appended to `data/audit.jsonl`.

The audit ledger records operation metadata but does not record fetched file contents. Search terms and opaque file references are represented by SHA-256 fingerprints and lengths rather than raw values. Denied operations include a bounded error type and message so the security boundary can be reviewed without storing requested file content.

## Remote exposure status

No accepted public Byte-MCP endpoint is active as part of V1.1.

A restricted local profile exposing only a harmless `share` root passed loopback MCP discovery. An account-less Cloudflare Quick Tunnel also established outbound connectivity, but the remote MCP smoke test did not complete and the nested client exception was not captured by the current smoke-test wrapper.

Cloudflare documents Quick Tunnels as development-only and states that they do not support Server-Sent Events. A Quick Tunnel is therefore not an accepted final Byte-MCP transport:

- https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/trycloudflare/

Future remote deployment must begin with a separate restricted roots profile and must pass every gate in:

- [Remote Integration Resumption](REMOTE-INTEGRATION-RESUMPTION.md)

## ChatGPT deployment boundary

A remote endpoint does not by itself authorize ChatGPT to register or invoke a custom MCP server. The active account must expose the required custom-app capability.

The V1.1 closeout records ChatGPT deployment as an external dependency because the deployment account used during closeout did not expose the required custom MCP registration path. Review current OpenAI documentation before resumption:

- https://help.openai.com/en/articles/12584461-developer-mode-and-full-mcp-connectors-in-chatgpt-beta

## Frozen authority

V1.1 contains no write, rename, move, delete, shell, execute, process-control, registry, application-control, or arbitrary HTTP tools.

Adding any such authority requires:

1. a new version;
2. a separate capability contract;
3. threat modelling and adversarial tests;
4. explicit confirmation and rollback design where mutation is possible;
5. a new release and deployment review.

The separate chess-capability branch is not part of V1.1 and must not be merged merely to complete remote connectivity.
