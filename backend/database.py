"""The UnderCover database, seeded from the business data in data/."""

import json
import os
import re
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DOCUMENTS = {
    "policy_wording": "policy_wording.md",
    "claims_manual": "claims_manual.md",
}

SCHEMA = """
CREATE TABLE settings (
    payout_approval_limit REAL NOT NULL
);
CREATE TABLE sections (
    document TEXT NOT NULL,
    section INTEGER NOT NULL,
    title TEXT NOT NULL,
    text TEXT NOT NULL,
    PRIMARY KEY (document, section)
);
CREATE TABLE handlers (
    handler_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    role TEXT NOT NULL,
    can_approve_over_limit INTEGER NOT NULL
);
CREATE TABLE customers (
    customer_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    record TEXT NOT NULL
);
CREATE TABLE policies (
    policy_id TEXT PRIMARY KEY,
    record TEXT NOT NULL
);
CREATE TABLE claims (
    claim_id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL REFERENCES customers,
    record TEXT NOT NULL,
    status TEXT NOT NULL,
    thread_id TEXT,
    failures INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE decisions (
    claim_id TEXT PRIMARY KEY REFERENCES claims,
    decision TEXT NOT NULL,
    payout REAL NOT NULL,
    section TEXT NOT NULL,
    reason TEXT NOT NULL,
    decided_at TEXT NOT NULL
);
CREATE TABLE payments (
    claim_id TEXT PRIMARY KEY REFERENCES claims,
    amount REAL NOT NULL,
    paid_at TEXT NOT NULL,
    signed_off_by TEXT
);
CREATE TABLE steps (
    step_id INTEGER PRIMARY KEY AUTOINCREMENT,
    claim_id TEXT NOT NULL REFERENCES claims,
    thread_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE runs (
    run_id TEXT PRIMARY KEY,
    cap INTEGER NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    todos TEXT NOT NULL,
    summary TEXT
);
CREATE VIEW claim_view AS
SELECT
    claims.claim_id, claims.record, claims.status, claims.thread_id,
    customers.name AS customer_name,
    decisions.decision, decisions.payout, decisions.section, decisions.reason,
    decisions.decided_at,
    payments.amount, payments.paid_at, payments.signed_off_by
FROM claims
JOIN customers USING (customer_id)
LEFT JOIN decisions USING (claim_id)
LEFT JOIN payments USING (claim_id);
"""


def database_path() -> Path:
    """Return the database file from UNDERCOVER_DB, or undercover.db at the root."""
    return Path(os.getenv("UNDERCOVER_DB", str(ROOT / "undercover.db")))


def connect() -> sqlite3.Connection:
    """Open the database, with rows that can be read by column name."""
    connection = sqlite3.connect(database_path(), check_same_thread=False)
    connection.row_factory = sqlite3.Row
    return connection


def load(name: str) -> Any:
    """Read one of the JSON files in data/."""
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def split_sections(text: str) -> list[tuple[int, str, str]]:
    """Split a document at its "## 1. Title" headings into numbered sections."""
    sections = []
    for part in re.split(r"^## ", text, flags=re.MULTILINE)[1:]:
        heading, _, body = part.partition("\n")
        number, _, title = heading.partition(". ")
        sections.append((int(number), title.strip(), body.strip()))
    return sections


def seed(path: Path) -> dict[str, int]:
    """Build a fresh database at path from data/ and count what it holds."""
    company = load("company.json")
    handlers = load("handlers.json")
    customers = load("customers.json")
    policies = load("policies.json")
    claims = load("claims.json")
    sections = [
        (document, *section)
        for document, name in DOCUMENTS.items()
        for section in split_sections((DATA / name).read_text(encoding="utf-8"))
    ]
    path.unlink(missing_ok=True)
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.executescript(SCHEMA)
        connection.execute(
            "INSERT INTO settings VALUES (?)", (company["payout_approval_limit"],)
        )
        connection.executemany("INSERT INTO sections VALUES (?, ?, ?, ?)", sections)
        connection.executemany(
            "INSERT INTO handlers VALUES (?, ?, ?, ?)",
            [
                (h["handler_id"], h["name"], h["role"], h["can_approve_over_limit"])
                for h in handlers
            ],
        )
        connection.executemany(
            "INSERT INTO customers VALUES (?, ?, ?)",
            [(c["customer_id"], c["name"], json.dumps(c)) for c in customers],
        )
        connection.executemany(
            "INSERT INTO policies VALUES (?, ?)",
            [(p["policy_id"], json.dumps(p)) for p in policies],
        )
        connection.executemany(
            "INSERT INTO claims (claim_id, customer_id, record, status)"
            " VALUES (?, ?, ?, 'waiting')",
            [(c["claim_id"], c["customer_id"], json.dumps(c)) for c in claims],
        )
    return {
        "claims": len(claims),
        "policies": len(policies),
        "customers": len(customers),
        "handlers": len(handlers),
    }
