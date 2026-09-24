# wa-autodelete

When the other person in **one chat you choose** replies, every earlier message **you** sent in that chat is deleted **for everyone**. Messages you send after their reply stay until they reply again.

It runs on your computer as a WhatsApp *linked device* (like WhatsApp Web), so it works no matter whether you type on your Android phone, WhatsApp Web, or the desktop app.

## Requirements

- A Windows, macOS, or Linux computer that stays **on and awake**.
- Node.js 20 LTS (18+ works): https://nodejs.org
- Your phone with WhatsApp (to scan a QR code once).

A private copy of Chrome is downloaded automatically during `npm install`. It doesn't touch your normal browser.

## Install and first run

Open a terminal in this folder and run:

```bash
npm install
npm test            # optional: 52 checks of the deletion logic against a simulated chat
npm run setup       # scan the QR code, then pick your chat from the list
```

Setup asks you two things.

- **Which chat.** Type a number, or type part of a name or phone number to search.
- **Whether messages already in the chat are included.** The default is *no*, which means only messages you send from now on are affected.

It then shows a preview of what would happen and exits.

Before going live, you can do a trial run. Nothing is deleted; it only logs what it would do. Stop it with Ctrl+C.

```bash
npm run dry-run
```

## Run it 24/7 (recommended)

```bash
npm install -g pm2
npm run service                       # starts it in the background and saves the process list
pm2 install pm2-logrotate             # keeps log files from growing forever
pm2 set pm2-logrotate:max_size 10M
pm2 set pm2-logrotate:retain 7
```

**Start automatically after a reboot:**

- **Linux / macOS:** run `pm2 startup`, copy and run the command it prints, then run `pm2 save`.
- **Windows:** open Task Scheduler and choose *Create Task*. Set the trigger to **At log on** (your user). Set the action to *Start a program* with program `cmd.exe` and arguments `/c pm2 resurrect`. Tick *Run with highest privileges*.

Chrome or Edge is found automatically; `CHROME_PATH` is only needed for an unusual install location. Also disable sleep in your power settings. A sleeping computer can't delete anything, though it catches up when it wakes.

## Everyday commands

| Command | What it does |
|---|---|
| `npm run status` | Health, connection state, last check, total deleted |
| `npm run logs` | Live log |
| `npm run stop` / `npm run restart` | Stop or restart the background service |
| `npm run stop` then `npm run setup` | Change the chat (then `npm run restart`) |

## Control it from your phone

The script keeps running on your computer, and your phone works as the remote. On your phone, open your **"Message yourself"** chat. If you don't have one, start a new chat and pick yourself at the top of the contact list. Send one of these as the *entire* message. Capitals don't matter, and a leading `!` is optional:

| Send | What happens | Reaction you'll see |
|---|---|---|
| `pause` | Stops deleting until you resume | ⏸️ |
| `pause 30m` / `pause 2h` / `pause 1d` | Pauses, then resumes by itself | ⏸️, changing to ▶️ when time's up |
| `resume` | Starts again. Messages you sent while paused are **not kept**: they're deleted with the rest after their reply. | ▶️ |
| `status` | Tells you whether it's running | ✅ running, ⏸️ paused, ⚠️ problem |

Ordinary notes to yourself are ignored. "stop by the shop" does nothing; only a message that is exactly a command counts. Only you can control it: messages from anyone else, or in any other chat, never count as commands. The pause survives restarts and reboots.

The reaction usually appears within a few seconds. If the computer was asleep, it appears within about a minute of the computer waking up.

## Settings (`config.json` → `"settings"`)

Invalid values are ignored with a warning and the safe default is used. Run `npm run restart` after editing.

| Setting | Default | Meaning |
|---|---|---|
| `dryRun` | `false` | `true` = log only, never delete |
| `settleDelaySec` | `[4, 12]` | Random wait after their reply before acting |
| `settleMaxSec` | `45` | Maximum wait during a burst of replies |
| `deleteDelaySec` | `[2.5, 7]` | Random gap between individual deletions |
| `maxDeletesPerHour` / `maxDeletesPerDay` | `60` / `400` | Hard safety caps. They persist across restarts. |
| `maxMessageAgeHours` | `58` | Never tries messages older than this (WhatsApp's own limit is about 60h) |
| `scanDepth` | `3000` | Upper limit on how many messages it scrolls back through. It normally stops sooner, as soon as it has covered `maxMessageAgeHours`, because anything older can't be deleted for everyone anyway. The log says how far back each check reached. |
| `periodicSweepMin` | `[8, 16]` | Self-healing re-check interval |
| `maxAttemptsPerMessage` | `3` | Retries before giving up on one message |
| `circuitBreakerFailures` / `circuitBreakerPauseMin` | `4` / `30` | Pause after repeated failures |

## How it keeps running

These situations recover automatically, with no action from you:

- **The process or browser crashes, or WhatsApp's page crashes or hangs.** A watchdog checks health every minute and pm2 restarts the process.
- **Internet drops or the computer wakes from sleep.** It waits for WhatsApp to reconnect, restarts only if that takes more than 20 minutes, then re-checks the chat.
- **Missed events.** A periodic re-check catches any reply that arrived while it was offline or restarting.
- **Memory growth.** There's a planned browser refresh roughly once a day, and never in the middle of deleting.
- **Leftovers from a crash.** Leftover browser processes and stale lock files are cleaned up at startup.
- **Repeated startup failures.** These back off exponentially (15s up to 15min) instead of hammering WhatsApp.
- **Corrupt files.** State files are written atomically, and a corrupt state file is set aside rather than causing a crash.
- **Accidental double start.** A second copy can't run at the same time.

## What it does to reduce ban risk

It sends no messages, sends no read receipts, and never marks anything as seen. It only deletes your own messages in one chat, only when WhatsApp itself says "delete for everyone" is allowed. Deletions are human-paced with random delays and capped per hour and per day. It sets your presence to *offline*, so you don't appear online 24/7 and your phone keeps getting notifications. It keeps one persistent login instead of re-linking, and it runs from your home internet connection rather than a datacenter.

**Honest caveat:** any unofficial automation is against WhatsApp's Terms of Service. These measures make it look like normal, light use, but no tool can guarantee zero risk.

## What still needs you (no software can avoid these)

- **WhatsApp Web updates that break things.** Message reading and deleting go through `wa.js`, which talks to WhatsApp Web directly and already copes with the mid-2026 ID rename that makes whatsapp-web.js 1.34.7 fail with the error `r`. A future change could still break it. Deletions pause safely, the log tells you, and nothing wrong gets deleted. To fix it:
  `npm run stop && npm run update-lib && npm test && npm run restart`
- **Logged out**, either because you removed the linked device or because your phone was offline for about 14 days. Open `data/qr.png` and scan it, or run `npm run setup`.
- **The computer is off, or asleep with sleep enabled.**
- **Messages older than WhatsApp's delete-for-everyone window** (about 2.5 days) can't be deleted for everyone by anyone.

## Privacy

Everything runs locally. Message text is never written to logs; the logs contain only times, types, and short IDs. The `data/` folder contains your WhatsApp login session, so treat it like a password and never share it.

## Raspberry Pi / ARM Linux

Install Chromium (`sudo apt install chromium`) and start with `CHROME_PATH=/usr/bin/chromium npm run service`.
