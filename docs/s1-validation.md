# Input and image validation

The client supports explicit clipboard paste, image drafts, safe workspace file
selection and folded text pastes in both backends. Image limits are checked again
on the server, and persisted messages contain metadata rather than image bytes.
Pillow 12.3.0 is pinned for Python 3.10+; decoder modules are included in executables.

## Automated checks

Targeted tests cover detection without clipboard access, Windows format handling,
Linux output/time limits, draft operations, shared image validation, rejection of
old servers, SQLite metadata, subsequent turns, completion filters, file changes,
exact pasted line endings and paste editing/removal. CI builds Linux Python 3.10
and Windows Python 3.12 executables and checks startup separately from unit tests.
Final integration on 19 October 2026:

- Full regression: 210 tests, OK, one real-Supabase integration skipped.
- `bash tests/test_deploy_install.sh`: deployment preflight PASS.
- `git diff --check`: PASS (whitespace only).
- Local Linux executable: build and offline standalone startup PASS.
- Pillow 12.3.0 binary wheels downloaded for Linux CPython 3.10 and Windows CPython 3.12.
- Independent subagent review completed before the PR. Two reproduced P2 issues
  (image bytes disabling tools, oversized drafts exiting the CLI) were fixed and
  rechecked. Final image-context and persistence checks had no new findings.
- CI run results and executable artifacts are linked from the draft PR. Build and
  startup checks are distinct from real terminal/clipboard/provider acceptance.

The sandbox stalled the existing TestClient/anyio portal before endpoint execution;
that test and the full regression passed when run outside the sandbox.

## Required interactive acceptance — pending

Run on Windows, Linux Wayland and X11, using the actual executables and terminals:

1. Copy a screenshot; type text, Ctrl+V, inspect the name/size, send in local mode.
   Repeat in remote mode with an active account and updated server.
2. Add multiple screenshots; remove one with `/remove N`; check that typed text
   survives. Repeat with `/paste` if the terminal intercepts Ctrl+V.
3. Copy plain text, an empty clipboard and a file list. No action should send a
   request. Missing utilities, blocked clipboard and invalid images preserve drafts.
4. Ask a second question about the image and exercise a tool continuation. Restart
   the client: image metadata is retained, missing bytes require reattachment.
5. Select `@путь с пробелом.py:1-5`; reject confirmation, then allow it. Change the
   file after selection and verify rejection. Secret paths must not appear.
6. Paste a long multiline block, resize the terminal, view/edit/remove it and send.
   Verify line endings, command completion and ordinary arrow-key history.
7. Check both accounts' histories and server logs for absence of image payloads.

Mocks and build/startup checks do not complete this acceptance. No deployment,
production database change or release publication is part of this sprint branch.
