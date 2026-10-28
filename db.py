"""SQLite storage layer: schema, generic CRUD for category tables, portfolio loading."""
import json
import os
import sqlite3

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("PORTFOLIO_DB", os.path.join(BASE, "portfolio.db"))

# Editable fields per category table (id / profile_id are managed here).
TABLES = {
    "education": ["institution", "degree", "field", "start_year", "end_year", "grade", "details"],
    "skills": ["name", "category", "proficiency"],
    "certifications": ["name", "issuer", "issue_date", "credential_url", "details"],
    "projects": ["title", "description", "technologies", "url", "start_date", "end_date"],
    "experience": ["company", "role", "kind", "location", "start_date", "end_date", "description", "technologies"],
    "achievements": ["title", "issuer", "date", "description"],
    "publications": ["title", "venue", "date", "url", "description"],
    "languages": ["name", "proficiency"],
}
PROFILE_FIELDS = ["full_name", "headline", "email", "phone", "location", "linkedin", "github", "website", "summary"]
REQUIRED = {  # first field is required for every table
    t: f[0] for t, f in TABLES.items()
}
REQUIRED["experience"] = "company"


def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    with connect() as c, open(os.path.join(BASE, "schema.sql")) as f:
        c.executescript(f.read())


def _rows(conn, sql, args=()):
    return [dict(r) for r in conn.execute(sql, args)]


def get_profile_id(conn):
    row = conn.execute("SELECT id FROM profile ORDER BY id LIMIT 1").fetchone()
    return row["id"] if row else None


def load_portfolio(conn=None):
    """Return the whole portfolio as one dict (profile + every category list)."""
    own = conn is None
    conn = conn or connect()
    try:
        p = conn.execute("SELECT * FROM profile ORDER BY id LIMIT 1").fetchone()
        if not p:
            return {"profile": {}, **{t: [] for t in TABLES}}
        data = {"profile": dict(p)}
        for t in TABLES:
            order = "id"
            data[t] = _rows(conn, f"SELECT * FROM {t} WHERE profile_id=? ORDER BY {order}", (p["id"],))
        return data
    finally:
        if own:
            conn.close()


def save_profile(values):
    clean = {k: (values.get(k) or "").strip() for k in PROFILE_FIELDS}
    if not clean["full_name"]:
        raise ValueError("full_name is required")
    with connect() as c:
        pid = get_profile_id(c)
        if pid is None:
            cols = ",".join(PROFILE_FIELDS)
            c.execute(f"INSERT INTO profile ({cols}) VALUES ({','.join('?' * len(PROFILE_FIELDS))})",
                      [clean[k] for k in PROFILE_FIELDS])
        else:
            sets = ",".join(f"{k}=?" for k in PROFILE_FIELDS)
            c.execute(f"UPDATE profile SET {sets} WHERE id=?", [clean[k] for k in PROFILE_FIELDS] + [pid])


def _clean(table, values):
    out = {k: ("" if values.get(k) is None else str(values.get(k)).strip()) for k in TABLES[table]}
    if not out[REQUIRED[table]]:
        raise ValueError(f"'{REQUIRED[table]}' is required for {table}")
    return out


