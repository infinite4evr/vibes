# TG Drive 2.3.1

Every file in your Telegram (every channel, group, private chat, bot and Saved Messages) in one place that works like Google Drive: folders, search that understands what you mean, streaming, downloads and uploads. It signs in as your own account and runs on your computer. Nothing goes anywhere except Telegram.

## Install on Linux

**AppImage (recommended).** Download `TG_Drive-2.3.1-x86_64.AppImage`, then:

```bash
chmod +x TG_Drive-2.3.1-x86_64.AppImage
./TG_Drive-2.3.1-x86_64.AppImage
```

It runs on any 64-bit Linux from about 2019 onwards (glibc 2.28+: Ubuntu 20.04+, Debian 10+, Fedora 29+, Mint 20+, RHEL/Rocky/Alma 8+, openSUSE 15.1+, Arch, Manjaro, Pop!_OS …). The first start adds TG Drive to your applications menu. To remove that entry: `./TG_Drive-*.AppImage --uninstall-desktop-entry`.

If it doesn't start, install FUSE (`sudo apt install fuse3`, `sudo dnf install fuse3`, `sudo pacman -S fuse3`) or run it with `--appimage-extract-and-run`.

**Straight from this folder.** `bash start.sh` sets everything up on first run and opens TG Drive. `bash start.sh --install` adds it to your applications menu with its icon, creates a `tgdrive` command and adds **Send to TG Drive** to the right-click menu of Nautilus/Files, Nemo, Caja, Dolphin and Thunar; `bash start.sh --uninstall` removes all of that. `--browser` opens it in your web browser, `--demo` tries it on made-up data.

**From source** (ARM computers, older systems, or if you prefer): `packaging/install_from_source.sh` creates a private Python environment, installs the dependencies and adds TG Drive to the menu. `--no-gui` skips the desktop window and opens TG Drive in your browser instead.

**Upgrading from 0.1 / 1.x.** On first start TG Drive finds data from the old zip version (in `~/tgdrive/data`, `~/Downloads/tgdrive/data` and similar) and offers to import your signed-in accounts and index, so you don't have to sign in or re-index. Running from the old folder keeps using its `data/` folder directly.

## First start

