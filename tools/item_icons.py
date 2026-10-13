"""Writes images/items/game/<code>.png: each tracked item's icon as the game draws it, cut from the sprite sheets the
randomizer mod's SpriteDump debug setting writes, the way the mod picks an item's look (its ItemSwap.Looks): an item
or key item its own sprite, a medal its medal sprite, a party member the pause menu's party icon, an artifact its
chapter's icon on the start menu (StartMenu.psprite), an ability the icon of the member who uses it. Items the game has
no sprite for keep the export's drawn icon.

    python tools/item_icons.py --archipelago <your Archipelago checkout> <your Bug Fables install>/BepInEx
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

PACK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PACK / "tools"))
import export  # noqa: E402

# The game's sprite indexes the mod uses for these looks (decompiled StartMenu.psprite; ItemSwap.MemberSprite).
ARTIFACT_ICONS = [99, 112, 114, 115, 123, 124, 125]
MEMBER_ICON = 94
# The mod's own key items borrow a game item's look (its CustomItems.cs): the Boat Ticket and Progressive Boat the
# Platinum Card's, the submarine the Big Gear's until one is picked.
LOOKS_LIKE = {200: 176, 212: 159, 213: 176}


def labelled(picture: Image.Image, word: str) -> Image.Image:
    """The picture on a 64 by 64 square with a word along its bottom, white edged in black."""
    out = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    out.alpha_composite(picture, ((64 - picture.width) // 2, 0))
    draw = ImageDraw.Draw(out)
    size = 15
    while size > 8 and draw.textlength(word, font=ImageFont.load_default(size=size)) > 60:
        size -= 1
    font = ImageFont.load_default(size=size)
    width = draw.textlength(word, font=font)
    draw.text(((64 - width) / 2, 46), word, font=font, fill=(255, 255, 255, 255), stroke_width=2,
              stroke_fill=(0, 0, 0, 255))
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--archipelago", required=True, type=Path)
    parser.add_argument("bepinex", type=Path)
    args = parser.parse_args()
    dump = args.bepinex.resolve()
    w = export.load_world(args.archipelago.resolve())
    data = w["data"]
    tracked = {item["name"]: item["code"] for item in export.build(w)["items"]}

    def table(name: str, key) -> dict:
        with open(dump / name, encoding="utf-8", newline="") as source:
            return {key(row): row for row in csv.DictReader(source, delimiter="\t")}
    items = table("bugfablesap-itemsprites.tsv", lambda r: (int(r["kind"]), int(r["id"])))
    gui = table("bugfablesap-guisprites.tsv", lambda r: int(r["index"]))
    sheets: dict[str, Image.Image] = {}

    def cut(row: dict) -> Image.Image:
        sheet = sheets.setdefault(row["sheet"], Image.open(dump / f"bugfablesap-sheet-{row['sheet']}.png").convert("RGBA"))
        x, y, width, height = (int(row[k]) for k in ("x", "y", "w", "h"))
        # A sprite's rect counts from the sheet's bottom left.
        return sheet.crop((x, sheet.height - y - height, x + width, sheet.height - y))

    holders = {}
    first_ability = {}
    for name, ability in w["abilities"].ABILITIES.items():
        if ability.holder:
            holders.setdefault(ability.item, ability.holder)
        if ability.level == 1:
            first_ability[ability.item] = name
    members = list(w["items"].MEMBERS)
    out_dir = PACK / "images/items/game"
    out_dir.mkdir(parents=True, exist_ok=True)
    icons = {}
    for item in data.ITEMS:
        code = tracked.get(item.name)
        if code is None:
            continue
        row = None
        if item.kind in (data.ITEM_KIND, data.KEY_ITEM_KIND):
            row = items.get((0, LOOKS_LIKE.get(item.game_id, item.game_id)))
        elif item.kind == data.MEDAL_KIND:
            row = items.get((1, item.game_id))
        elif item.kind == data.MEMBER_KIND:
            row = gui.get(MEMBER_ICON + item.game_id)
        elif item.kind == data.ARTIFACT_KIND and 1 <= item.game_id <= len(ARTIFACT_ICONS):
            row = gui.get(ARTIFACT_ICONS[item.game_id - 1])
        elif item.kind == data.MOVE_KIND and item.name in holders:
            row = gui.get(MEMBER_ICON + members.index(holders[item.name]))
        if row is not None:
            picture = cut(row)
        elif item.kind == data.MOVE_KIND and (dump / "bugfablesap-apicon.png").exists():
            # An ability no member holds (Jump): the mod's own Archipelago icon, as the mod shows it (its apicon).
            picture = Image.open(dump / "bugfablesap-apicon.png").convert("RGBA")
        else:
            continue
        picture.thumbnail((64, 64), Image.LANCZOS)
        if item.kind == data.MOVE_KIND and item.name in first_ability:
            # The member's face for each of their abilities, as the mod shows them: its first ability's word on it
            # (a second copy's, Halt, Horn Dash or Icicle, is the grid's count of 2).
            picture = labelled(picture, first_ability[item.name].split()[-1])
        picture.save(out_dir / f"{code}.png", optimize=True)
        icons[code] = f"images/items/game/{code}.png"
    out = {"_about": "Each tracked item's icon cut from the game's sprite sheets (tools/item_icons.py); the others keep "
                     "the export's drawn icon.", "icons": dict(sorted(icons.items()))}
    (PACK / "data/item_icons.json").write_text(json.dumps(out, indent=1) + "\n", "utf-8", newline="\n")
    print(f"{len(icons)} of {len(tracked)} items with the game's icon")


if __name__ == "__main__":
    main()
