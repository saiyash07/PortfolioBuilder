"""Gemini integration + deterministic matching/verification.

Gemini proposes; the portfolio decides. Every AI output that reaches a resume is
checked against the stored portfolio (see verify_* functions). If no API key is
configured, a keyword-based fallback keeps the app usable and says so.
"""
import json
import os
import re

import requests

from db import split_tech

MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

ALIASES = {  # normalised term -> equivalent forms
    "js": "javascript", "node": "node.js", "nodejs": "node.js", "reactjs": "react", "react.js": "react",
    "py": "python", "ml": "machine learning", "dl": "deep learning", "k8s": "kubernetes",
    "postgres": "postgresql", "gcp": "google cloud", "tf": "tensorflow", "sklearn": "scikit-learn",
    "nlp": "natural language processing", "llms": "llm", "rest apis": "rest api", "restful apis": "rest api",
}
STOP = set("""a an the and or of to in for with on at by is are be as this that you we our your will have has
experience years year strong knowledge ability skills skill good great excellent working work team teams
role looking candidate required preferred plus nice must should etc using use including""".split())


class GeminiError(Exception):
    pass


def enabled():
    return bool(os.environ.get("GEMINI_API_KEY"))


def norm(term):
    t = re.sub(r"\s+", " ", (term or "").strip().lower())
    return ALIASES.get(t, t)


def _call(prompt, schema_hint=None, temperature=0.2):
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise GeminiError("GEMINI_API_KEY not set")
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": temperature, "responseMimeType": "application/json"},
    }
    try:
        r = requests.post(URL.format(model=MODEL), params={"key": key}, json=body, timeout=60)
    except requests.RequestException as e:
        raise GeminiError(f"network error: {type(e).__name__}") from None
    if r.status_code != 200:
        # never echo the request URL (it carries the key)
        raise GeminiError(f"Gemini API {r.status_code}: {r.text[:200]}")
    try:
        text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
        return json.loads(text)
    except (KeyError, IndexError, ValueError):
        raise GeminiError("Gemini returned an unparseable response") from None


# ---------------------------------------------------------------- portfolio vocabulary
def vocabulary(pf):
    """Every term the user can legitimately claim, normalised -> where it comes from."""
    vocab = {}
    def add(term, src):
        n = norm(term)
        if n:
            vocab.setdefault(n, src)
    for s in pf.get("skills", []):
        add(s["name"], "skill")
    for t in ("projects", "experience"):
        for r in pf.get(t, []):
            for tech in split_tech(r.get("technologies")):
                add(tech, t)
    for c in pf.get("certifications", []):
        add(c["name"], "certification")
    for l in pf.get("languages", []):
        add(l["name"], "language")
    return vocab


def item_text(table, row):
    parts = [str(v) for k, v in row.items() if k not in ("id", "profile_id") and v]
    return " ".join(parts).lower()


def _contains(text, term):
    term = norm(term)
    if not term:
        return False
    return re.search(r"(?<![\w+#.])" + re.escape(term) + r"(?![\w+#])", text) is not None


# ---------------------------------------------------------------- JD analysis
def analyze_jd(jd):
    if enabled():
        prompt = f"""Analyse this job description. Return JSON with keys:
"role_title" (string), "required_skills" (array of short skill/tool names), "preferred_skills" (array),
"qualifications" (array of degree/experience requirements), "responsibilities" (array of short phrases),
"keywords" (array of important ATS keywords). Use only terms present in the text. Skill names must be concise (1-3 words).

JOB DESCRIPTION:
{jd}"""
        out = _call(prompt)
        res = {k: out.get(k) or ([] if k != "role_title" else "") for k in
               ("role_title", "required_skills", "preferred_skills", "qualifications", "responsibilities", "keywords")}
        res["source"] = "gemini"
        # guard: keep only skills/keywords that are literally grounded in the JD text
        low = jd.lower()
        for k in ("required_skills", "preferred_skills", "keywords"):
            res[k] = [x for x in dict.fromkeys(map(str, res[k])) if _contains(low, x) or norm(x) in low]
        return res
    return _fallback_jd(jd)


def _fallback_jd(jd):
    low = jd.lower()
    known = set(ALIASES.values()) | set(KNOWN_TECH)
    found = [t for t in sorted(known) if _contains(low, t)]
    for a, canon in ALIASES.items():
        if canon not in found and _contains(low, a):
            found.append(canon)
    pref_idx = min([m.start() for m in re.finditer(r"nice to have|preferred|plus|bonus", low)] or [len(low)])
    req = [t for t in found if (low.find(t) if low.find(t) >= 0 else 0) < pref_idx]
    pref = [t for t in found if t not in req]
    title = next((l.strip() for l in jd.splitlines() if l.strip()), "")[:80]
    return {"role_title": title, "required_skills": req, "preferred_skills": pref, "qualifications":
            re.findall(r"[^.\n]*(?:degree|bachelor|master|\d\+? years)[^.\n]*", jd, re.I)[:5],
            "responsibilities": [], "keywords": found, "source": "fallback-keywords"}


