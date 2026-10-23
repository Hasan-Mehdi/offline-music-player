#!/usr/bin/env python3
"""2026-10-15 pass over the soundtrack catalog (data/ost_catalog.json), from the H2 user's
"so many soundtracks are all just Sonic; we're lacking Pokémon and Zelda": the groups the
heuristic made from song titles ("title", "Menu", "Credits", one Sonic zone by five
artists...) go, real games get their series, duplicate names merge, and the soundtracks
downloaded whole from YouTube playlists (scripts/harvest_ost_playlists.py) come in under
Pokémon, The Legend of Zelda and Need for Madness. A backup of the catalog is kept.

  .venv\\Scripts\\python scripts\\curate_osts_2026_10_15.py
"""
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CAT = ROOT / "data" / "ost_catalog.json"

KEEP = {   # group key -> (canonical, franchise)
    "the legend of zelda: twilight princess": ("The Legend of Zelda: Twilight Princess", "The Legend of Zelda"),
    "sonic generations": ("Sonic Generations", "Sonic"),
    "professor layton and the last specter": ("Professor Layton and the Last Specter", "Professor Layton"),
    "professor layton and the miracle mask": ("Professor Layton and the Miracle Mask", "Professor Layton"),
    "the legend of zelda: breath of the wild": ("The Legend of Zelda: Breath of the Wild", "The Legend of Zelda"),
    "zelda: breath of the wild official": ("The Legend of Zelda: Breath of the Wild", "The Legend of Zelda"),
    "the legend of zelda breath of the wild": ("The Legend of Zelda: Breath of the Wild", "The Legend of Zelda"),
    "the legend of zelda skyward sword": ("The Legend of Zelda: Skyward Sword", "The Legend of Zelda"),
    "the legend of zelda: link's awakening": ("The Legend of Zelda: Link's Awakening", "The Legend of Zelda"),
    "the legend of zelda: link's awakening orchestral arrangement": ("The Legend of Zelda: Link's Awakening Orchestral Arrangement", "The Legend of Zelda"),
    "hyrule warriors age of calamity": ("Hyrule Warriors: Age of Calamity", "The Legend of Zelda"),
    "zelda metal vol. iii": ("Zelda Metal Vol. III", "The Legend of Zelda"),
    "banjo kazooie": ("Banjo-Kazooie", "Banjo-Kazooie"),
    "banjo tooie": ("Banjo-Tooie", "Banjo-Kazooie"),
    "fire emblem: three houses": ("Fire Emblem: Three Houses", "Fire Emblem"),
    "fire emblem echoes: shadows of valentia": ("Fire Emblem Echoes: Shadows of Valentia", "Fire Emblem"),
    "fire emblem: fates": ("Fire Emblem: Fates", "Fire Emblem"),
    "persona 5: the phantom x": ("Persona 5: The Phantom X", "Persona"),
    "persona 3 reload": ("Persona 3 Reload", "Persona"),
    "runescape music": ("RuneScape", "RuneScape"),
    "runescape 3 music": ("RuneScape", "RuneScape"),
    "remix album by kunning fox) #pokemon #remix #backtounova": ("Back to Unova (Kunning Fox)", ""),
    "remix album by kunning fox)": ("Back to Unova (Kunning Fox)", ""),
    "pokémon legends: z-a": ("Pokémon Legends: Z-A", "Pokémon"),
    "mega dimension dlc": ("Pokémon Legends: Z-A", "Pokémon"),
    "pokémon sword and shield": ("Pokémon Sword & Shield", "Pokémon"),
    "pokémon black and white": ("Pokémon Black & White", "Pokémon"),
    "pokémon quest": ("Pokémon Quest", "Pokémon"),
    "pokemon sun and moon": ("Pokémon Sun & Moon", "Pokémon"),
    "pokemon scarlet/violet": ("Pokémon Scarlet & Violet", "Pokémon"),
    "pokémon x/y": ("Pokémon X & Y", "Pokémon"),
    "pokémon mystery dungeon: explorers of time/darkness/sky": ("Pokémon Mystery Dungeon: Explorers of Sky", "Pokémon"),
    "deltarune chapter 3": ("Deltarune", "Undertale/Deltarune"),
    "deltarune chapter 2": ("Deltarune", "Undertale/Deltarune"),
    "undertale yellow": ("Undertale Yellow", "Undertale/Deltarune"),
    "animal crossing: new leaf": ("Animal Crossing: New Leaf", "Animal Crossing"),
    "kirby super star ultra": ("Kirby Super Star Ultra", "Kirby"),
    "kirby's return to dream land": ("Kirby's Return to Dream Land", "Kirby"),
    "kirby: planet robobot": ("Kirby: Planet Robobot", "Kirby"),
    "kirby 64: the crystal shards": ("Kirby 64: The Crystal Shards", "Kirby"),
    "dedede's drum dash deluxe": ("Dedede's Drum Dash Deluxe", "Kirby"),
    "magolor epilogue": ("Kirby's Return to Dream Land Deluxe: Magolor Epilogue", "Kirby"),
    "mario kart wii": ("Mario Kart Wii", "Mario Kart"),
    "mario kart 64": ("Mario Kart 64", "Mario Kart"),
    "super mario 3d land": ("Super Mario 3D Land", "Mario"),
    "super mario galaxy": ("Super Mario Galaxy", "Mario"),
    "super mario galaxy 2": ("Super Mario Galaxy 2", "Mario"),
    "super mario rpg": ("Super Mario RPG", "Mario"),
    "super mario world": ("Super Mario World", "Mario"),
    "super mario bros. wonder": ("Super Mario Bros. Wonder", "Mario"),
    "bowser's fury": ("Bowser's Fury", "Mario"),
    "what a mario world!": ("What a Mario World", "Mario"),
    "yoshi's woolly world": ("Yoshi's Woolly World", "Yoshi"),
    "yoshi's island": ("Yoshi's Island", "Yoshi"),
    "sonic racing crossworlds": ("Sonic Racing: CrossWorlds", "Sonic"),
    "team sonic racing": ("Team Sonic Racing", "Sonic"),
    "sonic adventure": ("Sonic Adventure", "Sonic"),
    "sonic frontiers": ("Sonic Frontiers", "Sonic"),
    "sonic forces: speed battle": ("Sonic Forces: Speed Battle", "Sonic"),
    "monster hunter wilds": ("Monster Hunter Wilds", "Monster Hunter"),
    "monster hunter world iceborne": ("Monster Hunter World: Iceborne", "Monster Hunter"),
    "xenoblade chronicles x": ("Xenoblade Chronicles X", "Xenoblade"),
    "earthbound": ("EarthBound", "Mother"),
    "r4 / ridge racer type 4 / direct audio": ("R4: Ridge Racer Type 4", ""),
    "r4: ridge racer type 4": ("R4: Ridge Racer Type 4", ""),
    "block tales": ("Block Tales", ""), "castle crashers": ("Castle Crashers", ""),
    "league of legends": ("League of Legends", ""), "friday night funkin'": ("Friday Night Funkin'", ""),
    "miitopia": ("Miitopia", ""), "kingdom hearts 3d dream drop distance": ("Kingdom Hearts 3D: Dream Drop Distance", ""),
    "monogatari series off & monster season": ("Monogatari Series Off & Monster Season", ""),
    "penny's big breakaway": ("Penny's Big Breakaway", ""), "omori": ("OMORI", ""),
    "tomodachi life": ("Tomodachi Life", ""), "minecraft volume alpha": ("Minecraft - Volume Alpha", ""),
    "off": ("OFF", ""), "big money! deluxe": ("Big Money! Deluxe", ""), "item asylum": ("Item Asylum", ""),
    "ace attorney 6: spirit of justice": ("Phoenix Wright: Ace Attorney - Spirit of Justice", ""),
    "adventure time: hey ice king! why'd you steal our garbage?!!": ("Adventure Time: Hey Ice King! Why'd You Steal Our Garbage?!!", ""),
    "gimmick!": ("Gimmick!", ""), "plok": ("Plok", ""), "pvz soundfont cover": ("PvZ Soundfont Cover", ""),
    "the consouls": ("The Consouls", ""), "skeleton boomerang": ("Skeleton Boomerang", ""),
    "artificial fear": ("Artificial Fear", ""), "unitres dreams": ("UNITRES Dreams", ""),
    "deconstructed": ("Deconstructed", ""),
    # the soundtracks downloaded whole (scripts/harvest_ost_playlists.py)
    "pokémon legends: arceus": ("Pokémon Legends: Arceus", "Pokémon"),
    "pokémon colosseum": ("Pokémon Colosseum", "Pokémon"),
    "pokémon black & white": ("Pokémon Black & White", "Pokémon"),
    "pokémon black 2 & white 2": ("Pokémon Black 2 & White 2", "Pokémon"),
    "pokémon diamond, pearl & platinum": ("Pokémon Diamond, Pearl & Platinum", "Pokémon"),
    "pokémon sword & shield": ("Pokémon Sword & Shield", "Pokémon"),
    "pokémon heartgold & soulsilver": ("Pokémon HeartGold & SoulSilver", "Pokémon"),
    "the legend of zelda: ocarina of time": ("The Legend of Zelda: Ocarina of Time", "The Legend of Zelda"),
    "the legend of zelda: the wind waker": ("The Legend of Zelda: The Wind Waker", "The Legend of Zelda"),
    "the legend of zelda: tears of the kingdom": ("The Legend of Zelda: Tears of the Kingdom", "The Legend of Zelda"),
    "the legend of zelda: majora's mask": ("The Legend of Zelda: Majora's Mask", "The Legend of Zelda"),
    "need for madness": ("Need for Madness", "Need for Madness"),
    "need for madness 2": ("Need for Madness 2", "Need for Madness"),
    "hollow knight": ("Hollow Knight", "Hollow Knight"),
    "hollow knight: gods & nightmares": ("Hollow Knight: Gods & Nightmares", "Hollow Knight"),
    "hollow knight: silksong": ("Hollow Knight: Silksong", "Hollow Knight"),
}

