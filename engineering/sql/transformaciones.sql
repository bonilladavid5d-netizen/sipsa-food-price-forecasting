-- Hechos mensuales de la canasta a partir del detalle normalizado.
-- Requiere: vista det_abastecimiento (Parquet), tablas de referencia y precio_observado cargadas.

-- 1) Suma mensual de kg de TODO el abastecimiento (sin deduplicar ingresos). La suma se hace en
--    DECIMAL a partir del texto original: es exacta e independiente del orden de lectura.
INSERT INTO abastecimiento_mes_todos
SELECT s.snapshot_id, d.month, d.mercado, d.producto, d.grupo,
       CASE WHEN count(d.kg) = count(*) THEN sum(CAST(d.kg_raw AS DECIMAL(38, 10))) END AS kg,
       count(*) AS source_rows,
       count(*) - count(d.kg) AS invalid_value_rows,
       count(*) FILTER (WHERE d.kg <= 0) AS nonpositive_rows,
       count(DISTINCT d.date) AS observed_days
FROM det_abastecimiento d
JOIN source_snapshot s ON s.sha256 = d.source_sha256 AND s.component = 'abastecimiento'
GROUP BY ALL;

-- 2) Precio mensual de la canasta: correspondencia literal vigente en el mes.
INSERT INTO price_month
SELECT pc.product_id, mc.market_id, p.month,
       CAST(substr(p.month, 1, 4) AS INTEGER) * 12 + CAST(substr(p.month, 6, 2) AS INTEGER) - 1 AS mes_idx,
       p.snapshot_id, p.precio, p.source_sheet, p.source_row,
       NULL AS published_at, s.retrieved_at AS first_seen_at
FROM precio_observado p
JOIN source_snapshot s USING (snapshot_id)
JOIN product_crosswalk pc ON pc.component = 'precios' AND pc.raw_label = p.producto
     AND p.month >= pc.valid_from_month AND (pc.valid_to_month IS NULL OR p.month <= pc.valid_to_month)
JOIN market_crosswalk mc ON mc.component = 'precios' AND mc.raw_label = p.mercado
     AND p.month >= mc.valid_from_month AND (mc.valid_to_month IS NULL OR p.month <= mc.valid_to_month);

-- 3) Abastecimiento mensual de la canasta: suma de subgrupos/CPC solo para la misma etiqueta literal.
INSERT INTO supply_month
SELECT pc.product_id, mc.market_id, a.month,
       CAST(substr(a.month, 1, 4) AS INTEGER) * 12 + CAST(substr(a.month, 6, 2) AS INTEGER) - 1 AS mes_idx,
       a.snapshot_id, sum(a.kg) AS kg, sum(a.source_rows) AS source_rows,
       NULL AS published_at, max(s.retrieved_at) AS first_seen_at
FROM abastecimiento_mes_todos a
JOIN source_snapshot s USING (snapshot_id)
JOIN product_crosswalk pc ON pc.component = 'abastecimiento' AND pc.raw_label = a.producto
     AND a.month >= pc.valid_from_month AND (pc.valid_to_month IS NULL OR a.month <= pc.valid_to_month)
JOIN market_crosswalk mc ON mc.component = 'abastecimiento' AND mc.raw_label = a.mercado
     AND a.month >= mc.valid_from_month AND (mc.valid_to_month IS NULL OR a.month <= mc.valid_to_month)
GROUP BY pc.product_id, mc.market_id, a.month, a.snapshot_id
HAVING count(a.kg) = count(*);
