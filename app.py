"""Flask app: REST API + static single-page UI. Secrets live only in server-side environment."""
import json
import os
import re

from dotenv import load_dotenv
from flask import Flask, Response, jsonify, request, send_from_directory

load_dotenv()

import db  # noqa: E402  (after load_dotenv so PORTFOLIO_DB can be set in .env)
import gemini  # noqa: E402
import resume  # noqa: E402
import sheets  # noqa: E402

BASE = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__, static_folder="static", static_url_path="/static")
app.config["MAX_CONTENT_LENGTH"] = 1_000_000


@app.errorhandler(ValueError)
def _bad(e):
    return jsonify(error=str(e)), 400


@app.errorhandler(KeyError)
def _missing(e):
    return jsonify(error=str(e).strip("'\"")), 404


@app.errorhandler(gemini.GeminiError)
def _gem(e):
    return jsonify(error=f"Gemini: {e}"), 502


@app.errorhandler(Exception)
def _any(e):
    if hasattr(e, "code") and isinstance(e.code, int):  # werkzeug HTTPException
        return jsonify(error=e.description), e.code
    app.logger.exception("unhandled")
    return jsonify(error=f"{type(e).__name__}: {e}"), 500


def source_portfolio():
    """Portfolio used for matching/resume. ?source=sheet reads the Google Sheet (the spec's data source)."""
    if request.args.get("source") == "sheet" or (request.is_json and (request.json or {}).get("source") == "sheet"):
        pf = sheets.pull()
        for t, rows in pf.items():  # sheet rows have no ids: assign positional ids
            if t != "profile":
                for i, r in enumerate(rows, 1):
                    r["id"] = i
        return pf
    return db.load_portfolio()


@app.get("/")
def index():
    return send_from_directory("static", "index.html")


@app.get("/api/status")
def status():
    return jsonify(gemini=gemini.enabled(), model=gemini.MODEL, sheets=sheets.configured(),
                   sheet_url=os.environ.get("SHEET_PUBLIC_URL", ""), tables=list(db.TABLES))


@app.get("/api/samples/<name>")
def sample(name):
    if name not in ("jd_backend_python", "jd_data_ml", "unstructured_input"):
        raise KeyError("no such sample")
    with open(os.path.join(BASE, "samples", name + ".txt")) as f:
        return jsonify(text=f.read())


# ---------------- portfolio CRUD ----------------
@app.get("/api/portfolio")
def portfolio():
    return jsonify(db.load_portfolio())


@app.put("/api/profile")
def put_profile():
    db.save_profile(request.get_json(force=True))
    return jsonify(ok=True)


@app.post("/api/<table>")
def create(table):
    return jsonify(id=db.add_item(table, request.get_json(force=True))), 201


@app.put("/api/<table>/<int:item_id>")
def update(table, item_id):
    db.update_item(table, item_id, request.get_json(force=True))
    return jsonify(ok=True)


@app.delete("/api/<table>/<int:item_id>")
def remove(table, item_id):
    db.delete_item(table, item_id)
    return jsonify(ok=True)


# ---------------- Gemini: unstructured -> structured ----------------
@app.post("/api/organize")
def organize():
    text = (request.get_json(force=True).get("text") or "").strip()
    if len(text) < 20:
        raise ValueError("Paste some text to organise (at least a sentence)")
    return jsonify(gemini.organize(text))


@app.post("/api/organize/commit")
def organize_commit():
    """Save reviewed records. Only rows the user kept are sent; `grounded` flags are dropped."""
    data = request.get_json(force=True)
    prof = data.get("profile") or {}
    if prof.get("full_name") and not db.load_portfolio()["profile"]:
        db.save_profile(prof)
    added = {}
    for t in db.TABLES:
        for r in data.get(t, []):
            db.add_item(t, r)
            added[t] = added.get(t, 0) + 1
    return jsonify(added=added)


