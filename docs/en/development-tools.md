# Code, tests, Git and pull requests

[Русский](../development-tools.md) · [English](development-tools.md) · [Home](../../README.en.md)

Start with `/dev help`. `python_symbols` builds a bounded Python map with file
paths and line numbers after approval. `find_files` and `search_text` work without
a language server. Import-based dependency suggestions are useful starting points,
not proof that every affected file or test has been found.

## Optional Python language server

Install the pinned requirements in a separate environment, not the client environment:

```sh
python -m venv /opt/example/pylsp
/opt/example/pylsp/bin/python -m pip install -r client/requirements-lsp.txt
export GEMINI_CLI_PYLSP=/opt/example/pylsp/bin/pylsp
```

Or in PowerShell:

```powershell
py -3.12 -m venv C:\Tools\pylsp
C:\Tools\pylsp\Scripts\python.exe -m pip install -r client/requirements-lsp.txt
$env:GEMINI_CLI_PYLSP='C:\Tools\pylsp\Scripts\pylsp.exe'
```

Use a directory you can write. This server runs locally over stdio after explicit
approval; workspace configurations are not launched automatically. An external
language server can inspect the project and its configuration, so trust the workspace.

Ask for `python_lsp action=definition` or `references`, a `filepath`, a 1-based
`line` and a 0-based UTF-16 `character`. It reads saved files, not editor buffers,
and limits the workspace to 400 Python files / 4 MiB. Untracked external URIs and
versions that no longer match the snapshot are rejected.

Diagnostics wait for the selected document; a timeout is not a clean result.
Rename converts supported text edits into the normal reviewed file-change path,
with snapshot checks, confirmation and `/undo`. Unsupported file operations,
overlapping edits and unknown versions are rejected. A multi-file write is not
one atomic transaction; partial outcomes are reported.

## Run tests deliberately

`run_tests modules=["tests.test_example"] timeout=120` runs unittest after approval.
An empty module list discovers `tests/`. This executes project code with your user
permissions. The result separates the runner report from stdout and includes
counts, failures, errors, skips, discovery errors and bounded logs. Printed success
text is not a result; empty suites, cancellation and missing reports are not success.

For a packaged client, set `GEMINI_CLI_PYTHON` to the absolute Python executable of
your project environment. Source clients use their interpreter by default.

`affected_tests files=["pkg/core.py"]` suggests unittest modules through static
imports without running them. Dynamic imports, deleted files and configuration
can require wider checks; the tool reports that uncertainty.

## Prepare a focused commit

`git_read` accepts `action=status|diff|log|blame` and explicit `files`. Choose both
old and new paths for renames. Output is bounded to 32 KiB and marked if truncated;
blame is limited to one file and 100 lines. The workspace must be the repository root.

`git_commit action=prepare files=["src/app.py"] message="Fix parser" task="..."`
returns a one-use token and reviewed diff, including new files. Then
`action=commit token=...` checks the plan again and asks for confirmation.
Selection covers whole files, including their staged and unstaged changes.
Unrelated index/worktree changes are retained. Hooks run normally; failures are
not hidden, and no push occurs. Once commit starts, cancellation lets hook/index
finalization finish; it does not promise to undo an existing commit.

If a hook pauses for a human check, finish it in that interface. Do not launch
a duplicate commit while the original is waiting. Git source and commit-plan
contents are redacted before permanent chat storage.

## Open a PR through personal GitHub MCP

Enable the tools described in [GitHub setup](mcp-github.md). Publish the branch
separately, then explicitly request `github_pr action=create base=dev title=... body=...`.
It creates a draft; repeating create returns an existing open PR for that head/base.
`action=update` edits title/body; `action=checks` reads checks and combined status.
Unknown or incomplete checks are not green. After an interrupted write, inspect
the remote PR first; there is no hidden retry, automatic push, merge or permission expansion.
