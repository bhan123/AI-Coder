"""Separate append-only evidence store; reads never initialize a database."""
from contextlib import closing
from datetime import datetime
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
import sqlite3

from app.review_evidence import ClosingEvidence, SHANGHAI


class ClosingEvidenceStore:
    def __init__(self, path, *, clock=None):
        self.path = Path(path)
        self.clock = clock or (lambda: datetime.now(SHANGHAI))

    def record(self, quote: ClosingEvidence) -> str:
        quote = ClosingEvidence.model_validate(quote.model_dump())
        received = self.clock()
        if received.tzinfo is None or received < quote.fetched_at:
            raise ValueError("receipt time must be aware and not before fetch time")
        payload = quote.model_dump(mode="json")
        canonical = self._canonical(payload)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path, timeout=15)) as conn, conn:
            conn.row_factory = sqlite3.Row
            conn.execute("""CREATE TABLE IF NOT EXISTS closing_evidence (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                evidence_id TEXT NOT NULL UNIQUE, code TEXT NOT NULL,
                trade_date TEXT NOT NULL, received_at TEXT NOT NULL,
                payload_json TEXT NOT NULL)""")
            conn.execute("""CREATE INDEX IF NOT EXISTS closing_evidence_lookup
                         ON closing_evidence(code, trade_date, received_at)""")
            conn.execute("BEGIN IMMEDIATE")
            prior = conn.execute("SELECT * FROM closing_evidence WHERE code=? AND trade_date=? ORDER BY sequence DESC",
                                 (quote.code, quote.trade_date.isoformat())).fetchall()
            previous_id = ""
            for row in prior:
                saved = json.loads(row["payload_json"])
                if saved["source"] == quote.source:
                    if self._canonical(saved) == canonical:
                        return row["evidence_id"]
                    if quote.fetched_at < datetime.fromisoformat(saved["fetched_at"]):
                        raise ValueError("older fetch cannot replace newer source evidence")
                    previous_id = row["evidence_id"]
                    break
            evidence_id = sha256((previous_id + canonical).encode("utf-8")).hexdigest()
            conn.execute("INSERT OR IGNORE INTO closing_evidence(evidence_id,code,trade_date,received_at,payload_json) VALUES(?,?,?,?,?)",
                         (evidence_id, quote.code, quote.trade_date.isoformat(), received.astimezone(SHANGHAI).isoformat(),
                          json.dumps(payload, ensure_ascii=False)))
        return evidence_id

    @staticmethod
    def _canonical(payload):
        return json.dumps({k: v for k, v in payload.items() if k not in {"fetched_at", "fetch_started_at"}},
                          sort_keys=True, ensure_ascii=False)

    def latest(self, code: str, trade_date: str, *, as_of: datetime) -> dict | None:
        if as_of.tzinfo is None:
            raise ValueError("as_of must include timezone")
        if not self.path.exists():
            return None
        with closing(sqlite3.connect(self.path.resolve().as_uri() + "?mode=ro", uri=True)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("""SELECT * FROM closing_evidence WHERE code=? AND trade_date=?
                               AND received_at<=? ORDER BY received_at DESC, sequence DESC""",
                                (code, trade_date, as_of.astimezone(SHANGHAI).isoformat())).fetchall()
        latest_by_source = {}
        for row in rows:
            payload = json.loads(row["payload_json"])
            latest_by_source.setdefault(payload["source"], {
                "evidence_id": row["evidence_id"], "received_at": row["received_at"], "quote": payload})
        values = list(latest_by_source.values())
        if not values:
            return None
        prices = {tuple(Decimal(item["quote"][k]) if item["quote"].get(k) is not None else None
                        for k in ("close", "limit_up", "day_high")) for item in values}
        if len(prices) > 1:
            return {"conflict": True, "candidates": values}
        return values[0]
