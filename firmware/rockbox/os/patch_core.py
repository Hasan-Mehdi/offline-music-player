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


def wrap(rel, old, new, marker, count=1):
    """Replace every `old` with `new` (which carries `marker`) once; a no-op afterwards."""
    p = SRC / rel
    s = p.read_text()
    if marker in s:
        return False
    assert s.count(old) == count, f"{rel}: found {s.count(old)}x: {old[:60]!r}"
    p.write_text(s.replace(old, new))
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
changed.append(wrap("apps/main.c", "\n    show_logo_boot();\n",
    "\n#ifdef CODA_OS /* coda: boot frame */\n"
    "    {   /* Coda's boot animation, frame 0: shows while Rockbox starts up */\n"
    "        extern const struct plugin_api *plugin_get_api(void);\n"
    "        extern void coda_os_logo(const struct plugin_api *api);\n"
    "        coda_os_logo(plugin_get_api());\n"
    "    }\n"
    "#else\n    show_logo_boot();\n#endif\n", "coda: boot frame", count=2))   # native + hosted init()
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

# --- panic.c: Coda's crash screen, then a restart (stock waits forever on this player)
changed.append(wrap("firmware/panic.c", "    va_end( ap );\n\n    lcd_set_viewport(NULL);\n",
    "    va_end( ap );\n\n"
    "#ifdef CODA_OS /* coda: crash screen */\n"
    "    {   /* Coda OS: say it in Coda's colours and restart; never returns on the device */\n"
    "        extern void coda_os_panic(const char *msg);\n"
    "        coda_os_panic(panic_buf);\n"
    "    }\n"
    "#endif\n"
    "    lcd_set_viewport(NULL);\n", "coda: crash screen"))

# --- misc.c: Coda's power-off animation instead of the "Shutting down" splash (and Coda's
# own low/empty battery note). Only the message changes: the battery checks, the order of
# the shutdown and the power-off itself are Rockbox's, untouched.
changed.append(wrap("apps/misc.c",
    "                if (global_settings.show_shutdown_message)\n"
    "                    splash(0, str(LANG_SHUTTINGDOWN));\n",
    "#ifdef CODA_OS /* coda: power-off animation */\n"
    "                {\n                    extern void coda_os_shutdown(int why);\n"
    "                    coda_os_shutdown(0);\n                }\n#else\n"
    "                if (global_settings.show_shutdown_message)\n"
    "                    splash(0, str(LANG_SHUTTINGDOWN));\n#endif\n",
    "coda: power-off animation"))
# ...and no blank frame before it: stock clears the screen and shows that before its splash,
# which flashed between Coda's last frame and its animation
changed.append(wrap("apps/misc.c",
    "        clear_screen_buffer(false);\n"
    "        FOR_NB_SCREENS(i)\n        {\n            screens[i].update();\n"
    "            screens[i].scroll_stop();\n        }\n",
    "#ifndef CODA_OS /* coda: no blank before the power-off */\n"
    "        clear_screen_buffer(false);\n#endif\n"
    "        FOR_NB_SCREENS(i)\n        {\n#ifndef CODA_OS\n            screens[i].update();\n#endif\n"
    "            screens[i].scroll_stop();\n        }\n",
    "coda: no blank before the power-off"))
changed.append(wrap("apps/misc.c",
    "                msg_id = LANG_WARNING_BATTERY_LOW;\n"
    "                splashf(0, \"%s %s\", str(LANG_WARNING_BATTERY_LOW),\n"
    "                                    str(LANG_SHUTTINGDOWN));\n",
    "                msg_id = LANG_WARNING_BATTERY_LOW;\n#ifdef CODA_OS /* coda: battery low note */\n"
    "                {\n                    extern void coda_os_shutdown(int why);\n"
    "                    coda_os_shutdown(1);\n                }\n#else\n"
    "                splashf(0, \"%s %s\", str(LANG_WARNING_BATTERY_LOW),\n"
    "                                    str(LANG_SHUTTINGDOWN));\n#endif\n",
    "coda: battery low note"))
changed.append(wrap("apps/misc.c",
    "            msg_id = LANG_WARNING_BATTERY_EMPTY;\n"
    "            splashf(0, \"%s %s\", str(LANG_WARNING_BATTERY_EMPTY),\n"
    "                                str(LANG_SHUTTINGDOWN));\n",
    "            msg_id = LANG_WARNING_BATTERY_EMPTY;\n#ifdef CODA_OS /* coda: battery empty note */\n"
    "            {\n                extern void coda_os_shutdown(int why);\n"
    "                coda_os_shutdown(2);\n            }\n#else\n"
    "            splashf(0, \"%s %s\", str(LANG_WARNING_BATTERY_EMPTY),\n"
    "                                str(LANG_SHUTTINGDOWN));\n#endif\n",
    "coda: battery empty note"))

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

