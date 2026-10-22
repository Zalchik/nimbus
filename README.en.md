# Nimbus

**English** · [Русский](README.md)

A VPN client for Windows and Linux built on [Xray-core](https://github.com/XTLS/Xray-core) and [sing-box](https://github.com/SagerNet/sing-box).
Add a subscription link, pick a server and connect. Nimbus takes care of the rest.

**[Download the latest version →](https://github.com/Zalchik/nimbus/releases/latest)**

## Quick start

1. Download Nimbus from the [releases page](https://github.com/Zalchik/nimbus/releases/latest).
2. Copy your subscription link and press `Ctrl+V` in Nimbus, or click «＋ Add».
3. Double-click a server to connect.
4. Need the VPN for games or programs that ignore the system proxy? Turn on **TUN** mode.

## Installing and updating

Nimbus checks for new versions at launch and every 6 hours. When one is out, it shows what's new, and the «Download» button updates it by itself: it downloads the file (through the VPN if it's on), checks its size and SHA-256, disconnects, replaces the files and starts again. Subscriptions and settings are kept. The check can be turned off in «Settings → App», where the «Check for updates» button also is.

**Installer `Nimbus-<version>-setup.exe`**

- Installs into `%LOCALAPPDATA%\Programs\Nimbus` without administrator rights. Data lives in `%APPDATA%\Nimbus`.
- Updating by hand: run the new version's installer. It closes Nimbus, restores the proxy settings and replaces the files. Subscriptions and settings are kept.
- Uninstalling: «Settings → Apps → Nimbus» in Windows, or the button in Nimbus settings. The uninstaller asks whether to delete the data.

**Portable `Nimbus-<version>-portable.zip`**

- Unpack it anywhere except `Program Files`. Data is kept in the `data` folder next to `Nimbus.exe`, so the folder can be moved or carried on a USB stick.
- Updating by hand: unpack the new version over the old one. The `data` folder stays.

**Linux (beta): `Nimbus-<version>-x86_64.AppImage`**

- Make the file executable (`chmod +x Nimbus-*.AppImage`) and run it. FUSE 2 is needed (the `libfuse2` package). Data lives in `~/.config/Nimbus`.
- TUN mode asks for the administrator password once, the first time: only the sing-box core gets network rights, Nimbus itself runs as a normal user.
- The system proxy is set in GNOME and KDE; elsewhere the `HTTP_PROXY` / `HTTPS_PROXY` variables work. The tray icon in GNOME needs the AppIndicator extension.
- It updates itself like the Windows version: the new AppImage replaces the old one.

**Linux: `Nimbus-<version>-amd64.deb` and `Nimbus-<version>-x86_64.rpm` packages**

The same program as the AppImage, installed like any other: in the applications menu, the `nimbus` command, no FUSE.

- Debian, Ubuntu, Mint: `sudo apt install ./Nimbus-*-amd64.deb`. Fedora: `sudo dnf install ./Nimbus-*-x86_64.rpm`. openSUSE: `sudo zypper install --allow-unsigned-rpm ./Nimbus-*-x86_64.rpm`. Or double-click the file.
- It updates itself: Nimbus downloads the new package, checks it and installs it through the package manager; the system asks for the password once.
- Removing: `sudo apt remove nimbus-vpn` or `sudo dnf remove nimbus-vpn`. A running Nimbus disconnects and puts the proxy settings back first. Settings and subscriptions stay in `~/.config/Nimbus`.

**Linux from source: `make install`**

No AppImage and no FUSE: Nimbus is installed for your user in `~/.local`, without root. You get an applications menu entry, the `nimbus` command and the `nimbus://` link handler. Everything else works as in the AppImage, TUN included.

```bash
git clone https://github.com/Zalchik/nimbus.git && cd nimbus && make install
```

- It needs Python 3.10+, `make` and the internet: the Xray and sing-box cores come from their GitHub releases, PySide6 and httpx from PyPI (about 250 MB, into a separate environment; the system Python isn't touched). Debian/Ubuntu/Mint also need the `python3-venv` package. Works on x86-64 and ARM64.
- For every user of the computer: `sudo make install PREFIX=/usr/local`.
- Updating: get the new source code (`git pull`) and run `make install` again. A running Nimbus is closed; settings stay. After a system upgrade to a new Python version, run `make install` too.
- Removing: `make uninstall` (with the same `PREFIX`). Settings and subscriptions stay in `~/.config/Nimbus`.
- For development: `make run` (runs from the source folder), `make test`, `make appimage`.

The data folder holds `settings.json` (settings), `profiles.json` (subscriptions, groups, balancers) and `logs`. Open it from «Settings → App».

## Features

- **Your own balancers** from servers of any subscriptions: traffic goes through the fastest server by itself.
- **Sharing configs:** as a link, a QR code, Xray JSON or a whole subscription.
- **Subscriptions** with traffic, expiry, provider announcements and HWID. Full Xray JSON configs run as they are.
- **Protocols:** VLESS (Reality, Vision, XHTTP), VMess, Trojan, Shadowsocks, Hysteria2, SOCKS5, WireGuard.
- **System proxy or TUN** for all traffic, games included.
- **Routing:** provider rules, «Russian sites direct», your own presets by program and site.
- **Kill switch** and DNS and IPv6 leak protection.
- **Real latency** of servers and your IP with its country.
- Tray, start with Windows, auto-connect, auto-update, dark and light themes, English and Russian.

## Balancers

- Build your own balancer from servers of **any** subscriptions and groups. Nimbus checks them and sends traffic through the fastest; if a server stops responding, it moves to the next one without reconnecting.
- **«Stable» mode:** the server changes only if the new one is at least 50 ms and 30% faster. The IP rarely changes and sites don't log you out.
- **«Fastest» mode:** always the best server.
- Check interval from 10 seconds to 10 minutes. Tick a whole subscription and its future servers join the balancer too.
- A notification when a balancer switches servers. The window shows which server the traffic goes through right now.
- A balancer works like any server: with TUN, presets and latency checks.

## Sharing configs

- A server as a link (`vless://`, `hy2://` and so on) or a QR code. The QR code can be saved as PNG.
- The full config as Xray JSON: to the clipboard or a file. This keeps everything a link can't hold, such as a balancer.
- Several servers at once, or a whole subscription as a list of links.
- The subscription URL as a link or a QR code, to open it on a phone.

## Subscriptions and configs

- **«Add to app» links.** A `nimbus://import/<subscription URL>` link opens Nimbus and offers to add the subscription. Nimbus also understands the same kind of links in other formats (`…://add/…`, `…://install-sub?url=…`, `…://install-config?url=…`, `…://import-remote-profile?url=…`), both at launch and when pasted with `Ctrl+V` or «Add».
- **Encrypted Happ links** (`happ://crypt…/…`, and the `crypt://crypt4/…` form): Nimbus decrypts them itself and adds what they hold — a subscription when the link carries its address, configs when it carries the server links. Decryption happens on your computer; the link is never sent anywhere. If this version has no key for the link, Nimbus says so and asks you to get the plain `https://…` link from your provider.
- **Subscriptions from your VPN provider** by an `https://…` link. Servers are loaded and kept up to date by themselves: at launch and on a timer (every 2 hours by default, or as the provider says).
- **Full Xray JSON configs** run as they are, with everything the provider set: a balancer, server checks and routing rules.
- **Links and base64.** Subscriptions of plain links, one per line, are accepted, base64 included.
- **Subscription card:** the name, traffic used and the limit, days left, the provider's announcement, support and website links.
- **User-Agent** for all subscriptions or for each one. It decides the format a panel sends the subscription in.
- **HWID** for panels that limit devices. Modes: «automatically» (only if the subscription doesn't load without it), «always», «never». You can enter your own HWID or generate one to move a device.
- **Your own groups.** Folders for individual configs. Add them as text, as `.json`, `.txt` and `.conf` files, or by dropping files onto the window. Servers move between groups.
- Subscriptions update through the VPN that is already on, if the provider can't be reached directly.

## Protocols

VLESS (Reality, XTLS Vision, XHTTP, gRPC, WebSocket, HTTPUpgrade), VMess, Trojan, Shadowsocks (2022 included), Hysteria2 (salamander, port hopping), SOCKS5, WireGuard.

## Connection modes

- **System proxy.** Browsers and programs that use the Windows proxy go through the VPN. You can also set `HTTP_PROXY` / `HTTPS_PROXY` for console programs: git, curl, npm, pip and others.
- **TUN.** All of the computer's traffic, including games and programs without proxy support. It runs through a sing-box virtual adapter (auto route, DNS hijacking, sniffing), while Xray still runs the configs. Needs administrator rights; Nimbus offers to restart itself.
- SOCKS and HTTP ports, MTU and connections from the local network are configurable.

## Routing

- **«Smart»:** the rules from the provider's subscription, for example Russian sites direct.
- **«All traffic»:** everything through the VPN, or your own «Russian sites direct» mode.
- **Presets.** Your own rules by program and site:
  - «Bypass VPN»: the ticked ones go direct, the rest through the VPN.
  - «Only through VPN»: only the ticked ones go through the VPN.
  - Programs are picked from the installed ones (Start menu, registry, Steam, Epic Games) and the running ones. You can add an `.exe` or a whole game folder.
  - Sites: domains with all their subdomains, `*.example.com` masks, IPs and subnets, the ready `geosite:…` and `geoip:…` lists.
  - A preset can work together with the provider's rules.
- Ad blocking, local networks direct, domain strategy.
- geoip/geosite databases updated with one button.

The routing mode and preset switch right on the main screen and from the tray.

## Leak protection

- **Kill switch in TUN:** strict route. Windows Filtering Platform blocks DNS queries outside the tunnel, and IPv6 if the tunnel doesn't carry it.
- **Kill switch in proxy mode:** if the core crashes, the proxy stays on and traffic doesn't go direct.
- Xray's own connections are bound to the physical adapter and don't loop back into the tunnel.
- If the core stops, Nimbus reconnects by itself, up to 3 times in a row.
- When the network changes (another Wi-Fi, a cable), Nimbus reconnects by itself.
- If Windows or Nimbus crashed while connected, the previous proxy settings come back at the next launch.

## DNS

- Remote DNS through the tunnel: plain, DoH (`https://…`), TCP, QUIC.
- Direct DNS for sites that bypass the VPN.
- FakeDNS in TUN mode: sites open faster, without an extra DNS round trip through the tunnel.

## Getting past blocks

- TLS ClientHello fragmentation: packets, length and interval are configurable.
- Mux with a choice of the number of streams.
- Sniffing: the domain is taken from the traffic.

These settings apply to servers from links. Provider configs aren't changed.

## Checking servers

- **Real latency**, through the server itself rather than an ICMP ping. All servers are checked in parallel.
- Check all servers, one subscription, a group or the selected ones.
- Sort by the provider's order, by latency or alphabetically, separately for each subscription.
- **Your IP through the VPN** and its country, as sites see them. A click copies the IP.

## The app

- Dark and light themes, country flags next to servers, server search, a list of recent ones.
- Live download and upload speed, session traffic, connection time.
- Interface in English and Russian: the system's language, or the choice in «Settings → App».
- Tray: connect and disconnect, choose a server, recent servers and balancers, routing mode and preset.
- Start with Windows, start minimized to the tray, auto-connect.
- Core logs right in the app.
- A single copy of the app: launching it again opens the window that is already running.

## Privacy

Nimbus collects no statistics and sends no telemetry. Besides your VPN provider, it only talks to these addresses:

- **IP and country:** the project's own server, and if it doesn't answer, Cloudflare or ipwho.is. The request goes through the VPN like any site.
- **Latency checks:** `https://www.gstatic.com/generate_204`. The address can be changed in settings.
- **Update checks:** `api.github.com` and downloads from GitHub. Can be turned off in settings.
- **geoip/geosite updates** (only on the button): [Loyalsoldier/v2ray-rules-dat](https://github.com/Loyalsoldier/v2ray-rules-dat) releases on GitHub.

## Building from source

Requires Python 3.13.

```bash
pip install PySide6 httpx pyinstaller Pillow
python tests/test_core_logic.py
python build.py
```

The result appears in `dist/<version>/`: the `Nimbus` folder, `Nimbus-<version>-portable.zip`, `Nimbus-<version>-setup.exe` and `SHA256SUMS.txt`. Upload these files (and the Linux AppImage) to the GitHub release with one shared `SHA256SUMS.txt`: the built-in updater checks downloads against `SHA256SUMS.txt`. The release tag is `v<version>`, as in `nimbus/paths.py`.

- Before building, put `xray.exe`, `geoip.dat` and `geosite.dat` from the [Xray-core release](https://github.com/XTLS/Xray-core/releases) into `vendor/xray/`, plus `sing-box.exe` (windows-amd64, version 1.15 or newer) from the [sing-box release](https://github.com/SagerNet/sing-box/releases). Wintun is built into sing-box.
- The installer needs [Inno Setup 6](https://jrsoftware.org/isinfo.php) (`winget install JRSoftware.InnoSetup`). The script is `installer/nimbus.iss`. Don't change its `AppId`: that's how the installer finds an installed Nimbus.
- The version is set in `nimbus/paths.py` (`VERSION`).
- Linux: `python tools/fetch_cores.py linux` and `python build_linux.py` on Linux x86_64 build `Nimbus-<version>-x86_64.AppImage`, plus the `.deb` and `.rpm` when `dpkg-deb` and `rpmbuild` are there (or `make appimage`). GitHub Actions (`.github/workflows/build.yml`) builds both versions on a `v*` tag and keeps them as build artifacts only; it doesn't publish a release.

## Licenses

- Xray-core: MPL-2.0.
- sing-box: GPL-3.0 (source: https://github.com/SagerNet/sing-box). Runs as a separate process.
- Montserrat and IBM Plex Mono fonts: SIL Open Font License.
- Country by IP: [IP Geolocation by DB-IP](https://db-ip.com) (CC BY 4.0).

The license texts are in the `core` folder next to the app.
