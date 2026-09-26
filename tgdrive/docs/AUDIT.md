# TG Drive: feature audit and roadmap

Version 2.0.0 · September 2026

This audit covers TG Drive 0.1 (the web app delivered first) against what a Drive-style manager for **your** Telegram needs: 437,688 indexed files (4.8 TB) across 383k channel files. The biggest chat has 49,749 files; 146k are documents (mostly PDFs without previews) and 15k are videos (mostly long lectures). Each gap is marked **Built** (in 2.0) or **Next** (not built yet, listed in the roadmap at the end).

## 1. "Search doesn't respond": root causes and fixes

Measured on a synthetic index with your exact shape: 437,688 files, the same kind mix, and a 49,749-file biggest chat.

| Cause in 0.1 | Effect | Fix in 2.0 |
| --- | --- | --- |
| Thumbnails and API shared one origin, so the browser's 6-connections-per-host limit applied to both. Thumbnail requests could hang for up to 120 s on Telegram flood-waits. | Search requests queued behind stuck thumbnails, so the app looked frozen. | Media runs on its own port. Thumbnails time out after 25 s and back off on flood-waits (the server answers 503 with Retry-After). The browser loads at most 6 at a time, visible cards first. Tiny inline previews are stored in the index, so a card shows its preview with no request at all. |
| SQLite queries ran on the server's event loop. | One slow query blocked everything else, including typing-ahead. | A pool of reader threads with per-query deadlines. A newer keystroke interrupts the older query. |
| `COUNT(*)` and per-type counts scanned the whole table on every search (about 8 s at this size). | Results waited for counts. | Kept-up-to-date statistics tables. Results come first; counts arrive separately and can be cancelled. |
| OFFSET paging | Scrolling deep into 400k files got slower with every page. | Keyset paging on date, size and name. |
| Exact-token FTS only | "test series" missed TestSeries and test_series, typos found nothing, and Hindi didn't match Latin script. | The smart search below. |

Now, with a warm cache: an empty query answers in about 4 ms, `polity` in 190 ms, `test series` in 290 ms (48k matches), `seires` in 310 ms (corrected to *series*), later pages in 3 to 30 ms, and counts in 3 to 200 ms. On a cold start the index file is pre-fetched in the background, and the vocabulary is built at launch.

## 2. Audit by area

### Search
| Gap | Status |
| --- | --- |
| Joined/split words (testseries, test_series, TestSeries, series-test), camelCase and letter–digit splits (GS2, Paper1) | **Built** (hidden keyword forms at index time; variant expansion at query time) |
| Substring inside words (trigram index) | **Built** |
| Word endings (notes/note, series) | **Built** (Porter stemming) |
| Typos, corrected from your own vocabulary ("did you mean") | **Built** |
| Abbreviations ↔ phrases (pyq ↔ previous year questions, acronyms auto-derived from names) | **Built** |
| Hindi ↔ Latin script (संविधान ↔ samvidhan) | **Built** |
| Synonyms: a built-in study list plus your own | **Built** |
| Meaning-based "related" results (offline model, int8 vectors, Hamming prefilter) | **Built** |
| Tiered ranking with a badge showing how each result matched | **Built** |
| Operators: type, ext, mime, size, dur, width/height, dates (absolute and relative), chat, sender, source kind, folder, tag, topic, starred, album, forwarded, mine, caption/note/tags, name:, caption:, phrases, exclusions, exact mode | **Built** |
| Live search as you type, suggestions (files, chats, folders, filters, history, saved), search inside a chat, folder or Telegram folder, saved searches, search history | **Built** |
| Watched / unwatched / in-progress filters | **Built** |
| Search inside document text (PDF/DOCX/EPUB contents), OCR, speech transcripts, image content | **Next** (needs downloading content; see roadmap) |
| Boolean OR and grouping | **Next** |

