"""Logic parity: the pack's Lua (scripts/logic.lua, run by lupa's Lua 5.4, the version PopTracker packs run) against
the apworld's own logic, on generated seeds with random options and random item sets. Both answer the same question:
which of the seed's locations can be reached with these items.

    ARCHIPELAGO_DIR=<your Archipelago checkout> python -m pytest tests
"""
from __future__ import annotations

import os
import random
import sys
import unittest
from pathlib import Path

PACK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PACK / "tools"))
import export  # noqa: E402

WORLD = export.load_world(Path(os.environ["ARCHIPELAGO_DIR"]).resolve())

from lupa.lua54 import LuaRuntime  # noqa: E402

from BaseClasses import CollectionState  # noqa: E402
from Options import Choice, Range, Toggle  # noqa: E402
from test.general import setup_multiworld  # noqa: E402
from worlds.AutoWorld import call_all  # noqa: E402
from worlds.bug_fables.world import BugFablesWorld  # noqa: E402

STEPS = ("generate_early", "create_regions", "create_items", "set_rules", "connect_entrances", "generate_basic",
         "pre_fill")
SEEDS = int(os.environ.get("PARITY_SEEDS", "60"))
STATES_PER_SEED = 12
# The options that change the logic or the location set, each rolled at random.
ROLLED = (*WORLD["slot_data"].SLOT_OPTIONS, "starting_party_member", "starting_location")


def random_options(rng: random.Random) -> dict:
    options = {}
    for name in ROLLED:
        option = BugFablesWorld.options_dataclass.type_hints[name]
        if issubclass(option, Toggle):
            options[name] = rng.random() < 0.5
        elif issubclass(option, Choice):
            options[name] = rng.choice(sorted(set(option.options.values())))
        elif issubclass(option, Range):
            options[name] = rng.randint(option.range_start, option.range_end)
    return options


class Lua:
    """The pack's logic in a Lua runtime, with PopTracker's Tracker answering from the counts set here."""

    def __init__(self) -> None:
        self.counts: dict[str, int] = {}
        self.runtime = LuaRuntime(unpack_returned_tuples=True)
        scripts = (PACK / "scripts").as_posix()
        self.runtime.execute(f'package.path = "{scripts}/?.lua;{scripts}/?/init.lua;" .. package.path')
        self.runtime.globals().Tracker = self.runtime.table_from(
            {"ProviderCountForCode": lambda _tracker, code: self.counts.get(code, 0)})
        self.runtime.execute('require("logic")')
        self.g = self.runtime.globals()

    def set_seed(self, slot_data: dict, location_ids: list[int] | None) -> None:
        ids = None if location_ids is None else self.runtime.table_from(location_ids)
        self.g.bf_set_seed(self.runtime.table_from(slot_data, recursive=True), ids)


def every_custom_rule() -> list:
    """Each of the apworld's own rules with each argument it takes, and the rules built from them: the logic may not
    use one yet (a one-way's way back waits for the rooms to be mapped), so they're compared one by one too."""
    from rule_builder.rules import Has

    rules = WORLD["custom_rules"]
    abilities = WORLD["abilities"].ABILITIES
    return [*(rules.CanUse(name) for name in abilities), *(rules.MoveItem(name) for name in abilities),
            *(rules.Member(name) for name in WORLD["items"].MEMBERS), rules.Boat(1), rules.Boat(2),
            rules.WayBack(Has("Jump")), rules.one_way(Has("Explorer Permit"), Has("Jump")),
            rules.WHOLE_PARTY, rules.ALL_ATTACKS, WORLD["rules"].JUMP]


class TestParity(unittest.TestCase):
    def test_rules(self) -> None:
        rng = random.Random(1003)
        lua = Lua()
        codes = {item["name"]: item["code"] for item in export.build(WORLD)["items"]}
        rules = [(rule, lua.runtime.table_from(rule.to_dict(), recursive=True)) for rule in every_custom_rule()]
        for n in range(SEEDS):
            options = random_options(rng)
            multiworld = setup_multiworld(BugFablesWorld, steps=(), seed=rng.getrandbits(32), options=options)
            # Through create_items: the starting members are start inventory there.
            for step in STEPS[:3]:
                call_all(multiworld, step)
            world = multiworld.worlds[1]
            lua.set_seed({"options": WORLD["slot_data"].options_for_slot(world), "door_targets": [],
                          "starting_member": world.starting_member,
                          "world_version": WORLD["data"].WORLD_VERSION}, None)
            for k in range(STATES_PER_SEED):
                held = {name: rng.randint(0, 2) for name in codes if rng.random() < 0.6}
                state = CollectionState(multiworld)
                for name, count in held.items():
                    for _ in range(count):
                        state.collect(world.create_item(name), prevent_sweep=True)
                lua.counts.clear()
                lua.counts.update({codes[name]: count for name, count in held.items()})
                for rule, table in rules:
                    with self.subTest(rule=str(rule), options=options, held=held):
                        self.assertEqual(lua.g.bf_eval(table), rule.resolve(world)(state))

    def test_seeds(self) -> None:
        rng = random.Random(20261003)
        lua = Lua()
        codes = {item["name"]: item["code"] for item in export.build(WORLD)["items"]}
        for n in range(SEEDS):
            options = random_options(rng)
            seed = rng.getrandbits(32)
            with self.subTest(seed=seed, options=options):
                multiworld = setup_multiworld(BugFablesWorld, steps=(), seed=seed, options=options)
                for step in STEPS:
                    call_all(multiworld, step)
                world = multiworld.worlds[1]
                ids = sorted(loc.address for loc in world.get_locations() if loc.address is not None)
                slot_data = dict(world.fill_slot_data())

                # Which locations a seed holds: from the server's list, and from the options alone (no server).
                lua.set_seed(slot_data, None)
                self.assertEqual({i for i in WORLD["data"].LOCATION_NAME_TO_ID.values() if lua.g.bf_in_seed(i)},
                                 set(ids), "the categories")
                lua.set_seed(slot_data, ids)

                pool = [item for item in multiworld.itempool if item.player == 1 and item.advancement]
                events = [loc for loc in world.get_locations() if loc.address is None]
                for k in range(STATES_PER_SEED):
                    share = (0.0, 1.0)[k] if k < 2 else rng.random()
                    held = [item for item in pool if rng.random() < share]
                    state = CollectionState(multiworld)
                    for item in held:
                        state.collect(item, prevent_sweep=True)
                    state.sweep_for_advancements(locations=events)
                    expected = {loc.address for loc in world.get_locations()
                                if loc.address is not None and loc.can_reach(state)}
                    lua.counts.clear()
                    for item in held:
                        code = codes.get(item.name)
                        if code:
                            lua.counts[code] = lua.counts.get(code, 0) + 1
                    got = {i for i in ids if lua.g.bf_location(i)}
                    names = {loc.address: loc.name for loc in world.get_locations()}
                    self.assertEqual(sorted(names[i] for i in got - expected), [], f"state {k}: Lua only")
                    self.assertEqual(sorted(names[i] for i in expected - got), [], f"state {k}: apworld only")


if __name__ == "__main__":
    unittest.main()
