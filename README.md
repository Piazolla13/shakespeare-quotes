# Shakespeare Daily Wallpaper

Sets a new Shakespeare quote as the wallpaper on every display once a day (04:00, and at login).
The macOS lock screen shows the main display's wallpaper, so the quote appears there too.

## Setup

```sh
/usr/bin/python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp launchd/com.shakespeare.wallpaper.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.shakespeare.wallpaper.plist
```

## Usage

```sh
.venv/bin/python shakespeare_wallpaper.py                           # new quote now
.venv/bin/python shakespeare_wallpaper.py --dry-run --output /tmp/x # render only
launchctl kickstart -k gui/$(id -u)/com.shakespeare.wallpaper       # trigger the agent
launchctl bootout gui/$(id -u)/com.shakespeare.wallpaper            # uninstall
```

- Quotes: `quotes.json` (`quote`, `play`, `character`). Recently shown quotes are tracked in
  `state.json` and skipped until every quote has been used.
- Images: `~/Pictures/ShakespeareDaily/` (a new filename each run, since macOS caches wallpapers by path).
- Logs: `logs/out.log`, `logs/err.log`.
- After editing the plist, copy it again and `bootout` + `bootstrap`.

## Menu bar app

`menubar.py` adds a ❦ icon to the menu bar: shows the current quote, **New Quote Now**,
**Add Quote…**, **Remove Current Quote…**, **Edit quotes.json…**, **Open Wallpaper Folder**.
It also redraws the wallpaper when a display is connected or removed. The daily change above
keeps working whether or not the app is running.

```sh
.venv/bin/python menubar.py                                       # try it from a terminal
cp launchd/com.shakespeare.menubar.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.shakespeare.menubar.plist
launchctl bootout gui/$(id -u)/com.shakespeare.menubar            # uninstall
```

The agent starts the app at login and restarts it after a crash; choosing **Quit** keeps it closed
until the next login. Logs: `logs/menubar.out.log`, `logs/menubar.err.log`.
