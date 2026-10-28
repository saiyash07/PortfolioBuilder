"""Build a resume from portfolio + selection, and render it as HTML (preview), PDF and DOCX.
Only rows that exist in the portfolio can appear: selection holds ids, text is copied from rows."""
import html
import io

from db import split_tech

SECTION_ORDER = ["experience", "projects", "education", "skills", "certifications", "achievements", "publications", "languages"]


def build(pf, sel, jd_terms=None):
    """sel = {summary, <table>: [ids], skill_order optional}. Unknown ids are dropped silently."""
    jd = {t.lower() for t in (jd_terms or [])}
    def pick(t):
        by = {r["id"]: r for r in pf.get(t, [])}
        return [by[i] for i in sel.get(t, []) if i in by]
    p = pf["profile"]
    skills = pick("skills")
    groups = {}
    for s in skills:
        groups.setdefault(s["category"] or "Technical", []).append(s["name"])
    for g in groups.values():  # JD-relevant skills first
        g.sort(key=lambda n: (n.lower() not in jd, n.lower()))
    return {
        "name": p.get("full_name", ""), "headline": p.get("headline", ""),
        "contact": [x for x in (p.get("email"), p.get("phone"), p.get("location"), p.get("linkedin"), p.get("github"), p.get("website")) if x],
        "summary": (sel.get("summary") if sel.get("summary") is not None else p.get("summary")) or "",
        "experience": pick("experience"), "projects": pick("projects"), "education": pick("education"),
        "skill_groups": groups, "certifications": pick("certifications"), "achievements": pick("achievements"),
        "publications": pick("publications"), "languages": pick("languages"),
        "highlight": jd,
    }


def _bullets(text):
    lines = [l.strip(" -•\t") for l in (text or "").splitlines() if l.strip()]
    return lines


def _dates(a, b):
    a, b = (a or "").strip(), (b or "").strip()
    return f"{a} – {b}" if a and b else (a or b)


def _entries(r):
    """Yield normalised (heading, subheading, dates, bullets, tech) tuples for each section."""
    out = {}
    out["experience"] = [(f"{x['role']} — {x['company']}", ", ".join(v for v in (x.get("kind"), x.get("location")) if v),
                          _dates(x.get("start_date"), x.get("end_date")), _bullets(x.get("description")), ", ".join(split_tech(x.get("technologies")))) for x in r["experience"]]
    out["projects"] = [(x["title"], x.get("url") or "", _dates(x.get("start_date"), x.get("end_date")), _bullets(x.get("description")),
                        ", ".join(split_tech(x.get("technologies")))) for x in r["projects"]]
    out["education"] = [(f"{x['degree']}{', ' + x['field'] if x.get('field') else ''}", x["institution"], _dates(x.get("start_year"), x.get("end_year")),
                         _bullets(("Grade: " + x["grade"] if x.get("grade") else "") + ("\n" + x["details"] if x.get("details") else "")), "") for x in r["education"]]
    out["certifications"] = [(x["name"], x.get("issuer") or "", x.get("issue_date") or "", _bullets(x.get("details")), "") for x in r["certifications"]]
    out["achievements"] = [(x["title"], x.get("issuer") or "", x.get("date") or "", _bullets(x.get("description")), "") for x in r["achievements"]]
    out["publications"] = [(x["title"], x.get("venue") or "", x.get("date") or "", _bullets(x.get("description")), "") for x in r["publications"]]
    return out


TITLES = {"experience": "Experience", "projects": "Projects", "education": "Education", "skills": "Skills",
          "certifications": "Certifications", "achievements": "Achievements & Awards",
          "publications": "Publications & Research", "languages": "Languages"}


def _languages(r):
    return ", ".join(f"{l['name']}{' (' + l['proficiency'] + ')' if l.get('proficiency') else ''}" for l in r["languages"])


