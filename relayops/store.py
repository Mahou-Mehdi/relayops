"""SQLite persistence for a local, single-process RelayOps installation."""

from contextlib import contextmanager
from pathlib import Path
import sqlite3
import threading
import uuid


SCHEMA = """
CREATE TABLE IF NOT EXISTS cases (
  id TEXT PRIMARY KEY, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  revision INTEGER NOT NULL, body TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
  id TEXT PRIMARY KEY, case_id TEXT NOT NULL REFERENCES cases(id),
  status TEXT NOT NULL, body TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS one_active_run ON runs(case_id)
  WHERE status IN ('queued', 'running', 'cancel_requested');
CREATE TABLE IF NOT EXISTS proposals (
  id TEXT PRIMARY KEY, case_id TEXT NOT NULL REFERENCES cases(id),
  status TEXT NOT NULL, body TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS operations (
  id TEXT PRIMARY KEY, case_id TEXT NOT NULL REFERENCES cases(id),
  proposal_id TEXT NOT NULL UNIQUE REFERENCES proposals(id),
  status TEXT NOT NULL, body TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS target_receipts (
  idempotency_key TEXT PRIMARY KEY, case_id TEXT NOT NULL REFERENCES cases(id),
  order_id TEXT NOT NULL, job_id TEXT NOT NULL, payload_hash TEXT NOT NULL,
  receipt TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
  sequence INTEGER PRIMARY KEY AUTOINCREMENT,
  case_id TEXT NOT NULL REFERENCES cases(id), body TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS runs_by_case ON runs(case_id);
CREATE INDEX IF NOT EXISTS proposals_by_case ON proposals(case_id);
CREATE INDEX IF NOT EXISTS operations_by_case ON operations(case_id);
CREATE INDEX IF NOT EXISTS events_by_case ON events(case_id, sequence);
PRAGMA user_version = 1;
"""


class Store:
    """Every operation opens its own connection; writers serialize at BEGIN IMMEDIATE.

    A keeper connection makes ':memory:' safe with the same connection-per-operation
    interface. File databases use WAL and can be reopened after process restart.
    """

    def __init__(self, path):
        self._lock = threading.RLock()
        self.path = str(path)
        self._uri = self.path == ":memory:"
        self._database = (f"file:relayops-{uuid.uuid4()}?mode=memory&cache=shared"
                          if self._uri else self.path)
        if not self._uri:
            Path(self.path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
        self._keeper = self._connect() if self._uri else None
        with self.read() as connection:
            if not self._uri:
                connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript(SCHEMA)

    def _connect(self):
        connection = sqlite3.connect(self._database, timeout=15, isolation_level=None,
                                     uri=self._uri, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=15000")
        return connection

    @contextmanager
    def read(self):
        with self._lock:
            connection = self._connect()
            try:
                yield connection
            finally:
                connection.close()

    @contextmanager
    def transaction(self):
        with self.read() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
                connection.commit()
            except BaseException:
                connection.rollback()
                raise

    def close(self):
        if self._keeper is not None:
            self._keeper.close()
            self._keeper = None
