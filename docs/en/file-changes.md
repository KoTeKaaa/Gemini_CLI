# Inspect and undo file edits

[Русский](../file-changes.md) · [English](file-changes.md) · [Home](../../README.en.md)

`/diff` and `/undo` without a path list files changed by the agent in the current
chat. `/diff src/file.py` opens a scrollable view: PgUp/PgDn scroll, `/` searches,
Esc/q returns. Paths support completion; spaces do not require surrounding quotes.

`/undo src/file.py` restores the file to its state before the retained agent edits;
an agent-created file is removed. Other files are unchanged. Later manual edits,
deletion, permission changes or manual changes between agent writes block undo.
The client refuses to overwrite that work. Git is not required.

File writes require confirmation. Before writing, the client checks that the
reviewed version still matches, preserves permissions and line endings, and replaces
one file atomically. A multi-file operation can have a partial outcome, shown explicitly.

Checkpoints live outside the workspace under `~/.gemini_cli/checkpoints` or the
Windows profile equivalent. They have private POSIX permissions but are not encrypted.
Storage is limited to 64 MiB and checkpoints expire after seven days; cleanup
runs before a new save. Missing, expired or damaged checkpoints prevent undo.
Protected secret paths and links are not recorded.

The in-memory journal retains up to eight backend/account/chat/workspace combinations,
32 edit turns and 64 MiB per journal. Ordinary messages do not erase prior edits;
the client reports when old history is evicted. The journal is unavailable after restart.
Shell commands, network operations and other external effects are outside this journal.
