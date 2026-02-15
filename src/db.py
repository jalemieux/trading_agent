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

CREATE TABLE IF NOT EXISTS price_history (
    product_id TEXT NOT NULL,
    price REAL NOT NULL,
    timestamp TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_price_history_product_time ON price_history(product_id, timestamp);

CREATE TABLE IF NOT EXISTS predictions (
    id TEXT PRIMARY KEY,
    product_id TEXT NOT NULL,
    action TEXT NOT NULL,
    predicted_price REAL,
    current_price REAL NOT NULL,
    confidence REAL,
    reasoning TEXT,
    model TEXT NOT NULL,
    timestamp TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_predictions_time ON predictions(timestamp);

CREATE TABLE IF NOT EXISTS news_history (
    id TEXT PRIMARY KEY,
    prediction_id TEXT NOT NULL,
    headline TEXT NOT NULL,
    source TEXT,
    sentiment TEXT,
    timestamp TEXT NOT NULL,
    FOREIGN KEY (prediction_id) REFERENCES predictions(id)
);
CREATE INDEX IF NOT EXISTS idx_news_prediction ON news_history(prediction_id);

CREATE TABLE IF NOT EXISTS portfolio_snapshots (
    id TEXT PRIMARY KEY,
    timestamp TEXT NOT NULL,
    total_value_usd REAL NOT NULL,
    position_value_usd REAL NOT NULL,
    realized_pnl_cumulative REAL NOT NULL,
    unrealized_pnl REAL NOT NULL,
    num_open_positions INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_portfolio_time ON portfolio_snapshots(timestamp);
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