### Browsing and interface
| Gap | Status |
| --- | --- |
| Redesigned interface: design tokens, light/dark/system themes, density, 3 card sizes, list/grid, date grouping | **Built** |
| Instant previews with no request (stripped thumbnails), coloured document icons by type (PDFs have no Telegram previews) | **Built** |
| Tabs with counts, filter chips, advanced filter panel, 11 sort orders (best match, date, name, size, chat, duration, type, extension) | **Built** |
| Starred, Recent, Continue watching, Tags, Telegram chat folders, forum topics, albums | **Built** |
| Keyboard control of everything, shortcut sheet, context menus, multi-select, drag and drop | **Built** |
| Details panel: all metadata, folder path, duplicates, note, tags, Telegram link, local copy | **Built** |
| Storage analytics, duplicate finder, index manager, activity log, settings (12 sections) | **Built** |
| Mobile/narrow layout | **Built** (responsive) |
| Screen-reader labels, focus handling, reduced motion | **Built** (baseline; a full WCAG audit is **Next**) |
| Interface translations (Hindi etc.) | **Next** |

### Organisation
| Gap | Status |
| --- | --- |
| Folder colours and descriptions, nesting, drag and drop, breadcrumbs | **Built** |
| Stars, tags, notes; bulk rename with patterns; rename (alias) without touching Telegram | **Built** |
| Undo (Ctrl+Z), manifest backups and restore, merge between computers (newest wins, tombstones) | **Built** |
| Save a copy to Drive, send or forward to any chat | **Built** |
| A file in several folders, smart (rule-based) folders, trash with restore | **Next** |

### Streaming and preview
| Gap | Status |
| --- | --- |
| Byte-range streaming of anything (video, audio, voice, round, GIF, PDF, images, text) with a disk cache and read-ahead | **Built** |
| Native player for H.264/H.265/AAC, which the app window can't decode (most Telegram videos), with seeking, speed and full screen | **Built** |
| Resume where you left off (viewer, background player, native player), progress bars, watched ticks | **Built** |
| Background audio player with a queue; auto-play next | **Built** |
| Open in VLC/mpv; folder or search as an .m3u playlist | **Built** |
| PDF viewer, text viewer, image zoom, neighbour prefetch | **Built** |
| Subtitles, audio-track choice, on-the-fly transcoding, Office/EPUB/archive previews | **Next** |

### Transfers
| Gap | Status |
| --- | --- |
| Parallel multi-part downloads and uploads, pause/resume across restarts, retry, cancel, speed and ETA | **Built** |
| Folder download (keeping the structure or as a zip), selection zip | **Built** |
| Upload files and folders (drag and drop, native picker, straight from disk without temporary copies) | **Built** |
| Upload into any chat with a caption; as a document or as media (falls back to a file if Telegram refuses it as a photo) | **Built** |
| Stream cache reused by downloads; local copies detected | **Built** |
| Notifications when transfers finish | **Built** |
| Bandwidth limit, scheduling, auto-download rules, two-way folder sync, >4 GB splitting, client-side encryption | **Next** |

### Indexing and Telegram
| Gap | Status |
| --- | --- |
| Resumable full-history index, live updates (new, edited, deleted), periodic resync | **Built** |
| Background verification that indexed messages still exist | **Built** |
| Per-type and per-chat-kind index policies, exclude/include, pause, rescan | **Built** |
| Telegram chat folders, forum topics, archived chats, member counts | **Built** |
| Flood-wait handling everywhere, file-reference refresh | **Built** |
| Takeout API for faster first indexing, public channels without joining, discussion comments, stories | **Next** |

### Accounts, sign-in and settings
| Gap | Status |
| --- | --- |
| First-run app-key setup in the app, QR sign-in, phone + code + 2FA | **Built** |
| Several accounts, switcher, remove (keeping or deleting data) | **Built** |
| Import from the 0.1 zip (accounts, index, API key) | **Built** |
| Proxy: SOCKS5/4, HTTP, MTProto | **Built** |
| All settings in the app, applied live | **Built** |

