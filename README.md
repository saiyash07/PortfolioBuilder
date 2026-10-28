# Portfolio Resume Studio

AI-assisted portfolio database + job-specific resume generator.
Flask · SQLite · Gemini API · Google Sheets (Apps Script bridge) · ReportLab (PDF) · python-docx (DOCX).

## What it does
1. **Portfolio database** – profile, education, skills, certifications, projects, experience, achievements, publications, languages (full add/edit/delete UI). Schema: [`schema.sql`](schema.sql); sample data: [`samples/sample_portfolio.json`](samples/sample_portfolio.json) (dummy person, auto-loaded on first run).
2. **Gemini integration** (`gemini.py`)
   - *Organise* unstructured text into structured records (reviewed by you before saving; ungrounded rows are flagged).
   - *Analyse a JD* (required/preferred skills, keywords, qualifications).
   - *Compare* the JD with your portfolio → match %, matched/missing terms, per-item relevance.
   - *Suggest* a tailored summary and improvement tips.
3. **Google Sheets sync** (`sheets.py`, `apps_script/Code.gs`) – one tab per category. Push DB→Sheet, pull Sheet→DB, and the resume builder can read directly from the Sheet. `.xlsx` export works with no setup.
4. **Resume builder** – paste a JD, see matches, tick/untick items, edit the summary; the preview refreshes on every change. Download **PDF** or **DOCX**. Setups can be saved/loaded.

### No invented facts – how it is enforced
- The resume is built from **portfolio row ids**; text is copied from the rows. Unknown ids are dropped.
- Matching/scoring is deterministic code over stored data, not model output. JD skills you don't have are listed as *missing* and are never added.
- Gemini's JD terms must literally appear in the JD; its summary is rejected (and replaced by a grounded one) if it mentions any tech term absent from your portfolio (`verify_text`).
- Organise-from-text output is only a draft; nothing is saved without your confirmation.
- Without a Gemini key the app falls back to keyword matching and says so in the UI.

## Setup
```bash
cd 28OCT
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # then edit .env
python app.py             # http://127.0.0.1:5050
```
Python 3.10+. Tests: `python -m pytest -q tests`.

### Gemini API
Create a key at https://aistudio.google.com/apikey and set `GEMINI_API_KEY` in `.env` (server-side only; never sent to the browser, `.env` is git-ignored). `GEMINI_MODEL` defaults to `gemini-2.5-flash`.

### Google Sheets
1. Create a blank Google Sheet → **Extensions → Apps Script**, paste `apps_script/Code.gs`.
2. **Project Settings → Script properties**: add `SECRET` = a long random string.
3. **Deploy → New deployment → Web app**; execute as *Me*, access *Anyone*. Copy the URL.
4. In `.env`: `SHEETS_WEBAPP_URL=<url>`, `SHEETS_SECRET=<same secret>`, `SHEET_PUBLIC_URL=<sheet link>`.
5. In the app: **Google Sheets → Push database → Sheet**. Edit cells in Sheets, then **Pull** (or choose *Data source: Google Sheet* in the Resume Builder).

Sheet link for submission: *(add your shared sheet link here after step 5)*

## Workflow to demo
Portfolio tab (CRUD) → AI Import (paste `samples/unstructured_input.txt`) → Google Sheets (push) → Resume Builder: load **Backend (Python)** JD → analyse → tweak selections → PDF; then load **Data / ML** JD → analyse → PDF.

## Sample outputs (generated from the same portfolio)
`sample_outputs/Aarav_Mehta_Backend_Python_Resume.pdf|docx` and `…Data_ML_Resume.pdf|docx` (keyword-fallback mode), plus `portfolio_sheet.xlsx`. Sample JDs: `samples/jd_*.txt`. Regenerating with a Gemini key will give Gemini-written summaries.

## Screenshots (`screenshots/`, sample data)
`01_portfolio_database` · `02_edit_project_entry` · `03_gemini_organise_unstructured` · `04_sheets_sync_tab` · `05_backend_*` and `06_datasci_*` (JD match, selections, preview, downloaded PDF). Gemini-written resumes: `sample_outputs/*_gemini.pdf`.

## Layout
`app.py` API + routes · `db.py` storage · `gemini.py` AI + matching + verification · `sheets.py` sync · `resume.py` HTML/PDF/DOCX · `static/index.html` UI · `tests/`

## Not included (you must produce)
Demo video and the live Google Sheet link need your own Google account / screen recording; this repo provides everything to create them.
