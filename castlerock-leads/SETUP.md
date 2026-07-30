# Running the Castle Rock lead pipeline on your own computer

This is the step-by-step for running it live. You need to do this on a normal
computer/internet connection (home or office) — the county and legal-notice
sites block cloud/datacenter servers, so it must run from a regular machine.

No programming experience required. It's copy-paste. Budget ~15 minutes the
first time; after that each run is one command.

---

## Step 1 — Install Python (one time)

**macOS**
1. Open **Terminal** (press `Cmd+Space`, type "Terminal", Enter).
2. Check if Python is already there: type `python3 --version` and press Enter.
   If it prints `Python 3.10` or higher, skip to Step 2.
3. Otherwise install it from <https://www.python.org/downloads/> — download the
   macOS installer and run it (accept the defaults).

**Windows**
1. Install Python from <https://www.python.org/downloads/>. **Important:** on
   the first screen of the installer, check the box **"Add python.exe to PATH"**,
   then click Install.
2. Open **PowerShell** (Start menu, type "PowerShell", Enter).
3. Check it: type `python --version`, Enter. You should see `Python 3.11` (or
   similar).

> Wherever this guide says `python3`, on Windows type `python` instead.

---

## Step 2 — Download the code (one time)

Easiest way, no tools needed:

1. Go to the branch on GitHub:
   <https://github.com/adencesmat/Copy-Paste-Multiplies/tree/claude/castle-rock-foreclosure-obituary-aa58z2>
2. Click the green **`< > Code`** button → **Download ZIP**.
3. Unzip it. You'll get a folder like `Copy-Paste-Multiplies-claude-...`.
   Inside it is a folder called **`castlerock-leads`** — that's the one you want.

Now point your terminal at that folder. In Terminal/PowerShell type `cd ` (with a
space), then **drag the `castlerock-leads` folder onto the window** and press
Enter. Your prompt should now show you're inside `castlerock-leads`.

---

## Step 3 — Set it up (one time)

Copy-paste these one at a time.

**macOS**
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp config.example.yaml config.yaml
```

**Windows (PowerShell)**
```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy config.example.yaml config.yaml
```

(If Windows blocks the `Activate.ps1` step with a security message, run this
once: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, answer `Y`, then
retry the activate line.)

---

## Step 4 — Confirm the live sources are reachable

```bash
python3 -m castlerock_leads --config config.yaml check-endpoints
```

This is the moment of truth. It contacts each source from your network and:
- confirms the county foreclosure app, legal-notice site, and obituary feeds
  respond (you want to see `OK`), and
- **prints the county GIS layer numbers and field names.** Jot these down — if
  they differ from the defaults, put them into `config.yaml` under
  `enrichment.parcels_layer_id` and `enrichment.fields`. (Open `config.yaml` in
  any text editor; it's all commented.)

If a source shows an error here, tell me exactly what it printed and I'll adjust.

---

## Step 5 — Run it for real

```bash
python3 -m castlerock_leads --config config.yaml run
```

It prints a summary and writes two files into the `output` folder:
`leads-YYYY-MM-DD.csv` (open in Excel) and `leads-YYYY-MM-DD.html` (open in any
browser — this is the ranked report). Double-click either to open.

Run it again tomorrow and it only shows **new** leads (it remembers what you've
already seen).

---

## Step 6 (optional) — Have it run automatically every morning

- **macOS/Linux:** `scripts/run_daily.sh` is ready for `cron`. See the comment
  at the top of that file for the one-line crontab entry.
- **Windows:** use **Task Scheduler** to run, daily,
  `C:\path\to\castlerock-leads\.venv\Scripts\python.exe -m castlerock_leads --config C:\path\to\castlerock-leads\config.yaml run`.
- **Email digest:** set `email.enabled: true` in `config.yaml` and provide your
  mail server details as environment variables (`SMTP_HOST`, `SMTP_PORT`,
  `SMTP_USER`, `SMTP_PASSWORD`). Ask me and I'll walk you through it for your
  email provider.

---

## Everyday use, after the one-time setup

Open the terminal, go to the folder, activate, run:

```bash
cd /path/to/castlerock-leads
source .venv/bin/activate          # Windows: .venv\Scripts\Activate.ps1
python3 -m castlerock_leads --config config.yaml run
```

---

## If something goes wrong

- **`command not found: python3`** — Python isn't installed or (Windows) "Add to
  PATH" wasn't checked. Redo Step 1.
- **A source shows an error in `check-endpoints`** — copy the exact message to me.
  The two scraped sites (foreclosures, legal notices) may need a small selector
  update once we see their live page; that's expected and quick to fix.
- **Report is empty but no errors** — there may genuinely be no new Castle Rock
  foreclosures/estates today, or a filter is too strict (e.g. `obituaries.min_age`).
  Tell me and we'll check.
- **Always sanity-check the first batch** against the actual source websites
  before contacting anyone.
