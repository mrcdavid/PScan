# PScan: your phone as a document scanner

Take photos of document pages with the **PScan app on your Android phone**. Your **PC** straightens and cleans
each page, makes the text searchable, combines the pages into one **A4** PDF (or Letter, Long bond, Legal) and saves it
in `C:\Users\Marc\dev\PScan\Scans`. Both devices just need to be on the same Wi-Fi. Built for Marc.

```
 Phone (PScan app, Python/Toga)              PC (pscan_server, Python, starts with Windows)
 ─────────────────────────────              ───────────────────────────────────────────────
 finds the PC        ── UDP 8766 ──▶  discovery (answers + broadcasts "I'm here")
 6-digit pairing     ── HTTP 8765 ─▶  pairing (code shown as a Windows notification)
 📷 photo per page   ── JPEG ──────▶  OpenCV: find page edges → straighten → clean up
 thumbnails          ◀── preview ──   (Tesseract detects sideways pages)
 💾 Save PDF         ── finish ────▶  Tesseract OCR → merged PDF → Scans\ → notification
```

## What's where

| Path | What |
|---|---|
| `pc\` | PC server (`python -m pscan_server`), its settings (`config.toml`), setup scripts and tests |
| `pc\data\` | Runtime data: paired phones, scans in progress, logs (`pc\data\logs\pscan.log`) |
| `phone\` | The Android app (a BeeWare Briefcase project), `briefcase.ps1` wrapper, icons |
| `phone\src\pscan\ui\` | The app's screen: one HTML/CSS/JS page shown in a WebView (theme: maroon `#8d1436`, green `#00563F`, gold `#FFB61C`) |
| `phone\src\pscan\controller.py` | Everything the app does: finding and pairing the PC, uploads, page edits, saving |
| `Scans\` | **Your finished PDFs** |

## 1. Set up the PC (once)

1. **Install the Python packages and open the firewall** (asks for admin rights for the firewall part):
   ```
   powershell -ExecutionPolicy Bypass -File C:\Users\Marc\dev\PScan\pc\scripts\setup.ps1
   ```
2. **Install Tesseract OCR** (for searchable PDFs and auto-rotating sideways pages):
   ```
   winget install --id UB-Mannheim.TesseractOCR
   ```
   For Filipino text too, add the `fil` language in the Tesseract installer, then set `ocr_lang = "eng+fil"` in `pc\config.toml`.
3. **Make PScan start with Windows** (also starts it now):
   ```
   powershell -ExecutionPolicy Bypass -File C:\Users\Marc\dev\PScan\pc\scripts\install_autostart.ps1
   ```
   A PScan icon appears next to the clock (maybe under the **^** arrow). Right-click it for:
   *Open Scans folder · Show pairing code · Forget paired phones · Quit*. PScan takes a few seconds to start.

   To run it by hand instead: `cd C:\Users\Marc\dev\PScan\pc` then `.venv\Scripts\python -m pscan_server`
   (add `--no-tray` to run in the console).

If Windows asks whether to allow **Python** on networks, tick **Private** and click **Allow**.

## 2. Build and install the phone app (once)

Run these from `C:\Users\Marc\dev\PScan\phone`. The `briefcase.ps1` wrapper keeps the Android tools (Java + Android SDK,
about 2–3 GB) in `C:\Users\Marc\dev\.briefcase`.

1. **Create the Android project.** The first time, this downloads the Android tools and asks you to accept Google's
   Android SDK licenses:
   ```
   powershell -ExecutionPolicy Bypass -File .\briefcase.ps1 create android
   ```
2. **Build the installable APK** (a release build signed with PScan's own key):
   ```
   powershell -ExecutionPolicy Bypass -File .\release.ps1
   ```
   The result is `phone\dist\PScan-<version>.apk`, signed with the key in `phone\signing\`. That key was made once
   with `.\release.ps1 -NewKey`; never make a new one while phones have PScan installed.
   **Back that folder up**: phones only accept updates signed with the same key.
   To release a new version, raise `version` in `phone\pyproject.toml` first; the script re-creates the Android
   project so the version number inside the APK changes too.
3. **Install it.** Copy the APK to the phone, open it from *Files → Download*, and allow *Install unknown apps* if
   asked. Or, with USB debugging on (Settings → About device → Version → tap **Build number** 7 times; then
   Additional settings → Developer options → **USB debugging** and **Install via USB**):
   ```
   ..\..\.briefcase\tools\android_sdk\platform-tools\adb install -r dist\PScan-0.3.0.apk
   ```

### If Play Protect blocks the install

PScan isn't from the Play Store, so Google Play Protect doesn't know it.
* If the dialog has **More details → Install anyway**, use that.
* If it only offers *OK*, you can pause scanning yourself: **Play Store → your profile picture → Play Protect → ⚙ →
  Scan apps with Play Protect: off**, install PScan, then **turn it back on**.
* *App not installed / package conflicts*: an older PScan signed with a different key is installed (every version
  before 0.2.1 used a different key). Uninstall it first, then install the new APK and pair the phone again.

For quick testing during development, `.\briefcase.ps1 run android -u` still builds a debug version and installs it over USB.

## 3. Use it

1. Open **PScan** on the phone. The first time, it lists the PCs it finds. Tap yours, and type the **6-digit code** the PC
   shows in a notification (or right-click the tray icon → *Show pairing code*).
2. Tap **📷 Add page**, photograph the page, and repeat for every page. Each page uploads straight away, and the cropped
   preview appears when the PC has processed it.
3. Tap a page to **Rotate**, **Move left/right**, **Retake**, switch **Crop** on/off or **Delete** it.
4. The chips above the buttons set the **paper size** (A4 by default), the **page style** (Color / Grayscale /
   Black & white) and whether the text is **Searchable**.
5. Tap **Save PDF**, optionally type a file name, and confirm. A notification on the PC opens the PDF when clicked.

Every PDF page comes out exactly the chosen paper size. A photographed sheet within 6% of that shape (normal for a
slightly skewed photo) is stretched to fit; anything else (a receipt, an ID) is centred on white, never cut or distorted.
The ⓘ button explains what PScan is for and what it's built with.

Pages already taken survive the app being closed, and the PC keeps unfinished scans for 24 hours.

## 4. More than one PC (e.g. a laptop at home and a desktop at the office)

Each PC runs its own PScan server (set it up with section 1) and keeps its own PDFs in its own `Scans` folder.

* **Pair the phone with each PC once.** Tap the **PC** button in the app's header, then **Add another PC**, and
  pair as usual. The PCs you paired before stay paired.
* **The app picks the PC itself.** It sends scans to the PC marked **In use**. When that PC isn't on the current
  Wi‑Fi but another paired PC is, it switches automatically, but only if no pages of the current scan are already
  on the old PC. Otherwise it says which PC is here, and you can switch in the **PC** sheet.
* Pages already sent to one PC can't move to another. Save the scan before switching, or they're left out.
* Tap the trash icon next to a PC to forget it.

## 5. Setting up the code on another PC

Cloning the repo gives you all the code. These are the git-ignored parts, and how each one is made on the new PC:

| Not in the repo | On the new PC |
|---|---|
| `pc\.venv` (Python packages) | Made by `pc\scripts\setup.ps1`, which also opens the firewall |
| `pc\data` (this PC's identity, paired phones, logs) | Created on first start. **Never copy it from another PC**: two PCs with the same identity confuse the phone. |
| `Scans\` | Created on first start; each PC keeps its own PDFs |
| `phone\.venv`, Android tools | Only needed to build the app: `phone\setup.ps1`, then `phone\briefcase.ps1 create android` |
| `phone\signing\` (signing key) | Only needed to build release APKs: copy it from the PC that has it (USB drive, not GitHub). Without it `release.ps1` stops instead of making a new key. |
| `phone\build`, `phone\dist`, logs, caches | Generated when needed |

Steps on the new PC:
1. Install **Python 3.12+** (python.org, tick *Add to PATH*), **Git**, and **Tesseract** (`winget install --id UB-Mannheim.TesseractOCR`).
2. Clone the repo into a folder outside OneDrive, e.g. `C:\Users\<you>\dev\PScan` (see the git steps below).
3. Run `pc\scripts\setup.ps1`, then `pc\scripts\install_autostart.ps1`. The firewall rules cover Private and Domain
   (company) networks but never Public ones; check yours with `Get-NetConnectionProfile`.
4. On the phone: **PC** button → **Add another PC** → pair with the new PC.

Git:
```
cd C:\Users\<you>\dev
git clone https://github.com/mrcdavid/PScan.git
```
Afterwards, `git pull` brings in changes pushed from the other PC; commit and `git push` as usual.

## Troubleshooting

| Problem | Fix |
|---|---|
| App says "No PC found" | Check that PScan is running (tray icon) and that the phone and PC are on the same Wi-Fi. Otherwise type the IP shown in the tray menu into the app. |
| Found but can't connect / uploads fail | Firewall: run `setup.ps1` again. If you once clicked *Cancel* on Windows' "allow Python" prompt, open *Windows Defender Firewall → Allow an app*, find **Python** and tick **Private**. |
| Works at home but not on school/office Wi-Fi | Many such networks block devices from talking to each other. Turn on the **phone's hotspot**, connect the PC to it, and reopen PScan. Local traffic doesn't use mobile data. |
| PDFs aren't searchable | Install Tesseract (step 1.2). The notification says why when OCR didn't run. |
| Page cropped wrongly | Tap **Crop: on** to switch it off for that page; a dark, plain background under the paper helps detection. |
| Lost the phone / new phone | Tray icon → *Forget paired phones*, then pair again. |
| Phone doesn't find the office PC | Office desktops are often on wired Ethernet, a different network from the Wi‑Fi, and broadcast discovery doesn't cross between them. Type the desktop's IP (tray menu) in the app instead. If that fails too, the network blocks phone-to-PC traffic. |
| Anything else | See `pc\data\logs\pscan.log`. When installed with `briefcase run android`, the phone's log streams in that terminal. |

## Settings (`pc\config.toml`)

`server_name`, `port` (8765), `discovery_port` (8766), `output_dir` (`../Scans`), `default_mode`, `paper` (`A4`;
the phone can choose another size per scan), `ocr`, `ocr_lang`, `tesseract_path`, `max_long_edge` (3000 px),
`jpeg_quality` (85). Restart PScan after editing.

## Development

```
cd C:\Users\Marc\dev\PScan
pc\.venv\Scripts\python -m pytest pc\tests phone\tests
pc\.venv\Scripts\ruff check .
pc\.venv\Scripts\ruff format --check .
```
`phone\tests` runs the app's controller, bridge and network code against a real server on this PC.

**Preview the phone UI in a browser** (fake camera with sample pages, no APK build needed):
```
cd C:\Users\Marc\dev\PScan\phone\tools
..\..\pc\.venv\Scripts\python preview_ui.py
```
Open the printed URL in a browser's phone/responsive view.
