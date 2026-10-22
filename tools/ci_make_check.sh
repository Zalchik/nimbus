#!/bin/sh
# CI: what a user does with the source code, in a fresh home folder. make install, start Nimbus
# (it must show its window), install again over it (an update), make uninstall.
set -eu
HOME="$(mktemp -d)"
export HOME
unset XDG_CONFIG_HOME XDG_DATA_HOME
python3 --version

make install
test -x "$HOME/.local/bin/nimbus"
test -x "$HOME/.local/lib/nimbus/app/vendor/xray/sing-box"
test -s "$HOME/.local/share/icons/hicolor/256x256/apps/nimbus.png"
desktop-file-validate "$HOME/.local/share/applications/nimbus.desktop"
cat "$HOME/.local/share/applications/nimbus.desktop"

set +e
xvfb-run -a timeout 40 "$HOME/.local/bin/nimbus" > smoke.log 2>&1
code=$?
set -e
cat smoke.log
cat "$HOME/.config/Nimbus/logs/startup.log"
test "$code" -eq 124   # still running when timeout stopped it
grep -q "window shown" "$HOME/.config/Nimbus/logs/startup.log"

make install           # again: an update over the installed copy
make uninstall
test ! -e "$HOME/.local/bin/nimbus"
test ! -e "$HOME/.local/lib/nimbus"
test ! -e "$HOME/.local/share/applications/nimbus.desktop"
test -d "$HOME/.config/Nimbus/logs"   # settings and data stay
echo "make install / uninstall: OK"