# ------------------------------------------------------------------ HTML preview
CSS = """.resume{font-family:Georgia,'Times New Roman',serif;color:#111;line-height:1.35;font-size:13px}
.resume h1{font-size:26px;margin:0;letter-spacing:.5px}.resume .head{color:#333;font-size:14px;margin:2px 0}
.resume .contact{color:#444;font-size:12px;margin-bottom:8px}.resume h2{font-size:13px;text-transform:uppercase;letter-spacing:1.2px;
border-bottom:1.5px solid #222;margin:14px 0 6px;padding-bottom:2px}.resume .row{display:flex;justify-content:space-between;gap:12px}
.resume .t{font-weight:bold}.resume .s{color:#444;font-style:italic}.resume .d{color:#444;white-space:nowrap}
.resume ul{margin:3px 0 8px 18px;padding:0}.resume .tech{font-size:12px;color:#333}.resume mark{background:#fff3a8;padding:0 1px}"""


def render_html(r, fragment=False):
    esc = html.escape
    hi = r["highlight"]
    def mk(text):
        out = esc(text)
        return out
    h = [f'<div class="resume"><h1>{esc(r["name"])}</h1>']
    if r["headline"]:
        h.append(f'<div class="head">{esc(r["headline"])}</div>')
    h.append(f'<div class="contact">{" &nbsp;|&nbsp; ".join(esc(c) for c in r["contact"])}</div>')
    if r["summary"]:
        h.append(f'<h2>Professional Summary</h2><p>{esc(r["summary"])}</p>')
    ents = _entries(r)
    for sec in SECTION_ORDER:
        if sec == "skills":
            if r["skill_groups"]:
                h.append("<h2>Skills</h2>")
                for g, names in r["skill_groups"].items():
                    items = ", ".join(f"<mark>{esc(n)}</mark>" if n.lower() in hi else esc(n) for n in names)
                    h.append(f'<div><b>{esc(g)}:</b> {items}</div>')
        elif sec == "languages":
            if r["languages"]:
                h.append(f'<h2>Languages</h2><div>{esc(_languages(r))}</div>')
        elif ents[sec]:
            h.append(f"<h2>{TITLES[sec]}</h2>")
            for head, sub, dates, bullets, tech in ents[sec]:
                h.append(f'<div class="row"><div><span class="t">{esc(head)}</span>{" — <span class=s>" + esc(sub) + "</span>" if sub else ""}</div><div class="d">{esc(dates)}</div></div>')
                if bullets:
                    h.append("<ul>" + "".join(f"<li>{esc(b)}</li>" for b in bullets) + "</ul>")
                if tech:
                    h.append(f'<div class="tech"><b>Tech:</b> {esc(tech)}</div>')
    h.append("</div>")
    body = "".join(h)
    return body if fragment else f"<!doctype html><meta charset=utf-8><style>{CSS}</style><body style='margin:24px'>{body}"


# ------------------------------------------------------------------ PDF
def render_pdf(r):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import HRFlowable, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    esc = html.escape
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm, topMargin=14 * mm, bottomMargin=14 * mm,
                            title=f"{r['name']} - Resume", author=r["name"])
    base = ParagraphStyle("b", fontName="Helvetica", fontSize=9.5, leading=12.5)
    st = {
        "name": ParagraphStyle("n", parent=base, fontName="Helvetica-Bold", fontSize=20, leading=24),
        "head": ParagraphStyle("h", parent=base, fontSize=11, textColor=colors.HexColor("#333333")),
        "contact": ParagraphStyle("c", parent=base, fontSize=8.5, textColor=colors.HexColor("#444444")),
        "h2": ParagraphStyle("h2", parent=base, fontName="Helvetica-Bold", fontSize=10, spaceBefore=9, spaceAfter=1),
        "t": ParagraphStyle("t", parent=base, fontName="Helvetica-Bold"),
        "d": ParagraphStyle("d", parent=base, alignment=2, textColor=colors.HexColor("#444444"), fontSize=9),
        "li": ParagraphStyle("li", parent=base, leftIndent=11, bulletIndent=2),
        "tech": ParagraphStyle("tech", parent=base, fontSize=8.8, textColor=colors.HexColor("#333333"), spaceAfter=4),
    }
    f = [Paragraph(esc(r["name"]), st["name"])]
    if r["headline"]:
        f.append(Paragraph(esc(r["headline"]), st["head"]))
    f.append(Paragraph(" | ".join(esc(c) for c in r["contact"]), st["contact"]))
    def h2(title):
        return [Paragraph(title.upper(), st["h2"]), HRFlowable(width="100%", thickness=0.8, color=colors.black, spaceAfter=3)]
    if r["summary"]:
        f += h2("Professional Summary") + [Paragraph(esc(r["summary"]), base)]
    ents = _entries(r)
    for sec in SECTION_ORDER:
        if sec == "skills" and r["skill_groups"]:
            f += h2("Skills")
            for g, names in r["skill_groups"].items():
                f.append(Paragraph(f"<b>{esc(g)}:</b> {esc(', '.join(names))}", base))
        elif sec == "languages" and r["languages"]:
            f += h2("Languages") + [Paragraph(esc(_languages(r)), base)]
        elif sec not in ("skills", "languages") and ents[sec]:
            f += h2(TITLES[sec])
            for head, sub, dates, bullets, tech in ents[sec]:
                line = f"<b>{esc(head)}</b>" + (f" — <i>{esc(sub)}</i>" if sub else "")
                row = Table([[Paragraph(line, base), Paragraph(esc(dates), st["d"])]], colWidths=[None, 38 * mm])
                row.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                                         ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
                block = [row] + [Paragraph(esc(b), st["li"], bulletText="•") for b in bullets]
                if tech:
                    block.append(Paragraph(f"<b>Tech:</b> {esc(tech)}", st["tech"]))
                else:
                    block.append(Spacer(1, 3))
                f.append(KeepTogether(block))
    doc.build(f)
    return buf.getvalue()


