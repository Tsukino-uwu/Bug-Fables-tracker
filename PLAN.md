# Plan: a PopTracker pack for the Bug Fables Archipelago randomizer

Planned 2026-10-01; building since 2026-10-03, in this repo (MIT, like the randomizer; its GitHub repo comes later,
made by the user), never inside the randomizer's repo. Each step is written up as a build step in the randomizer's
`agent_docs/apimplementation.md` (the user, 2026-10-03).

## Goal

- **Full** PopTracker support (the user, 2026-10-01): every feature PopTracker's docs offer that applies, none
  left optional. Anything that doesn't apply is recorded under "Not applicable" with its reason.
- A PopTracker pack that tracks a Bug Fables Archipelago seed: items, checks, and which checks are in logic.
- A map **drawn by code** (no AI art, no game art), its look picked by the user on screen.
- Normal seeds: a fixed layout, since the rooms never move.
- Room Swap seeds: each room appears in the slot it now sits in.
- Coupled/Decoupled door shuffle: rooms stay at their normal place, with no connections drawn.
- **Fog of war:** unvisited rooms hidden by default, with a toggle to show them. Only this pack has it, to keep the
  map's layout unspoiled; Universal Tracker always shows every location in logic (the user, 2026-10-01).

## PopTracker facts it builds on (`doc/PACKS.md`, `doc/AUTOTRACKING.md`, master, read 2026-10-01; re-read 2026-10-03 at `dad3675`, release v0.35.4)

- Packs run Lua 5.4 (the `.luarc.json` example beside its LuaLS definition file, `api/lua/definition`).
- Pack logic can't read a JSON file of its own: data the Lua needs goes in as a generated Lua table (`require`).

- A map is one fixed image; pins have fixed x/y. Lua can hide or show pins and sections (`visibility_rules`,
  `force_invisibility_rules`), set item icons and badges, and switch tabs, zoom and pan. It cannot draw.
- `manifest.json` with the `"ap"` flag turns on Archipelago auto-tracking.
- Handlers: Clear (receives slot_data on connect), Item, Location, SetReply. `Archipelago:SetNotify(keys)`
  watches data storage keys.
- Rules: strings ANDed within, ORed across; `$func|arg` calls Lua; `@location/section` reuses another rule.

## What it reads from the randomizer