DROP = """battle theme|sonic mania remix|traditional japanese version|instrumental|nintendo 3ds|sonic xg|
piano version|chemical plant zone|dearly beloved|sonic studio|special stage|staff roll|super slowed|title|act 3|
athletic theme|boss theme|deltarune ust|epic orchestral cover|file select|gerudo valley|hydrocity zone act 2|
main menu|orchestral cover|penumbra phantasm|raindrops keep falling on my head|reminiscence|song of healing|
the world revolving|title theme|ultra slowed|underwater|act 2|black knife|megalovania|nicolas quiles|
nintendo 3ds camera|rainbow road|rude buster|september|star light zone|stickerbush symphony|summer|title screen|
album]|aquatic ruin zone|brentalfloss|corneria|death by glamour|deltarune remix|doomsday zone|fantasy|
field of hopes and dreams|flying battery zone|lucaspucas|mines|mr.asyu|nintendo eshop|outset island|
piano version)|secret of the forest|siivagunner: king for another day|super mario bros. cd|
super mario land 2 remastered '92 style|super mario world remastered|time|ultrakill p-3 fanmade|windy summer|
your love|8-bit famitracker|accumula town|copyright free music|cover|credits|cupid|deltarune fan-secret boss theme|
dire, dire docks|dragon roost island|drum & bass|dt remix|ending theme|epic orchestral arrangement|erhu cover|
fanmade sm64 song|fear factory|final boss|forest interlude|game over|his theme|hydrocity act 2|i love you|
i miss you|iluvslapbass|isabella's lullaby|it's tv time!|kakariko village|krptic unknown|lofi|magic|
main menu theme|menu|metropolis zone|midna's lament|overworldb|pallet town|paradise|piano|point of no return|
ponpiehi|quartz quadrant|remember summer days|resonance|ritmo zelda|ruder buster|scrap brain zone|
sega genesis cover|shop|sonic mania inspired remix|space|sped up|sunset|survive|sweden|system settings|tell me|
the intro stage|theme|theme song|timeless|tines sensahthe|with lyrics|zelda: breath of the wild soundtrack medley"""


def main():
    cat = json.loads(CAT.read_text(encoding="utf-8")) if CAT.exists() else {}
    bak = CAT.with_name("ost_catalog.2026-10-15.bak.json")
    if CAT.exists() and not bak.exists():
        shutil.copy2(CAT, bak)
    for k, (canon, fr) in KEEP.items():
        cat[k] = {"keep": True, "canonical": canon, "franchise": fr}
    for k in [x.strip() for x in DROP.replace("\n", "").split("|") if x.strip()]:
        cat[k] = {"keep": False, "canonical": "", "franchise": ""}
    CAT.write_text(json.dumps(cat, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"catalog: {len(cat)} entries ({sum(1 for v in cat.values() if not v.get('keep', True))} dropped)")


if __name__ == "__main__":
    main()