1. TG Drive asks for a Telegram app key: sign in at [my.telegram.org/apps](https://my.telegram.org/apps), create an app (any name, platform Desktop) and paste the **api_id** and **api_hash**. They stay on this computer.
2. Sign in by scanning a QR code with Telegram on your phone (Settings → Devices → Link Desktop Device), or with your phone number and the code Telegram sends. Two-step passwords are supported.
3. Indexing starts. Big accounts take a while the first time (Telegram limits how fast history can be read); files appear chat by chat and new files arrive live after that. TG Drive runs only while its window is open: closing the window quits it, and indexing picks up where it left off next time (Settings → Desktop can keep it running in the tray instead).

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

**New in 2.3.2: quits fast, and nothing stays behind.**

- *Closing the window quits TG Drive*, and every part of it stops: the service, background indexing, the Telegram connection, and the drive mounted in your file manager. It no longer starts at login or hides in the tray unless you switch that on in Settings → Desktop (older settings were reset to this once).
- *Quitting takes about a second* instead of 10–45 seconds. Everything is told to stop at once and stops together; the window disappears immediately while the last saving finishes; a long background job is interrupted instead of waited for. However stuck anything is, the service ends itself within 25 seconds, and it also stops if the window is killed or crashes.
- *Browser mode* (`--browser`) stops about 20 seconds after you close its last TG Drive tab or window.
- The log says how long quitting took and which step was slowest.
- *UI review fixes:* the Settings menu no longer spills into the page; photos no longer run under the date rail; list headings no longer cover the “Files” label or show over an empty list; list names stay on one line; PDF preview fixed (a crash when the window resized while opening, a cramped toolbar with no close button on phones, pages blown up to 230 % on wide screens); crash notices show the actual error; `type:pdf` works like `ext:pdf`, and a search TG Drive can't read is explained instead of offered as “Try again”; nonsense words no longer find “related” files; settings search also finds choices (“dark”, “socks”); paths keep their leading “/”; storage tiles line up; form fields share one text size.
- *Signing in without a connection* no longer spins forever: after 25 seconds it says it can't reach Telegram, with a Try again button, and **Connection settings (proxy)** is right on the sign-in screen for networks where Telegram is blocked.

**New in 2.3.1: quiet on the CPU.**

- *Fixed a CPU drain.* In a library where most files have no name or caption (photos), the meaning index started its statistics over and over, keeping a core busy for as long as TG Drive ran. It now finishes and goes quiet.
- *Background work* (Settings → General): **Gentle** (the default) runs the meaning index, subject tagging and the duplicate finder at low priority, resting three times as long as they work, so each uses at most about a quarter of a core; **Full speed** finishes a first big index sooner; **Paused** stops them.
- numpy's maths no longer starts a thread per core; endless animations (the indexing dot, the debug banner) stop after a few beats, nothing animates in a hidden window, and a window closed to the tray is frozen until you open it again.
- *See it yourself:* Settings → About & diagnostics → CPU use → Measure now shows what each part of the service is using.

**New in 2.3.**

- *Sidebar your way.* Drag the sidebar's right edge to make it wider or narrower (double-click it for the default), or set the width in Settings → Appearance. Hide it with the sidebar button at the top left, **Ctrl B**, or the « that appears on its edge; a thin tab on the window's left edge brings it back.
- *A calmer search bar.* One rounded field, lined up with the files below it, with the shortcut shown inside it until you start typing; it fits phones too.
- *One View menu.* Grid or list, card size, grouping and albums for files; tiles, cards or list and the order for folders; and the sidebar. All in the View button above the files.
- *PDF pages on the cards.* Most PDFs on Telegram have no preview, so TG Drive draws the first page of each PDF card you see (fetching only what that page needs) and keeps the picture.
- *Cards show where a file is from.* The chat (and folder) has its own line; the copies badge appears when you point at a card.
- *Settings search.* Type in the box above the settings list to find any option.
- *Faster and steadier.* The desktop window and TG Drive's service run as two processes, so the window never waits on the service's work, and if the service ever stops the window starts it again. The window gets status and notifications pushed to it instead of asking every few seconds. Playing and previewing get their own connections to Telegram, so a big download can't make a video stutter. Uploads send parts from a queue, so one slow part never holds the others up.
- *Safer with your data.* Pieces of files from Telegram are checked for size before they are used or kept; the stream cache and downloads can't be corrupted by parts written at the same time or by a crash; folder changes made while an earlier change was still saving are saved too, even after a restart; uploads can't post the same file twice when a connection drops, and stop if the file changes while uploading; downloads and uploads check the free space first; a lost connection shows as offline and everything missed meanwhile is fetched when it comes back.
- *Folder sync takes more care.* Files still being written wait for the next round; removing many files (more than 25, or more than 30% of the folder) always asks first, and so does a folder that has suddenly become empty (an unplugged drive); files with the same name keep their names.
- *Better crash reports.* Every report now says what the app was doing (accounts, transfers, background tasks, threads, memory) and ends with the last log lines. A stuck service, a crash inside native code and a background task that fails are all recorded too. `kill -USR1 <pid>` writes the stacks of all threads to `crashes/faulthandler-*.log`.
- *Removed:* the Places map and PDF highlights, bookmarks and reading position. PDFs open in a simple preview (zoom, fit to width, jump to a page, select and copy text).

**New in 2.2.**

- *Preview on click.* Clicking a file opens its details with a live preview straight away: the full picture, a playable video or song, the first page of a PDF (with its page count), the start of a text file. Arrowing through files only starts streams for the one you stop on.
- *Inter.* The interface uses Inter, the typeface most modern apps use, bundled so it looks the same everywhere.
- *Always shows it's working.* A progress bar along the top of the window for anything you started that takes a moment, a spinner on the button you pressed, skeletons while details and pages load, shimmer on pictures still on their way.
- *Motion.* Panels slide, menus and dialogs pop, lists fade in row by row, toasts rise and fall, cards lift on hover. Turned off with the system's "reduce motion" setting.
- *Better meaning-based search.* Word weights learned from your own library (so "pdf", "notes" or a channel's "join @…" line stop counting), file names weigh more than captions, the vectors are centred, and synonyms and spelling fixes are handed to the model too. On a test set of 30 queries: right answer ranked first far more often (MRR 0.62 → 0.77), 40% more of the right files in the top 10 and about 40% fewer unrelated ones. Subjects found by meaning are much more accurate too. The meaning index rebuilds itself once after updating (seconds to a minute).
- *Calmer screens.* Camera and Telegram file names (`photo_2026-05-07_01-50-00.jpg`) show as "Photo · 7 May, 1:50 AM"; one info line per card; star and download on hover; voice notes as waveforms. Filters sit behind one button (F) and the header shrinks as you scroll; the selection bar floats at the bottom; date headers stay pinned while you scroll. The details panel has the name as a title (click or F2 to rename) and one row of icons for the rarer actions. Collapsible sidebar sections, short counts (49.7k), a compact index status, a transfers button with a progress ring, a tuned dark theme and a consistent type scale.
- *One title bar.* The desktop window draws its own title bar: drag the top bar to move it, double-click to maximize, window buttons at the right (Settings → Desktop to switch back to the system's).
- *Hide duplicates* (on by default; the ⧉ button in the toolbar, or Settings → General). A file forwarded into many chats, or uploaded again with the same name and size, shows as one card with a ⧉ count; its details list every copy. The copy shown is the one in your folders, starred, downloaded or in your own channel, else the oldest. A chat still shows its own files, and counts match the list. `copies:show` in a search shows them all once. Runs in the background in a few seconds even for 400k+ files; scrolling and search stay as fast.
- *Detailed debug logging* (Settings → About & diagnostics, or the account menu). Records every request with its timing, what the window did (navigation, clicks, shortcuts, errors with stack traces, failed media, slow frames), transfers, streaming, indexing, search plans and crashes with full tracebacks to `logs/tgdrive-debug.log`. Takes effect at once; a large striped banner stays at the top while it's on. View, download or clear all logs from the banner or Settings.

**New in 2.1.**

- *Looks.* Redesigned folders (tiles, cards with cover pictures, or a list; emoji icons and colours), custom accent colour, high-contrast theme and text size (Settings → Appearance).
- *Smart folders and subjects.* A smart folder shows everything that matches a rule; an auto-filing folder moves matching unfiled files into itself as they arrive. Files are tagged by subject automatically (Polity, Economy, History… plus your own subjects) and `subject:polity` works in search.
- *Big lists.* Grid and list are virtualised, so scrolling stays smooth at 100k+ results. Choose, reorder and resize list columns. Albums show as stacks.
- *Photos.* A timeline with a date scrubber and a slideshow.
- *Context.* "Show in chat" opens the messages around a file: who sent it, what was said, replies.
- *Two panes.* Split view (drag between panes) or open another window.
- *Paste to upload.* Ctrl V with files or a screenshot on the clipboard uploads them to the folder you're in.
- *Folder sync.* Keep a folder on this computer and a TG Drive folder the same, both ways. Shows what the first sync will do and waits for your OK; stops and asks if a run would remove many files; nothing is ever deleted outright (removed files go to `.tgdrive-trash`, conflicts keep both copies).
- *Use from any app.* Settings → Drive on this computer mounts TG Drive in your file manager (WebDAV on 127.0.0.1 only, with a secret address), so any app can open its files.
- *Bug reports.* Crashes are recorded on this computer; Settings → About can make a diagnostics zip with names, numbers, keys and addresses removed. Nothing is sent anywhere.
- *Settings export and import* (Settings → About), without passwords or keys unless you ask.

**Keyboard.** `/` or `Ctrl K` search · arrows move · `Enter` open · `Space` quick look · `S` star · `T` tags · `M` move · `D` download · `F2` rename · `L` copy link · `Delete` · `Ctrl Z` undo · `V` grid/list · `G` then `D`/`A`/`S`/`R` to jump · `Ctrl B` show or hide the sidebar · `Ctrl ,` settings · `?` all shortcuts.

## Where things are

| | |
| --- | --- |
| Your data (accounts, index, cache, logs) | `~/.local/share/tgdrive` (change with `--data DIR` or `TGDRIVE_DATA`) |
| Downloads | `~/Downloads/TG Drive` (Settings → Downloads) |
| Logs | Settings → About & diagnostics, or `~/.local/share/tgdrive/logs/tgdrive.log` (and `tgdrive-debug.log` while debug logging is on) |

Command line: `tgdrive --send FILE…` (upload files or folders; what the right-click menu uses), `--open search|upload|new-window`, `tgdrive --minimized` (start in the tray), `TGDRIVE_IN_PROCESS=1` (run the service inside the window's process, as before 2.3), `--browser` (use your web browser instead of the window), `--port N`, `--no-gpu` (graphics driver problems), `--data DIR`, `--version`.

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
python -m pytest tests          # 65 tests, including a 60,000-file scale test
python -m desktop               # the desktop app from source
python run.py                   # server only; open http://127.0.0.1:8765
python -m tests.demo_server     # the UI on a fake account (http://127.0.0.1:8766)
python -m tests.bigdb out.db    # a 437,688-file synthetic index for benchmarks
```

Layout: `tgdrive/` (server: Telegram, index, search, streaming, transfers, folders), `web/` (the interface, plain ES modules, no build step), `desktop/` (Qt window, tray, native player), `packaging/` (AppImage build, source installer, icons), `tests/`, `docs/AUDIT.md` (feature audit and roadmap).
