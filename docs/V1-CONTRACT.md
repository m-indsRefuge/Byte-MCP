# Byte-MCP V1 Contract

## Purpose

Provide Byte with narrow, auditable, read-only access to files contained inside roots explicitly approved by Nolan.

## Tools

### `list_roots`

Returns configured aliases and their local paths.

### `list_directory`

Lists one directory inside an approved root.

### `search`

Searches approved roots by filename. Bounded content search is optional.

### `fetch`

Reads one search result using an opaque Byte-MCP reference and returns extracted content, metadata, and SHA-256.

## Invariants

1. No arbitrary absolute path input.
2. No access outside approved roots.
3. No traversal through `..`, symbolic links, or Windows junctions.
4. No write, execute, delete, rename, shell, process, or registry operations.
5. Common credential files and secret-bearing locations are denied in code.
6. File and response sizes are bounded.
7. Retrieved file content is data, never an instruction source.
8. Every allowed operation is recorded locally without logging file content.
