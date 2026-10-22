# Nimbus on Linux from the source code.
#
#   make install                         for you only, no root: ~/.local (menu entry, `nimbus` command)
#   sudo make install PREFIX=/usr/local  for every user of the computer
#   make uninstall                       removes it again (same PREFIX); settings stay in ~/.config/Nimbus
#
# It needs Python 3.10+ with venv (Debian/Ubuntu: sudo apt install python3-venv) and the internet:
# Xray-core and sing-box come from their GitHub releases, PySide6 and httpx from PyPI. Everything the
# AppImage does works the same, TUN included. Updates: get the new source code and run make install.
#
# For development: make run (from this folder), make test, make appimage.

PREFIX  ?= $(HOME)/.local
DESTDIR ?=
PYTHON  ?= python3
VENV    := .venv
DEV_PY  := $(VENV)/bin/python

.PHONY: help install uninstall cores run test appimage clean

help:
	@sed -n '2,12p' Makefile | sed 's/^# \{0,1\}//'

cores:
	$(PYTHON) tools/fetch_cores.py linux --if-needed

install: cores
	$(PYTHON) tools/linux_install.py install --prefix "$(PREFIX)" --destdir "$(DESTDIR)"

uninstall:
	$(PYTHON) tools/linux_install.py uninstall --prefix "$(PREFIX)"

$(DEV_PY): requirements.txt
	$(PYTHON) -m venv $(VENV)
	$(DEV_PY) -m pip install --disable-pip-version-check --quiet -r requirements.txt
	@touch $(DEV_PY)

run: cores $(DEV_PY)
	$(DEV_PY) main.py

test: $(DEV_PY)
	QT_QPA_PLATFORM=offscreen $(DEV_PY) tests/test_core_logic.py

appimage: cores $(DEV_PY)
	$(DEV_PY) -m pip install --disable-pip-version-check --quiet pyinstaller
	$(DEV_PY) build_linux.py

clean:
	rm -rf $(VENV) build
