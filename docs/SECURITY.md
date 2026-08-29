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

Byte-MCP explicitly binds to a loopback host. Supported V1 host values are:

- `127.0.0.1`
- `localhost`
- `::1`

The default endpoint is:

```text
http://127.0.0.1:8000/mcp
```

V1 rejects non-loopback values such as `0.0.0.0`. Do not expose the port through a router, public firewall rule, or unauthenticated generic tunnel.

The resumed ChatGPT validation uses OpenAI Secure MCP Tunnel while retaining the loopback-only Byte-MCP listener. The tunnel client is an outbound transport layer; it does not expand Byte-MCP's filesystem authority.

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

## MCP response boundary

MCP-facing responses must not expose the backing local absolute filesystem path.

The public addressing contract is:

- approved root alias;
- relative path within that approved root;
- opaque fetch reference where applicable.

`list_roots` returns aliases only. Search and fetch metadata return relative paths and do not include `absolute_path`.

This prevents a remote MCP caller from learning Windows user-profile or machine-specific path details that are unnecessary to use the service.

## Audit

Allowed, denied, and unexpected-error outcomes are appended to the configured audit ledger.

The audit ledger records operation metadata but does not record fetched file contents. Search terms and opaque file references are represented by SHA-256 fingerprints and lengths rather than raw values. Denied operations include a bounded error type and message so the security boundary can be reviewed without storing requested file content.

## Remote root boundary

The first accepted ChatGPT tunnel deployment is restricted to exactly one root:

```text
projects -> %USERPROFILE%\AIProjects
```

The remote profile must not expose Downloads, Documents, a drive root, the entire user profile, or any other filesystem root without a separate authorization and security review.

The `projects` alias does not grant arbitrary absolute-path access. All requests remain constrained beneath the configured AIProjects directory and are still subject to secret-name, traversal, symlink, junction, file-type, size, and response limits.

## Secure tunnel boundary

OpenAI Secure MCP Tunnel is the selected transport for the resumed ChatGPT integration validation.

Required tunnel properties:

- Byte-MCP remains on loopback;
- the tunnel client connects outbound;
- no router port forwarding is used;
- no public inbound Windows Firewall rule is added;
- the tunnel runtime uses a restricted Runtime API key with Tunnels **Read** + **Use** only;
- runtime credentials are never stored in Git or pasted into chat;
- the tunnel runtime points only to the reviewed local MCP endpoint.

Tunnel runtime permissions are transport permissions. They do not authorize filesystem writes or additional Byte-MCP tools.

The earlier Cloudflare Quick Tunnel experiment is historical evidence only and is not an accepted final transport.

## ChatGPT deployment boundary

The active ChatGPT workspace now exposes the custom plugin and tunnel-selection workflow required to continue validation. This removes the account-capability blocker recorded in the V1.1 closeout, but it does not by itself prove a successful deployment.

Acceptance still requires every gate in:

- [Remote Integration Resumption](REMOTE-INTEGRATION-RESUMPTION.md)

In particular, tool discovery must return exactly the four accepted read-only tools, and live ChatGPT calls must correlate with the local audit ledger.

## Frozen authority

The accepted capability boundary contains no write, rename, move, delete, shell, execute, process-control, registry, application-control, or arbitrary HTTP tools.

Adding any such authority requires:

1. a new version;
2. a separate capability contract;
3. threat modelling and adversarial tests;
4. explicit confirmation and rollback design where mutation is possible;
5. a new release and deployment review.

The separate chess-capability branch is not part of this remote integration increment and must not be merged merely to complete tunnel connectivity.