KNOWN_TECH = """python java javascript typescript c++ c# go rust sql nosql mysql postgresql mongodb redis sqlite
html css react angular vue node.js express flask django fastapi spring rest api graphql docker kubernetes aws azure
google cloud git github linux ci/cd jenkins terraform machine learning deep learning tensorflow pytorch scikit-learn
pandas numpy nlp natural language processing computer vision llm data analysis data visualization tableau power bi
excel spark hadoop kafka airflow etl agile scrum communication leadership teamwork problem solving""".split("\n")
KNOWN_TECH = [t for line in KNOWN_TECH for t in re.findall(r"[a-z+#./]+(?: (?:learning|cloud|vision|analysis|visualization|bi|language processing|solving|api))?", line)]
KNOWN_TECH = [t.strip() for t in KNOWN_TECH if t.strip() and t.strip() not in STOP]


# ---------------------------------------------------------------- matching (deterministic)
def match_portfolio(pf, analysis):
    """Compare JD requirements to the portfolio. Returns matched/missing requirements and a
    relevance score for every portfolio item. Pure function of stored data -> cannot invent anything."""
    req = list(dict.fromkeys(map(norm, analysis.get("required_skills", []))))
    pref = [p for p in dict.fromkeys(map(norm, analysis.get("preferred_skills", []))) if p not in req]
    kws = [k for k in dict.fromkeys(map(norm, analysis.get("keywords", []))) if k not in req and k not in pref]
    vocab = vocabulary(pf)
    corpus = {t: [(r, item_text(t, r)) for r in pf.get(t, [])] for t in
              ("projects", "experience", "certifications", "achievements", "publications", "education")}
    def evidence(term):
        ev = []
        for t, lst in corpus.items():
            for r, txt in lst:
                if _contains(txt, term):
                    ev.append({"table": t, "id": r["id"], "label": r.get("title") or r.get("name") or r.get("company") or r.get("degree")})
        return ev
    matched, missing = [], []
    for term, level in [(t, "required") for t in req] + [(t, "preferred") for t in pref] + [(t, "keyword") for t in kws]:
        in_skills = term in vocab
        ev = evidence(term)
        if in_skills or ev:
            matched.append({"term": term, "level": level, "in_skills": in_skills, "evidence": ev})
        else:
            missing.append({"term": term, "level": level})
    weight = {"required": 3, "preferred": 2, "keyword": 1}
    scores = {t: {} for t in ("skills", "projects", "experience", "certifications", "achievements", "publications", "education", "languages")}
    terms = [(t, weight["required"]) for t in req] + [(t, weight["preferred"]) for t in pref] + [(t, weight["keyword"]) for t in kws]
    for t in scores:
        for r in pf.get(t, []):
            txt = item_text(t, r)
            if t == "skills":
                txt = norm(r["name"])
                s = sum(w for term, w in terms if term == txt)
            else:
                s = sum(w for term, w in terms if _contains(txt, term))
            scores[t][r["id"]] = s
    total = sum(w for _, w in terms) or 1
    got = sum(weight[m["level"]] for m in matched)
    return {"matched": matched, "missing": missing, "scores": scores, "match_pct": round(100 * got / total)}


def suggest_selection(pf, match, limits=None):
    """Default selection: items with score>0 (top-N for projects/experience), always education + languages."""
    limits = limits or {"projects": 3, "experience": 4, "certifications": 4, "achievements": 3, "publications": 2}
    sel = {}
    for t in ("skills", "projects", "experience", "certifications", "achievements", "publications", "education", "languages"):
        ranked = sorted(pf.get(t, []), key=lambda r: -match["scores"][t].get(r["id"], 0))
        if t in ("education", "languages"):
            sel[t] = [r["id"] for r in pf.get(t, [])]
        elif t == "skills":
            sel[t] = [r["id"] for r in ranked if match["scores"][t].get(r["id"], 0) > 0] or [r["id"] for r in ranked[:8]]
        else:
            n = limits.get(t, 3)
            top = [r for r in ranked if match["scores"][t].get(r["id"], 0) > 0][:n]
            if not top and t in ("projects", "experience"):
                top = ranked[:min(n, 2)]
            sel[t] = [r["id"] for r in top]
    return sel


# ---------------------------------------------------------------- AI advice + summary (verified)
def _portfolio_for_prompt(pf):
    slim = {"profile": {k: pf["profile"].get(k) for k in ("full_name", "headline", "summary")}}
    for t in ("skills", "projects", "experience", "certifications", "achievements", "education"):
        slim[t] = [{k: v for k, v in r.items() if k not in ("profile_id",) and v} for r in pf.get(t, [])]
    return json.dumps(slim, ensure_ascii=False)


