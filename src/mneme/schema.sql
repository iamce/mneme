PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS domains (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  sort_order INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS captures (
  id TEXT PRIMARY KEY,
  created_at TEXT NOT NULL,
  source TEXT NOT NULL,
  modality TEXT NOT NULL,
  raw_text TEXT NOT NULL,
  attachment_path TEXT,
  metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS capture_domains (
  capture_id TEXT NOT NULL REFERENCES captures(id) ON DELETE CASCADE,
  domain_id TEXT NOT NULL REFERENCES domains(id),
  assigned_by TEXT NOT NULL CHECK (assigned_by IN ('user','agent')),
  confidence REAL NOT NULL DEFAULT 1.0 CHECK (confidence >= 0 AND confidence <= 1),
  PRIMARY KEY (capture_id, domain_id, assigned_by)
);

CREATE TABLE IF NOT EXISTS threads (
  id TEXT PRIMARY KEY,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  title TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('workstream','obligation','concern','relationship','decision','idea')),
  status TEXT NOT NULL CHECK (status IN ('open','dormant','closed')),
  canonical_summary TEXT NOT NULL DEFAULT '',
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  salience REAL NOT NULL DEFAULT 0.5 CHECK (salience >= 0 AND salience <= 1),
  confidence REAL NOT NULL DEFAULT 0.5 CHECK (confidence >= 0 AND confidence <= 1),
  metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS thread_domains (
  thread_id TEXT NOT NULL REFERENCES threads(id) ON DELETE CASCADE,
  domain_id TEXT NOT NULL REFERENCES domains(id),
  weight REAL NOT NULL DEFAULT 1.0 CHECK (weight >= 0),
  is_primary INTEGER NOT NULL DEFAULT 0 CHECK (is_primary IN (0,1)),
  PRIMARY KEY (thread_id, domain_id)
);

CREATE TABLE IF NOT EXISTS thread_states (
  id TEXT PRIMARY KEY,
  thread_id TEXT NOT NULL REFERENCES threads(id) ON DELETE CASCADE,
  observed_at TEXT NOT NULL,
  attention TEXT NOT NULL CHECK (attention IN ('active','background','dormant')),
  pressure TEXT NOT NULL CHECK (pressure IN ('low','medium','high','acute')),
  posture TEXT NOT NULL CHECK (posture IN ('clear','unclear','avoided','blocked','waiting','decided')),
  momentum TEXT NOT NULL CHECK (momentum IN ('drifting','stable','progressing')),
  affect TEXT NOT NULL CHECK (affect IN ('draining','neutral','energizing')),
  horizon TEXT NOT NULL CHECK (horizon IN ('now','soon','later')),
  confidence REAL NOT NULL DEFAULT 0.5 CHECK (confidence >= 0 AND confidence <= 1),
  is_current INTEGER NOT NULL DEFAULT 1 CHECK (is_current IN (0,1))
);

CREATE TABLE IF NOT EXISTS evidence_links (
  id TEXT PRIMARY KEY,
  subject_type TEXT NOT NULL CHECK (subject_type IN ('thread','thread_state','artifact')),
  subject_id TEXT NOT NULL,
  capture_id TEXT NOT NULL REFERENCES captures(id) ON DELETE CASCADE,
  relation TEXT NOT NULL CHECK (relation IN ('supports','mentions','contradicts','updates')),
  confidence REAL NOT NULL DEFAULT 0.5 CHECK (confidence >= 0 AND confidence <= 1),
  note TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS artifacts (
  id TEXT PRIMARY KEY,
  created_at TEXT NOT NULL,
  artifact_type TEXT NOT NULL CHECK (artifact_type IN ('extraction','summary','daily_review','weekly_review','chat_turn')),
  target_type TEXT NOT NULL CHECK (target_type IN ('capture','thread','system')),
  target_id TEXT,
  model TEXT NOT NULL,
  content_json TEXT NOT NULL DEFAULT '{}',
  text_output TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_captures_created_at ON captures(created_at);
CREATE INDEX IF NOT EXISTS idx_threads_status ON threads(status);
CREATE INDEX IF NOT EXISTS idx_thread_states_thread_current ON thread_states(thread_id, is_current);
CREATE INDEX IF NOT EXISTS idx_evidence_subject ON evidence_links(subject_type, subject_id);
