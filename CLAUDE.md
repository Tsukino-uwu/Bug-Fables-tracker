# Working notes for Claude

A PopTracker pack for the Bug Fables Archipelago randomizer. `PLAN.md` is the plan and its decisions; the randomizer
is its own repo (a sibling checkout, `../bug_fables_ap`), and its rules carry over here where they apply.

## What never changes

- **The logic is generated from the apworld, never written by hand** (`tools/export.py`): the pack can't drift from
  the seed it tracks. What the export can't express, the apworld fixes in the randomizer's repo, Archipelago's way.
- **Each step is written up in the randomizer's `agent_docs/apimplementation.md`** as a build step (the user,
  2026-10-03): how the pack was built, and why (lupa included), committed there in the same session.
- **No AI art, no game art:** the map is drawn by code, and the user picks every look on screen.
- **Licence first:** a project with no row in the randomizer's `agent_docs/licensing.md` is off limits, its licence
  included, until the user says yes; then its licence, then its row, committed, before anything else of it is read.
  Never copy another project's code. **Never look at another Bug Fables project.**
- **Facts come from docs and source, never memory:** PopTracker's `doc/` (re-read before each new use; it changes),
  Archipelago's docs at the tag the randomizer targets, the apworld itself.
- **No personal username, home path or machine detail in any tracked file.**

## Who verifies what

- **The user verifies the pack in PopTracker; you verify the code.** `tools/test.ps1` runs the tests (the export,
  lupa parity against the apworld's own logic) and PopTracker's `pack-checker`: all pass before a commit.
- **Nothing on screen is "verified" until the user confirms it.** Ask before starting PopTracker or a server, then
  close what you started. Ask before touching PopTracker's install, the game, or the Archipelago checkout.

## Working with the user

- Commit freely, straight to `main`; never create a branch. Push only when told, in that message. Subjects:
  imperative, 72 characters at most.
- Never suggest stopping or resuming later. Small runnable steps, each with a visible outcome.
- Comments are lean: one line, only where the code can't say it.
