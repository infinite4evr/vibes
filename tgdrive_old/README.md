# TG Drive 2.1

Every file in your Telegram (every channel, group, private chat, bot and Saved Messages) in one place that works like Google Drive: folders, search that understands what you mean, streaming, downloads and uploads. It signs in as your own account and runs on your computer. Nothing goes anywhere except Telegram.

## Install on Linux

**AppImage (recommended).** Download `TG_Drive-2.2.0-x86_64.AppImage`, then:

```bash
chmod +x TG_Drive-2.2.0-x86_64.AppImage
./TG_Drive-2.2.0-x86_64.AppImage
```

It runs on any 64-bit Linux from about 2019 onwards (glibc 2.28+: Ubuntu 20.04+, Debian 10+, Fedora 29+, Mint 20+, RHEL/Rocky/Alma 8+, openSUSE 15.1+, Arch, Manjaro, Pop!_OS …). The first start adds TG Drive to your applications menu. To remove that entry: `./TG_Drive-*.AppImage --uninstall-desktop-entry`.

If it doesn't start, install FUSE (`sudo apt install fuse3`, `sudo dnf install fuse3`, `sudo pacman -S fuse3`) or run it with `--appimage-extract-and-run`.

**Straight from this folder.** `bash start.sh` sets everything up on first run and opens TG Drive. `bash start.sh --install` adds it to your applications menu with its icon, creates a `tgdrive` command and adds **Send to TG Drive** to the right-click menu of Nautilus/Files, Nemo, Caja, Dolphin and Thunar; `bash start.sh --uninstall` removes all of that. `--browser` opens it in your web browser, `--demo` tries it on made-up data.

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

**New in 2.2.**

- *Preview on click.* Clicking a file opens its details with a live preview straight away: the full picture, a playable video or song, the first page of a PDF (with its page count), the start of a text file. Arrowing through files only starts streams for the one you stop on.
- *Inter.* The interface uses Inter, the typeface most modern apps use, bundled so it looks the same everywhere.
- *Always shows it's working.* A progress bar along the top of the window for anything you started that takes a moment, a spinner on the button you pressed, skeletons while details and pages load, shimmer on pictures still on their way.
- *Motion.* Panels slide, menus and dialogs pop, lists fade in row by row, toasts rise and fall, cards lift on hover. Turned off with the system's "reduce motion" setting.
- *Better meaning-based search.* Word weights learned from your own library (so "pdf", "notes" or a channel's "join @…" line stop counting), file names weigh more than captions, the vectors are centred, and synonyms and spelling fixes are handed to the model too. On a test set of 30 queries: right answer ranked first far more often (MRR 0.62 → 0.77), 40% more of the right files in the top 10 and about 40% fewer unrelated ones. Subjects found by meaning are much more accurate too. The meaning index rebuilds itself once after updating (seconds to a minute).
- *Calmer screens.* Camera and Telegram file names (`photo_2026-05-07_01-50-00.jpg`) show as "Photo · 7 May, 1:50 AM"; one info line per card; star and download on hover; voice notes as waveforms. Filters sit behind one button (F) and the header shrinks as you scroll; the selection bar floats at the bottom; date headers stay pinned while you scroll. The details panel has the name as a title (click or F2 to rename) and one row of icons for the rarer actions. Collapsible sidebar sections, short counts (49.7k), a compact index status, a transfers button with a progress ring, a tuned dark theme and a consistent type scale.
- *One title bar.* The desktop window draws its own title bar: drag the top bar to move it, double-click to maximize, window buttons at the right (Settings → Desktop to switch back to the system's).
- *Detailed debug logging* (Settings → About & diagnostics, or the account menu). Records every request with its timing, what the window did (navigation, clicks, shortcuts, errors with stack traces, failed media, slow frames), transfers, streaming, indexing, search plans and crashes with full tracebacks to `logs/tgdrive-debug.log`. Takes effect at once; a large striped banner stays at the top while it's on. View, download or clear all logs from the banner or Settings.

**New in 2.1.**

- *Looks.* Redesigned folders (tiles, cards with cover pictures, or a list; emoji icons and colours), custom accent colour, high-contrast theme and text size (Settings → Appearance).
- *Smart folders and subjects.* A smart folder shows everything that matches a rule; an auto-filing folder moves matching unfiled files into itself as they arrive. Files are tagged by subject automatically (Polity, Economy, History… plus your own subjects) and `subject:polity` works in search.
- *Big lists.* Grid and list are virtualised, so scrolling stays smooth at 100k+ results. Choose, reorder and resize list columns. Albums show as stacks.
- *Photos.* A timeline with a date scrubber, a map of geotagged photos (Places), and a slideshow.
- *PDFs.* A reader with highlights, bookmarks and notes that sync between computers, and it remembers where you stopped.
- *Context.* "Show in chat" opens the messages around a file: who sent it, what was said, replies.
- *Two panes.* Split view (drag between panes) or open another window.
- *Paste to upload.* Ctrl V with files or a screenshot on the clipboard uploads them to the folder you're in.
- *Folder sync.* Keep a folder on this computer and a TG Drive folder the same, both ways. Shows what the first sync will do and waits for your OK; stops and asks if a run would remove many files; nothing is ever deleted outright (removed files go to `.tgdrive-trash`, conflicts keep both copies).
- *Use from any app.* Settings → Drive on this computer mounts TG Drive in your file manager (WebDAV on 127.0.0.1 only, with a secret address), so any app can open its files.
- *Bug reports.* Crashes are recorded on this computer; Settings → About can make a diagnostics zip with names, numbers, keys and addresses removed. Nothing is sent anywhere.
- *Settings export and import* (Settings → About), without passwords or keys unless you ask.

**Keyboard.** `/` or `Ctrl K` search · arrows move · `Enter` open · `Space` quick look · `S` star · `T` tags · `M` move · `D` download · `F2` rename · `L` copy link · `Delete` · `Ctrl Z` undo · `V` grid/list · `G` then `D`/`A`/`S`/`R` to jump · `Ctrl ,` settings · `?` all shortcuts.

## Where things are

| | |
| --- | --- |
| Your data (accounts, index, cache, logs) | `~/.local/share/tgdrive` (change with `--data DIR` or `TGDRIVE_DATA`) |
| Downloads | `~/Downloads/TG Drive` (Settings → Downloads) |
| Logs | Settings → About & diagnostics, or `~/.local/share/tgdrive/logs/tgdrive.log` (and `tgdrive-debug.log` while debug logging is on) |

Command line: `tgdrive --send FILE…` (upload files or folders; what the right-click menu uses), `--open search|upload|new-window`, `tgdrive --minimized` (start in the tray), `--browser` (use your web browser instead of the window), `--port N`, `--no-gpu` (graphics driver problems), `--data DIR`, `--version`.

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