# ===================================================================== strip build
# -DCODA_OS_STRIP on top of -DCODA_OS: no Rockbox UI at all. Coda is the only screen.

# --- plugin.c: the API table with only Coda's entries (generated: gen_api_table.py)
p = SRC / "apps/plugin.c"
s = p.read_text()
if "coda_api_init.h" not in s:
    head = "static const struct plugin_api rockbox_api = {\n"
    assert s.count(head) == 1
    i = s.index(head) + len(head)
    j = s.index("\n};\n", i)
    s = (s[:i] + "#if defined(CODA_OS_STRIP) && !defined(CODA_API_GEN)\n"
         "#include \"coda_api_init.h\"   /* Coda OS strip: only what Coda calls */\n#else\n"
         + s[i:j + 1] + "#endif\n" + s[j + 1:])
    p.write_text(s)
    changed.append(True)

# --- main.c: Coda forever instead of root_menu(); no file-browser / list setup
changed.append(wrap("apps/main.c", "\n    CHART(\">root_menu\");\n    root_menu();\n",
    "\n#ifdef CODA_OS_STRIP /* coda: only UI */\n"
    "    {   /* Coda OS strip: Coda is the only UI; there is no Rockbox menu to go back to */\n"
    "        extern const struct plugin_api *plugin_get_api(void);\n"
    "        extern void coda_os_run(const struct plugin_api *api);\n"
    "        for (;;)\n            coda_os_run(plugin_get_api());\n"
    "    }\n#else\n    CHART(\">root_menu\");\n    root_menu();\n#endif\n", "coda: only UI"))
changed.append(wrap("apps/main.c", "\n    list_init();\n    tree_init();\n",
    "\n#ifndef CODA_OS_STRIP /* coda: no browser */\n    list_init();\n    tree_init();\n#endif\n",
    "coda: no browser"))

# --- main.c: no database scan at boot (Coda keeps its own library index)
changed.append(wrap("apps/main.c", "\n    init_tagcache();\n",
    "\n#ifndef CODA_OS_STRIP /* coda: no database */\n    init_tagcache();\n#endif\n",
    "coda: no database", count=2))

# --- usb_screen.c: Coda draws the USB screen (Rockbox still does all the USB work)
changed.append(wrap("apps/gui/usb_screen.c", "\n    usb_screens_draw(usb_screen_vps_ar);\n",
    "\n#ifdef CODA_OS /* coda: usb poster */\n"
    "    extern int coda_os_usb_draw(void);\n"
    "    if (!coda_os_usb_draw())\n"
    "#endif\n    usb_screens_draw(usb_screen_vps_ar);\n", "coda: usb poster"))

# --- unicode.c: no Unicode normalization of tags (utf8proc's 333 KB of tables). Rockbox
# normalizes title/artist/album for its own screens; Coda shows its own library's text.
changed.append(wrap("firmware/common/unicode.c",
    "void utf8_normalize(char *string)\n{\n    utf8proc_ssize_t result, orig;\n",
    "void utf8_normalize(char *string)\n{\n"
    "#ifdef CODA_OS_STRIP /* coda: tags as they are */\n"
    "    (void)string;      /* Coda OS strip: no Rockbox screen shows these tags */\n"
    "}\n#else\n"
    "    utf8proc_ssize_t result, orig;\n", "coda: tags as they are"))
changed.append(wrap("firmware/common/unicode.c",
    "    mutex_unlock(&norm_mutex);\n}\n",
    "    mutex_unlock(&norm_mutex);\n}\n#endif /* coda: end tags */\n", "coda: end tags"))

# --- settings_list.c: the settings table without Rockbox's menus. Value formatters and
# voice names exist only for menu screens; the menu-layout settings (context menu,
# hotkeys, root menu order) only for menus. Callbacks that apply a setting stay.
changed.append(wrap("apps/settings_list.c", "#define NODEFAULT INT(0)\n",
    "#define NODEFAULT INT(0)\n"
    "#ifdef CODA_OS_STRIP /* coda: no menu formatters */\n"
    "#define CODA_UI(f) NULL    /* Coda OS strip: no Rockbox screen formats or speaks values */\n"
    "#else\n#define CODA_UI(f) f\n#endif\n", "coda: no menu formatters"))
