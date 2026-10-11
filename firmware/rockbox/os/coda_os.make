#             __________               __   ___.
#   Open      \______   \ ____   ____ |  | _\_ |__   _______  ___
#   Source     |       _//  _ \_/ ___\|  |/ /| __ \ /  _ \  \/  /
#   Jukebox    |    |   (  <_> )  \___|    < | \_\ (  <_> > <  <
#   Firmware   |____|_  /\____/ \___  >__|_ \|___  /\____/__/\_ \
#                     \/            \/     \/    \/            \/
#
# Coda OS: Coda compiled into the firmware as the root app (offline-music-player repo,
# firmware/rockbox/os/). The same sources as the coda.rock plugin, built with the same
# plugin flags (so every rb-> call works unchanged; rb points at the core's own API
# table), then linked into ONE object whose symbols are all made local except the two
# entry points -- nothing of Coda's can clash with a Rockbox name.

CODAOS_SRCDIR := $(APPSDIR)/plugins/coda
CODAOS_OBJDIR := $(BUILDDIR)/apps/coda_os
CODAOS_LIB    := $(BUILDDIR)/lib/libcoda.a

CODAOS_SRC := $(wildcard $(CODAOS_SRCDIR)/core/*.c) $(wildcard $(CODAOS_SRCDIR)/ui/*.c) \
              $(wildcard $(CODAOS_SRCDIR)/rb/*.c) \
              $(APPSDIR)/plugins/lib/stdio_compat.c $(ROOTDIR)/lib/tlsf/src/tlsf.c
CODAOS_OBJ := $(patsubst $(ROOTDIR)/%.c,$(CODAOS_OBJDIR)/%.o,$(CODAOS_SRC))

CODAOSFLAGS = -I$(APPSDIR)/plugins -I$(APPSDIR)/plugins/lib -DPLUGIN -DCODA_OS \
              $(filter-out -O%,$(CFLAGS)) -O2 -std=gnu11 -fno-builtin -ffreestanding \
              -I$(CODAOS_SRCDIR)/core -I$(ROOTDIR)/lib/tlsf/src \
              -Wno-unused-parameter -Wno-sign-compare -Wno-unused-function

CORE_LIBS += $(CODAOS_LIB)

$(CODAOS_OBJDIR)/%.o: $(ROOTDIR)/%.c $(CODAOS_SRCDIR)/coda.make $(CODAOS_SRCDIR)/rb/rbcompat.h \
                      $(BUILDDIR)/sysfont.h $(BUILDDIR)/lang_enum.h
	$(SILENT)mkdir -p $(dir $@)
	$(call PRINTS,CC coda_os/$(subst $(ROOTDIR)/,,$<))$(CC) -I$(dir $<) $(CODAOSFLAGS) \
		$(if $(findstring /plugins/coda/,$<),-include $(CODAOS_SRCDIR)/rb/rbcompat.h,) -c $< -o $@

$(CODAOS_LIB): $(CODAOS_OBJ)
	$(call PRINTS,LD coda_os.o)$(LD) -r -o $(CODAOS_OBJDIR)/coda_all.o $(CODAOS_OBJ)
	$(SILENT)$(OC) --keep-global-symbol=coda_os_run --keep-global-symbol=coda_os_logo \
		$(CODAOS_OBJDIR)/coda_all.o $(CODAOS_OBJDIR)/coda_os.o
	$(SILENT)rm -f $@
	$(call PRINTS,AR $(@F))$(AR) rcs $@ $(CODAOS_OBJDIR)/coda_os.o
