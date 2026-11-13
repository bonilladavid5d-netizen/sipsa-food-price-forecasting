-- Conciliación de totales mercado-mes (todos los alimentos) con el histórico agregado del DANE.
INSERT INTO conciliacion_totales
WITH micro AS (
  SELECT month, mercado AS market, sum(kg) AS microdata_kg
  FROM abastecimiento_mes_todos
  WHERE mercado IN (SELECT label FROM alcance_mercado)
  GROUP BY ALL
)
SELECT coalesce(o.month, m.month), coalesce(o.market, m.market), o.official_tonnes, o.source_row,
       m.microdata_kg,
       CAST(m.microdata_kg AS DOUBLE) - o.official_tonnes * 1000 AS difference_kg,
       (CAST(m.microdata_kg AS DOUBLE) - o.official_tonnes * 1000) / (o.official_tonnes * 1000) AS relative_difference,
       abs(CAST(m.microdata_kg AS DOUBLE) - o.official_tonnes * 1000) <= 1 AS within_1kg,
       e.month IS NOT NULL AS excepcion_aprobada
FROM historico_oficial o
FULL OUTER JOIN micro m ON m.month = o.month AND m.market = o.market
LEFT JOIN excepcion_conciliacion e ON e.month = coalesce(o.month, m.month) AND e.market = coalesce(o.market, m.market);