def add_item(table, values):
    _check(table)
    vals = _clean(table, values)
    with connect() as c:
        pid = get_profile_id(c)
        if pid is None:
            raise ValueError("Create the profile first")
        cols = ["profile_id"] + TABLES[table]
        cur = c.execute(f"INSERT INTO {table} ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                        [pid] + [vals[k] for k in TABLES[table]])
        _relink(c, table, cur.lastrowid)
        return cur.lastrowid


def update_item(table, item_id, values):
    _check(table)
    vals = _clean(table, values)
    with connect() as c:
        sets = ",".join(f"{k}=?" for k in TABLES[table])
        cur = c.execute(f"UPDATE {table} SET {sets} WHERE id=?", [vals[k] for k in TABLES[table]] + [item_id])
        if cur.rowcount == 0:
            raise KeyError(f"{table} {item_id} not found")
        _relink(c, table, item_id)
        if table == "skills":  # a renamed/added skill may change links elsewhere
            relink_all(c)


def delete_item(table, item_id):
    _check(table)
    with connect() as c:
        cur = c.execute(f"DELETE FROM {table} WHERE id=?", (item_id,))
        if cur.rowcount == 0:
            raise KeyError(f"{table} {item_id} not found")
        if table in ("projects", "experience"):
            c.execute("DELETE FROM item_skills WHERE item_type=? AND item_id=?", (table, item_id))


def _check(table):
    if table not in TABLES:
        raise KeyError(f"unknown table {table}")


def split_tech(text):
    return [t.strip() for t in (text or "").replace(";", ",").split(",") if t.strip()]


def _relink(conn, table, item_id):
    """Rebuild item_skills for a project/experience row from its `technologies` text.
    Only links to skills that already exist in the portfolio; nothing is invented."""
    if table == "skills":
        return
    if table not in ("projects", "experience"):
        return
    row = conn.execute(f"SELECT profile_id, technologies FROM {table} WHERE id=?", (item_id,)).fetchone()
    conn.execute("DELETE FROM item_skills WHERE item_type=? AND item_id=?", (table, item_id))
    if not row:
        return
    names = {t.lower() for t in split_tech(row["technologies"])}
    for s in conn.execute("SELECT id, name FROM skills WHERE profile_id=?", (row["profile_id"],)):
        if s["name"].lower() in names:
            conn.execute("INSERT OR IGNORE INTO item_skills VALUES (?,?,?)", (table, item_id, s["id"]))


def relink_all(conn):
    for t in ("projects", "experience"):
        for r in conn.execute(f"SELECT id FROM {t}").fetchall():
            _relink(conn, t, r["id"])


def replace_portfolio(data):
    """Replace every portfolio row with `data` (used by seeding and by Sheet -> DB pull)."""
    with connect() as c:
        c.execute("DELETE FROM profile")  # cascades to children
        p = {k: (data.get("profile", {}).get(k) or "") for k in PROFILE_FIELDS}
        if not p["full_name"]:
            raise ValueError("profile.full_name missing")
        cur = c.execute(f"INSERT INTO profile ({','.join(PROFILE_FIELDS)}) VALUES ({','.join('?' * len(PROFILE_FIELDS))})",
                        [p[k] for k in PROFILE_FIELDS])
        pid = cur.lastrowid
        for t, fields in TABLES.items():
            for row in data.get(t, []):
                vals = [("" if row.get(f) is None else str(row.get(f))) for f in fields]
                if not vals[0].strip() and not (t == "experience" and row.get("company")):
                    continue
                c.execute(f"INSERT INTO {t} (profile_id,{','.join(fields)}) VALUES (?,{','.join('?' * len(fields))})",
                          [pid] + vals)
        relink_all(c)


# ---- saved resume configs ----
def save_config(name, jd, selection, config_id=None):
    with connect() as c:
        pid = get_profile_id(c)
        blob = json.dumps(selection)
        if config_id:
            c.execute("UPDATE resume_configs SET name=?, job_description=?, selection_json=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                      (name, jd, blob, config_id))
            return config_id
        return c.execute("INSERT INTO resume_configs (profile_id,name,job_description,selection_json) VALUES (?,?,?,?)",
                         (pid, name, jd, blob)).lastrowid


def list_configs():
    with connect() as c:
        return _rows(c, "SELECT id,name,updated_at FROM resume_configs ORDER BY updated_at DESC, id DESC")


def get_config(config_id):
    with connect() as c:
        r = c.execute("SELECT * FROM resume_configs WHERE id=?", (config_id,)).fetchone()
        if not r:
            raise KeyError("config not found")
        d = dict(r)
        d["selection"] = json.loads(d.pop("selection_json"))
        return d


def delete_config(config_id):
    with connect() as c:
        c.execute("DELETE FROM resume_configs WHERE id=?", (config_id,))
