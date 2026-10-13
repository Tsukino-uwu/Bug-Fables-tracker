# Plan: a PopTracker pack for the Bug Fables Archipelago randomizer

Planned 2026-10-01; building since 2026-10-03, in this repo (MIT, like the randomizer; its GitHub repo made by the
user 2026-10-04, private until released), never inside the randomizer's repo. Each step is written up as a build
step in the randomizer's `agent_docs/apimplementation.md` (the user, 2026-10-03).

## Goal

- **Full** PopTracker support (the user, 2026-10-01): every feature PopTracker's docs offer that applies, none
  left optional. Anything that doesn't apply is recorded under "Not applicable" with its reason.
- A PopTracker pack that tracks a Bug Fables Archipelago seed: items, checks, and which checks are in logic.
- A map from the game itself: the World tab is the game's own pause map, and each room a render of the room from
  above (the user, 2026-10-13: "use the game's world map", then the rooms as pictures), both made by the mod's dev
  console; what the game has no picture of (an area's layout, doors, lines) is drawn by code. No AI art; the user
  picks every look on screen.
- Normal seeds: a fixed layout, since the rooms never move.
- Room Swap seeds: each room appears in the slot it now sits in.
- Coupled/Decoupled door shuffle: rooms stay at their normal place, with no connections drawn.
- **Fog of war:** unvisited rooms hidden by default, with a toggle to show them. Only this pack has it, to keep the
  map's layout unspoiled; Universal Tracker always shows every location in logic (the user, 2026-10-01).

## PopTracker facts it builds on

From `doc/PACKS.md` and `doc/AUTOTRACKING.md` on master: read 2026-10-01; re-read 2026-10-03 at `dad3675` (release
v0.35.4); `AUTOTRACKING.md`'s Archipelago interface and `PACKS.md`'s Tracker section again 2026-10-08 at `d2af7f1`.

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
  - `start`: {map, from, door}, or {} for the game's own start. Since the randomizer's build step 96 the logic
    begins beside that door, and the opening's quiet checks sit in Menu; the pack follows it since 2026-10-13
    (`start_regions` in the export, `seed_entrances` in the Lua).
  - `starting_member` (top level): 0 Vi, 1 Kabbu, 2 Leif alone, 3 all three, -1 the story's party.
  - `options` (since the randomizer's build step 39, 2026-10-03): the options as the seed applied them, toggles as
    JSON booleans: `shuffle_field_moves`, `shuffle_jump`, `points_of_no_return`, `artifacts_required` (capped),
    `progressive_boat`, the location categories, `entrance_randomizer`, `shop_contents`, `filler_starting_checks`,
    `exclude_locations`, `extra_roadblocks` (since the randomizer's build step 48; a set, sent as a sorted list).
    The old top-level `shuffle_moves`, `shuffle_jump`, `points_of_no_return` and `artifacts_required` are gone, and
    nothing reads older seeds (the user: no support for older versions).
  - Universal Tracker rebuilds the seed from these same keys (the randomizer's build step 40).
- **Data storage**, through `SetNotify`. The mod writes all three since 2026-10-08: the doors key with the
  randomizer's build step 55, the other two with its build step 57 (not yet seen in game). Names and formats are a
  contract between the two:

  | Key | Written by the mod | Used here for |
  |---|---|---|
  | `bug_fables_visited_{team}_{slot}` | each map load: `update` with `[map]` | fog of war |
  | `bug_fables_map_{team}_{slot}` | each map load: `replace` with the map | auto tab, zoom/pan to the room |
  | `bug_fables_doors_{team}_{slot}` | each door taken: `update` with `[door]` | where shuffled doors lead |

  The doors key is also Universal Tracker's for its deferred entrances (the randomizer's build step 55, 2026-10-08:
  shuffled doors hidden there until taken), so `door` is the apworld's entrance name for the door walked through.

- **Hints:** Archipelago's `_read_hints_{team}_{slot}` (`docs/network protocol.md`, Get), for highlighting
  hinted checks. The server answers `SetNotify` on a `_read_` key with `SetReply` (`MultiServer.py`, 0.6.8), and
  PopTracker passes every key's `Retrieved` and `SetReply` on to the pack (`src/ap/aptracker.h`, `d2af7f1`).
- **The apworld itself,** for the logic export: from the randomizer's checkout, recording its commit and
  `world_version`, until the next release, then that release pinned (the user, 2026-10-08).

## Randomizer facts it builds on (the randomizer's repo, 2026-10-01)

- One region per game map: 243 maps, 508 shuffled doors (`apworld/bug_fables/data/doors.json`), plus fixed links
  and transfers (boat, elevators, story) that are never shuffled. Since the randomizer's build step 48 (2026-10-05) a
  map a roadblock cuts in parts has a region per part ("Map (Area)"), and a door or a location may stand in one.
- **Room Swap** moves "areas" (a map plus the maps joined to it by fixed doors) into another area's slot, within
  one of the 10 world parts and with the same door count. The slot graph stays vanilla (`entrances.py`).
- **Coupled/Decoupled** hand all 508 doors to Archipelago's `randomize_entrances`: any door to any door.
- No coordinates exist for rooms or locations in the apworld. The game has them: the pause map's 25 area positions
  (`PauseMenu.MapSetup`), each map's area (`MapControl.areaid`, the mod's map dump), and each door's spot and landing
  (the mod's entity dump). See the randomizer's `MEASURED.md`.

## What it contains

1. **Logic export** (a generator script): imports the apworld and writes the logic data: each region's
   entrances and each location's rule from Rule Builder `to_dict` (Archipelago 0.6.8 `docs/rule builder.md`,
   Serialization: the intended way to a tracker). The custom rules `CanUse`, `Member`, `MoveItem`, `Boat` and
   `WayBack` are exported by name and evaluated in Lua from the seed's slot_data options; `ItemOnHand` serializes
   itself as the `Or` of the item shops it stands for (its `to_dict`, "Custom serialization"), so only Archipelago's
   built-in rules carry it, `CanReachRegion` among them. Option filters: the comparisons, `contains` and `in`, each
   checked by the export against the kind of option the Lua compares it for.
2. **Lua:** an evaluator for the exported rule trees, and a region sweep (from the origin over the region graph with
   `door_targets` applied, a door leading to the region its target's partner stands in, until nothing changes, so a
   `CanReachRegion` read too early is asked again), rerun when items change.
3. **Items and locations:** every Archipelago item with its code; one location per room, one section per check (a
   check in a part of a map is a section of that map's pin).
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
   - **Superseded 2026-10-13 by the game's own pictures** (the user's ask), laid out as crystal-ap-tracker lays out
     its rooms (the user's pick; that tracker read for it, its row in the randomizer's `licensing.md`):
     - the World tab is the pause map's art, opened and rendered from above by the mod's dev command `worldmap`, each
       area pin where the game puts its pip (`tools/world_map.py`, `data/world_map.json`; no lines drawn);
     - then eight regions grouping the game's areas as the world map's picture does, in story order, then each area
       by its game name, then a tab for every room, checks or not (`data/area_pips.json`'s `regions` and `names`;
       Crystal gives every room its own tab too). Rooms in walking order from the game's start or from where an
       earlier area leads in. The area overviews and their door lines are gone;
     - each room's tab is the room as a seed shows it (`roomshot all`, its scenery as a new file has it with a seed's
       `scenery_hidden` and `scenery_present` on top; outline shells and builders' placeholder cubes left out; water in
       its own colour; `tools/room_pictures.py`), seen from the front at 30° (the user's pick over straight down and
       the game's own 10°), the view starting just before the entity nearest the camera so a dome, a front wall or a
       trunk before them is cut; a few rooms straight down by look (Beehive Main Area, Mystery Island, Power Plant,
       Honey Factory Core, Beehive Scanner Room); nine more fixed one by one, the user picking each from renders side
       by side (2026-10-13: five cut above a height, three without the view's cut, Barren Lands Cloud without its
       cloud floor; the mod's `Dev/MapShots.cs`). A pin at each check's own entity, its height counted (520 of 614),
       the rest in the room's middle. Nested tabs and `ActivateTab` read in PopTracker's `src/ui/trackerview.cpp` and
       `src/uilib/tabs.cpp` at `19f0b1f`: every tab set switches only if it has a tab of that name;
     - still to come: room names for the rooms only Enemysanity names (the apworld's to give, the user's yes for
       each).
     Pictures are fixed per map; with the doors shuffled the rooms stay at home and their doors tell where they lead
     (item 7), as Crystal does.
5. **Room Swap:** superseded 2026-10-13: with a tab and a picture per room, each room keeps its own checks wherever
   it was swapped to, and its doors say where they lead (item 7), as for every door shuffle.
6. **Fog of war:** a pin shows only when its room is in the visited list, unless the toggle item "Show unvisited
   rooms" is on (off by default). Only with the doors shuffled (the user, 2026-10-13): with the game's own doors
   every room shows.
7. **Doors:** with the door shuffle on, each door taken (the doors key) shows where it led, as far as PopTracker
   can show it: a badge or section on the room's pin, never a drawn line. Find the best fit in the docs then.
   Built 2026-10-08: the key read (item 21) and each taken door's destination worked out in Lua (`bf_door_led_to`,
   tested against every door of generated seeds). Still to come: showing it as Crystal does (the user, 2026-10-13):
   a pin on each door of its room's tab, the door taken badged with where it led, a click jumping to that room's
   tab; later a route between two doors.
8. **Items:** built 2026-10-13 with the game's own icons (`tools/item_icons.py`, the looks the mod gives them), one
   grid in rows: the party and Jump, the abilities (their member's face with the ability's word), the artifacts, the
   keys and passes with the other items after them, the gears and the boats (the user's pick).
9. **Following the player:** built 2026-10-13: on a current-map change, `ActivateTab` to the room's region, area
   and room; a setting, on by default (off stays where you are).
10. **Hints:** hinted checks highlighted (`Highlight` on sections, since 0.32.0). Built 2026-10-08: each of this
    slot's hinted checks takes the `Highlight` of its hint's status (PopTracker's states are Archipelago's
    `HintStatus`: Unspecified, NoPriority, Avoid, Priority; found is None), read from `_read_hints_{team}_{slot}`.
11. **Variants** (manifest `variants`): "Map" and "Compact" (items only). PopTracker has no checks-list widget: a
    layout's types are container, dock, array, tabbed, group, item, itemgrid, map, layout, recentpins, text and
    canvas (`doc/PACKS.md`, Layouts, 2026-10-03), so checks show only as pins on a map.
12. **Layouts:** `tracker_default`, `tracker_broadcast` (a stream view), and `settings_popup` holding the fog of
    war and auto tabbing toggles (built 2026-10-13, also in the bottom bar's Settings).
13. **Updates:** `versions_url` in the manifest, and a listing in PopTracker's pack list (its `packlist` branch,
    read its rules first).
14. **Version check:** `min_poptracker_version` and `target_poptracker_version` set to what was tested. The minimum
    is 0.33.0 since 2026-10-08, the newest API the pack uses (`Archipelago.Seed`; its `CHANGELOG.md`).

The rest of PopTracker's Archipelago interface (`doc/AUTOTRACKING.md`, `d2af7f1`), every part of it (the user,
2026-10-05: "support them all"; added 2026-10-08):

15. **A DeathLink shown:** `Archipelago:AddBouncedHandler`, whose argument is the bounce as a table; one tagged
    `DeathLink` marks the party in the item grid for a while (the look picked by the user on screen). Built
    2026-10-08 with a first look: "DL" in red on the party's items for 10 seconds (`BadgeText`,
    `ScriptHost:AddOnFrameHandler`).
16. **The goal shown as done:** Archipelago's read-only `_read_client_status_{team}_{slot}` (`docs/network
    protocol.md`, Get; 30 is `CLIENT_GOAL`). Built 2026-10-08: a Goal item at the end of the grid, lit when the key
    reads `Archipelago.ClientStatus.GOAL`. `SetNotify` covers a `_read_` key: the server notifies its subscribers
    (`MultiServer.py`, `on_client_status_change`, 0.6.8) and PopTracker passes every key on (`src/ap/aptracker.h`).
17. **A new seed starts fresh:** `Archipelago.Seed`, `.TeamNumber` and `.PlayerNumber` against what the pack kept; on a
    different seed or slot, the pack's own state (fog of war's toggle state, anything stored) is reset. Built
    2026-10-08, the data storage values read so far being that state for now.
18. **Checks right at connect:** `Archipelago.CheckedLocations` and `.MissingLocations` read in the Clear handler, so
    the pins are right before the first Location handler fires. Built 2026-10-03 (`8b40d72`), tested 2026-10-08.
19. **Hints that say whose item:** `Archipelago:GetPlayerAlias`, `:GetPlayerGame` and `:GetItemName` (since 0.28.1)
    for each hint of item 10: "whose item, which game". Not built: a section shows no text of its own, so where to
    show it is a pick on screen.
20. **The connect replay in one go:** not needed. PopTracker defers logic updates by itself for packs with the `ap`
    flag that target 0.31 or later (its `CHANGELOG.md`, v0.31.0, "Default to AllowDeferredLogicUpdate for packs with
    'ap' flag"; v0.30.2: this "may make any use of BulkUpdate obsolete"), and this pack targets 0.35.4.
21. **Data storage read at connect:** `Archipelago:Get(keys)` from the Clear handler beside `SetNotify`, with
    `AddRetrievedHandler`, so fog of war, the map and the doors are right before the first change. Built 2026-10-08
    the way PopTracker's own `examples/ap-storage-example` does it: `SetNotify`, then `Get`, one handler for both
    answers, each value's type checked.

Added 2026-10-13, from crystal-ap-tracker's look (the user's asks):

22. **What blocks the way:** a pin on each gated door and on each part of a room on a way onward that a key item, a
    story step or one clearing ability opens (77), saying what it needs from the apworld's own rule; terrain left
    out (the user: like Crystal's Sudowoodo, not every ledge).
23. **The bottom bar:** the map at full width, and along the bottom Items, the Goal on its own (its badge the
    artifacts received against `artifacts_required`), Events (the story's milestones among the logic's events,
    marked by hand; each counts for the logic) and Settings.
24. **Still to come:** a Bosses tab beside Items (bosses, mini-bosses and bounties, beaten or not), an Enemies tab
    like Crystal's Pokédex for Enemysanity, and events marked by the mod through a data storage key (a randomizer
    change, after 0.4.0).

## Not applicable (recorded so it's a decision, not a gap)

- `"apmanual"` (the pack sending checks): the mod sends every check itself.
- `"aphintgame"` (the pack scouting locations): it would reveal items the player hasn't found, and it is for hint
  games (the `HintGame` tag). Decided off (the user, 2026-10-06): seen items are never made hints in the randomizer
  either; the pack shows the server's hints (`_read_hints`, item 10).
- The `"tracker_capture_item"` layout: "not supported yet" (`doc/PACKS.md`, 2026-10-08). Until PopTracker has it.
- Memory and UAT auto-tracking: Archipelago gives everything the pack needs.

## Order

1. The logic export, the item grid, and the checks as pins on a placeholder map drawn by code (built 2026-10-03:
   `tools/export.py`, `scripts/logic.lua`, `tests/test_parity.py`); exported again at world 0.3.0 (2026-10-08: map
   areas, `CanReachRegion`, `ItemOnHand`, the new options; the randomizer's build step 56). Exported again
   2026-10-13 with every room mapped: 614 locations in 182 rooms of 25 areas; the start from slot_data; the last
   fight's artifact gate (`HasFromListUnique` with Rule Builder's `FromWorldAttr`, the randomizer's build step 94).
2. The map (its first version built 2026-10-04, see item 4), following the player, and hints.
3. Fog of war and doors: the randomizer writes their data storage keys since 2026-10-08 (its build steps 55 and 57).
4. Updates and the pack list, once the repo goes public with a release.
5. Items 15-21: built 2026-10-08 (`scripts/autotracking.lua`, `tests/test_autotracking.py`), but 19, which waits
   for a place on screen, and 20, which PopTracker does itself.

## Rules carried over from the randomizer

- No AI art; game art only as the game itself shows it, rendered by the mod's dev console (the user, 2026-10-13),
  and the user picks every look on screen.
- A project's licence before anything else of it, and the user's yes before reading it at all. PopTracker is
  GPL-3.0; the pack is its own data and Lua, with no PopTracker code copied. This repo is MIT (the user, 2026-10-03).
- Facts about PopTracker, Archipelago and the game come from their docs and source, never from memory.
- Ask before touching the game install, the Archipelago checkout or PopTracker's install.

## Decisions (2026-10-03, the user's)

- **The apworld comes from the randomizer's checkout**, imported through your Archipelago checkout (at the tag the
  world targets) where the randomizer's development guide links it in as `worlds/bug_fables`. The export records the
  randomizer's commit and `world_version`. A release pin waits for the next release (the user, 2026-10-08: v0.3.0
  has slot_data's `options` but not today's rooms; pinned once the next one is out).
- **Checks:** PopTracker's own `pack-checker` (its CI action, as the Crystal pack's CI runs it; it validates against
  PopTracker's schemas), plus **lupa parity tests**. Archipelago has no standard for testing a tracker's Lua (its core
  runs no Lua; Rule Builder's Serialization section leaves the export to the world dev), and the Crystal pack has
  none: it checks with pack-checker only, its logic hand-ported. Ours is generated, so a Python test can run the
  pack's Lua (Lua 5.4 through lupa) beside the apworld's own logic and prove they agree.
- **MIT**, like the randomizer. lupa (MIT, its Lua MIT) is a test dependency only; pack-checker (GPL-3.0) is run,
  never copied or shipped. Pillow (MIT-CMU) is a tools dependency since 2026-10-13, for the game's pictures (the
  randomizer's `licensing.md`). The game's pictures in the pack are the game's, not MIT: to be said in the README
  and the release.

## Verification

- Generator tests: every location id appears once (pending ones out), every rule names a real item and a real
  region, every door of `doors.json` found in the room data, the manifest is valid.
- Logic parity (lupa): the pack's Lua against the apworld's Python logic, over many seeds and item states: the
  locations, the regions reached and every entrance Archipelago made, each door mode as often as the others.
- `pack-checker` on the source folder, and on the release zip before a release.
- The user loads the pack in PopTracker against a local server (ask before starting either) and confirms on screen:
  the checks, logic colours, the item grid, the map, Room Swap placement, following the player, hints, doors,
  fog of war, both variants and the broadcast view.
