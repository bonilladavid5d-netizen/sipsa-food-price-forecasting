-- Panel mensual auditado: malla completa producto x mercado x mes. Los huecos quedan NULL, nunca cero.
CREATE TABLE panel_mensual AS
WITH meses AS (
  SELECT strftime(m, '%Y-%m') AS month FROM range(DATE '2018-01-01', DATE '2026-01-01', INTERVAL 1 MONTH) t(m)
), malla AS (
  SELECT meses.month, mk.market_id, mk.label AS market, pr.product_id, pr.label AS product, pr.grupo
  FROM meses CROSS JOIN market mk CROSS JOIN product pr
)
SELECT g.month,
       CAST(substr(g.month, 1, 4) AS INTEGER) * 12 + CAST(substr(g.month, 6, 2) AS INTEGER) - 1 AS mes_idx,
       g.market_id, g.market, g.product_id, g.product, g.grupo,
       p.price, p.snapshot_id AS price_snapshot_id, p.source_sheet AS price_source_sheet, p.source_row AS price_source_row,
       CAST(s.kg AS DOUBLE) AS kg, s.kg AS kg_exacto, s.snapshot_id AS supply_snapshot_id, s.source_rows AS supply_source_rows,
       p.price IS NOT NULL AS price_present, s.kg IS NOT NULL AS supply_present,
       CAST(NULL AS TIMESTAMPTZ) AS historical_available_at,
       'current_snapshot' AS vintage_status,
       a.month IS NOT NULL AS source_month_has_imputation_notice
FROM malla g
LEFT JOIN (SELECT * FROM price_month WHERE snapshot_id IN (SELECT snapshot_id FROM snapshot_retrospectivo)) p
       ON p.product_id = g.product_id AND p.market_id = g.market_id AND p.month = g.month
LEFT JOIN (SELECT * FROM supply_month WHERE snapshot_id IN (SELECT snapshot_id FROM snapshot_retrospectivo)) s
       ON s.product_id = g.product_id AND s.market_id = g.market_id AND s.month = g.month
LEFT JOIN aviso_imputacion a ON a.market_id = g.market_id AND a.month = g.month
ORDER BY g.month, g.market_id, g.product_id;
