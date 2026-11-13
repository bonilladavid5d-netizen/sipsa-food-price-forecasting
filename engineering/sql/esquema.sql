-- Modelo relacional del lote SIPSA (DuckDB). Evoluciona config/heredado_viabilidad/modelo_datos.sql.
-- Claves primarias, foráneas y CHECK se aplican al insertar. published_at queda NULL a propósito:
-- ninguna fecha histórica de publicación ha sido observada.

CREATE TABLE lote_info (clave TEXT PRIMARY KEY, valor TEXT NOT NULL);

CREATE TABLE source_snapshot (
  snapshot_id TEXT PRIMARY KEY,
  component TEXT NOT NULL CHECK (component IN ('precios', 'abastecimiento', 'historico_agregado')),
  source_year INTEGER,
  url TEXT NOT NULL,
  sha256 TEXT NOT NULL UNIQUE CHECK (length(sha256) = 64),
  retrieved_at TIMESTAMPTZ NOT NULL,
  relative_path TEXT NOT NULL,
  bytes BIGINT NOT NULL CHECK (bytes > 0),
  historical_release_at TIMESTAMPTZ,            -- desconocida: NULL, nunca supuesta
  vintage_status TEXT NOT NULL,
  approved_in TEXT NOT NULL,                    -- archivo de configuración que aprobó el contenido
  capture_sidecar_sha256 TEXT NOT NULL CHECK (length(capture_sidecar_sha256) = 64),  -- JSON lateral verificado
  first_seen_basis TEXT NOT NULL,               -- referencia de la que proviene retrieved_at (v2)
  retro_vigente BOOLEAN NOT NULL                -- versión usada por panel y escenarios retrospectivos
);

-- Restricción vigente: UNA versión aprobada por componente/año para panel y escenarios retrospectivos.
-- El modo estricto puede ver varias versiones (elige la última observada antes del corte); los escenarios no.
-- Para admitir una revisión habrá que decidir explícitamente cuál queda retro_vigente (contrato en validar.py).
CREATE VIEW snapshot_retrospectivo AS SELECT * FROM source_snapshot WHERE retro_vigente;

CREATE TABLE market (market_id TEXT PRIMARY KEY, label TEXT NOT NULL UNIQUE);

CREATE TABLE product (
  product_id TEXT PRIMARY KEY,
  label TEXT NOT NULL UNIQUE,
  grupo TEXT NOT NULL,
  price_unit TEXT NOT NULL CHECK (price_unit = 'COP/kg'),
  quantity_unit TEXT NOT NULL CHECK (quantity_unit = 'kg')
);

-- Equivalencias versionadas con vigencia. Una etiqueta de origen apunta a una sola identidad en cada vigencia.
CREATE TABLE product_crosswalk (
  component TEXT NOT NULL CHECK (component IN ('precios', 'abastecimiento')),
  raw_label TEXT NOT NULL,
  product_id TEXT NOT NULL REFERENCES product (product_id),
  rule TEXT NOT NULL,
  cpc_observed TEXT,                            -- auditoría; CPC no es llave suficiente
  version TEXT NOT NULL,
  valid_from_month TEXT NOT NULL CHECK (valid_from_month GLOB '[0-9][0-9][0-9][0-9]-[0-1][0-9]'),
  valid_to_month TEXT CHECK (valid_to_month IS NULL OR valid_to_month >= valid_from_month),
  decision TEXT NOT NULL,
  PRIMARY KEY (component, raw_label, valid_from_month)
);

CREATE TABLE market_crosswalk (
  component TEXT NOT NULL CHECK (component IN ('precios', 'abastecimiento')),
  raw_label TEXT NOT NULL,
  market_id TEXT NOT NULL REFERENCES market (market_id),
  rule TEXT NOT NULL,
  version TEXT NOT NULL,
  valid_from_month TEXT NOT NULL,
  valid_to_month TEXT,
  decision TEXT NOT NULL,
  PRIMARY KEY (component, raw_label, valid_from_month)
);

