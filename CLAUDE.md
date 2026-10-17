# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# FirstDev

Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform. Author: Issa Jber.

## Commands

- `uv sync` — install dependencies
- `scripts/check.sh` — ruff check, ruff format --check, pytest, pip-audit
- `uv run pytest tests/test_x.py::test_name` — run a single test
- `uv run uvicorn firstdev.app:app --reload` — run the API

Git hooks live in `.githooks` (`core.hooksPath`): pre-commit scans staged content for secrets, blocks `.env` and runs ruff; post-commit writes an Obsidian note.

Status: Part 1 in progress — see docs/specs/2026-10-17-part1-design.md

## Development protocol (applies to every task)

1. **Models:** planning, architecture, edge cases and threat modeling on Opus 5.5 (`claude-opus-5-5`). Code writing, scripts, test runs and CLI work on Sonnet 5.5 (`claude-sonnet-5-5`): delegate to subagents with `model: "sonnet"`, following the approved plan exactly.
2. **Skills/agents:** use the skills and agents already installed instead of rebuilding their workflows.
3. **Plan first:** no code before a written plan is approved.
4. **Security at every stage:** check for injection (XSS, SQL, shell), prompt injection in any LLM-facing input, input sanitization, and API keys or secrets in code.
5. **Testing after every implementation:** E2E on the real flow, regression on existing features, then edge cases (empty, missing, very long, invalid, boundary). Report actual results, failures included.
6. **Code quality:** clean, commented code. Finish every module; no placeholders left behind.
7. **Progress log:** when a milestone or task is done, save a structured progress/state summary to Obsidian (`fort nox/Claude Log/FirstDev`, via `scripts/obsidian_log.py`).
8. **Copyright header:** every source and doc file starts with the notice in that file type's comment syntax: `# Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform.` (Python, shell, TOML, INI), `/* ... */` (JS/TS/CSS), `<!-- ... -->` (Markdown/HTML). Not possible in JSON or generated lock files. Package metadata author is `Issa Jber`.
9. **Design system:** all UI work follows `docs/design-system.md` (dark-first urban/terminal theme, palette tokens, Inter/Geist + JetBrains Mono).
