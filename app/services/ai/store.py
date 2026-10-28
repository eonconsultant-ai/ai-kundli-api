"""Quota, entitlement and safety-report storage.

One interface, two backends: SQLite for local development and a single VM, and
Firestore for Cloud Run, where the filesystem is ephemeral and request traffic
lands on whichever instance happens to be warm. Only counters, entitlements and
reports are kept — never birth details or message history.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, time, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from app.core.config import Settings

IST = ZoneInfo("Asia/Kolkata")
# One install cannot log more than this in a day; a stuck client loop should cost
# nothing and a forged client should not be able to inflate the dashboard.
ACTIVITY_DAILY_CAP = 2000
_lock = threading.Lock()
_initialized: set[str] = set()

_SCHEMA = """
CREATE TABLE IF NOT EXISTS daily_usage (
    install_id TEXT NOT NULL,
    day TEXT NOT NULL,
    used INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (install_id, day)
);
CREATE TABLE IF NOT EXISTS live_daily_usage (
    install_id TEXT NOT NULL,
    day TEXT NOT NULL,
    used INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (install_id, day)
);
CREATE TABLE IF NOT EXISTS global_usage (
    day TEXT PRIMARY KEY,
    calls INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS entitlements (
    install_id TEXT PRIMARY KEY,
    plan TEXT NOT NULL,
    expires_at TEXT,
    source TEXT,
    purchase_token TEXT,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ai_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    install_id TEXT,
    created_at TEXT NOT NULL,
    reason TEXT NOT NULL,
    question TEXT,
    reply TEXT
);
CREATE TABLE IF NOT EXISTS live_sessions (
    token TEXT PRIMARY KEY,
    install_id TEXT NOT NULL,
    plus INTEGER NOT NULL DEFAULT 0,
    facts TEXT NOT NULL,
    language TEXT NOT NULL,
    history TEXT NOT NULL,
    expires_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS activity_events (
    install_id TEXT NOT NULL,
    day TEXT NOT NULL,
    name TEXT NOT NULL,
    count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (install_id, day, name)
);
CREATE TABLE IF NOT EXISTS activity_labels (
    install_id TEXT NOT NULL,
    day TEXT NOT NULL,
    label TEXT NOT NULL,
    count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (install_id, day, label)
);
"""


def _now() -> datetime:
    return datetime.now(UTC)


def _local_day(now: datetime | None = None) -> str:
    return (now or _now()).astimezone(IST).date().isoformat()


def _resets_at(now: datetime | None = None) -> str:
    local = (now or _now()).astimezone(IST)
    next_day = datetime.combine(local.date() + timedelta(days=1), time.min, tzinfo=IST)
    return next_day.isoformat()


def _quota_body(limit: int, used: int, plus: bool, enforced: bool, now: datetime | None) -> dict:
    return {
        "limit": limit,
        "used": used,
        "remaining": max(0, limit - used),
        "plus": plus,
        "enforced": enforced,
        "resets_at": _resets_at(now),
    }


def _active(expires_at: str | None, now: datetime) -> bool:
    if not expires_at:
        return False
    try:
        expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
    except ValueError:
        return False
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=UTC)
    return expiry > now


def _activity_body(
    daily: dict[str, dict],
    *,
    distinct_installs: int,
    plus_active: int,
    days: int,
    now: datetime,
) -> dict:
    """Shape both store backends into the same dashboard payload."""
    today = now.astimezone(IST).date()
    series = []
    totals = {"ai_messages": 0, "ai_voice_turns": 0, "events": {}, "labels": {}}
    for offset in range(days - 1, -1, -1):
        day = (today - timedelta(days=offset)).isoformat()
        row = daily.get(day, {})
        events = dict(row.get("events") or {})
        labels = dict(row.get("labels") or {})
        series.append(
            {
                "day": day,
                "active_installs": int(row.get("active_installs", 0)),
                "ai_messages": int(row.get("ai_messages", 0)),
                "ai_voice_turns": int(row.get("ai_voice_turns", 0)),
                "events": events,
                "labels": labels,
            }
        )
        totals["ai_messages"] += int(row.get("ai_messages", 0))
        totals["ai_voice_turns"] += int(row.get("ai_voice_turns", 0))
        for name, count in events.items():
            totals["events"][name] = totals["events"].get(name, 0) + int(count)
        for label, count in labels.items():
            totals["labels"][label] = totals["labels"].get(label, 0) + int(count)
    return {
        "generated_at": now.isoformat(),
        "days": series,
        "totals": {"active_installs": distinct_installs, **totals},
        "plus_active": plus_active,
    }


class UsageStore(Protocol):
    def entitlement_record(self, install_id: str) -> dict | None: ...

    def entitlement(self, install_id: str, now: datetime | None = None) -> dict | None: ...

    def grant_plus(
        self,
        install_id: str,
        *,
        expires_at: str,
        source: str,
        purchase_token: str | None = None,
    ) -> None: ...

    def quota(
        self,
        install_id: str,
        *,
        limit: int,
        plus: bool,
        enforced: bool,
        now: datetime | None = None,
    ) -> dict: ...

    def consume_message(self, install_id: str, limit: int, now: datetime | None = None) -> int | None: ...

    def refund_message(self, install_id: str, now: datetime | None = None) -> None: ...

    def live_quota(
        self,
        install_id: str,
        *,
        limit: int,
        plus: bool,
        enforced: bool,
        now: datetime | None = None,
    ) -> dict: ...

    def consume_live_turn(self, install_id: str, limit: int, now: datetime | None = None) -> int | None: ...

    def refund_live_turn(self, install_id: str, now: datetime | None = None) -> None: ...

    def consume_global(self, limit: int, now: datetime | None = None) -> bool: ...

    def refund_global(self, now: datetime | None = None) -> None: ...

    def save_live_session(
        self,
        *,
        token: str,
        install_id: str,
        plus: bool,
        facts: dict,
        language: str,
        history: list[dict],
        expires_at: float,
    ) -> None: ...

    def claim_live_session(self, token: str, now: float) -> dict | None: ...

    def take_expired_live_sessions(self, now: float) -> list[str]: ...

    def record_report(
        self,
        *,
        install_id: str,
        reason: str,
        question: str,
        reply: str,
    ) -> None: ...

    def record_events(
        self,
        install_id: str,
        events: list[tuple[str, str | None]],
        now: datetime | None = None,
    ) -> int: ...

    def activity(self, days: int, now: datetime | None = None) -> dict: ...

    def prune(self, now: datetime | None = None) -> None: ...


class SqliteStore:
    """Single-file store. Used for local development and the VM deployment."""

    def __init__(self, path: Path):
        self.path = Path(path)

    @contextmanager
    def _session(self) -> Iterator[sqlite3.Connection]:
        with _lock:
            path = Path(self.path)
            path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(path, timeout=10)
            try:
                connection.execute("PRAGMA journal_mode=WAL")
                connection.execute("PRAGMA busy_timeout=5000")
                key = str(path.resolve())
                if key not in _initialized:
                    connection.executescript(_SCHEMA)
                    connection.commit()
                    _initialized.add(key)
                yield connection
            finally:
                connection.close()

    def entitlement_record(self, install_id: str) -> dict | None:
        with self._session() as connection:
            row = connection.execute(
                "SELECT plan, expires_at, source, purchase_token, updated_at FROM entitlements WHERE install_id = ?",
                (install_id,),
            ).fetchone()
        if row is None:
            return None
        plan, expires_at, source, purchase_token, updated_at = row
        return {
            "plan": plan,
            "expires_at": expires_at,
            "source": source,
            "purchase_token": purchase_token,
            "updated_at": updated_at,
        }

    def entitlement(self, install_id: str, now: datetime | None = None) -> dict | None:
        moment = now or _now()
        with self._session() as connection:
            row = connection.execute(
                "SELECT plan, expires_at, source FROM entitlements WHERE install_id = ?",
                (install_id,),
            ).fetchone()
        if row is None:
            return None
        plan, expires, source = row
        if plan != "plus" or not _active(expires, moment):
            return None
        return {"plan": "plus", "expires_at": expires, "source": source}

    def grant_plus(
        self,
        install_id: str,
        *,
        expires_at: str,
        source: str,
        purchase_token: str | None = None,
    ) -> None:
        with self._session() as connection:
            connection.execute(
                """
                INSERT INTO entitlements(install_id, plan, expires_at, source, purchase_token, updated_at)
                VALUES(?, 'plus', ?, ?, ?, ?)
                ON CONFLICT(install_id) DO UPDATE SET
                    plan = 'plus',
                    expires_at = excluded.expires_at,
                    source = excluded.source,
                    purchase_token = excluded.purchase_token,
                    updated_at = excluded.updated_at
                """,
                (install_id, expires_at, source, purchase_token, _now().isoformat()),
            )
            connection.commit()

    def quota(
        self,
        install_id: str,
        *,
        limit: int,
        plus: bool,
        enforced: bool,
        now: datetime | None = None,
    ) -> dict:
        day = _local_day(now)
        with self._session() as connection:
            row = connection.execute(
                "SELECT used FROM daily_usage WHERE install_id = ? AND day = ?",
                (install_id, day),
            ).fetchone()
        used = row[0] if row else 0
        return _quota_body(limit, used, plus, enforced, now)

    def consume_message(self, install_id: str, limit: int, now: datetime | None = None) -> int | None:
        """Reserve one message. Returns the new usage count, or None when exhausted."""
        day = _local_day(now)
        with self._session() as connection:
            row = connection.execute(
                """
                INSERT INTO daily_usage(install_id, day, used) VALUES(?, ?, 1)
                ON CONFLICT(install_id, day) DO UPDATE SET used = used + 1
                    WHERE daily_usage.used < ?
                RETURNING used
                """,
                (install_id, day, limit),
            ).fetchone()
            connection.commit()
        return row[0] if row else None

    def refund_message(self, install_id: str, now: datetime | None = None) -> None:
        day = _local_day(now)
        with self._session() as connection:
            connection.execute(
                "UPDATE daily_usage SET used = max(used - 1, 0) WHERE install_id = ? AND day = ?",
                (install_id, day),
            )
            connection.commit()

    def live_quota(
        self,
        install_id: str,
        *,
        limit: int,
        plus: bool,
        enforced: bool,
        now: datetime | None = None,
    ) -> dict:
        day = _local_day(now)
        with self._session() as connection:
            row = connection.execute(
                "SELECT used FROM live_daily_usage WHERE install_id = ? AND day = ?",
                (install_id, day),
            ).fetchone()
        used = row[0] if row else 0
        return _quota_body(limit, used, plus, enforced, now)

    def consume_live_turn(self, install_id: str, limit: int, now: datetime | None = None) -> int | None:
        """Reserve one voice turn. Returns the new count, or None when exhausted."""
        day = _local_day(now)
        with self._session() as connection:
            row = connection.execute(
                """
                INSERT INTO live_daily_usage(install_id, day, used) VALUES(?, ?, 1)
                ON CONFLICT(install_id, day) DO UPDATE SET used = used + 1
                    WHERE live_daily_usage.used < ?
                RETURNING used
                """,
                (install_id, day, limit),
            ).fetchone()
            connection.commit()
        return row[0] if row else None

    def refund_live_turn(self, install_id: str, now: datetime | None = None) -> None:
        day = _local_day(now)
        with self._session() as connection:
            connection.execute(
                "UPDATE live_daily_usage SET used = max(used - 1, 0) WHERE install_id = ? AND day = ?",
                (install_id, day),
            )
            connection.commit()

    def consume_global(self, limit: int, now: datetime | None = None) -> bool:
        day = _local_day(now)
        with self._session() as connection:
            row = connection.execute(
                """
                INSERT INTO global_usage(day, calls) VALUES(?, 1)
                ON CONFLICT(day) DO UPDATE SET calls = calls + 1
                    WHERE global_usage.calls < ?
                RETURNING calls
                """,
                (day, limit),
            ).fetchone()
            connection.commit()
        return row is not None

    def refund_global(self, now: datetime | None = None) -> None:
        day = _local_day(now)
        with self._session() as connection:
            connection.execute(
                "UPDATE global_usage SET calls = max(calls - 1, 0) WHERE day = ?",
                (day,),
            )
            connection.commit()

    def save_live_session(
        self,
        *,
        token: str,
        install_id: str,
        plus: bool,
        facts: dict,
        language: str,
        history: list[dict],
        expires_at: float,
    ) -> None:
        """Store a single-use voice token. It is deleted as soon as a stream claims it."""
        with self._session() as connection:
            connection.execute(
                """
                INSERT INTO live_sessions(token, install_id, plus, facts, language, history, expires_at)
                VALUES(?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    token,
                    install_id,
                    int(plus),
                    json.dumps(facts, ensure_ascii=False),
                    language,
                    json.dumps(history, ensure_ascii=False),
                    expires_at,
                ),
            )
            connection.commit()

    def claim_live_session(self, token: str, now: float) -> dict | None:
        """Consume a token atomically. Any worker may claim it exactly once."""
        with self._session() as connection:
            row = connection.execute(
                """
                DELETE FROM live_sessions
                WHERE token = ? AND expires_at > ?
                RETURNING install_id, plus, facts, language, history
                """,
                (token, now),
            ).fetchone()
            connection.commit()
        if row is None:
            return None
        install_id, plus, facts, language, history = row
        return {
            "install_id": install_id,
            "plus": bool(plus),
            "facts": json.loads(facts),
            "language": language,
            "history": json.loads(history),
        }

    def take_expired_live_sessions(self, now: float) -> list[str]:
        """Delete expired tokens and return the install IDs whose turn to refund."""
        with self._session() as connection:
            rows = connection.execute(
                "DELETE FROM live_sessions WHERE expires_at <= ? RETURNING install_id",
                (now,),
            ).fetchall()
            connection.commit()
        return [row[0] for row in rows]

    def record_report(
        self,
        *,
        install_id: str,
        reason: str,
        question: str,
        reply: str,
    ) -> None:
        with self._session() as connection:
            connection.execute(
                "INSERT INTO ai_reports(install_id, created_at, reason, question, reply) VALUES(?, ?, ?, ?, ?)",
                (install_id, _now().isoformat(), reason, question[:1000], reply[:2000]),
            )
            connection.commit()

    def record_events(
        self,
        install_id: str,
        events: list[tuple[str, str | None]],
        now: datetime | None = None,
    ) -> int:
        if not events:
            return 0
        day = _local_day(now)
        with self._session() as connection:
            row = connection.execute(
                "SELECT COALESCE(SUM(count), 0) FROM activity_events WHERE install_id = ? AND day = ?",
                (install_id, day),
            ).fetchone()
            allowance = max(0, ACTIVITY_DAILY_CAP - int(row[0] or 0))
            accepted = events[:allowance]
            for name, label in accepted:
                connection.execute(
                    """
                    INSERT INTO activity_events(install_id, day, name, count) VALUES(?, ?, ?, 1)
                    ON CONFLICT(install_id, day, name) DO UPDATE SET count = count + 1
                    """,
                    (install_id, day, name),
                )
                if label:
                    connection.execute(
                        """
                        INSERT INTO activity_labels(install_id, day, label, count) VALUES(?, ?, ?, 1)
                        ON CONFLICT(install_id, day, label) DO UPDATE SET count = count + 1
                        """,
                        (install_id, day, label),
                    )
            connection.commit()
        return len(accepted)

    def activity(self, days: int, now: datetime | None = None) -> dict:
        moment = now or _now()
        today = moment.astimezone(IST).date()
        start = (today - timedelta(days=days - 1)).isoformat()
        end = today.isoformat()
        daily: dict[str, dict] = {}
        with self._session() as connection:
            for day, installs in connection.execute(
                """
                SELECT day, COUNT(DISTINCT install_id) FROM activity_events
                WHERE day BETWEEN ? AND ? GROUP BY day
                """,
                (start, end),
            ):
                daily.setdefault(day, {})["active_installs"] = installs
            for day, name, count in connection.execute(
                """
                SELECT day, name, SUM(count) FROM activity_events
                WHERE day BETWEEN ? AND ? GROUP BY day, name
                """,
                (start, end),
            ):
                daily.setdefault(day, {}).setdefault("events", {})[name] = count
            for day, label, count in connection.execute(
                """
                SELECT day, label, SUM(count) FROM activity_labels
                WHERE day BETWEEN ? AND ? GROUP BY day, label
                """,
                (start, end),
            ):
                daily.setdefault(day, {}).setdefault("labels", {})[label] = count
            for day, used in connection.execute(
                "SELECT day, SUM(used) FROM daily_usage WHERE day BETWEEN ? AND ? GROUP BY day",
                (start, end),
            ):
                daily.setdefault(day, {})["ai_messages"] = used
            for day, used in connection.execute(
                "SELECT day, SUM(used) FROM live_daily_usage WHERE day BETWEEN ? AND ? GROUP BY day",
                (start, end),
            ):
                daily.setdefault(day, {})["ai_voice_turns"] = used
            installs = connection.execute(
                "SELECT COUNT(DISTINCT install_id) FROM activity_events WHERE day BETWEEN ? AND ?",
                (start, end),
            ).fetchone()[0]
            expiries = connection.execute(
                "SELECT expires_at FROM entitlements WHERE plan = 'plus'"
            ).fetchall()
        plus_active = sum(1 for (expiry,) in expiries if _active(expiry, moment))
        return _activity_body(
            daily,
            distinct_installs=int(installs or 0),
            plus_active=plus_active,
            days=days,
            now=moment,
        )

    def prune(self, now: datetime | None = None) -> None:
        moment = now or _now()
        cutoff_day = (moment.astimezone(IST).date() - timedelta(days=35)).isoformat()
        cutoff_time = (moment - timedelta(days=180)).isoformat()
        with self._session() as connection:
            connection.execute("DELETE FROM daily_usage WHERE day < ?", (cutoff_day,))
            connection.execute("DELETE FROM live_daily_usage WHERE day < ?", (cutoff_day,))
            connection.execute("DELETE FROM global_usage WHERE day < ?", (cutoff_day,))
            connection.execute("DELETE FROM ai_reports WHERE created_at < ?", (cutoff_time,))
            connection.execute("DELETE FROM activity_events WHERE day < ?", (cutoff_day,))
            connection.execute("DELETE FROM activity_labels WHERE day < ?", (cutoff_day,))
            connection.commit()


class FirestoreStore:
    """Shared store for Cloud Run, where instances come and go and a local file
    would be lost and never shared between them."""

    def __init__(self, project: str | None, database: str):
        # Imported here so SQLite deployments never pay for the client import.
        from google.cloud import firestore

        self._fs = firestore
        self._db = firestore.Client(project=project, database=database)

    @staticmethod
    def _daily_key(install_id: str, day: str) -> str:
        return f"{install_id}__{day}"

    def entitlement_record(self, install_id: str) -> dict | None:
        snapshot = self._db.collection("entitlements").document(install_id).get()
        if not snapshot.exists:
            return None
        data = snapshot.to_dict() or {}
        return {
            "plan": data.get("plan"),
            "expires_at": data.get("expires_at"),
            "source": data.get("source"),
            "purchase_token": data.get("purchase_token"),
            "updated_at": data.get("updated_at"),
        }

    def entitlement(self, install_id: str, now: datetime | None = None) -> dict | None:
        moment = now or _now()
        snapshot = self._db.collection("entitlements").document(install_id).get()
        if not snapshot.exists:
            return None
        data = snapshot.to_dict() or {}
        if data.get("plan") != "plus" or not _active(data.get("expires_at"), moment):
            return None
        return {"plan": "plus", "expires_at": data.get("expires_at"), "source": data.get("source")}

    def grant_plus(
        self,
        install_id: str,
        *,
        expires_at: str,
        source: str,
        purchase_token: str | None = None,
    ) -> None:
        self._db.collection("entitlements").document(install_id).set(
            {
                "plan": "plus",
                "expires_at": expires_at,
                "source": source,
                "purchase_token": purchase_token,
                "updated_at": _now().isoformat(),
            }
        )

    def quota(
        self,
        install_id: str,
        *,
        limit: int,
        plus: bool,
        enforced: bool,
        now: datetime | None = None,
    ) -> dict:
        used = self._used("daily_usage", self._daily_key(install_id, _local_day(now)))
        return _quota_body(limit, used, plus, enforced, now)

    def consume_message(self, install_id: str, limit: int, now: datetime | None = None) -> int | None:
        day = _local_day(now)
        reference = self._db.collection("daily_usage").document(self._daily_key(install_id, day))
        return self._consume(reference, "used", limit, {"install_id": install_id, "day": day})

    def refund_message(self, install_id: str, now: datetime | None = None) -> None:
        day = _local_day(now)
        self._refund(self._db.collection("daily_usage").document(self._daily_key(install_id, day)), "used")

    def live_quota(
        self,
        install_id: str,
        *,
        limit: int,
        plus: bool,
        enforced: bool,
        now: datetime | None = None,
    ) -> dict:
        used = self._used("live_daily_usage", self._daily_key(install_id, _local_day(now)))
        return _quota_body(limit, used, plus, enforced, now)

    def consume_live_turn(self, install_id: str, limit: int, now: datetime | None = None) -> int | None:
        day = _local_day(now)
        reference = self._db.collection("live_daily_usage").document(self._daily_key(install_id, day))
        return self._consume(reference, "used", limit, {"install_id": install_id, "day": day})

    def refund_live_turn(self, install_id: str, now: datetime | None = None) -> None:
        day = _local_day(now)
        self._refund(self._db.collection("live_daily_usage").document(self._daily_key(install_id, day)), "used")

    def consume_global(self, limit: int, now: datetime | None = None) -> bool:
        day = _local_day(now)
        reference = self._db.collection("global_usage").document(day)
        return self._consume(reference, "calls", limit, {"day": day}) is not None

    def refund_global(self, now: datetime | None = None) -> None:
        self._refund(self._db.collection("global_usage").document(_local_day(now)), "calls")

    def save_live_session(
        self,
        *,
        token: str,
        install_id: str,
        plus: bool,
        facts: dict,
        language: str,
        history: list[dict],
        expires_at: float,
    ) -> None:
        self._db.collection("live_sessions").document(token).set(
            {
                "install_id": install_id,
                "plus": int(plus),
                "facts": json.dumps(facts, ensure_ascii=False),
                "language": language,
                "history": json.dumps(history, ensure_ascii=False),
                "expires_at": expires_at,
            }
        )

    def claim_live_session(self, token: str, now: float) -> dict | None:
        reference = self._db.collection("live_sessions").document(token)
        transactional = self._fs.transactional

        @transactional
        def claim(transaction) -> dict | None:
            snapshot = reference.get(transaction=transaction)
            if not snapshot.exists:
                return None
            data = snapshot.to_dict() or {}
            if float(data.get("expires_at", 0)) <= now:
                return None
            transaction.delete(reference)
            return data

        record = claim(self._db.transaction())
        if record is None:
            return None
        return {
            "install_id": record["install_id"],
            "plus": bool(record.get("plus")),
            "facts": json.loads(record["facts"]),
            "language": record["language"],
            "history": json.loads(record["history"]),
        }

    def take_expired_live_sessions(self, now: float) -> list[str]:
        query = self._db.collection("live_sessions").where(filter=self._fs.FieldFilter("expires_at", "<=", now))
        install_ids: list[str] = []
        while True:
            documents = list(query.limit(400).stream())
            if not documents:
                return install_ids
            batch = self._db.batch()
            for document in documents:
                data = document.to_dict() or {}
                if data.get("install_id"):
                    install_ids.append(data["install_id"])
                batch.delete(document.reference)
            batch.commit()

    def record_report(
        self,
        *,
        install_id: str,
        reason: str,
        question: str,
        reply: str,
    ) -> None:
        self._db.collection("ai_reports").add(
            {
                "install_id": install_id,
                "created_at": _now().isoformat(),
                "reason": reason,
                "question": question[:1000],
                "reply": reply[:2000],
            }
        )

    def record_events(
        self,
        install_id: str,
        events: list[tuple[str, str | None]],
        now: datetime | None = None,
    ) -> int:
        if not events:
            return 0
        moment = now or _now()
        day = _local_day(moment)
        reference = self._db.collection("activity").document(f"{install_id}__{day}")
        transactional = self._fs.transactional

        @transactional
        def run(transaction) -> int:
            snapshot = reference.get(transaction=transaction)
            data = (snapshot.to_dict() or {}) if snapshot.exists else {}
            used = int(data.get("total", 0))
            accepted = events[: max(0, ACTIVITY_DAILY_CAP - used)]
            names = dict(data.get("events") or {})
            labels = dict(data.get("labels") or {})
            for name, label in accepted:
                names[name] = int(names.get(name, 0)) + 1
                if label:
                    labels[label] = int(labels.get(label, 0)) + 1
            transaction.set(
                reference,
                {
                    "day": day,
                    "install_id": install_id,
                    "total": used + len(accepted),
                    "events": names,
                    "labels": labels,
                    "first_at": data.get("first_at") or moment.isoformat(),
                    "last_at": moment.isoformat(),
                },
            )
            return len(accepted)

        return run(self._db.transaction())

    def activity(self, days: int, now: datetime | None = None) -> dict:
        moment = now or _now()
        today = moment.astimezone(IST).date()
        cutoff = (today - timedelta(days=days - 1)).isoformat()
        daily: dict[str, dict] = {}
        installs: set[str] = set()
        documents = self._db.collection("activity").where(
            filter=self._fs.FieldFilter("day", ">=", cutoff)
        )
        for document in documents.stream():
            data = document.to_dict() or {}
            day = data.get("day")
            if not day:
                continue
            row = daily.setdefault(day, {})
            row["active_installs"] = int(row.get("active_installs", 0)) + 1
            names = row.setdefault("events", {})
            for name, count in (data.get("events") or {}).items():
                names[name] = int(names.get(name, 0)) + int(count)
            labels = row.setdefault("labels", {})
            for label, count in (data.get("labels") or {}).items():
                labels[label] = int(labels.get(label, 0)) + int(count)
            if data.get("install_id"):
                installs.add(data["install_id"])
        for collection, key in (
            ("daily_usage", "ai_messages"),
            ("live_daily_usage", "ai_voice_turns"),
        ):
            query = self._db.collection(collection).where(
                filter=self._fs.FieldFilter("day", ">=", cutoff)
            )
            for document in query.stream():
                data = document.to_dict() or {}
                day = data.get("day")
                if not day:
                    continue
                row = daily.setdefault(day, {})
                row[key] = int(row.get(key, 0)) + int(data.get("used", 0))
        plus_active = 0
        for document in self._db.collection("entitlements").stream():
            data = document.to_dict() or {}
            if data.get("plan") == "plus" and _active(data.get("expires_at"), moment):
                plus_active += 1
        return _activity_body(
            daily,
            distinct_installs=len(installs),
            plus_active=plus_active,
            days=days,
            now=moment,
        )

    def prune(self, now: datetime | None = None) -> None:
        """Delete old counters and reports at most once a day per deployment."""
        moment = now or _now()
        day = _local_day(moment)
        marker = self._db.collection("meta").document("prune")
        snapshot = marker.get()
        if snapshot.exists and (snapshot.to_dict() or {}).get("day") == day:
            return
        cutoff_day = (moment.astimezone(IST).date() - timedelta(days=35)).isoformat()
        cutoff_time = (moment - timedelta(days=180)).isoformat()
        for collection, field, cutoff in (
            ("daily_usage", "day", cutoff_day),
            ("live_daily_usage", "day", cutoff_day),
            ("global_usage", "day", cutoff_day),
            ("ai_reports", "created_at", cutoff_time),
            ("activity", "day", cutoff_day),
        ):
            self._delete_before(collection, field, cutoff)
        marker.set({"day": day, "at": moment.isoformat()})

    def _used(self, collection: str, key: str) -> int:
        snapshot = self._db.collection(collection).document(key).get()
        if not snapshot.exists:
            return 0
        return int((snapshot.to_dict() or {}).get("used", 0))

    def _consume(self, reference, field: str, limit: int, extra: dict[str, Any]) -> int | None:
        transactional = self._fs.transactional

        @transactional
        def run(transaction) -> int | None:
            snapshot = reference.get(transaction=transaction)
            used = int((snapshot.to_dict() or {}).get(field, 0)) if snapshot.exists else 0
            if used >= limit:
                return None
            transaction.set(reference, {**extra, field: used + 1})
            return used + 1

        return run(self._db.transaction())

    def _refund(self, reference, field: str) -> None:
        transactional = self._fs.transactional

        @transactional
        def run(transaction) -> None:
            snapshot = reference.get(transaction=transaction)
            if not snapshot.exists:
                return
            used = int((snapshot.to_dict() or {}).get(field, 0))
            transaction.update(reference, {field: max(used - 1, 0)})

        run(self._db.transaction())

    def _delete_before(self, collection: str, field: str, cutoff: str) -> None:
        query = self._db.collection(collection).where(filter=self._fs.FieldFilter(field, "<", cutoff))
        while True:
            documents = list(query.limit(400).stream())
            if not documents:
                return
            batch = self._db.batch()
            for document in documents:
                batch.delete(document.reference)
            batch.commit()


@lru_cache(maxsize=8)
def _sqlite_store(path: str) -> SqliteStore:
    return SqliteStore(Path(path))


@lru_cache(maxsize=4)
def _firestore_store(project: str, database: str) -> FirestoreStore:
    return FirestoreStore(project or None, database)


def get(settings: Settings) -> UsageStore:
    """Resolve the configured backend. Cached per connection target."""
    if settings.usage_store == "firestore":
        return _firestore_store(settings.firestore_project or "", settings.firestore_database)
    return _sqlite_store(str(settings.ai_usage_db_path))
