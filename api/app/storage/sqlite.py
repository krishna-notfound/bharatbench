"""SQLite implementation of Storage (aiosqlite, one connection, JSON blobs for models)."""

from pathlib import Path

import aiosqlite

from app.models import Finding, Run, RunEvent

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    apk_path TEXT NOT NULL,
    created_at TEXT NOT NULL,
    data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS findings (
    id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    ord INTEGER PRIMARY KEY AUTOINCREMENT,
    data TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_findings_run ON findings(run_id);
CREATE TABLE IF NOT EXISTS events (
    run_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    data TEXT NOT NULL,
    PRIMARY KEY (run_id, seq)
);
"""


class SqliteStorage:
    def __init__(self, db_path: Path) -> None:
        self._path = Path(db_path)
        self._db: aiosqlite.Connection | None = None

    @property
    def db(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("SqliteStorage.init() was not called")
        return self._db

    async def init(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self._path)
        await self._db.executescript(SCHEMA)
        await self._db.commit()

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

    async def create_run(self, run: Run, apk_path: str) -> None:
        await self.db.execute(
            "INSERT INTO runs (id, apk_path, created_at, data) VALUES (?, ?, ?, ?)",
            (run.id, apk_path, run.created_at.isoformat(), run.model_dump_json()),
        )
        await self.db.commit()

    async def update_run(self, run: Run) -> None:
        await self.db.execute("UPDATE runs SET data = ? WHERE id = ?", (run.model_dump_json(), run.id))
        await self.db.commit()

    async def get_run(self, run_id: str) -> Run | None:
        async with self.db.execute("SELECT data FROM runs WHERE id = ?", (run_id,)) as cur:
            row = await cur.fetchone()
        return Run.model_validate_json(row[0]) if row else None

    async def get_apk_path(self, run_id: str) -> str | None:
        async with self.db.execute("SELECT apk_path FROM runs WHERE id = ?", (run_id,)) as cur:
            row = await cur.fetchone()
        return row[0] if row else None

    async def list_runs(self) -> list[Run]:
        async with self.db.execute("SELECT data FROM runs ORDER BY created_at DESC, rowid DESC") as cur:
            rows = await cur.fetchall()
        return [Run.model_validate_json(r[0]) for r in rows]

    async def add_findings(self, run_id: str, findings: list[Finding]) -> None:
        await self.db.executemany(
            "INSERT INTO findings (id, run_id, data) VALUES (?, ?, ?)",
            [(f.id, run_id, f.model_dump_json()) for f in findings],
        )
        await self.db.commit()

    async def delete_findings(self, run_id: str) -> None:
        await self.db.execute("DELETE FROM findings WHERE run_id = ?", (run_id,))
        await self.db.commit()

    async def list_findings(self, run_id: str) -> list[Finding]:
        async with self.db.execute(
            "SELECT data FROM findings WHERE run_id = ? ORDER BY ord", (run_id,)
        ) as cur:
            rows = await cur.fetchall()
        return [Finding.model_validate_json(r[0]) for r in rows]

    async def add_event(self, event: RunEvent) -> None:
        await self.db.execute(
            "INSERT INTO events (run_id, seq, data) VALUES (?, ?, ?)",
            (event.run_id, event.seq, event.model_dump_json()),
        )
        await self.db.commit()

    async def list_events(self, run_id: str, after_seq: int = 0) -> list[RunEvent]:
        async with self.db.execute(
            "SELECT data FROM events WHERE run_id = ? AND seq > ? ORDER BY seq", (run_id, after_seq)
        ) as cur:
            rows = await cur.fetchall()
        return [RunEvent.model_validate_json(r[0]) for r in rows]

    async def next_seq(self, run_id: str) -> int:
        async with self.db.execute(
            "SELECT COALESCE(MAX(seq), 0) + 1 FROM events WHERE run_id = ?", (run_id,)
        ) as cur:
            row = await cur.fetchone()
        return int(row[0])
