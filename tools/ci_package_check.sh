#!/bin/sh
# CI, as root: install the .deb / .rpm, start Nimbus as a normal user under a virtual display,
# reinstall the package while it runs (an upgrade), start it again, then remove the package
# while it runs. Each time the package must close Nimbus before changing its files.
#   sh tools/ci_package_check.sh deb|rpm <package file> <user>
set -eu
kind=$1
pkg=$(readlink -f "$2")
user=$3
uid=$(id -u "$user")
home=$(getent passwd "$user" | cut -d: -f6)
log="$home/.config/Nimbus/logs/startup.log"
rt=/run/user/$uid
[ -d "$rt" ] || rt=

pm() {   # the package manager: install <file> | reinstall <file> | remove
    case "$kind.$1" in
        deb.install) apt-get install -y "$pkg" ;;
        deb.reinstall) apt-get install -y --reinstall "$pkg" ;;
        deb.remove) apt-get remove -y nimbus-vpn ;;
        rpm.install) dnf install -y "$pkg" ;;
        rpm.reinstall) dnf reinstall -y "$pkg" ;;
        rpm.remove) dnf remove -y nimbus-vpn ;;
    esac
}

running() {
    for d in /proc/[0-9]*; do
        [ "$(cat "$d/comm" 2>/dev/null)" = Nimbus ] && return 0
    done
    return 1
}

start() {   # start Nimbus as the user and wait for its window
    rm -f "$log"
    runuser -u "$user" -- env HOME="$home" ${rt:+XDG_RUNTIME_DIR=$rt} \
        xvfb-run -a /usr/bin/nimbus > /tmp/nimbus.log 2>&1 &
    for _ in $(seq 60); do
        grep -qs "window shown" "$log" && break
        sleep 1
    done
    cat /tmp/nimbus.log
    cat "$log"
    grep -q "window shown" "$log"
    running
}

closed() {   # Nimbus must be gone right after the package manager is done
    sleep 1
    if running; then
        echo "Nimbus still runs after: $1"
        exit 1
    fi
}

pm install
test -x /usr/bin/nimbus
test "$(cat /opt/nimbus/package)" = "$kind"
desktop-file-validate /usr/share/applications/nimbus.desktop

start
pm reinstall
closed "an upgrade"
test -x /usr/bin/nimbus

start
pm remove
closed "the removal"
test ! -e /opt/nimbus
test ! -e /usr/bin/nimbus
test ! -e /usr/share/applications/nimbus.desktop
echo "$kind package: OK"
