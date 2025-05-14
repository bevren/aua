CREATE TABLE IF NOT EXISTS devices (
    id TEXT PRIMARY KEY,
    device_serial TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    device_id TEXT NOT NULL,
    title TEXT,
    messages TEXT NOT NULL,
    directory TEXT DEFAULT "none",
    FOREIGN KEY (device_id) REFERENCES devices(id)
);