# ------------------------------------------------------------------ DOCX
def render_docx(r):
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Mm, Pt
    d = Document()
    for s in d.sections:
        s.left_margin = s.right_margin = Mm(16)
        s.top_margin = s.bottom_margin = Mm(14)
    d.styles["Normal"].font.name = "Calibri"
    d.styles["Normal"].font.size = Pt(10)
    def para(text="", bold=False, size=None, italic=False, align=None, space_after=2):
        p = d.add_paragraph()
        run = p.add_run(text)
        run.bold, run.italic = bold, italic
        if size:
            run.font.size = Pt(size)
        p.paragraph_format.space_after = Pt(space_after)
        p.paragraph_format.space_before = Pt(0)
        if align:
            p.alignment = align
        return p
    para(r["name"], bold=True, size=20, space_after=0)
    if r["headline"]:
        para(r["headline"], size=11, space_after=0)
    para(" | ".join(r["contact"]), size=9, space_after=4)
    def h2(title):
        p = para(title.upper(), bold=True, size=10.5, space_after=2)
        p.paragraph_format.space_before = Pt(8)
        from docx.oxml import OxmlElement
        from docx.oxml.ns import qn
        pPr = p._p.get_or_add_pPr()
        b = OxmlElement("w:pBdr")
        bt = OxmlElement("w:bottom")
        for k, v in (("w:val", "single"), ("w:sz", "6"), ("w:space", "1"), ("w:color", "000000")):
            bt.set(qn(k), v)
        b.append(bt)
        pPr.append(b)
    if r["summary"]:
        h2("Professional Summary")
        para(r["summary"])
    ents = _entries(r)
    for sec in SECTION_ORDER:
        if sec == "skills" and r["skill_groups"]:
            h2("Skills")
            for g, names in r["skill_groups"].items():
                p = d.add_paragraph()
                p.paragraph_format.space_after = Pt(1)
                p.add_run(f"{g}: ").bold = True
                p.add_run(", ".join(names))
        elif sec == "languages" and r["languages"]:
            h2("Languages")
            para(_languages(r))
        elif sec not in ("skills", "languages") and ents[sec]:
            h2(TITLES[sec])
            for head, sub, dates, bullets, tech in ents[sec]:
                p = d.add_paragraph()
                p.paragraph_format.space_after = Pt(0)
                p.paragraph_format.space_before = Pt(3)
                p.add_run(head).bold = True
                if sub:
                    p.add_run(f" — {sub}").italic = True
                if dates:
                    p.add_run(f"   ({dates})")
                for b in bullets:
                    bp = d.add_paragraph(b, style="List Bullet")
                    bp.paragraph_format.space_after = Pt(0)
                if tech:
                    tp = d.add_paragraph()
                    tp.add_run("Tech: ").bold = True
                    tp.add_run(tech)
                    tp.paragraph_format.space_after = Pt(3)
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()
