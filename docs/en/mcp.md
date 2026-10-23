# Connect your own MCP tools

[Русский](../mcp.md) · [English](mcp.md) · [Home](../../README.en.md)

Start with `/mcp help`. The guide also opens when your configuration is malformed.
MCP runs on your computer in both modes. Remote receives bounded tool declarations
and selected results, not connection configuration, environment secrets or bearer tokens.
Remote requires a compatible server and subscription feature; Local needs no server subscription.

## Add a connection

Create `mcp.json` in the private CLI directory: `~/.gemini_cli` on Linux or
`%USERPROFILE%\.gemini_cli` on Windows. Workspace configurations are not loaded.
Keep tokens, passwords and secret argument values out of this file.

```json
{"version": 1, "servers": [
  {"name": "github", "transport": "http",
   "url": "https://api.githubcopilot.com/mcp/x/repos/readonly",
   "auth": "bearer", "tools": ["get_file_contents"], "timeout": 30}
]}
```

Supported transports are stdio (`command`, `args`, `env_keys`) and Streamable HTTP
(`url`, `auth`: `none`, `bearer` or `oauth`). `env_keys` lists names only; enter
their values through `/mcp login`. Restart the client after editing configuration.
Reading configuration never starts a process by itself.

HTTP URLs require HTTPS without embedded credentials, query or fragment. Private
destinations or local HTTP need explicit `allow_private: true` in a trusted entry.
Redirects are rejected, TLS is checked and public IPs are pinned for a connection.

## Check, enable and use

```text
/mcp check github
/mcp tools github
/mcp login github memory
/mcp enable github
/mcp disable github
/mcp logout github
```

`check` connects and refreshes the catalog without enabling it for the model.
`enable` makes the cached catalog available; `disable` disconnects it and removes
its tools from subsequent requests. Login verifies access but does not enable tools.
Every call shows arguments and requires confirmation, including read-only tools.
`/undo` cannot reverse external MCP actions.

`memory` keeps credentials until exit. `keyring` requires a working OS secret
store; failures do not trigger a plaintext or memory fallback. Password input is
hidden and excluded from input history. Logout removes local credentials;
revoke access at the service separately when needed.

OAuth uses SDK registration, PKCE/state and a loopback callback. Services requiring
unsupported pre-registration may need their documented bearer access instead.

## Bounds and installation

Up to 8 connections and 16 MCP tools can be declared, with a total schema limit
of 32 KiB. Unsupported JSON Schema features are reported rather than executed.
Transport input is bounded; model output is limited to 8 KiB. Binary media is
skipped with a notice. Private MCP arguments/results are omitted from permanent
history and its copies. Esc cancels waiting and future calls; a completed external
action may still have taken effect.

Packaged clients include the SDK. For a lightweight source installation, use
`python -m pip install -r client/requirements-mcp.txt`; local dependencies provide
keyring support. Service examples: [GitHub](mcp-github.md), [Playwright](mcp-playwright.md).
