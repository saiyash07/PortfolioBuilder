-- Portfolio database schema (SQLite). Every category table references profile(id).
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS profile (
  id INTEGER PRIMARY KEY,
  full_name TEXT NOT NULL, headline TEXT, email TEXT, phone TEXT, location TEXT,
  linkedin TEXT, github TEXT, website TEXT,
  summary TEXT                       -- career objective / professional summary (base version)
);
CREATE TABLE IF NOT EXISTS education (
  id INTEGER PRIMARY KEY, profile_id INTEGER NOT NULL REFERENCES profile(id) ON DELETE CASCADE,
  institution TEXT NOT NULL, degree TEXT NOT NULL, field TEXT, start_year TEXT, end_year TEXT,
  grade TEXT, details TEXT
);
CREATE TABLE IF NOT EXISTS skills (
  id INTEGER PRIMARY KEY, profile_id INTEGER NOT NULL REFERENCES profile(id) ON DELETE CASCADE,
  name TEXT NOT NULL, category TEXT NOT NULL DEFAULT 'Technical',  -- Technical | Soft | Tool | Domain
  proficiency TEXT, UNIQUE(profile_id, name)
);
CREATE TABLE IF NOT EXISTS certifications (
  id INTEGER PRIMARY KEY, profile_id INTEGER NOT NULL REFERENCES profile(id) ON DELETE CASCADE,
  name TEXT NOT NULL, issuer TEXT, issue_date TEXT, credential_url TEXT, details TEXT
);
CREATE TABLE IF NOT EXISTS projects (
  id INTEGER PRIMARY KEY, profile_id INTEGER NOT NULL REFERENCES profile(id) ON DELETE CASCADE,
  title TEXT NOT NULL, description TEXT, technologies TEXT, url TEXT, start_date TEXT, end_date TEXT
);
CREATE TABLE IF NOT EXISTS experience (
  id INTEGER PRIMARY KEY, profile_id INTEGER NOT NULL REFERENCES profile(id) ON DELETE CASCADE,
  company TEXT NOT NULL, role TEXT NOT NULL, kind TEXT DEFAULT 'Internship',  -- Internship | Full-time | ...
  location TEXT, start_date TEXT, end_date TEXT, description TEXT, technologies TEXT
);
CREATE TABLE IF NOT EXISTS achievements (
  id INTEGER PRIMARY KEY, profile_id INTEGER NOT NULL REFERENCES profile(id) ON DELETE CASCADE,
  title TEXT NOT NULL, issuer TEXT, date TEXT, description TEXT
);
CREATE TABLE IF NOT EXISTS publications (
  id INTEGER PRIMARY KEY, profile_id INTEGER NOT NULL REFERENCES profile(id) ON DELETE CASCADE,
  title TEXT NOT NULL, venue TEXT, date TEXT, url TEXT, description TEXT
);
CREATE TABLE IF NOT EXISTS languages (
  id INTEGER PRIMARY KEY, profile_id INTEGER NOT NULL REFERENCES profile(id) ON DELETE CASCADE,
  name TEXT NOT NULL, proficiency TEXT
);
-- Many-to-many: which skills a project / experience entry used (derived from `technologies`).
CREATE TABLE IF NOT EXISTS item_skills (
  item_type TEXT NOT NULL CHECK (item_type IN ('projects','experience')),
  item_id INTEGER NOT NULL,
  skill_id INTEGER NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
  PRIMARY KEY (item_type, item_id, skill_id)
);
-- Saved resume configurations (a target JD + the user's selections).
CREATE TABLE IF NOT EXISTS resume_configs (
  id INTEGER PRIMARY KEY, profile_id INTEGER NOT NULL REFERENCES profile(id) ON DELETE CASCADE,
  name TEXT NOT NULL, job_description TEXT, selection_json TEXT NOT NULL,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
