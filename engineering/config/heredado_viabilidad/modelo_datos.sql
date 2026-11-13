-- Prototype executed with SQLite 3. No server required for this feasibility panel.
PRAGMA foreign_keys = ON;
CREATE TABLE source_snapshot (
 snapshot_id TEXT PRIMARY KEY, component TEXT NOT NULL CHECK(component IN ('precios','abastecimiento')),
 source_year INTEGER NOT NULL, url TEXT NOT NULL, sha256 TEXT NOT NULL CHECK(length(sha256)=64),
 retrieved_at TEXT NOT NULL, relative_path TEXT NOT NULL, bytes INTEGER NOT NULL CHECK(bytes>0)
);
CREATE TABLE product (
 product_id TEXT PRIMARY KEY, label TEXT NOT NULL UNIQUE,
 price_unit TEXT NOT NULL CHECK(price_unit='COP/kg'), quantity_unit TEXT NOT NULL CHECK(quantity_unit='kg')
);
CREATE TABLE market (market_id TEXT PRIMARY KEY, label TEXT NOT NULL UNIQUE);
CREATE TABLE product_crosswalk (
 component TEXT NOT NULL, raw_label TEXT NOT NULL, product_id TEXT NOT NULL REFERENCES product,
 rule TEXT NOT NULL, PRIMARY KEY(component,raw_label)
);
CREATE TABLE price_month (
 product_id TEXT NOT NULL REFERENCES product, market_id TEXT NOT NULL REFERENCES market,
 month TEXT NOT NULL CHECK(month GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]' AND substr(month,6,2) BETWEEN '01' AND '12'),
 snapshot_id TEXT NOT NULL REFERENCES source_snapshot,
 price REAL NOT NULL CHECK(price>0), source_sheet TEXT NOT NULL, source_row INTEGER NOT NULL CHECK(source_row>0),
 published_at TEXT, first_seen_at TEXT NOT NULL,
 PRIMARY KEY(product_id,market_id,month,snapshot_id)
);
CREATE TABLE supply_month (
 product_id TEXT NOT NULL REFERENCES product, market_id TEXT NOT NULL REFERENCES market,
 month TEXT NOT NULL CHECK(month GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]' AND substr(month,6,2) BETWEEN '01' AND '12'),
 snapshot_id TEXT NOT NULL REFERENCES source_snapshot,
 kg REAL NOT NULL CHECK(kg>=0), source_rows INTEGER NOT NULL CHECK(source_rows>0),
 published_at TEXT, first_seen_at TEXT NOT NULL,
 PRIMARY KEY(product_id,market_id,month,snapshot_id)
);
CREATE INDEX price_asof ON price_month(product_id,market_id,month,first_seen_at);
CREATE INDEX supply_asof ON supply_month(product_id,market_id,month,first_seen_at);
-- Publish/retrieval dates remain different. NULL published_at is deliberate.
