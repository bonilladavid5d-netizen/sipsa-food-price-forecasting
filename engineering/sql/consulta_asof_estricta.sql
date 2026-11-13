-- Modo estricto: solo lo que ESTE sistema observó antes del corte ($corte, TIMESTAMPTZ ISO).
-- first_seen_at = retrieved_at de config/capturas_aprobadas.json (JSON lateral verificado por SHA-256).
-- Para el corte de un mes use util.cierre_mes('YYYY-MM') o `sipsa estricto --mes`: cierre del mes calendario
-- en hora de Colombia. El mes del corte se calcula con TimeZone = America/Bogota (fijado en la conexión).
-- No se fabrica una fecha histórica a partir del mes, del año del archivo ni de Last-Modified.
-- Devuelve la última versión conocida de cada celda (precio y abastecimiento) con mes anterior al corte.
WITH conocidos AS (
  SELECT 'precio' AS componente, product_id, market_id, month, snapshot_id, first_seen_at, price AS valor FROM price_month
  UNION ALL
  SELECT 'abastecimiento', product_id, market_id, month, snapshot_id, first_seen_at, CAST(kg AS DOUBLE) FROM supply_month
), visibles AS (
  SELECT *, row_number() OVER (PARTITION BY componente, product_id, market_id, month
                               ORDER BY first_seen_at DESC, snapshot_id DESC) AS rn
  FROM conocidos
  WHERE first_seen_at <= CAST($corte AS TIMESTAMPTZ) AND month < strftime(CAST($corte AS TIMESTAMPTZ), '%Y-%m')
)
SELECT componente, product_id, market_id, month, snapshot_id, valor
FROM visibles WHERE rn = 1
ORDER BY componente, product_id, market_id, month;
