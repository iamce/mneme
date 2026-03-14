from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from importlib import resources


DEFAULT_DOMAINS = (
    "Work",
    "Money",
    "Home",
    "Body",
    "Family",
    "Social",
    "Self",
    "Stability",
)


@dataclass(frozen=True)
class CaptureRecord:
    id: str
    created_at: str
    source: str
    modality: str
    raw_text: str
    domains: tuple[str, ...]


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def find_repo_root(start: Path | None = None) -> Path:
    current = (start or Path.cwd()).resolve()
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists():
            return candidate
    return current


def default_data_dir(start: Path | None = None) -> Path:
    return find_repo_root(start) / ".mneme"


def default_db_path(start: Path | None = None) -> Path:
    return default_data_dir(start) / "mneme.db"


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    path = db_path or default_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def initialize(conn: sqlite3.Connection) -> None:
    schema = resources.files("mneme").joinpath("schema.sql").read_text()
    conn.executescript(schema)
    seed_domains(conn)
    conn.commit()


def seed_domains(conn: sqlite3.Connection) -> None:
    existing = conn.execute("SELECT COUNT(*) AS count FROM domains").fetchone()["count"]
    if existing:
        return

    rows = [
        (new_id("dom"), name, sort_order)
        for sort_order, name in enumerate(DEFAULT_DOMAINS, start=1)
    ]
    conn.executemany(
        "INSERT INTO domains (id, name, sort_order) VALUES (?, ?, ?)",
        rows,
    )


def domain_ids_by_name(conn: sqlite3.Connection) -> dict[str, str]:
    rows = conn.execute("SELECT id, name FROM domains ORDER BY sort_order").fetchall()
    return {row["name"].lower(): row["id"] for row in rows}


def normalize_domains(names: Iterable[str]) -> tuple[str, ...]:
    seen: list[str] = []
    for name in names:
        cleaned = name.strip()
        if cleaned and cleaned.lower() not in {value.lower() for value in seen}:
            seen.append(cleaned)
    return tuple(seen)


def insert_capture(
    conn: sqlite3.Connection,
    *,
    raw_text: str,
    source: str = "cli",
    modality: str = "text",
    domains: Iterable[str] = (),
    metadata: dict[str, Any] | None = None,
) -> CaptureRecord:
    capture_id = new_id("cap")
    created_at = now_utc()
    metadata_json = json.dumps(metadata or {}, sort_keys=True)

    conn.execute(
        """
        INSERT INTO captures (id, created_at, source, modality, raw_text, metadata_json)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (capture_id, created_at, source, modality, raw_text, metadata_json),
    )

    names = normalize_domains(domains)
    lookup = domain_ids_by_name(conn)
    for name in names:
        domain_id = lookup.get(name.lower())
        if domain_id is None:
            raise ValueError(f"Unknown domain: {name}")
        conn.execute(
            """
            INSERT INTO capture_domains (capture_id, domain_id, assigned_by, confidence)
            VALUES (?, ?, 'user', 1.0)
            """,
            (capture_id, domain_id),
        )

    conn.commit()
    return CaptureRecord(
        id=capture_id,
        created_at=created_at,
        source=source,
        modality=modality,
        raw_text=raw_text,
        domains=names,
    )


def recent_captures(
    conn: sqlite3.Connection,
    *,
    limit: int = 10,
    days: int | None = None,
) -> list[sqlite3.Row]:
    where_clause = ""
    params: list[Any] = []
    if days is not None:
        where_clause = "WHERE datetime(c.created_at) >= datetime('now', ?)"
        params.append(f"-{days} days")

    params.append(limit)
    sql = f"""
        SELECT c.*, GROUP_CONCAT(d.name, ', ') AS domains
        FROM captures AS c
        LEFT JOIN capture_domains AS cd ON cd.capture_id = c.id
        LEFT JOIN domains AS d ON d.id = cd.domain_id
        {where_clause}
        GROUP BY c.id
        ORDER BY c.created_at DESC
        LIMIT ?
    """
    return conn.execute(sql, params).fetchall()


def search_captures(conn: sqlite3.Connection, query: str, *, limit: int = 8) -> list[sqlite3.Row]:
    tokens = [token.lower() for token in query.split() if len(token.strip()) >= 3]
    if not tokens:
        return recent_captures(conn, limit=limit)

    clauses = " OR ".join("LOWER(c.raw_text) LIKE ?" for _ in tokens)
    params: list[Any] = [f"%{token}%" for token in tokens]
    params.append(limit)
    sql = f"""
        SELECT c.*, GROUP_CONCAT(d.name, ', ') AS domains
        FROM captures AS c
        LEFT JOIN capture_domains AS cd ON cd.capture_id = c.id
        LEFT JOIN domains AS d ON d.id = cd.domain_id
        WHERE {clauses}
        GROUP BY c.id
        ORDER BY c.created_at DESC
        LIMIT ?
    """
    return conn.execute(sql, params).fetchall()


def domain_activity(conn: sqlite3.Connection, *, days: int = 7) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT d.name, COUNT(*) AS capture_count
        FROM capture_domains AS cd
        JOIN domains AS d ON d.id = cd.domain_id
        JOIN captures AS c ON c.id = cd.capture_id
        WHERE datetime(c.created_at) >= datetime('now', ?)
        GROUP BY d.id, d.name
        ORDER BY capture_count DESC, d.sort_order ASC
        """,
        (f"-{days} days",),
    ).fetchall()


def recent_threads(conn: sqlite3.Connection, *, limit: int = 5) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT title, kind, status, salience, last_seen_at
        FROM threads
        ORDER BY salience DESC, last_seen_at DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()


def create_artifact(
    conn: sqlite3.Connection,
    *,
    artifact_type: str,
    target_type: str,
    target_id: str | None,
    model: str,
    content: dict[str, Any],
    text_output: str,
) -> str:
    artifact_id = new_id("art")
    conn.execute(
        """
        INSERT INTO artifacts (
          id, created_at, artifact_type, target_type, target_id, model, content_json, text_output
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            artifact_id,
            now_utc(),
            artifact_type,
            target_type,
            target_id,
            model,
            json.dumps(content, sort_keys=True),
            text_output,
        ),
    )
    conn.commit()
    return artifact_id