### Desktop app
| Gap | Status |
| --- | --- |
| Native window (Qt WebEngine), single instance, tray (pause indexing, open downloads), close to tray, start minimised, autostart | **Built** |
| Applications-menu entry and icons, installed automatically by the AppImage | **Built** |
| Native file/folder pickers, desktop notifications, links opened in the browser or Telegram | **Built** |
| Native media player window | **Built** |
| Browser mode fallback (`--browser`), software rendering switch (`--no-gpu`) | **Built** |
| AppImage for x86_64 (glibc 2.28+), source installer for everything else | **Built** |
| Auto-update, Flatpak/.deb/.rpm/AUR, ARM64, Windows/macOS | **Next** |

### Security and privacy
| Gap | Status |
| --- | --- |
| Loopback-only binding, Host-header check (DNS rebinding) | **Built** |
| Per-launch access token (desktop); a separate stream-only token for copied links, playlists and the native player | **Built** |
| Custom header required for state-changing calls (CSRF) | **Built** |
| Content Security Policy on the app; scripts in HTML/SVG from Telegram can't run (sandboxed) | **Built** |
| Renderer sandbox kept on wherever the OS allows it | **Built** |
| External links limited to http(s)/tg/mailto; the native player only plays local stream URLs | **Built** |
| Session files mode 600; app lock (PBKDF2) with auto-lock; password required to serve beyond localhost | **Built** |
| Programs started from TG Drive get a clean environment (no bundled library paths) | **Built** |
| Encryption at rest (index/session in the OS keyring or SQLCipher), signed releases | **Next** |

### Reliability and maintenance
| Gap | Status |
| --- | --- |
| Versioned schema migrations (v1 → v3) that keep all data; search index rebuilt in the background while the app stays usable | **Built** |
| Optimise, vacuum, integrity check, rebuild search/meaning index, clear caches, CSV export | **Built** |
| Rotating log file with an in-app viewer | **Built** |
| 18 automated tests, including a 60k-file scale test and an old-index upgrade test; the whole suite also passes on the bundled runtime | **Built** |
| Crash reporter, diagnostics bundle, settings export/import | **Next** |

## 3. Roadmap: everything that could still be added

Grouped by area and roughly ordered by value within each group.

**Search and discovery**
1. Full-text search inside PDFs, DOCX, PPTX, EPUB and TXT (opt-in per chat and size cap, text extracted while streaming)
2. OCR of scanned PDFs and images, Hindi + English (Tesseract)
3. Speech-to-text transcripts of lectures, voice notes and audio (local Whisper), searchable with timestamps that jump the player
4. Image content search ("map of India", "handwritten notes") with a local CLIP model
5. Larger optional multilingual meaning model for better Hindi and mixed-language results
6. "More like this" from any file
7. OR, parentheses and regex in queries
8. Facet sidebar with counts by chat, year, extension and size band
9. Natural-language dates ("last week", "March 2024 lectures")
10. Saved-search alerts: notify when new files match
11. Search across all accounts at once
12. Learning from clicks: rank what you open more highly
13. Search inside zip/rar/7z listings
14. Index and search non-file messages: links, text posts, polls
15. Synonym suggestions mined from your file names

**Browsing and interface**
16. Virtualised grid (recycled cards) for smooth scrolling through 100k+ results
17. Photo timeline with a date scrubber
18. ~~Map of geotagged photos~~ (built in 2.1, removed in 2.3)
19. Slideshow mode
20. Customisable list columns (choose, resize, reorder)
21. Dual-pane view and multiple windows or tabs
22. Chat context view: the files around a message, with replies and threads
23. Albums shown as stacks in the grid
24. Folder cover images and emoji icons
25. Hindi and other interface languages; right-to-left support
26. Custom accent colour, high-contrast theme, font-size setting
27. Onboarding tour and in-app help
28. Full WCAG 2.2 AA accessibility audit
29. Command palette (Ctrl+Shift+P)
30. Installable PWA for other devices on your network