for old, new, n in (
        ("{cb, unit, step, min, max, formatter, get_talk_id}}}}",
         "{cb, unit, step, min, max, CODA_UI(formatter), CODA_UI(get_talk_id)}}}}", 2),
        ("{cb, formatter, get_talk_id, unit, count,       \\",
         "{cb, CODA_UI(formatter), CODA_UI(get_talk_id), unit, count,       \\", 1),
        ("{cb, formatter, get_talk_id, unit, count, cfg_vals, list}}}}",
         "{cb, CODA_UI(formatter), CODA_UI(get_talk_id), unit, count, cfg_vals, list}}}}", 1)):
    p = SRC / "apps/settings_list.c"
    s = p.read_text()
    if new not in s:
        assert s.count(old) == n, f"settings_list.c: {old!r} x{s.count(old)}"
        p.write_text(s.replace(old, new))
        changed.append(True)
changed.append(wrap("apps/settings_list.c",
    "   CUSTOM_SETTING(0, context_wps,\n",
    "#ifndef CODA_OS_STRIP /* coda: no menu layouts */\n   CUSTOM_SETTING(0, context_wps,\n",
    "coda: no menu layouts"))
changed.append(wrap("apps/settings_list.c",
    "#endif /* HAVE_HOTKEY */\n\n    INT_SETTING(F_TIME_SETTING, resume_rewind,",
    "#endif /* HAVE_HOTKEY */\n#endif /* coda: menu layouts */\n\n"
    "    INT_SETTING(F_TIME_SETTING, resume_rewind,", "coda: menu layouts */"))
changed.append(wrap("apps/settings_list.c",
    "   CUSTOM_SETTING(0, root_menu_customized,\n                  LANG_ROCKBOX_TITLE, /* lang string here is never actually used */\n"
    "                  NULL, \"root menu order\",\n"
    "                  root_menu_load_from_cfg, root_menu_write_to_cfg,\n"
    "                  root_menu_is_changed, root_menu_set_default),\n",
    "#ifndef CODA_OS_STRIP /* coda: no root menu order */\n"
    "   CUSTOM_SETTING(0, root_menu_customized,\n                  LANG_ROCKBOX_TITLE, /* lang string here is never actually used */\n"
    "                  NULL, \"root menu order\",\n"
    "                  root_menu_load_from_cfg, root_menu_write_to_cfg,\n"
    "                  root_menu_is_changed, root_menu_set_default),\n#endif\n",
    "coda: no root menu order"))

# --- main.c: Rockbox's boot logo is never drawn under Coda OS (Coda's boot frame is)
changed.append(wrap("apps/main.c",
    "/* The disk isn't ready at boot, rblogo is stored in bin and erased after boot */\n"
    "int show_logo_boot( void ) INIT_ATTR;\nint show_logo_boot( void )\n{\n",
    "#ifndef CODA_OS /* coda: no rockbox logo */\n"
    "/* The disk isn't ready at boot, rblogo is stored in bin and erased after boot */\n"
    "int show_logo_boot( void ) INIT_ATTR;\nint show_logo_boot( void )\n{\n",
    "coda: no rockbox logo"))
p = SRC / "apps/main.c"
s = p.read_text()
i = s.index("#ifndef CODA_OS /* coda: no rockbox logo */")
j = s.index("\n}\n", i) + 3
CODA_LOGO = ("#else /* coda: logo is Coda's */\n"
             "int show_logo_boot( void )\n{   /* every place Rockbox redraws its logo (after a disk scan, the\n"
             "     * database check) shows Coda's boot frame instead */\n"
             "    extern const struct plugin_api *plugin_get_api(void);\n"
             "    extern void coda_os_logo(const struct plugin_api *api);\n"
             "    coda_os_logo(plugin_get_api());\n    return 0;\n}\n"
             "#endif /* coda: end logo */\n")
if "coda: logo is Coda's" not in s:
    if "#endif /* coda: end logo */\n" in s:
        s = s.replace("#endif /* coda: end logo */\n", CODA_LOGO, 1)
    else:
        s = s[:j] + CODA_LOGO + s[j:]
    p.write_text(s)
    changed.append(True)

# --- main.c (strip): no shortcuts menu (it alone keeps the context menu, playlist viewer,
# settings menus and the debug screen alive) and no voice-file announcement
changed.append(wrap("apps/main.c", "\n    shortcuts_init();\n",
    "\n#ifndef CODA_OS_STRIP /* coda: no shortcuts */\n    shortcuts_init();\n#endif\n",
    "coda: no shortcuts", count=2))
