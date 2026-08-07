"""SQLite-laag: schema, helpers en ingest-logica."""
import re
import sqlite3
import threading
from datetime import datetime, timedelta, timezone

from . import config

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS repeaters(
  id INTEGER PRIMARY KEY,
  slug TEXT UNIQUE NOT NULL,
  pubkey_prefix TEXT UNIQUE NOT NULL,
  name TEXT NOT NULL,
  is_public INTEGER NOT NULL DEFAULT 1,
  sort_order INTEGER NOT NULL DEFAULT 0,
  last_seen TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS latest(
  repeater_id INTEGER NOT NULL REFERENCES repeaters(id) ON DELETE CASCADE,
  metric TEXT NOT NULL,
  ts TEXT NOT NULL,
  value REAL,
  value_str TEXT,
  PRIMARY KEY(repeater_id, metric)
);
CREATE TABLE IF NOT EXISTS samples(
  repeater_id INTEGER NOT NULL,
  metric TEXT NOT NULL,
  ts TEXT NOT NULL,
  value REAL NOT NULL,
  PRIMARY KEY(repeater_id, metric, ts)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS neighbors(
  repeater_id INTEGER NOT NULL REFERENCES repeaters(id) ON DELETE CASCADE,
  prefix TEXT NOT NULL,
  name TEXT,
  snr REAL,
  last_seen TEXT NOT NULL,
  PRIMARY KEY(repeater_id, prefix)
);
CREATE TABLE IF NOT EXISTS tokens(
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  token_hash TEXT UNIQUE NOT NULL,
  created_at TEXT NOT NULL,
  last_used TEXT,
  revoked INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS admins(
  id INTEGER PRIMARY KEY,
  username TEXT UNIQUE NOT NULL,
  pw_hash TEXT NOT NULL
);
"""


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(config.DB_PATH, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.execute("PRAGMA foreign_keys=ON")
        _conn.executescript(SCHEMA)
        _conn.commit()
    return _conn


def q(sql: str, params=()) -> list[sqlite3.Row]:
    with _lock:
        return get_conn().execute(sql, params).fetchall()


def qone(sql: str, params=()) -> sqlite3.Row | None:
    rows = q(sql, params)
    return rows[0] if rows else None


def execute(sql: str, params=()) -> int:
    with _lock:
        conn = get_conn()
        cur = conn.execute(sql, params)
        conn.commit()
        return cur.lastrowid


def slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s or "repeater"


def get_or_create_repeater(pubkey_prefix: str, name: str | None) -> sqlite3.Row:
    row = qone("SELECT * FROM repeaters WHERE pubkey_prefix=?", (pubkey_prefix,))
    if row:
        # Naam bijwerken als HA een (nieuwe) naam meestuurt
        if name and name != row["name"]:
            execute("UPDATE repeaters SET name=? WHERE id=?", (name, row["id"]))
            row = qone("SELECT * FROM repeaters WHERE id=?", (row["id"],))
        return row
    base = slugify(name or pubkey_prefix)
    slug = base
    i = 2
    while qone("SELECT 1 FROM repeaters WHERE slug=?", (slug,)):
        slug = f"{base}-{i}"
        i += 1
    execute(
        "INSERT INTO repeaters(slug, pubkey_prefix, name, created_at) VALUES(?,?,?,?)",
        (slug, pubkey_prefix, name or pubkey_prefix, utcnow()),
    )
    return qone("SELECT * FROM repeaters WHERE pubkey_prefix=?", (pubkey_prefix,))


def ingest(repeater_id: int, ts: str, metrics: dict, neighbors: list | None):
    """Sla een snapshot op. Numerieke waarden gaan alleen de historiek in als
    ze wijzigden t.o.v. de laatste waarde, of als de laatste ouder is dan de
    heartbeat-interval (zodat grafieken blijven doorlopen)."""
    heartbeat = timedelta(minutes=config.HEARTBEAT_MIN)
    with _lock:
        conn = get_conn()
        for name, raw in metrics.items():
            value = value_str = None
            if isinstance(raw, bool):
                value = 1.0 if raw else 0.0
            elif isinstance(raw, (int, float)):
                value = float(raw)
            else:
                try:
                    value = float(raw)
                except (TypeError, ValueError):
                    value_str = None if raw is None else str(raw)[:255]
            prev = conn.execute(
                "SELECT ts, value, value_str FROM latest WHERE repeater_id=? AND metric=?",
                (repeater_id, name),
            ).fetchone()
            conn.execute(
                "INSERT INTO latest(repeater_id, metric, ts, value, value_str) VALUES(?,?,?,?,?) "
                "ON CONFLICT(repeater_id, metric) DO UPDATE SET ts=excluded.ts, "
                "value=excluded.value, value_str=excluded.value_str",
                (repeater_id, name, ts, value, value_str),
            )
            if value is None:
                continue
            store = True
            if prev is not None and prev["value"] == value:
                try:
                    prev_dt = datetime.strptime(prev["ts"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                    now_dt = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                    store = (now_dt - prev_dt) >= heartbeat
                except ValueError:
                    store = False
            if store:
                conn.execute(
                    "INSERT OR REPLACE INTO samples(repeater_id, metric, ts, value) VALUES(?,?,?,?)",
                    (repeater_id, name, ts, value),
                )
        if neighbors is not None:
            for nb in neighbors:
                prefix = str(nb.get("prefix", "")).lower()
                if not prefix:
                    continue
                # 'seen_min' = minuten sinds laatst gehoord -> echte laatst-gehoord-tijd
                last = ts
                seen_min = nb.get("seen_min")
                if isinstance(seen_min, (int, float)):
                    try:
                        ts_dt = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                        last = (ts_dt - timedelta(minutes=seen_min)).strftime("%Y-%m-%dT%H:%M:%SZ")
                    except ValueError:
                        pass
                snr = nb.get("snr")
                prev_nb = conn.execute(
                    "SELECT snr FROM neighbors WHERE repeater_id=? AND prefix=?",
                    (repeater_id, prefix),
                ).fetchone()
                conn.execute(
                    "INSERT INTO neighbors(repeater_id, prefix, name, snr, last_seen) VALUES(?,?,?,?,?) "
                    "ON CONFLICT(repeater_id, prefix) DO UPDATE SET "
                    "name=COALESCE(excluded.name, name), snr=COALESCE(excluded.snr, snr), "
                    "last_seen=excluded.last_seen",
                    (repeater_id, prefix, nb.get("name"), snr, last),
                )
                # Linkhistoriek: SNR-verloop per individuele buurlink
                if isinstance(snr, (int, float)) and (prev_nb is None or prev_nb["snr"] != snr):
                    conn.execute(
                        "INSERT OR REPLACE INTO samples(repeater_id, metric, ts, value) VALUES(?,?,?,?)",
                        (repeater_id, f"neighbor_{prefix}", ts, float(snr)),
                    )
        conn.execute("UPDATE repeaters SET last_seen=? WHERE id=?", (ts, repeater_id))
        conn.commit()


def history(repeater_id: int, metric: str, hours: int) -> list[tuple[str, float]]:
    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
    if hours <= 48:
        rows = q(
            "SELECT ts, value FROM samples WHERE repeater_id=? AND metric=? AND ts>=? ORDER BY ts",
            (repeater_id, metric, since),
        )
        return [(r["ts"], r["value"]) for r in rows]
    # Langere periodes: per uur gemiddeld om de payload klein te houden
    rows = q(
        "SELECT substr(ts,1,13)||':00:00Z' AS bucket, AVG(value) AS value "
        "FROM samples WHERE repeater_id=? AND metric=? AND ts>=? GROUP BY bucket ORDER BY bucket",
        (repeater_id, metric, since),
    )
    return [(r["bucket"], round(r["value"], 3)) for r in rows]


def latest_for(repeater_id: int) -> dict[str, sqlite3.Row]:
    return {r["metric"]: r for r in q("SELECT * FROM latest WHERE repeater_id=?", (repeater_id,))}


def prune():
    cutoff = (datetime.now(timezone.utc) - timedelta(days=config.RETENTION_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    execute("DELETE FROM samples WHERE ts<?", (cutoff,))
    # Buren die 7 dagen niet meer gezien zijn verdwijnen uit de lijst
    nb_cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
    execute("DELETE FROM neighbors WHERE last_seen<?", (nb_cutoff,))