**Organisation**
31. A file in several folders (shortcuts)
32. Smart folders: rules that file automatically (e.g. PDFs from Vision IAS with "polity" go to Polity)
33. Auto-tagging by rules or AI (subject, paper, year)
34. Trash: deletions go to a private channel first, restorable for 30 days
35. Version groups: newer uploads of the same document are grouped
36. Ordered collections and playlists (a lecture series in order)
37. ~~PDF bookmarks, highlights and reading progress~~ (built in 2.1, removed in 2.3)
38. Shared folders with other Telegram users (a shared manifest channel)
39. Duplicate clean-up with rules (keep the oldest, or the copy in Drive) in one click
40. Import a folder structure from disk; export the tree as JSON or HTML

**Streaming and preview**
41. Subtitles (embedded tracks, and .srt files from the same chat)
42. Audio-track and chapter selection
43. On-the-fly transcoding (FFmpeg → WebM/HLS), so every video plays inside the window
44. Hardware video decoding (VA-API) in the native player
45. Thumbnail scrubbing previews on the seek bar
46. Picture-in-picture
47. Cast to Chromecast or DLNA TVs
48. Office documents (docx, pptx, xlsx) and EPUB readers
49. Browse archives and extract single files without downloading everything
50. Code and Markdown rendering
51. Audio waveform and lyrics
52. "Available offline": pin files to the local cache
53. Remember playback speed per file or series

**Transfers and sync**
54. Bandwidth limit and scheduled transfers (off-peak)
55. Auto-download rules (new files from a chat go to a folder on disk)
56. Two-way sync of a local folder with a Drive folder (Dropbox-style)
57. Backup mode: one-way backup of a folder, deduplicated
58. Transparent splitting and joining of files over 2 GB / 4 GB
59. Client-side encryption of uploads, decrypted transparently when streaming
60. Checksum verification after download
61. Reorder the queue and set priorities
62. Rules for name conflicts (rename, skip, overwrite)
63. Export a whole chat's files to disk
64. "Send to TG Drive" in file managers (Nautilus, Dolphin, Nemo) and a browser extension
65. Paste from the clipboard (Ctrl+V) to upload

**Indexing and Telegram**
66. Takeout sessions for faster first indexing of very large accounts
67. Browse public channels by @username without joining
68. Index discussion-group comments on channel posts
69. Stories and highlights media
70. Optional sticker indexing
71. Per-chat index priority and date-range limits
72. Faster deletion detection via channel difference updates
73. Merged view of several accounts
74. Session manager: list and end other Telegram sessions

**Desktop integration**
75. Mount TG Drive as a drive (FUSE or WebDAV), so any app can open files
76. GNOME Shell search provider and KRunner plugin
77. Global quick-search hotkey
78. MPRIS media controls (keyboard media keys, lock screen)
79. Notification actions (Open, Show in folder)
80. Drag files out of TG Drive into other apps
81. Auto-update (AppImageUpdate/zsync) with release notes
82. Flatpak, Snap, .deb, .rpm and AUR packages
83. ARM64 build; Windows and macOS builds
84. Portable mode (data next to the AppImage)
85. Command-line interface (search, download, upload from the terminal)
86. Documented local API with keys; webhooks; plugins

**Security and privacy**
87. Encrypt the index and sessions at rest (SQLCipher; keys in the OS keyring)
88. Store the API hash and passcode in the Secret Service keyring
89. Per-account passcodes and a panic-lock hotkey
90. Audit log of destructive actions (delete, forget, restore)
91. Signed releases and reproducible builds
92. Warn before opening executables; optional ClamAV scan of downloads
93. AppArmor profile for the AppImage

**Reliability and operations**
94. Automatic index backups with one-click restore
95. Local crash reporter and a diagnostics bundle for bug reports
96. Health panel: flood-wait timers per data centre, queue depths, cache hit rate
97. Settings export and import
98. Low-memory mode for older PCs
99. Continuous-integration pipeline, coverage report, fuzzing of the query parser, 1M-file load test
100. Import from other Telegram-drive tools (e.g. Teldrive)

**AI study features (all offline)**
101. Summaries of PDFs and lectures
102. Ask questions across your study material, with answers citing the files
103. Automatic subject classification (Polity, Economy, History …)
104. Flashcards and quizzes from notes
105. Perceptual duplicates (the same PDF or video uploaded by different channels)
106. Translate captions and file names
