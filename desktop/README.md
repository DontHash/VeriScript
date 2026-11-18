# VeriScript desktop

A native window around the studio. Install it, open it, drop a page in: no
Python setup, no browser tab, no server to start by hand, and nothing leaves
the computer.

```
┌ VeriScript (Tauri window) ───────────────────────────────┐
│ splash (desktop/ui) ──▶ http://127.0.0.1:<random>/studio │
└───────────────┬──────────────────────────────────────────┘
                │ starts, waits for /api/health, stops on exit
                ▼
     veriscript-server (webapp/server.py, frozen)
     VERISCRIPT_WEB_MODE=local · per-launch token · app-data runs dir
```

## How it works

- **Port and secret.** The shell picks a free `127.0.0.1` port and a
  64-character random token for every launch. The server refuses any request
  without the token (`DesktopSessionMiddleware`). The window exchanges it
  once at `/__desktop/session` for an HttpOnly, SameSite=Strict cookie, so
  other programs on the machine and web pages probing localhost get 403.
- **Local mode.** `VERISCRIPT_WEB_MODE=local` switches the studio's wording to
  "processed on this computer". The shell also turns off the hosted demo's
  quotas: 200 MB uploads, no daily page limits, no PDF page cap or run
  timeout (long files run as background jobs with progress and Cancel), and
  results kept until you delete them.
- **Library.** Every result stays in the app-data folder until deleted.
  The studio's **Library** page lists them, searches their titles and text,
  and reopens, renames or deletes them (desktop only; the demo hides it).
- **Where files go.** Runs go to the app-data folder
  (`%APPDATA%\live.veriscript.desktop\runs` on Windows). The server log goes
  to the app log folder (`%LOCALAPPDATA%\live.veriscript.desktop\logs\server.log`)
  and is rewritten on each launch.
- **Lifetime.** Closing the window stops the server. On Windows the server
  also runs in a job object, so it stops even if the shell crashes.
- **Navigation.** The window only shows the splash and the local studio.
  Other links open in the default browser. Same-origin pop-ups (full-size
  video previews) open in a new app window.
- **Drag and drop.** Tauri's own drop handler is off, so files dropped on the
  window reach the studio's drop zone.

## Develop

Needs Rust (stable), Node 22 and a Python environment that can run
`webapp/server.py` (`pip install -r requirements.txt -r webapp/requirements-web.txt`).

```bash
cd webapp/frontend && npm ci && npm run build
cd desktop && npm ci && npm run dev
```

Without a bundled sidecar the shell runs `python webapp/server.py` from this
checkout. Set `VERISCRIPT_DESKTOP_PYTHON` to use another interpreter, for
example a virtualenv's `python.exe`.

Unit tests for the shell (token, navigation allow-list, encoding):

```bash
cd desktop/src-tauri && cargo test
```

## Release build

```bash
python desktop/scripts/build_sidecar.py
cd desktop && npm ci && npm run build -- --config src-tauri/tauri.release.conf.json
```

`build_sidecar.py` freezes the server with
`packaging/veriscript-server.spec` into `src-tauri/binaries/`. The release
config adds it as `externalBin`. Installers are written to
`src-tauri/target/release/bundle/` (NSIS and MSI on Windows, DMG on macOS,
AppImage and deb on Linux).

### Release checklist

The shell was verified end to end in development on Windows 11: splash →
studio → OCR run → close, with the server stopped. Before the first public
installer:

- [ ] Build the sidecar in a clean virtualenv and run the installer on a
      clean Windows machine **with networking disabled**. The studio must open
      and read the example pages.
- [ ] Code-sign the installer and executables (Windows Authenticode; macOS
      Developer ID and notarization). Unsigned builds trigger SmartScreen.
- [ ] Check the first-start time on a 4 GB RAM machine. The splash allows 3
      minutes before it reports an error.
- [ ] Decide on updates. Nothing auto-updates today, which keeps the offline
      promise. Any updater must stay opt-in.

### Not yet implemented

- "Open with VeriScript" file associations. The studio has no endpoint that
  reads a local path, and adding one needs care so that other programs cannot
  use it to read arbitrary files.
- Native save dialogs. Downloads use WebView2's own download flow and land in
  the Downloads folder.
