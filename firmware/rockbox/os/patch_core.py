#!/usr/bin/env python3
"""Coda OS hooks in the pinned Rockbox tree (~/rockbox, 7d090f24b9). Idempotent: every edit
is guarded by a marker, so re-running is a no-op. Everything is #ifdef CODA_OS, so the same
tree still builds stock Rockbox + the coda.rock plugin.

  python3 firmware/rockbox/os/patch_core.py [~/rockbox]

  apps/plugin.c     plugin_get_api(): the core's own API table, for Coda's rb pointer
  apps/main.c       Coda's first boot frame instead of the Rockbox logo; no clear after init
  apps/root_menu.c  boot into Coda; Rockbox's menus only after the hidden way out, and Back
                    at their root returns to Coda
  apps/apps.make    build Coda into the firmware (apps/coda/coda_os.make)
"""
import sys
from pathlib import Path

SRC = Path(sys.argv[1] if len(sys.argv) > 1 else Path.home() / "rockbox")
MARK = "CODA_OS"


def edit(rel, anchor, new, after=True, count=1):
    p = SRC / rel
    s = p.read_text()
    if (anchor + new if after else new + anchor) in s:
        return False
    assert s.count(anchor) == count, f"{rel}: anchor found {s.count(anchor)}x: {anchor[:60]!r}"
    s = s.replace(anchor, anchor + new if after else new + anchor)
    p.write_text(s)
    return True


changed = []

# --- plugin.c: hand out the API table
p = SRC / "apps/plugin.c"
s = p.read_text()
if "plugin_get_api" not in s:
    s = s.replace("int plugin_load(const char* plugin, const void* parameter)\n{",
                  "/* Coda OS: Coda is linked into the firmware and calls the core through this */\n"
                  "const struct plugin_api *plugin_get_api(void)\n{\n    return &rockbox_api;\n}\n\n"
                  "int plugin_load(const char* plugin, const void* parameter)\n{", 1)
    p.write_text(s)
    changed.append(True)

# --- main.c: our first frame instead of the Rockbox logo; keep it on screen after init
changed.append(edit("apps/main.c", "    show_logo_boot();\n",
    "#ifdef CODA_OS\n"
    "    {   /* Coda's boot animation, frame 0: shows while Rockbox starts up */\n"
    "        extern const struct plugin_api *plugin_get_api(void);\n"
    "        extern void coda_os_logo(const struct plugin_api *api);\n"
    "        coda_os_logo(plugin_get_api());\n"
    "    }\n"
    "#else\n", after=False, count=4))                 # native, sim and hosted init()s
changed.append(edit("apps/main.c", "#else\n    show_logo_boot();\n", "#endif\n", count=4))
p = SRC / "apps/main.c"
s = p.read_text()
old = ("    CHART(\"<init\");\n    FOR_NB_SCREENS(i)\n    {\n        screens[i].clear_display();\n"
       "        screens[i].update();\n    }\n")
if "#ifndef CODA_OS /* keep Coda's boot frame */" not in s:
    assert s.count(old) == 1
    s = s.replace(old, "    CHART(\"<init\");\n#ifndef CODA_OS /* keep Coda's boot frame */\n"
                       "    FOR_NB_SCREENS(i)\n    {\n        screens[i].clear_display();\n"
                       "        screens[i].update();\n    }\n#endif\n")
    p.write_text(s)
    changed.append(True)

# --- root_menu.c: Coda is the root; Rockbox's menus are the escape hatch
p = SRC / "apps/root_menu.c"
s = p.read_text()
if MARK not in s:
    old = "    push_current_activity(ACTIVITY_MAINMENU);\n    next_screen = root_menu_setup_screens();\n"
    assert s.count(old) == 1
    s = s.replace(old, old +
        "#ifdef CODA_OS\n"
        "    /* Coda OS: Coda is the root app. Its hidden way out (Menu + Back held) lands in\n"
        "     * Rockbox's main menu; Back at that menu's root goes back to Coda. */\n"
        "    extern const struct plugin_api *plugin_get_api(void);\n"
        "    extern void coda_os_run(const struct plugin_api *api);\n"
        "    coda_os_run(plugin_get_api());\n"
        "    next_screen = GO_TO_ROOT;\n"
        "#endif\n")
    old = ("                next_screen = do_menu(&root_menu_, &selected, NULL, false);\n\n"
           "                ignore_back_button_stub(false);\n")
    assert s.count(old) == 1
    s = s.replace(old, old +
        "#ifdef CODA_OS\n"
        "                if (next_screen == GO_TO_PREVIOUS || next_screen == GO_TO_WPS)\n"
        "                {   /* Back (or the music key) at Rockbox's root: home to Coda */\n"
        "                    coda_os_run(plugin_get_api());\n"
        "                    next_screen = GO_TO_ROOT;\n"
        "                    break;\n"
        "                }\n"
        "#endif\n")
    p.write_text(s)
    changed.append(True)

# --- menu.c: Back at Rockbox's root menu returns (to Coda) instead of doing nothing
changed.append(edit("apps/menu.c",
    "            else if (menu != &root_menu_)\n            {\n                ret = GO_TO_PREVIOUS;\n"
    "                done = true;\n            }\n",
    "#ifdef CODA_OS\n            else\n            {   /* Coda OS: Back at the root goes home to Coda */\n"
    "                ret = GO_TO_PREVIOUS;\n                done = true;\n            }\n#endif\n"))

# --- root_menu.c: a "Coda" item on top of Rockbox's menu; no Plugins entry
p = SRC / "apps/root_menu.c"
s = p.read_text()
if "coda_home" not in s:
    old = "struct menu_item_ex root_menu_;\n"
    assert s.count(old) == 1
    s = s.replace(old,
        "#ifdef CODA_OS\nMENUITEM_RETURNVALUE(coda_home, \"Coda\", GO_TO_PREVIOUS, NULL, Icon_Audio);\n#endif\n"
        + old, 1)
    old = "    /* Order here represents the default ordering */\n"
    assert s.count(old) == 1
    s = s.replace(old, old + "#ifdef CODA_OS\n    { \"coda\", &coda_home },\n#endif\n", 1)
    old = "    { \"plugins\", &rocks_browser },\n"
    assert s.count(old) == 1
    s = s.replace(old, "#ifndef CODA_OS /* Coda OS: no plugin menus */\n" + old + "#endif\n", 1)
    p.write_text(s)
    changed.append(True)

# --- apps.make: build Coda into the firmware when configured with -DCODA_OS
changed.append(edit("apps/apps.make", "SRC += $(call preprocess, $(APPSDIR)/SOURCES)\n",
    "\n# Coda OS (offline-music-player): Coda as the root app, linked into the firmware\n"
    "ifneq (,$(findstring -DCODA_OS,$(EXTRA_DEFINES)))\n"
    "  include $(APPSDIR)/coda/coda_os.make\n"
    "endif\n"))

print("patched" if any(changed) else "already patched", SRC)