def advise(pf, analysis, match):
    """Ask Gemini for a tailored summary + improvement tips, then verify both."""
    vocab = vocabulary(pf)
    if not enabled():
        return _fallback_advice(pf, analysis, match)
    prompt = f"""You help tailor a resume. You may ONLY use facts that appear in PORTFOLIO below.
Never invent skills, tools, employers, degrees, certifications, numbers or achievements.
Return JSON: {{"summary": "2-3 sentence professional summary tailored to the job, first person omitted",
"suggestions": ["short actionable resume improvement tips; for JD skills missing from the portfolio say they are gaps to learn or add ONLY if truly held"]}}

JOB TARGET: {analysis.get('role_title')}
JD REQUIRED SKILLS: {analysis.get('required_skills')}
JD PREFERRED SKILLS: {analysis.get('preferred_skills')}
SKILLS MISSING FROM PORTFOLIO: {[m['term'] for m in match['missing']]}

PORTFOLIO:
{_portfolio_for_prompt(pf)}"""
    out = _call(prompt, temperature=0.3)
    summary = (out.get("summary") or "").strip()
    ok, bad = verify_text(summary, pf, analysis)
    notes = []
    if not ok:
        notes.append(f"AI summary mentioned terms not in your portfolio ({', '.join(bad)}); replaced with a grounded summary.")
        summary = _grounded_summary(pf, match)
    return {"summary": summary, "suggestions": [str(s) for s in (out.get("suggestions") or [])][:8],
            "verification_notes": notes, "source": "gemini"}


def verify_text(text, pf, analysis):
    """A text is acceptable only if every JD skill/keyword it mentions exists in the portfolio vocabulary
    or in the text of a portfolio item. Returns (ok, offending_terms)."""
    vocab = vocabulary(pf)
    alltext = " ".join(item_text(t, r) for t in ("projects", "experience", "achievements", "education", "certifications") for r in pf.get(t, []))
    alltext += " " + (pf["profile"].get("summary") or "").lower() + " " + (pf["profile"].get("headline") or "").lower()
    low = text.lower()
    bad = []
    candidates = set(map(norm, analysis.get("required_skills", []) + analysis.get("preferred_skills", []) + analysis.get("keywords", [])))
    candidates |= set(KNOWN_TECH)
    for term in sorted(candidates):
        if len(term) < 2 or term in STOP:
            continue
        if _contains(low, term) and term not in vocab and not _contains(alltext, term):
            bad.append(term)
    return (not bad), bad


def _grounded_summary(pf, match):
    p = pf["profile"]
    base = (p.get("summary") or "").strip()
    display = {norm(s["name"]): s["name"] for s in pf.get("skills", [])}
    hits = [display.get(m["term"], m["term"]) for m in match["matched"] if m["in_skills"]][:6]
    if hits:
        return (base + " " if base else "") + "Relevant strengths for this role: " + ", ".join(hits) + "."
    return base


def _fallback_advice(pf, analysis, match):
    sug = []
    miss_req = [m["term"] for m in match["missing"] if m["level"] == "required"]
    if miss_req:
        sug.append("JD requires skills not found in your portfolio: " + ", ".join(miss_req) +
                   ". Add them only if you genuinely have them; otherwise consider them learning goals.")
    unevidenced = [m["term"] for m in match["matched"] if m["in_skills"] and not m["evidence"]]
    if unevidenced:
        sug.append("These skills are listed but not backed by a project or experience entry: " + ", ".join(unevidenced[:6]) + ". Mention them in a project description.")
    if not (pf["profile"].get("summary") or "").strip():
        sug.append("Add a base professional summary to your profile.")
    sug.append("Gemini is not configured; suggestions come from keyword matching only.")
    return {"summary": _grounded_summary(pf, match), "suggestions": sug, "verification_notes": [], "source": "fallback-keywords"}


# ---------------------------------------------------------------- unstructured -> structured
def organize(raw_text):
    """Turn free text (old CV, notes) into structured records. Returns records to REVIEW, not saved.
    Each record gets `grounded: bool` = its key field literally appears in the source text."""
    if not enabled():
        raise GeminiError("Gemini API key required to organise unstructured text")
    from db import TABLES
    spec = {t: f for t, f in TABLES.items()}
    prompt = f"""Extract portfolio information from the text into JSON. Use ONLY information stated in the text; leave
fields as empty strings if not stated. Never guess. Keys: "profile" (object with {PROFILE_KEYS}),
and arrays for each table with these fields: {json.dumps(spec)}.
"skills[].category" must be one of Technical, Soft, Tool, Domain. Dates as written in the text.

TEXT:
{raw_text}"""
    out = _call(prompt, temperature=0.0)
    low = raw_text.lower()
    result = {"profile": out.get("profile") or {}}
    from db import REQUIRED
    for t in spec:
        recs = []
        for r in (out.get(t) or []):
            if not isinstance(r, dict):
                continue
            key = str(r.get(REQUIRED[t]) or "").strip()
            if not key:
                continue
            r = {f: ("" if r.get(f) is None else str(r.get(f))) for f in spec[t]}
            r["grounded"] = key.lower() in low or all(w in low for w in key.lower().split()[:3])
            recs.append(r)
        result[t] = recs
    return result


PROFILE_KEYS = "full_name, headline, email, phone, location, linkedin, github, website, summary"
