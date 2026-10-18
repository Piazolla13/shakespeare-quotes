# Shakespeare Daily Wallpaper

[![tests](https://github.com/Piazolla13/shakespeare-quotes/actions/workflows/tests.yml/badge.svg)](https://github.com/Piazolla13/shakespeare-quotes/actions/workflows/tests.yml)

Sets a new Shakespeare quote as the wallpaper on every display once a day (04:00, and at login).
The macOS lock screen shows the main display's wallpaper, so the quote appears there too.

> [!WARNING]
> **This project is AI-generated code.** The code, tests, quote list and documentation were
> written by an AI assistant (Claude, via Claude Code) from a short plan by the repository owner,
> and tested on the owner's Mac. They have not been independently reviewed or audited.
> Read the code before running it — it installs background jobs (LaunchAgents) and changes your
> wallpaper — and use it at your own risk. Quote wording and attributions were also produced by
> the AI. They are checked automatically against one public-domain edition (see
> [Checking quotes](#checking-quotes)), not by a Shakespeare scholar.

Requires macOS (tested on macOS 27 with the system Python 3.9) and uses only fonts that ship with macOS.

## Install

```sh
git clone https://github.com/Piazolla13/shakespeare-quotes.git
cd shakespeare-quotes
./install.sh
```

`install.sh` creates `.venv` with the system Python (if `/usr/bin/python3` is missing, macOS offers
to install the Command Line Tools: `xcode-select --install`), installs the dependencies, and loads
two LaunchAgents generated for wherever you cloned the repository. The wallpaper changes right away.

| Option | |
|---|---|
| `--hour 7` | change the quote at 07:00 instead of 04:00 |
| `--no-menubar` | install the daily wallpaper only |
| `--dry-run DIR` | write the generated plists to `DIR` to inspect them; installs nothing |
| `--uninstall` | unload and remove both agents (keeps `.venv` and the images) |

Run `./install.sh` again after moving the folder or changing the templates in `launchd/`.
If the Mac is asleep at the scheduled hour, the quote changes when it wakes.

## Usage

```sh
.venv/bin/python shakespeare_wallpaper.py                           # new quote now
.venv/bin/python shakespeare_wallpaper.py --dry-run --output /tmp/x # render only
launchctl kickstart -k gui/$(id -u)/com.shakespeare.wallpaper       # trigger the daily agent
```

- Quotes: `quotes.json` (`quote`, `play`, `character`, and optionally `act` and `scene`, shown in the
  attribution). Recently shown quotes are tracked in
  `state.json` and skipped until every quote has been used.
- Images: `~/Pictures/ShakespeareDaily/` (a new filename each run, since macOS caches wallpapers by path).
- Logs: `logs/out.log`, `logs/err.log`.

## Themes

| Theme | |
|---|---|
| `ink` (default) | charcoal to black, cream text, gold accent |
| `parchment` | warm cream, dark-brown text, oxblood accent |
| `midnight` | deep navy, silver text |
| `auto` | `ink` in dark mode, `parchment` in light mode |

Pick one in the menu bar app (**Theme** submenu) or with
`.venv/bin/python shakespeare_wallpaper.py --theme parchment` (saved for future runs; add
`--dry-run --output /tmp/x` to preview without saving). With `auto`, the menu bar app redraws
the wallpaper when macOS switches between light and dark. The lock-screen clock is white, so it
stands out less on `parchment`.

## Menu bar app

`menubar.py` adds a ❦ icon to the menu bar: shows the current quote, **New Quote Now**,
**Add Quote…**, **Remove Current Quote…**, **Theme**, **Edit quotes.json…**, **Open Wallpaper Folder**.
It also redraws the wallpaper when a display is connected or removed. The daily change above
keeps working whether or not the app is running.

The agent starts the app at login and restarts it after a crash; choosing **Quit** keeps it closed
until the next login. Logs: `logs/menubar.out.log`, `logs/menubar.err.log`.

## Checking quotes

```sh
.venv/bin/python tools/check_quotes.py
```

Compares every entry in `quotes.json` with the
[Project Gutenberg Complete Works](https://www.gutenberg.org/ebooks/100) (downloaded once, cached in
`~/Library/Caches/shakespeare-quotes/`) and prints where each quote is found (play, act, scene,
speaker), flagging wording that isn't found, the wrong play or a different speaker. Exits with
status 1 if anything needs review. Punctuation, line breaks and spellings like *strain’d* are
ignored; play names must match the list in `tools/check_quotes.py`.

After adding quotes, `tools/check_quotes.py --write-refs` fills in `act` and `scene` for every
quote that passes, and later runs report a reference that doesn't match the text.

All 50 included quotes pass. Three are marked `CLOSE` because they use the wording common in
quotation and in some other editions rather than Gutenberg's text: *What a piece of work is
**a** man* (Gutenberg: "is man"), *by any other **word*** ("name") and *this **sun** of York*
("son", the line puns on both).

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
