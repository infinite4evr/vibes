# TG Drive 2.0

Every file in your Telegram (every channel, group, private chat, bot and Saved Messages) in one place that works like Google Drive: folders, search that understands what you mean, streaming, downloads and uploads. It signs in as your own account and runs on your computer. Nothing goes anywhere except Telegram.

## Install on Linux

**AppImage (recommended).** Download `TG_Drive-2.0.0-x86_64.AppImage`, then:

```bash
chmod +x TG_Drive-2.0.0-x86_64.AppImage
./TG_Drive-2.0.0-x86_64.AppImage
```

It runs on any 64-bit Linux from about 2019 onwards (glibc 2.28+: Ubuntu 20.04+, Debian 10+, Fedora 29+, Mint 20+, RHEL/Rocky/Alma 8+, openSUSE 15.1+, Arch, Manjaro, Pop!_OS …). The first start adds TG Drive to your applications menu. To remove that entry: `./TG_Drive-*.AppImage --uninstall-desktop-entry`.

If it doesn't start, install FUSE (`sudo apt install fuse3`, `sudo dnf install fuse3`, `sudo pacman -S fuse3`) or run it with `--appimage-extract-and-run`.

**From source** (ARM computers, older systems, or if you prefer): `packaging/install_from_source.sh` creates a private Python environment, installs the dependencies and adds TG Drive to the menu. `--no-gui` skips the desktop window and opens TG Drive in your browser instead.

**Upgrading from 0.1 / 1.x.** On first start TG Drive finds data from the old zip version (in `~/tgdrive/data`, `~/Downloads/tgdrive/data` and similar) and offers to import your signed-in accounts and index, so you don't have to sign in or re-index. Running from the old folder keeps using its `data/` folder directly.

## First start

