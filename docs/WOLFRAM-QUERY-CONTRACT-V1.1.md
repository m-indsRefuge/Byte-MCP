# Wolfram Query Contract V1.1

## Purpose

This contract defines how Byte forms and transmits bounded queries through
Byte-MCP to the Wolfram|Alpha LLM API.

It supplements the existing Wolfram provider, quota, privacy, routing, and
no-retry controls. It does not expand Wolfram into a general HTTP tool.

## Query formation

Byte should form Wolfram input according to the provider's LLM-oriented
query guidance:

- transmit one single-line query;
- formulate the query in English;
- simplify natural-language questions to computational keywords where useful;
- write scientific notation as `6*10^14`, not E-notation such as `6e14`;
- prefer single-letter mathematical variables;
- prefer named physical constants to manually substituted numeric values;
- separate components of compound units with spaces.

These are query-planning rules. Byte-MCP does not blindly rewrite arbitrary
mathematics, rename variables, translate content, or change unit expressions,
because mechanical rewriting could change semantic meaning.

The transport policy mechanically rejects CR/LF input so a multiline query
cannot cross the Wolfram provider boundary.

## Assumptions

The LLM API may report ambiguity together with assumption identifiers.

A follow-up assumption request:

1. is explicit;
2. uses the exact same input query;
3. may contain at most eight opaque assumption tokens;
4. preserves each token exactly;
5. screens tokens for blank, multiline, NUL, and secret-like content;
6. transmits multiple selections as repeated `assumption=value` query
   parameters;
7. records only the number of supplied assumptions in Byte-MCP audit data.

Raw assumption values are not persisted in the ordinary audit trail.

Byte remains responsible for deciding whether a returned assumption is
appropriate. Byte-MCP does not automatically choose one.

## Retry and budget semantics

One `wolfram_query` invocation causes at most one Wolfram provider request.

There are no automatic retries, including for ambiguity. An assumption
follow-up is a new explicit invocation and consumes a new local quota
reservation/provider request.

Startup, daemon supervision, tests, and CI make no live Wolfram calls.

## Transport

The underlying integration remains the fixed Wolfram|Alpha LLM API endpoint.

`input`, `maxchars`, and optional repeated `assumption` values are transmitted
as HTTP GET query parameters. The AppID remains in the Bearer Authorization
header and is never exposed through the MCP tool surface.

## Non-goals

V1.1 does not add:

- automatic translation;
- automatic query rewriting;
- automatic assumption selection;
- automatic provider retries;
- another Wolfram MCP tool;
- caller-selected endpoints, methods, headers, or AppIDs.
