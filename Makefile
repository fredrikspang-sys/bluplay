# bluplay - simple terminal music player for BluOS streamers
#
#   make              build ./bluplay
#   make san          build ./bluplay-san with AddressSanitizer + UBSan (for testing)
#   make test         run the smoke test against the bundled fake player (needs python3; pyte for UI tests)
#   make install      install bin + docs under $(DESTDIR)$(PREFIX) (PREFIX defaults to /usr/local)
#   make dist         source tarball bluplay-VERSION.tar.gz (git archive of HEAD)
#   make release      all release packages into dist/ (scripts/release.sh)
#   make uninstall / make clean

CC      ?= cc
PREFIX  ?= /usr/local
BINDIR  ?= $(PREFIX)/bin
DOCDIR  ?= $(PREFIX)/share/doc/bluplay
VERSION := $(shell sed -n "s/^\#define BLUPLAY_VERSION \"\(.*\)\"/\1/p" bluplay.c)
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
	install -d $(DESTDIR)$(DOCDIR)
	install -m 644 README.md LICENSE $(DESTDIR)$(DOCDIR)/

uninstall:
	rm -f $(DESTDIR)$(BINDIR)/bluplay
	rm -rf $(DESTDIR)$(DOCDIR)

dist:
	git archive --format=tar --prefix=bluplay-$(VERSION)/ HEAD | gzip -9n > bluplay-$(VERSION).tar.gz
	@echo bluplay-$(VERSION).tar.gz

release:
	sh scripts/release.sh $(VERSION)

clean:
	rm -f bluplay bluplay-san
	rm -rf dist bluplay-*.tar.gz bluplay.dSYM bluplay-san.dSYM tests/__pycache__

.PHONY: all san test test-san install uninstall clean dist release