- **slot_data on connect:**
  - `world_version`: the pack warns when it differs from the apworld version it was built from.
  - `door_targets`: a list of {map, door, like_map, like_door}. A door now leads where like_door leads in vanilla,
    so its destination is like_door's vanilla partner's map. Unchanged doors are left out.
  - `start`: {map, from}, or {} for the game's own start.
  - `starting_member` (top level): 0 Vi, 1 Kabbu, 2 Leif alone, 3 all three, -1 the story's party.
  - `options` (since the randomizer's build step 39, 2026-10-03): the options as the seed applied them, toggles as
    JSON booleans: `shuffle_field_moves`, `shuffle_jump`, `points_of_no_return`, `artifacts_required` (capped),
    `progressive_boat`, the location categories, `entrance_randomizer`, `shop_contents`, `filler_starting_checks`,
    `exclude_locations`. The old top-level `shuffle_moves`, `shuffle_jump`, `points_of_no_return` and
    `artifacts_required` are gone, and nothing reads older seeds (the user: no support for older versions).
  - Universal Tracker rebuilds the seed from these same keys (the randomizer's build step 40).
- **Data storage**, through `SetNotify`. The mod writes none of these yet; they're planned in the randomizer
  (its `UNIVERSAL-TRACKER-PLAN.md`, Step E). Names and formats are a contract between the two:

  | Key | Written by the mod | Used here for |
  |---|---|---|
  | `bug_fables_visited_{team}_{slot}` | each map load: `update` with `[map]` | fog of war |
  | `bug_fables_map_{team}_{slot}` | each map load: `replace` with the map | auto tab, zoom/pan to the room |
  | `bug_fables_doors_{team}_{slot}` | each door taken: `update` with `[door]` | where shuffled doors lead |

- **Hints:** Archipelago's `_read_hints_{team}_{slot}` (`docs/network protocol.md`, Get), for highlighting
  hinted checks. Check whether `SetNotify` covers a `_read_` key, or poll it with `Get`.
- **The apworld itself,** at a pinned release, for the logic export.

## Randomizer facts it builds on (the randomizer's repo, 2026-10-01)

- One region per game map: 243 maps, 508 shuffled doors (`apworld/bug_fables/data/doors.json`), plus fixed links
  and transfers (boat, elevators, story) that are never shuffled.
- **Room Swap** moves "areas" (a map plus the maps joined to it by fixed doors) into another area's slot, within
  one of the 10 world parts and with the same door count. The slot graph stays vanilla (`entrances.py`).
- **Coupled/Decoupled** hand all 508 doors to Archipelago's `randomize_entrances`: any door to any door.
- No coordinates exist for rooms or locations in the apworld. The game has them: the pause map's 25 area positions
  (`PauseMenu.MapSetup`), each map's area (`MapControl.areaid`, the mod's map dump), and each door's spot and landing
  (the mod's entity dump). See the randomizer's `MEASURED.md`.

## What it contains

1. **Logic export** (a generator script): imports the pinned apworld and writes the logic data: each region's
   entrances and each location's rule from Rule Builder `to_dict` (Archipelago 0.6.7 `docs/rule builder.md`,
   Serialization: the intended way to a tracker). The custom rules `CanUse`, `Member`, `MoveItem`, `Boat` and
   `WayBack` are exported by name and evaluated in Lua from the seed's slot_data options.
2. **Lua:** an evaluator for the exported rule trees, and a region sweep (breadth-first from the start region over
   the region graph with `door_targets` applied), rerun when items change.
3. **Items and locations:** every Archipelago item with its code; one location per room, one section per check.
4. **The map, drawn by code at build time** (a standard-library PNG writer). Built 2026-10-03/04 from the game's own
   data (the user's pick: game data first, a hand table to nudge later); "good enough until we have checks
   everywhere" (the user, 2026-10-04):
   - a World tab like the game's pause map: an area pin where the pause map puts it, its lines between areas
     (`data/area_pips.json`; +x left, +z down, fitted to the user's screenshot);
   - a tab per area with checks: every room of the logic, placed where its doors meet (`data/rooms.json` from the
     mod's entity dump, only `doors.json`'s doors); a side room entered from inside another is a box at its door; a
     one-way door is a ring; rooms that can't sit side by side (a loop, stacked floors) get matching coloured rings;
   - night and story versions of a room (their own maps in the logic) get no tab until one holds a check;
   - still to come: a hand-editable nudge table, room and area names from the game's text, a door-less image for
     Coupled/Decoupled seeds, Lua picking the tab from slot_data.
5. **Room Swap:** one pin per slot. Its sections are the checks of every area that can land there (same world part
   and door count), each visible only when the seed put that area there, derived from `door_targets`. If that
   proves unreliable, ask the randomizer for a slot_data key.
6. **Fog of war:** a pin shows only when its room is in the visited list, unless the toggle item "Show unvisited
   rooms" is on (off by default).
7. **Doors:** with the door shuffle on, each door taken (the doors key) shows where it led, as far as PopTracker
   can show it: a badge or section on the room's pin, never a drawn line. Find the best fit in the docs then.
8. **Items:** an item grid layout with every item that matters (party, abilities, key items, Artifacts count,
   Progressive Boat stages), auto-tracked from received items.
9. **Following the player:** on a current-map change, `ActivateTab` to its world part and `Pan`/`Zoom` to the
   room (Ui Hints, since 0.34.0).
10. **Hints:** hinted checks highlighted (`Highlight` on sections, since 0.32.0).
11. **Variants** (manifest `variants`): "Map" and "Compact" (items only). PopTracker has no checks-list widget: a
    layout's types are container, dock, array, tabbed, group, item, itemgrid, map, layout, recentpins, text and
    canvas (`doc/PACKS.md`, Layouts, 2026-10-03), so checks show only as pins on a map.
12. **Layouts:** `tracker_default`, `tracker_broadcast` (a stream view), and `settings_popup` holding the fog of
    war toggle.
13. **Updates:** `versions_url` in the manifest, and a listing in PopTracker's pack list (its `packlist` branch,
    read its rules first).
14. **Version check:** `min_poptracker_version` and `target_poptracker_version` set to what was tested.

## Not applicable (recorded so it's a decision, not a gap)

- `"apmanual"` (the pack sending checks): the mod sends every check itself.
- `"aphintgame"` (the pack scouting locations): it would reveal items the player hasn't found; only if the user
  wants that.
- Memory and UAT auto-tracking: Archipelago gives everything the pack needs.

## Order

1. The logic export, the item grid, and the checks as pins on a placeholder map drawn by code (built 2026-10-03:
   `tools/export.py`, `scripts/logic.lua`, `tests/test_parity.py`).
2. The map (its first version built 2026-10-04, see item 4), following the player, and hints.
3. Fog of war and doors, once the randomizer writes its data storage keys.
4. Updates and the pack list, once the user makes the repo.

## Rules carried over from the randomizer

- No AI art and no game art: code-drawn only, and the user picks every look on screen.
- A project's licence before anything else of it, and the user's yes before reading it at all. PopTracker is
  GPL-3.0; the pack is its own data and Lua, with no PopTracker code copied. This repo is MIT (the user, 2026-10-03).
- Facts about PopTracker, Archipelago and the game come from their docs and source, never from memory.
- Ask before touching the game install, the Archipelago checkout or PopTracker's install.

## Decisions (2026-10-03, the user's)

- **The apworld comes from the randomizer's checkout**, imported through your Archipelago checkout (at the tag the
  world targets) where the randomizer's development guide links it in as `worlds/bug_fables`. The export records the
  randomizer's commit and `world_version`. A release pin waits for a release with slot_data's `options`.
- **Checks:** PopTracker's own `pack-checker` (its CI action, as the Crystal pack's CI runs it; it validates against
  PopTracker's schemas), plus **lupa parity tests**. Archipelago has no standard for testing a tracker's Lua (its core
  runs no Lua; Rule Builder's Serialization section leaves the export to the world dev), and the Crystal pack has
  none: it checks with pack-checker only, its logic hand-ported. Ours is generated, so a Python test can run the
  pack's Lua (Lua 5.4 through lupa) beside the apworld's own logic and prove they agree.
- **MIT**, like the randomizer. lupa (MIT, its Lua MIT) is a test dependency only; pack-checker (GPL-3.0) is run,
  never copied or shipped.

## Verification

- Generator tests: every location id appears once, every rule names a real item, the manifest is valid.
- Logic parity (lupa): the pack's Lua against the apworld's Python logic, over many seeds and item states.
- `pack-checker` on the source folder, and on the release zip before a release.
- The user loads the pack in PopTracker against a local server (ask before starting either) and confirms on screen:
  the checks, logic colours, the item grid, the map, Room Swap placement, following the player, hints, doors,
  fog of war, both variants and the broadcast view.
