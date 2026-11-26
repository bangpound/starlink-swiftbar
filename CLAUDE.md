# Project Instructions for AI Agents

This file provides instructions and context for AI coding agents working on this project.

<!-- BEGIN BEADS INTEGRATION v:1 profile:minimal hash:6cd5cc61 -->
## Beads Issue Tracker

This project uses **bd (beads)** for issue tracking. Run `bd prime` to see full workflow context and commands.

### Quick Reference

```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd update <id> --claim  # Claim work
bd close <id>         # Complete work
```

### Rules

- Use `bd` for ALL task tracking — do NOT use TodoWrite, TaskCreate, or markdown TODO lists
- Run `bd prime` for detailed command reference and session close protocol
- Use `bd remember` for persistent knowledge — do NOT use MEMORY.md files

**Architecture in one line:** issues live in a local Dolt DB; sync uses `refs/dolt/data` on your git remote; `.beads/issues.jsonl` is a passive export. See https://github.com/gastownhall/beads/blob/main/docs/SYNC_CONCEPTS.md for details and anti-patterns.

## Agent Context Profiles

The managed Beads block is task-tracking guidance, not permission to override repository, user, or orchestrator instructions.

- **Conservative (default)**: Use `bd` for task tracking. Do not run git commits, git pushes, or Dolt remote sync unless explicitly asked. At handoff, report changed files, validation, and suggested next commands.
- **Minimal**: Keep tool instruction files as pointers to `bd prime`; use the same conservative git policy unless active instructions say otherwise.
- **Team-maintainer**: Only when the repository explicitly opts in, agents may close beads, run quality gates, commit, and push as part of session close. A current "do not commit" or "do not push" instruction still wins.

## Session Completion

This protocol applies when ending a Beads implementation workflow. It is subordinate to explicit user, repository, and orchestrator instructions.

1. **File issues for remaining work** - Create beads for anything that needs follow-up
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update issue status** - Close finished work, update in-progress items
4. **Handle git/sync by active profile**:
   ```bash
   # Conservative/minimal/default: report status and proposed commands; wait for approval.
   git status

   # Team-maintainer opt-in only, unless current instructions forbid it:
   git pull --rebase
   git push
   git status
   ```
5. **Hand off** - Summarize changes, validation, issue status, and any blocked sync/commit/push step

**Critical rules:**
- Explicit user or orchestrator instructions override this Beads block.
- Do not commit or push without clear authority from the active profile or the current user request.
- If a required sync or push is blocked, stop and report the exact command and error.
<!-- END BEADS INTEGRATION -->


## Build & Test

```bash
uv run --no-project python -m unittest discover -s tests -v   # unit tests + doctests; no deps, no dish
uvx ruff@0.17.6 check .                                        # lint (same pin as CI)
uv run ./starlink.30s.py                                       # render the menu once
uv run ./starlink.30s.py --debug                               # raw status + history JSON (needs the dish)
uv lock --script starlink.30s.py --upgrade                     # bump pinned grpcio/yagrc
```

CI (`.github/workflows/ci.yml`): ruff, tests on Python 3.11–3.15 (ARM Linux),
and a macOS smoke run of the plugin with `--locked`. The dish
(`192.168.100.1:9200`) is only reachable on the Starlink LAN; nothing in tests
or CI talks to it.

## Architecture Overview

One self-contained SwiftBar plugin, `starlink.30s.py` (a `uv` script with
inline metadata; `.30s.` is SwiftBar's refresh interval). `fetch_status()`
talks gRPC to the dish via server reflection (`yagrc`): `get_status`, plus
best-effort `get_history` for the 15-minute ping success rate. `render()` turns
the parsed dict into SwiftBar menu text. `main(argv) -> int` parses options
(argparse) and returns the exit code. `tests/test_starlink.py` loads the
dotted filename with `importlib` and also runs the module's doctests.

## Conventions & Patterns

- **Menu mode must exit 0**, even for error/unreachable menus: on a non-zero
  exit SwiftBar discards stdout and shows its own ⚠ instead
  (swiftbar/SwiftBar `RunScript.swift`, `MenuBarItem.swift`). Report failures
  in the menu itself, via `error_text()` (one line, no `|`).
- **Keep network imports lazy** (inside `fetch_status`), so tests need neither
  `grpcio` nor a dish. Mock only `fetch_status`, the network boundary.
- **`MessageToDict` quirks:** 64-bit ints arrive as strings, and zero or empty
  fields are omitted, so always read with `.get()` and defaults.
- History is a ring buffer: use `current` (total samples) to pick the valid,
  most recent samples. Never average the whole array.
- Tests are stdlib `unittest` only; TDD (red first). Keep dependencies in the
  script header and refresh `starlink.30s.py.lock` when they change.
- Actions are pinned to commit SHAs with a `# vX.Y.Z` comment (Dependabot
  bumps them). actionlint doesn't know `ubuntu-26.04-arm` yet, so pass
  `-ignore 'label "ubuntu-26.04-arm" is unknown'`.
