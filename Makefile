# bluplay - simple terminal music player for BluOS streamers
#
#   make              build ./bluplay
#   make san          build ./bluplay-san with AddressSanitizer + UBSan (for testing)
#   make test         run the smoke test against the bundled fake player (needs python3; pyte for UI tests)
#   make install      install to $(DESTDIR)$(PREFIX)/bin (PREFIX defaults to /usr/local)
#   make uninstall / make clean

CC      ?= cc
PREFIX  ?= /usr/local
BINDIR  ?= $(PREFIX)/bin
CFLAGS  ?= -O2
CFLAGS  += -std=gnu11 -Wall -Wextra
LDLIBS  += -lm
SANFLAGS = -std=gnu11 -O1 -g -fsanitize=address,undefined -fno-omit-frame-pointer -Wall -Wextra -Wshadow
PYTHON  ?= python3

all: bluplay

bluplay: bluplay.c
	$(CC) $(CPPFLAGS) $(CFLAGS) $(LDFLAGS) -o $@ bluplay.c $(LDLIBS)

san: bluplay-san
bluplay-san: bluplay.c
	$(CC) $(CPPFLAGS) $(SANFLAGS) $(LDFLAGS) -o $@ bluplay.c $(LDLIBS)

test: bluplay
	$(PYTHON) tests/smoke.py ./bluplay

test-san: bluplay-san
	$(PYTHON) tests/smoke.py ./bluplay-san

install: bluplay
	install -d $(DESTDIR)$(BINDIR)
	install -m 755 bluplay $(DESTDIR)$(BINDIR)/bluplay

uninstall:
	rm -f $(DESTDIR)$(BINDIR)/bluplay

clean:
	rm -f bluplay bluplay-san
	rm -rf bluplay.dSYM bluplay-san.dSYM tests/__pycache__

.PHONY: all san test test-san install uninstall clean
