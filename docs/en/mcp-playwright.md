# Playwright MCP in a separate browser

[Русский](../mcp-playwright.md) · [English](mcp-playwright.md) · [MCP basics](mcp.md)

This setup uses a separate, isolated browser. It does not attach your personal
browser profile, cookies or existing logins. Install Node LTS, npm and a compatible
browser explicitly; reading MCP configuration does not install anything.

## Linux

```sh
MCP_INSTALL_DIR="$HOME/.local/share/gemini-cli-mcp"
npm install --prefix "$MCP_INSTALL_DIR" @playwright/mcp@0.0.83
node "$MCP_INSTALL_DIR/node_modules/playwright/cli.js" install chromium
node -e "console.log(require(process.argv[1]).chromium.executablePath())" "$MCP_INSTALL_DIR/node_modules/playwright"
```

The last command gives the executable path. Install any required OS browser
dependencies following Playwright's documentation. Do not disable browser sandbox
or TLS validation to work around an installation error.

Add a server entry inside your private `mcp.json` `servers` array, replacing paths:

```json
{"name":"playwright","transport":"stdio","command":"node",
 "args":["/absolute/install/node_modules/@playwright/mcp/cli.js",
         "--headless","--isolated","--executable-path","/absolute/chromium/chrome"],
 "tools":["browser_tabs","browser_snapshot"],"timeout":30}
```

## Windows PowerShell

```powershell
$mcpInstallDir = Join-Path $env:LOCALAPPDATA 'gemini-cli-mcp'
npm install --prefix $mcpInstallDir @playwright/mcp@0.0.83
node (Join-Path $mcpInstallDir 'node_modules\playwright\cli.js') install chromium
node -e 'console.log(require(process.argv[1]).chromium.executablePath())' (Join-Path $mcpInstallDir 'node_modules\playwright')
```

Use the same server entry in `%USERPROFILE%\.gemini_cli\mcp.json`, with an absolute
`node.exe` command and escaped Windows paths. Calling Node directly avoids shell
quoting differences around `npx.cmd`. Restart the CLI after changing configuration.

## Try a small read

```text
/mcp check playwright
/mcp tools playwright
/mcp enable playwright
```

Request only `browser_tabs` with `action=list`, then approve that call. An isolated
browser usually starts at `about:blank`. A missing-browser error is not a successful
read. Text/tree output uses normal MCP bounds; screenshots are not inserted as raw
base64 text. Local stdio needs no personal service token, but websites can require
their own authorization and have their own terms or fees.

`/mcp disable playwright` stops the managed process and descendants. Remove the
configuration entry and your installation directory when no longer needed. Shared
Playwright browser caches may belong to other projects; do not remove them blindly.
