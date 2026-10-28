import json, os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["PORTFOLIO_DB"] = os.path.join(tempfile.mkdtemp(), "t.db")
os.environ.pop("GEMINI_API_KEY", None)
import pytest
import db, gemini, resume, sheets, app as appmod

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
read = lambda n: open(os.path.join(BASE, "samples", n)).read()

@pytest.fixture(autouse=True)
def fresh():
    if os.path.exists(db.DB_PATH): os.remove(db.DB_PATH)
    appmod.seed_if_empty()

def test_crud_and_links():
    pid = db.add_item("projects", {"title": "X", "technologies": "Python, Flask"})
    with db.connect() as c:
        assert c.execute("SELECT COUNT(*) FROM item_skills WHERE item_type='projects' AND item_id=?", (pid,)).fetchone()[0] == 2
    db.update_item("projects", pid, {"title": "X2", "technologies": "Python"})
    with db.connect() as c:
        assert c.execute("SELECT COUNT(*) FROM item_skills WHERE item_id=? AND item_type='projects'", (pid,)).fetchone()[0] == 1
    db.delete_item("projects", pid)
    with pytest.raises(ValueError): db.add_item("skills", {"name": " "})
    with pytest.raises(KeyError): db.delete_item("skills", 99999)

def test_jd_match_backend_vs_ml():
    pf = db.load_portfolio()
    be = gemini.match_portfolio(pf, gemini.analyze_jd(read("jd_backend_python.txt")))
    ml = gemini.match_portfolio(pf, gemini.analyze_jd(read("jd_data_ml.txt")))
    names = lambda m, t: {r["title"] for r in pf["projects"] if m["scores"]["projects"][r["id"]] > 0}
    assert "Inventory Management API" in names(be, "projects")
    assert "Customer Churn Predictor" in names(ml, "projects")
    assert any(m["term"] == "kubernetes" for m in be["missing"])      # not claimed, so reported missing
    assert all(m["term"] != "kubernetes" for m in be["matched"])

def test_selection_differs_per_jd():
    pf = db.load_portfolio()
    s = lambda f: gemini.suggest_selection(pf, gemini.match_portfolio(pf, gemini.analyze_jd(read(f))))
    assert s("jd_backend_python.txt")["projects"] != s("jd_data_ml.txt")["projects"]

def test_verify_text_rejects_invented_skill():
    pf = db.load_portfolio()
    an = gemini.analyze_jd(read("jd_backend_python.txt"))
    ok, bad = gemini.verify_text("Experienced Python developer with Kubernetes and Redis expertise.", pf, an)
    assert not ok and "kubernetes" in bad and "redis" in bad
    ok, _ = gemini.verify_text("Python developer who builds Flask REST APIs on PostgreSQL.", pf, an)
    assert ok

def test_resume_only_selected_and_unknown_ids_dropped():
    pf = db.load_portfolio()
    r = resume.build(pf, {"projects": [pf["projects"][0]["id"], 99999], "skills": [], "summary": "Hi"})
    assert len(r["projects"]) == 1 and r["experience"] == [] and r["summary"] == "Hi"
    html = resume.render_html(r)
    assert "Inventory Management API" in html and "Churn" not in html

def test_pdf_docx_bytes():
    pf = db.load_portfolio()
    sel = gemini.suggest_selection(pf, gemini.match_portfolio(pf, gemini.analyze_jd(read("jd_backend_python.txt"))))
    r = resume.build(pf, sel)
    assert resume.render_pdf(r)[:5] == b"%PDF-"
    assert resume.render_docx(r)[:2] == b"PK"

def test_sheet_roundtrip():
    pf = db.load_portfolio()
    back = sheets.from_tabs(sheets.to_tabs(pf))
    assert back["profile"]["full_name"] == pf["profile"]["full_name"]
    assert [p["title"] for p in back["projects"]] == [p["title"] for p in pf["projects"]]
    db.replace_portfolio(back)
    assert len(db.load_portfolio()["skills"]) == len(pf["skills"])

def test_api_flow():
    c = appmod.app.test_client()
    jd = read("jd_backend_python.txt")
    r = c.post("/api/analyze", json={"jd": jd}); assert r.status_code == 200
    d = r.get_json()
    assert d["match"]["match_pct"] > 50
    for fmt, magic in (("pdf", b"%PDF"), ("docx", b"PK")):
        x = c.post(f"/api/resume/{fmt}", json={"selection": d["selection"], "analysis": d["analysis"], "label": "Backend"})
        assert x.status_code == 200 and x.data[:len(magic)] == magic and "Backend" in x.headers["Content-Disposition"]
    assert c.post("/api/analyze", json={"jd": "short"}).status_code == 400
    assert c.post("/api/organize", json={"text": "x" * 40}).status_code == 502   # no key -> clear error
    assert c.put("/api/skills/99999", json={"name": "A"}).status_code == 404