changed.append(wrap("apps/main.c",
    "    talk_announce_voice_invalid(); /* notify user w/ voice prompt if voice file invalid */\n",
    "#ifndef CODA_OS_STRIP /* coda: no voice check */\n"
    "    talk_announce_voice_invalid(); /* notify user w/ voice prompt if voice file invalid */\n"
    "#endif\n", "coda: no voice check", count=2))

# --- settings.c (strip): none of the menu-screen resources (UI font, on-screen keyboard,
# peak meter, list icons, colour theme). Coda draws every pixel with its own fonts.
changed.append(wrap("apps/settings.c",
    "    peak_meter_init_times(\n        global_settings.peak_meter_release, global_settings.peak_meter_hold,\n"
    "        global_settings.peak_meter_clip_hold);\n",
    "#ifndef CODA_OS_STRIP /* coda: no peak meter */\n"
    "    peak_meter_init_times(\n        global_settings.peak_meter_release, global_settings.peak_meter_hold,\n"
    "        global_settings.peak_meter_clip_hold);\n#endif\n", "coda: no peak meter"))
changed.append(wrap("apps/settings.c",
    "        /* fonts need to be loaded before the WPS */\n",
    "#ifndef CODA_OS_STRIP /* coda: no ui font, no keyboard */\n"
    "        /* fonts need to be loaded before the WPS */\n", "coda: no ui font, no keyboard"))
changed.append(wrap("apps/settings.c",
    "        else\n            load_kbd(NULL);\n",
    "        else\n            load_kbd(NULL);\n#endif /* coda: end ui font */\n", "coda: end ui font"))
changed.append(wrap("apps/settings.c",
    "        /* load the icon set */\n        CHART(\">icons_init\");\n        icons_init();\n"
    "        CHART(\"<icons_init\");\n\n#ifdef HAVE_LCD_COLOR\n"
    "        CHART(\">read_color_theme_file\");\n        read_color_theme_file();\n"
    "        CHART(\"<read_color_theme_file\");\n#endif\n",
    "#ifndef CODA_OS_STRIP /* coda: no icons, no colour theme */\n"
    "        /* load the icon set */\n        CHART(\">icons_init\");\n        icons_init();\n"
    "        CHART(\"<icons_init\");\n\n#ifdef HAVE_LCD_COLOR\n"
    "        CHART(\">read_color_theme_file\");\n        read_color_theme_file();\n"
    "        CHART(\"<read_color_theme_file\");\n#endif\n#endif\n", "coda: no icons, no colour theme"))

# --- misc.c (strip): no automatic bookmarks; a new firmware copied over USB restarts into
# itself instead of asking with Rockbox's yes/no screen
changed.append(wrap("apps/misc.c", "            bookmark_autobookmark(false);\n",
    "#ifndef CODA_OS_STRIP /* coda: no bookmarks */\n            bookmark_autobookmark(false);\n#endif\n",
    "coda: no bookmarks"))
changed.append(wrap("apps/misc.c", "            bookmark_autobookmark(true);\n",
    "#ifndef CODA_OS_STRIP /* coda: no autobookmark */\n            bookmark_autobookmark(true);\n#endif\n",
    "coda: no autobookmark"))
changed.append(wrap("apps/misc.c",
    "                    if(gui_syncyesno_run(&message, NULL, NULL) == YESNO_YES)\n",
    "#ifdef CODA_OS_STRIP /* coda: update restarts */\n"
    "                    (void)message;   /* Coda OS strip: a new firmware -> straight into it */\n"
    "                    splash(HZ, \"Coda OS updated. Restarting.\");\n"
    "                    if (true)\n#else\n"
    "                    if(gui_syncyesno_run(&message, NULL, NULL) == YESNO_YES)\n#endif\n",
    "coda: update restarts"))

# --- playlist.c: resuming the queue after power-on says nothing (Coda OS resumes it behind
# its own screen; Rockbox's "Loading..." splash and progress bar would draw over Coda's)
changed.append(wrap("apps/playlist.c",
    "&pl_cmds_start;\n\n    splash(0, ID2P(LANG_WAIT));\n",
    "&pl_cmds_start;\n\n#ifndef CODA_OS /* coda: resume quietly */\n"
    "    splash(0, ID2P(LANG_WAIT));\n#endif\n", "coda: resume quietly"))
