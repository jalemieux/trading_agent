import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS positions (
    id TEXT PRIMARY KEY,
    product_id TEXT NOT NULL,
    side TEXT NOT NULL,
    entry_price REAL NOT NULL,
    quantity REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'OPEN',
    realized_pnl REAL DEFAULT 0.0,
    opened_at TEXT NOT NULL,
    closed_at TEXT
);

CREATE TABLE IF NOT EXISTS orders (
    id TEXT PRIMARY KEY,
    position_id TEXT,
    product_id TEXT NOT NULL,
    side TEXT NOT NULL,
    type TEXT NOT NULL,
    price REAL,
    quantity REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING',
    coinbase_id TEXT,
    filled_price REAL,
    filled_qty REAL,
    fee REAL,
    created_at TEXT NOT NULL,
    filled_at TEXT,
    FOREIGN KEY (position_id) REFERENCES positions(id)
);

CREATE TABLE IF NOT EXISTS daily_summary (
    date TEXT PRIMARY KEY,
    total_pnl REAL DEFAULT 0.0,
    num_trades INTEGER DEFAULT 0,
    fees_paid REAL DEFAULT 0.0,
    halted INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS kill_switch (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    active INTEGER DEFAULT 0,
    reason TEXT,
    activated_at TEXT
);

INSERT OR IGNORE INTO kill_switch (id, active) VALUES (1, 0);
"""


class Database:
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._conn: aiosqlite.Connection | None = None

    async def initialize(self) -> None:
        self._conn = await aiosqlite.connect(self._db_path)
        await self._conn.executescript(SCHEMA)
        await self._conn.commit()

    async def execute(self, sql: str, params: tuple = ()) -> None:
        assert self._conn is not None
        await self._conn.execute(sql, params)
        await self._conn.commit()

    async def execute_fetchall(self, sql: str, params: tuple = ()) -> list:
        assert self._conn is not None
        cursor = await self._conn.execute(sql, params)
        return await cursor.fetchall()

    async def execute_fetchone(self, sql: str, params: tuple = ()):
        assert self._conn is not None
        cursor = await self._conn.execute(sql, params)
        return await cursor.fetchone()

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()
