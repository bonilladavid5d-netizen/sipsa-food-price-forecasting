-- Ejemplos de entrenamiento utilizables al cierre de $origen con horizonte $h meses (escenario $escenario).
-- Una etiqueta (precio del mes objetivo m) solo puede usarse si ya estaba disponible en el origen:
--   m <= origen - retraso_precio.
-- Sus variables corresponden al pronóstico emitido al cierre de m - h y respetan el mismo escenario:
--   precios hasta m - h - retraso_precio; abastecimiento hasta m - h - retraso_abastecimiento.
WITH e AS (SELECT * FROM politica_temporal WHERE escenario_id = $escenario),
o AS (SELECT CAST(substr($origen, 1, 4) AS INTEGER) * 12 + CAST(substr($origen, 6, 2) AS INTEGER) - 1 AS idx)
SELECT p.product_id, p.market_id, p.month AS mes_objetivo, p.mes_idx AS mes_objetivo_idx, p.price AS etiqueta,
       p.mes_idx - $h AS origen_del_ejemplo_idx,
       p.mes_idx - $h - e.retraso_precio_meses AS ultimo_mes_precio_variables_idx,
       p.mes_idx - $h - e.retraso_abastecimiento_meses AS ultimo_mes_abastecimiento_variables_idx,
       e.escenario_id, 'supuesto' AS base
FROM price_month p, e, o
WHERE p.mes_idx <= o.idx - e.retraso_precio_meses
  AND p.snapshot_id IN (SELECT snapshot_id FROM snapshot_retrospectivo)
ORDER BY p.product_id, p.market_id, p.month;
