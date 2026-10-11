#             __________               __   ___.
#   Open      \______   \ ____   ____ |  | _\_ |__   _______  ___
#   Source     |       _//  _ \_/ ___\|  |/ /| __ \ /  _ \  \/  /
#   Jukebox    |    |   (  <_> )  \___|    < | \_\ (  <_> > <  <
#   Firmware   |____|_  /\____/ \___  >__|_ \|___  /\____/__/\_ \
#                     \/            \/     \/    \/            \/
#
# Coda -- the offline-music-player UI + autoplay brain as a full-screen plugin.
# Sources are synced in from the project repo by firmware/rockbox/sync_plugin.sh.

# In a Coda OS build (-DCODA_OS) Coda is linked into the firmware instead
# (firmware/rockbox/os/coda_os.make), so there is no plugin to build.
ifeq (,$(findstring -DCODA_OS,$(EXTRA_DEFINES)))

CODA_SRCDIR := $(APPSDIR)/plugins/coda
CODA_OBJDIR := $(BUILDDIR)/apps/plugins/coda

CODA_SRC := $(wildcard $(CODA_SRCDIR)/core/*.c) $(wildcard $(CODA_SRCDIR)/ui/*.c) \
            $(wildcard $(CODA_SRCDIR)/rb/*.c)
CODA_OBJ := $(call c2obj, $(CODA_SRC))

OTHER_SRC += $(CODA_SRC)
OTHER_INC += -I$(CODA_SRCDIR)/core
ROCKS += $(CODA_OBJDIR)/coda.rock

CODAFLAGS = $(filter-out -O%,$(PLUGINFLAGS)) -O2 -std=gnu11 \
            -I$(CODA_SRCDIR)/core -I$(TLSFLIB_DIR)/src \
            -include $(CODA_SRCDIR)/rb/rbcompat.h \
            -Wno-unused-parameter -Wno-sign-compare -Wno-unused-function -fstack-usage

$(CODA_OBJDIR)/coda.rock: $(CODA_OBJ) $(TLSFLIB)
	$(call PRINTS,LD $(@F))$(CC) $(PLUGINFLAGS) -o $(CODA_OBJDIR)/coda.elf \
		$(filter %.o, $^) \
		$(filter %.a, $+) \
		-lgcc $(filter-out -Wl%.map, $(PLUGINLDFLAGS)) -Wl,$(LDMAP_OPT),$(CODA_OBJDIR)/coda.map
	$(SILENT)$(call objcopy_plugin,$(CODA_OBJDIR)/coda.elf,$@)

$(CODA_OBJDIR)/%.o: $(CODA_SRCDIR)/%.c $(CODA_SRCDIR)/coda.make $(CODA_SRCDIR)/rb/rbcompat.h
	$(SILENT)mkdir -p $(dir $@)
	$(call PRINTS,CC $(subst $(ROOTDIR)/,,$<))$(CC) -I$(dir $<) $(CODAFLAGS) -c $< -o $@

# generated headers plugin.h pulls in must exist before any coda object compiles
$(CODA_SRCDIR)/rb/rbcompat.h: $(APPSDIR)/plugin.h $(BUILDDIR)/sysfont.h $(BUILDDIR)/lang_enum.h \
                              $(TLSFLIB_DIR)/src/tlsf.h

endif
