# Gemini CLI

[Русский](README.md) · [English](README.en.md) · [Download](https://github.com/KoTeKaaa/Gemini_CLI/releases/latest) · [What's new](docs/releases/v3.0.0.en.md)

Understand unfamiliar code, talk through a change, attach a screenshot or read
part of a spreadsheet without leaving your terminal. Gemini CLI keeps the
conversation and project tools together. You decide which files it may read,
which changes to write and which commands to run.

Use **Local** with your own Gemini key, directly with the provider, or **Remote**
with an account on your server. Local needs no application server or subscription.
This is an independent project, not Google's official Gemini CLI.

## Start here

1. Download `gemini-cli-linux-x64` or `gemini-cli-windows-x64.exe` and `SHA256SUMS`
   from the [latest release](https://github.com/KoTeKaaa/Gemini_CLI/releases/latest).
   The executable includes Python and the client dependencies.
2. Verify the checksum, then launch the client.
3. Choose Local and enter your personal key, or choose Remote and enter your
   server address. You can change this later with `/settings`.
4. Open your project with `/cd path` and try a small task.

For example: “Find where sign-in is handled and explain the code,” or attach
`@report.pdf#pages=2-3` and ask for the main points. Before a larger change,
ask for a proposal, review it and approve only the actions you want.

**Linux x64** — download both files to the same directory:

```bash
sha256sum --ignore-missing -c SHA256SUMS
chmod +x gemini-cli-linux-x64
./gemini-cli-linux-x64
```

**Windows x64** — download both files and open PowerShell in that directory:

```powershell
$expected = (Select-String -Path .\SHA256SUMS -Pattern '  gemini-cli-windows-x64\.exe$').Line.Split(' ')[0]
$actual = (Get-FileHash .\gemini-cli-windows-x64.exe -Algorithm SHA256).Hash
if ($actual -ne $expected) { throw 'SHA256 mismatch' }
.\gemini-cli-windows-x64.exe
```

Check your installed version with `gemini-cli --version`. Linux release builds
target Ubuntu 22.04 x64. For other architectures or system libraries, build from source.
The client interface and built-in help are currently in Russian; these guides
provide an English starting point.

## What you can do

- **Work with code.** Find files and text, read selected lines, inspect Python
  symbols, run unittest and prepare Git commits from explicitly selected files.
  An optional Python LSP adds definitions, references, diagnostics and reviewed rename.
- **Review and undo edits.** `/diff` opens changes in a scrollable view.
  `/undo` restores agent edits when later manual changes have not made that unsafe.
  Shell commands and external actions cannot be undone this way.
- **Keep long conversations useful.** `/compact` reduces model context while
  keeping the conversation. `/fork` starts another chat from a safe completed turn.
- **Bring in your own tools.** Personal MCP connections and selected skills extend
  the workflow. Workspace configuration never turns itself on.
- **Read documents selectively.** Choose PDF pages, DOCX paragraphs/sections/tables
  or CSV/XLSX cells. Original binary bytes stay local; selected text goes into context.
- **Use a real shell.** `/term` opens your shell; `exit-to-cli` returns to the chat.
  `exit-to-cli --sync-dir` also explicitly adopts the shell's current directory.
- **Search the web.** Optional Tavily Basic search and public-page reading work
  alongside project tools. Ordinary chat does not require a search key.

## Commands worth remembering

| Command | What it does |
| --- | --- |
| `/help` | Open built-in help |
| `/settings`, `/model` | Change backend, keys, server or model |
| `/cd path` | Select a workspace |
| `@file`, `@file:1-20` | Attach a text file or selected lines |
| `@file.pdf#pages=1-3` | Attach selected document text |
| `Ctrl+V`, `/paste` | Read clipboard text or an image after your action |
| `/attachments`, `/show 1`, `/edit 1`, `/remove 1` | Manage the unsent draft |
| `/diff`, `/undo` | Inspect or undo tracked agent file edits |
| `/chat`, `/fork`, `/compact` | Find, branch or compact a conversation |
| `/clear` | Clear a temporary chat; persistent chats are unchanged |
| `Ctrl+L` | Clear the screen without clearing context |
| `/limits` | Read Remote subscription budget; not a Local command |
| `/term` | Open a real shell and return with `exit-to-cli` |
| `/mcp help`, `/skill help`, `/dev help`, `/doc help` | Setup guides and examples |
| `Esc`, `F2` | Cancel the current turn or inspect tool details |

## Your data and permissions

Local sends personal provider keys directly to providers and keeps persistent
chats in a private profile SQLite database. Keys use OS keyring storage or an
explicit memory-only choice; there is no plaintext fallback. Remote uses an
origin/account-bound session and subscription-authorized server APIs.

File tools stay inside the workspace and reject protected secret paths and links.
**Approved shell commands run with your user permissions and can act outside that
directory.** Read each command before approving it. MCP and skill content does not
grant additional permission.

Raw image/document bytes are not stored in chat history. Sensitive tool results
are redacted before persistence, including file/document reads, MCP and Git diffs.
Text you attach to a user message remains part of that message, so choose it carefully.
Temporary chats and drafts remain in RAM for the current process. Checkpoints are
local, bounded and unencrypted; they do not provide rollback for external side effects.

## Guides

| Topic | Read more |
| --- | --- |
| External tools | [MCP](docs/en/mcp.md), [GitHub](docs/en/mcp-github.md), [Playwright](docs/en/mcp-playwright.md) |
| Reusable task instructions | [Skills](docs/en/skills.md) |
| Python, tests, Git and PR | [Development tools](docs/en/development-tools.md) |
| PDF, DOCX, CSV and XLSX | [Document ranges](docs/en/documents.md) |
| Changes and Remote budget | [File edits](docs/en/file-changes.md), [limits](docs/en/limits.md) |
| Hosting Remote | [Server setup](docs/en/server-setup.md), [updates](docs/en/auto-deploy.md), [subscriptions](docs/en/subscription-migration.md), [history schema](docs/en/history-migration.md) |
| Getting involved | [Contributing](CONTRIBUTING.md#english), [security](SECURITY.md#english) |

## Run or build from source

Python 3.10+ is required. From the repository directory:

```bash
./client/run.sh --with-local
```

On Windows, create and activate a virtual environment, install
`client/requirements-local.txt`, then run `python main.py`. Source-only Remote
installs can use `client/requirements.txt`. Optional LSP dependencies are separate.

To build an executable, run `./client/build.sh` on Linux or `./client/build.ps1`
in PowerShell on Windows. Outputs are `dist/gemini-cli` and `dist/gemini-cli.exe`.
Server setup is separate; Local never needs FastAPI, Supabase or a listening port.

## License

Current development uses [MIT with Commons Clause](LICENSE). You may use the CLI
at work; selling a repackaged product is restricted, with an important distinction
for substantial independent added value. Read the [licensing explanation](LICENSING.md).
This is source-available, not unrestricted MIT. **Released v3.0.0 remains MIT-licensed.**