changed.append(wrap("apps/playlist.c",
    "            splash_progress((total_read + count), control_file_size,\n"
    "                         \"%s (%s)\", str(LANG_WAIT), str(LANG_OFF_ABORT));\n",
    "#ifndef CODA_OS /* coda: resume without progress */\n"
    "            splash_progress((total_read + count), control_file_size,\n"
    "                         \"%s (%s)\", str(LANG_WAIT), str(LANG_OFF_ABORT));\n#endif\n",
    "coda: resume without progress"))

# --- playlist.c (strip): no skin progress counter to prime
changed.append(wrap("apps/playlist.c", "\n    wps_playlist_percent_prepare();\n",
    "\n#ifndef CODA_OS_STRIP /* coda: no skin tokens */\n    wps_playlist_percent_prepare();\n#endif\n",
    "coda: no skin tokens"))

# --- settings_list.c (strip): "start in screen" has no menu to open a browser from
changed.append(wrap("apps/settings_list.c", "                   , start_in_callback,\n",
    "                   , CODA_UI(start_in_callback), /* coda: no start browser */\n",
    "coda: no start browser"))
changed.append(wrap("apps/settings_list.c", "static void start_in_callback(int var)\n",
    "static void __attribute__((unused)) /* coda: may be unused */ start_in_callback(int var)\n",
    "coda: may be unused"))

# --- settings.c (strip): no voice prompts (without talk_init Rockbox behaves as with no
# voice file, which Coda OS ships without anyway; the speech codec drops out)
changed.append(wrap("apps/settings.c",
    "        CHART(\">talk_init\");\n        talk_init(); /* use voice of same language */\n"
    "        CHART(\"<talk_init\");\n",
    "#ifndef CODA_OS_STRIP /* coda: no voice */\n"
    "        CHART(\">talk_init\");\n        talk_init(); /* use voice of same language */\n"
    "        CHART(\"<talk_init\");\n#endif\n", "coda: no voice"))

# --- main.c (strip): no database, so no database state file to clear
changed.append(wrap("apps/main.c", "    if (rc < 0)\n        tagcache_remove_statefile();\n",
    "#ifndef CODA_OS_STRIP /* coda: no db state */\n"
    "    if (rc < 0)\n        tagcache_remove_statefile();\n#endif\n", "coda: no db state"))

# --- settings_list.c / settings.c: Coda draws the whole screen, so Rockbox's status bar
# is off by default under Coda OS, and the strip build keeps it off whatever config.cfg says
changed.append(wrap("apps/settings_list.c",
    "                  LANG_STATUS_BAR, STATUSBAR_TOP, \"statusbar\",\"off,top,bottom\",\n",
    "#ifdef CODA_OS /* coda: no status bar */\n"
    "                  LANG_STATUS_BAR, STATUSBAR_OFF, \"statusbar\",\"off,top,bottom\",\n#else\n"
    "                  LANG_STATUS_BAR, STATUSBAR_TOP, \"statusbar\",\"off,top,bottom\",\n#endif\n",
    "coda: no status bar"))
changed.append(wrap("apps/settings.c",
    "void settings_apply(bool read_disk)\n{\n    logf(\"%s\", __func__);\n    int rc;\n",
    "void settings_apply(bool read_disk)\n{\n    logf(\"%s\", __func__);\n    int rc;\n"
    "#ifdef CODA_OS_STRIP /* coda: status bar stays off */\n"
    "    global_settings.statusbar = STATUSBAR_OFF;\n#endif\n", "coda: status bar stays off"))

# --- usb_screen.c (strip): only Coda's USB picture (Rockbox's USB logo is never drawn)
changed.append(wrap("apps/gui/usb_screen.c",
    "    if (!coda_os_usb_draw())\n#endif\n    usb_screens_draw(usb_screen_vps_ar);\n",
    "    if (!coda_os_usb_draw())\n#endif\n#ifndef CODA_OS_STRIP /* coda: no usb logo */\n"
    "    usb_screens_draw(usb_screen_vps_ar);\n#else\n    ;\n#endif\n", "coda: no usb logo"))

# --- apps.make: build Coda into the firmware when configured with -DCODA_OS
changed.append(edit("apps/apps.make", "SRC += $(call preprocess, $(APPSDIR)/SOURCES)\n",
    "\n# Coda OS (offline-music-player): Coda as the root app, linked into the firmware\n"
    "ifneq (,$(findstring -DCODA_OS,$(EXTRA_DEFINES)))\n"
    "  include $(APPSDIR)/coda/coda_os.make\n"
    "endif\n"))

print("patched" if any(changed) else "already patched", SRC)
