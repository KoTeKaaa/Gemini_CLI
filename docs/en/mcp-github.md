# Personal GitHub MCP

[Русский](../mcp-github.md) · [English](mcp-github.md) · [MCP basics](mcp.md)

GitHub MCP authorization is separate from your Remote CLI account. Use a personal
connection and the least access needed for the chosen repositories. See
[GitHub's server documentation](https://github.com/github/github-mcp-server) for
current access requirements and service limits.

For a read-only first connection, use the `mcp.json` example in [MCP setup](mcp.md).
Then run:

```text
/mcp login github memory
/mcp check github
/mcp tools github
/mcp enable github
```

An unauthenticated HTTP 401 proves reachability only, not successful authorization.
Confirm a small read-only call against a repository you can access. Each tool
still asks for confirmation. Do not paste a token into chat, JSON or a screenshot.

Use `keyring` instead of `memory` only with a working OS secret store. Windows
uses Credential Manager; Linux needs an unlocked Secret Service. If storage is
unavailable, explicitly choose memory. The client does not silently save plaintext.

## Creating and checking pull requests

Use a write-capable endpoint such as `https://api.githubcopilot.com/mcp/` for PR
writes; the read-only endpoint cannot create a PR. Explicitly select these tools
in the server entry's `tools` list:

```json
["list_pull_requests", "create_pull_request", "update_pull_request", "pull_request_read"]
```

Grant Pull requests read/write for the selected repository, Checks read and Commit
statuses read for checks. Contents write is not needed by the CLI PR tool because
it does not push. Check the service's current permission documentation before granting access.

Publish your branch separately, inspect the proposed arguments, then ask for PR
creation or an update. [Development tools](development-tools.md) explains the
draft/idempotent behavior. On 401/403, inspect authorization; on 429, respect the
service retry guidance. An unknown check is not success.

`/mcp disable github` disconnects the service. `/mcp logout github` removes local
credentials; revoke the token on GitHub separately if it should no longer work.
