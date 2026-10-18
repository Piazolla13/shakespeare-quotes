# Shakespeare Daily Wallpaper

Sets a new Shakespeare quote as the wallpaper on every display once a day (04:00, and at login).
The macOS lock screen shows the main display's wallpaper, so the quote appears there too.

> [!WARNING]
> **This project is AI-generated code.** The code, tests, quote list and documentation were
> written by an AI assistant (Claude, via Claude Code) from a short plan by the repository owner,
> and tested on the owner's Mac. They have not been independently reviewed or audited.
> Read the code before running it — it installs background jobs (LaunchAgents) and changes your
> wallpaper — and use it at your own risk. Quote wording and attributions were also produced by
> the AI; check them against an edition of the plays if accuracy matters to you.

Requires macOS (tested on macOS 27 with the system Python 3.9) and uses only fonts that ship with macOS.

## Setup

The plists in `launchd/` contain absolute paths to `/Users/main/dev/shakespeare-quotes`.
If you cloned the repository somewhere else, replace that path in both files first.

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

## Development

```sh
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
```

The tests run against temporary copies of `quotes.json` and `state.json` and fake displays, so
they never change your wallpaper or your quote list. `tests/test_render.py` renders every quote in
`quotes.json` and checks that the text stays clear of the lock-screen clock and password field, so
run the tests after adding quotes.

## License

[MIT](LICENSE)
