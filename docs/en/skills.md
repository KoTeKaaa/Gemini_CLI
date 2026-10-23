# Reuse instructions with skills

[Русский](../skills.md) · [English](skills.md) · [Home](../../README.en.md)

A skill is a directory with `SKILL.md`, optional references, assets and scripts.
It gives the model instructions for a particular task. It does not grant permission
to run tools. `/skill help` explains setup and shows templates.

The client uses the [Agent Skills format](https://agentskills.io/specification).
Compatibility with other agents depends on their tools and rules; `allowed-tools`
metadata does not override Gemini CLI approvals.

## Register a directory

Copy selected [examples](../skills-examples) to a personal directory and inspect
their instructions and scripts. Create `skills.json` in `~/.gemini_cli` on Linux
or `%USERPROFILE%\.gemini_cli` on Windows:

```json
{"version": 1, "directories": ["/home/USER/my-skills"]}
```

Use an absolute directory containing skill folders. On Windows, escape backslashes
in JSON, for example `C:\\Users\\Example\\my-skills`. A project's location
does not automatically register its skills. Keep private values out of metadata.

A minimal `SKILL.md` looks like this:

```markdown
---
name: explain-code
description: Explain a small piece of unfamiliar code before proposing changes.
---
Read only the files needed for the question. Explain the behavior and assumptions.
Ask before changing files or running commands.
```

Use `/skill` to inspect available skills and choose the one appropriate for the
conversation. Selection is explicit and instructions count toward model context.
The client does not execute a discovered skill merely because a name matches.

## Resources and scripts

References and assets are loaded explicitly and bounded rather than all being
inserted into the first request. Paths cannot escape the registered skill or use
links to bypass restrictions. Treat their content as untrusted instructions.

Scripts require a review of their actual text and a separate confirmation. A file
changed after review must be reviewed again. The client runs a private snapshot
of that reviewed text in the workspace with your user permissions; it is not a sandbox.
Shell actions and external side effects are not reversible through `/undo`.

Supported script extensions are `.py`, `.sh` and `.ps1`, with the corresponding
Python, Bash or PowerShell installed. Source clients use their Python interpreter;
packaged clients need an external Python on `PATH` for Python scripts.