# ---------------- Sheets ----------------
@app.post("/api/sheets/push")
def sheets_push():
    return jsonify(rows=sheets.push(db.load_portfolio()))


@app.post("/api/sheets/pull")
def sheets_pull():
    """Replace the DB with the sheet's content (Sheet -> DB sync), keeping edits made in the sheet."""
    pf = sheets.pull()
    db.replace_portfolio(pf)
    return jsonify(ok=True)


@app.get("/api/sheets/xlsx")
def sheets_xlsx():
    path = sheets.export_xlsx(db.load_portfolio())
    with open(path, "rb") as f:
        return Response(f.read(), mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": "attachment; filename=portfolio_sheet.xlsx"})


# ---------------- JD analysis & resume ----------------
@app.post("/api/analyze")
def analyze():
    body = request.get_json(force=True)
    jd = (body.get("jd") or "").strip()
    if len(jd) < 30:
        raise ValueError("Paste a job description (at least a few lines)")
    pf = source_portfolio()
    if not pf["profile"]:
        raise ValueError("Portfolio is empty")
    analysis = gemini.analyze_jd(jd)
    match = gemini.match_portfolio(pf, analysis)
    advice = None
    try:
        advice = gemini.advise(pf, analysis, match)
    except gemini.GeminiError as e:
        advice = gemini._fallback_advice(pf, analysis, match)
        advice["verification_notes"].append(f"Gemini advice unavailable ({e}); showing keyword-based advice.")
    selection = gemini.suggest_selection(pf, match)
    selection["summary"] = advice["summary"]
    return jsonify(analysis=analysis, match=match, advice=advice, selection=selection, portfolio=pf)


def _terms(analysis):
    a = analysis or {}
    return list(a.get("required_skills", [])) + list(a.get("preferred_skills", [])) + list(a.get("keywords", []))


def _build(body):
    pf = source_portfolio()
    sel = body.get("selection") or {}
    return resume.build(pf, sel, _terms(body.get("analysis")))


@app.post("/api/resume/preview")
def preview():
    r = _build(request.get_json(force=True))
    return jsonify(html=resume.render_html(r, fragment=True), css=resume.CSS)


def _fname(r, ext, label=""):
    stem = re.sub(r"[^A-Za-z0-9]+", "_", f"{r['name']}_{label}".strip("_ ")) or "resume"
    return f"{stem}_Resume.{ext}"


@app.post("/api/resume/pdf")
def pdf():
    body = request.get_json(force=True)
    r = _build(body)
    return Response(resume.render_pdf(r), mimetype="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{_fname(r, "pdf", body.get("label", ""))}"'})


@app.post("/api/resume/docx")
def docx():
    body = request.get_json(force=True)
    r = _build(body)
    return Response(resume.render_docx(r), mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    headers={"Content-Disposition": f'attachment; filename="{_fname(r, "docx", body.get("label", ""))}"'})


# ---------------- saved configs ----------------
@app.get("/api/configs")
def configs():
    return jsonify(db.list_configs())


@app.post("/api/configs")
def config_save():
    b = request.get_json(force=True)
    if not (b.get("name") or "").strip():
        raise ValueError("Give the configuration a name")
    return jsonify(id=db.save_config(b["name"].strip(), b.get("jd", ""), {"selection": b.get("selection"), "analysis": b.get("analysis")}, b.get("id")))


@app.get("/api/configs/<int:cid>")
def config_get(cid):
    return jsonify(db.get_config(cid))


@app.delete("/api/configs/<int:cid>")
def config_delete(cid):
    db.delete_config(cid)
    return jsonify(ok=True)


def seed_if_empty():
    db.init_db()
    if not db.load_portfolio()["profile"]:
        with open(os.path.join(BASE, "samples", "sample_portfolio.json")) as f:
            db.replace_portfolio(json.load(f))


if __name__ == "__main__":
    seed_if_empty()
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", 5050)), debug=False)