1. TG Drive asks for a Telegram app key: sign in at [my.telegram.org/apps](https://my.telegram.org/apps), create an app (any name, platform Desktop) and paste the **api_id** and **api_hash**. They stay on this computer.
2. Sign in by scanning a QR code with Telegram on your phone (Settings → Devices → Link Desktop Device), or with your phone number and the code Telegram sends. Two-step passwords are supported.
3. Indexing starts. Big accounts take a while the first time (Telegram limits how fast history can be read); files appear chat by chat and new files arrive live after that. Indexing continues in the tray when you close the window.

## What it does

**Browse.** My Drive (your folders), All files, Starred, Recent, saved searches, your Telegram chat folders, tags, and every chat grouped by kind with file counts. Grid or list, three card sizes, compact mode, light/dark/system theme, date grouping, sort by best match, date, name, size, chat, type, duration or extension. Tabs with counts for photos, videos, documents, audio, voice, round videos and GIFs. Lists stay fast at hundreds of thousands of files (keyset paging, incremental loading, off-screen rendering skipped).

**Search that understands you.** Type naturally; results appear as you type, in tiers so the best matches come first:

| You type | Also finds |
| --- | --- |
| `test series` | TestSeries, testseries, test_series, Series-Test, "series of tests" |
| `pyq` | previous year questions, PYQs |
| `seires`, `polty` | series, polity (typo correction from your own file names) |
| `संविधान` / `samvidhan` | the same word in the other script |
| `ca`, `gs`, `ncert` | current affairs, general studies, NCERT (built-in study synonyms, and your own list) |
| `economy notes` | files about the same topic even without those words (an offline meaning model) |

Each result shows how it matched (exact, variant, similar, related). Filters by chip or operator:
`type:video` `ext:pdf,epub` `size>50mb` `dur>1h` `in:"Vision IAS"` `from:alice` `after:2024-01` `before:7d` `source:channel` `folder:"Tax"` `tag:exam` `topic:"Doubts"` `is:starred` `is:forwarded` `is:mine` `has:caption` `name:"exact words"` `caption:word` `"exact phrase"` `-excluded` `match:exact`. Search inside one chat, folder or Telegram folder; save searches; recent searches and suggestions (files, chats, folders, filters, did-you-mean) as you type.

**Organise.** Folders with colours and descriptions, nesting, drag and drop, move, copy to Drive, rename (single and bulk with patterns like `{n} - {name}`), stars, tags, notes, undo (Ctrl+Z). The folder tree lives in a private Telegram channel, so it syncs between computers and accounts, with automatic backups you can restore.

**Play and preview (streaming).** Videos, audio, voice notes, round videos, GIFs, photos, PDFs and text files open instantly without downloading first; seeking fetches just the part you jump to. Formats the app window can't decode (most Telegram videos: H.264/H.265 with AAC) play in TG Drive's own player with seeking, speed control and full screen. Background music player with a queue. Open any stream, or a whole folder as a playlist, in VLC or mpv. A disk cache (size in Settings) makes replays and seeking back instant.

**Transfers.** Parallel downloads and uploads with pause, resume (also after restarting), retry, cancel and speed/ETA; download whole folders or selections (keeping the folder structure, or as a zip); upload files and folders by drag and drop or the file picker; upload into any chat with a caption; files up to Telegram's limit (2 GB, 4 GB with Premium). Desktop notifications when they finish.

**Manage.** Storage view (by type, chat, kind of chat, year), duplicate finder (exact and similar), index manager (per-chat progress, pause, rescan, verify, exclude), activity log, several accounts, proxy (SOCKS5/4, HTTP, MTProto), app lock with a passcode and auto-lock, CSV export, database maintenance (optimise, vacuum, integrity check, rebuild search), logs.

**Keyboard.** `/` or `Ctrl K` search · arrows move · `Enter` open · `Space` quick look · `S` star · `T` tags · `M` move · `D` download · `F2` rename · `L` copy link · `Delete` · `Ctrl Z` undo · `V` grid/list · `G` then `D`/`A`/`S`/`R` to jump · `Ctrl ,` settings · `?` all shortcuts.

## Where things are

| | |
| --- | --- |
| Your data (accounts, index, cache, logs) | `~/.local/share/tgdrive` (change with `--data DIR` or `TGDRIVE_DATA`) |
| Downloads | `~/Downloads/TG Drive` (Settings → Downloads) |
| Logs | Settings → About & logs, or `~/.local/share/tgdrive/logs/tgdrive.log` |

Command line: `tgdrive --minimized` (start in the tray), `--browser` (use your web browser instead of the window), `--port N`, `--no-gpu` (graphics driver problems), `--data DIR`, `--version`.

## Privacy and security

- Your Telegram session files are readable only by your user (mode 600). TG Drive talks only to Telegram's servers.
- The local service listens on 127.0.0.1 only, checks the Host header (blocks DNS-rebinding), and in the desktop app every request needs a per-launch secret token. Links you copy for VLC/mpv carry a separate token that can only play media.
- Files from Telegram that could run scripts (HTML, SVG …) are sandboxed when opened. The window's renderer sandbox is on wherever the system allows it.
- Optional app lock (PBKDF2-hashed passcode) with auto-lock after inactivity.
- Serving to other devices on your network (`TGDRIVE_HOST=0.0.0.0 python run.py`) requires `TGDRIVE_PASSWORD`.

## Building the AppImage yourself

```bash
packaging/build_appimage.sh      # → dist/TG_Drive-<version>-x86_64.AppImage
```

Needs `uv` (or `PYTHON_DIST` pointing at a python-build-standalone build), `curl`, `dpkg-deb` or `ar`+`tar`, `objdump`, and internet access. It bundles a portable Python 3.12, Qt 6.9 and the search model, checks that nothing needs a glibc newer than 2.28, runs a smoke test and packs the image.

## Development

```bash
python -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt pytest httpx
python -m pytest tests          # 18 tests, including a 60,000-file scale test
python -m desktop               # the desktop app from source
python run.py                   # server only; open http://127.0.0.1:8765
python -m tests.demo_server     # the UI on a fake account (http://127.0.0.1:8766)
python -m tests.bigdb out.db    # a 437,688-file synthetic index for benchmarks
```

Layout: `tgdrive/` (server: Telegram, index, search, streaming, transfers, folders), `web/` (the interface, plain ES modules, no build step), `desktop/` (Qt window, tray, native player), `packaging/` (AppImage build, source installer, icons), `tests/`, `docs/AUDIT.md` (feature audit and roadmap).