-- Todos los precios publicados (todas las plazas y productos), con linaje fila a fila.
-- Sin clave única: existen 8 llaves repetidas fuera de la canasta que no se resuelven arbitrariamente.
CREATE TABLE precio_observado (
  snapshot_id TEXT NOT NULL REFERENCES source_snapshot (snapshot_id),
  source_sheet TEXT NOT NULL, source_row INTEGER NOT NULL CHECK (source_row > 0),
  month TEXT NOT NULL, grupo TEXT NOT NULL, producto TEXT NOT NULL, mercado TEXT NOT NULL,
  raw_cpc TEXT, precio_raw TEXT NOT NULL, precio DOUBLE,
  PRIMARY KEY (snapshot_id, source_sheet, source_row)
);

-- Suma mensual de kg de todos los alimentos y plazas (sin deduplicar ingresos), base de conciliación.
CREATE TABLE abastecimiento_mes_todos (
  snapshot_id TEXT NOT NULL REFERENCES source_snapshot (snapshot_id),
  month TEXT NOT NULL, mercado TEXT NOT NULL, producto TEXT NOT NULL, grupo TEXT NOT NULL,
  kg DECIMAL(38, 10), source_rows BIGINT NOT NULL CHECK (source_rows > 0),
  invalid_value_rows BIGINT NOT NULL, nonpositive_rows BIGINT NOT NULL, observed_days INTEGER NOT NULL,
  PRIMARY KEY (snapshot_id, month, mercado, producto, grupo)
);

CREATE TABLE price_month (
  product_id TEXT NOT NULL REFERENCES product (product_id),
  market_id TEXT NOT NULL REFERENCES market (market_id),
  month TEXT NOT NULL CHECK (month GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]' AND substr(month, 6, 2) BETWEEN '01' AND '12'),
  mes_idx INTEGER NOT NULL,
  snapshot_id TEXT NOT NULL REFERENCES source_snapshot (snapshot_id),
  price DOUBLE NOT NULL CHECK (price > 0),
  source_sheet TEXT NOT NULL, source_row INTEGER NOT NULL CHECK (source_row > 0),
  published_at TIMESTAMPTZ, first_seen_at TIMESTAMPTZ NOT NULL,
  PRIMARY KEY (product_id, market_id, month, snapshot_id)
);

CREATE TABLE supply_month (
  product_id TEXT NOT NULL REFERENCES product (product_id),
  market_id TEXT NOT NULL REFERENCES market (market_id),
  month TEXT NOT NULL CHECK (month GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]' AND substr(month, 6, 2) BETWEEN '01' AND '12'),
  mes_idx INTEGER NOT NULL,
  snapshot_id TEXT NOT NULL REFERENCES source_snapshot (snapshot_id),
  kg DECIMAL(38, 10) NOT NULL CHECK (kg >= 0),
  source_rows BIGINT NOT NULL CHECK (source_rows > 0),
  published_at TIMESTAMPTZ, first_seen_at TIMESTAMPTZ NOT NULL,
  PRIMARY KEY (product_id, market_id, month, snapshot_id)
);

CREATE TABLE aviso_imputacion (
  month TEXT NOT NULL, market_id TEXT NOT NULL REFERENCES market (market_id),
  source_sheet TEXT NOT NULL, source_row INTEGER NOT NULL, scope TEXT NOT NULL,
  PRIMARY KEY (month, market_id)
);

CREATE TABLE politica_temporal (
  escenario_id TEXT PRIMARY KEY, version TEXT NOT NULL,
  retraso_precio_meses INTEGER NOT NULL CHECK (retraso_precio_meses >= 1),
  retraso_abastecimiento_meses INTEGER NOT NULL CHECK (retraso_abastecimiento_meses >= 1),
  base TEXT NOT NULL CHECK (base = 'supuesto'),
  descripcion TEXT NOT NULL
);

CREATE TABLE canal_disponibilidad (
  canal TEXT PRIMARY KEY, componente TEXT NOT NULL, regla_documentada TEXT NOT NULL, evidencia TEXT NOT NULL,
  estado_verificacion TEXT NOT NULL, usa_la_receta TEXT NOT NULL, consecuencia TEXT NOT NULL
);

CREATE TABLE conciliacion_totales (
  month TEXT NOT NULL, market TEXT NOT NULL, official_tonnes DOUBLE, source_row INTEGER,
  microdata_kg DECIMAL(38, 10), difference_kg DOUBLE, relative_difference DOUBLE, within_1kg BOOLEAN,
  excepcion_aprobada BOOLEAN NOT NULL,
  PRIMARY KEY (month, market)
);
