-- Información permitida al cierre del mes calendario $origen ('YYYY-MM', hora de Colombia) bajo un escenario
-- retrospectivo declarado. Solo usa la versión retro_vigente de cada componente/año (una por diseño).
-- Es un SUPUESTO de disponibilidad, no una publicación observada. Columna base='supuesto' siempre.
-- Precio: mes <= origen - retraso_precio. Abastecimiento: mes <= origen - retraso_abastecimiento.
WITH e AS (
  SELECT * FROM politica_temporal WHERE escenario_id = $escenario
), o AS (
  SELECT CAST(substr($origen, 1, 4) AS INTEGER) * 12 + CAST(substr($origen, 6, 2) AS INTEGER) - 1 AS idx
)
SELECT 'precio' AS componente, p.product_id, p.market_id, p.month, p.snapshot_id, p.price AS valor,
       e.escenario_id, 'supuesto' AS base,
       p.mes_idx + e.retraso_precio_meses AS disponible_desde_idx
FROM price_month p, e, o
WHERE p.mes_idx <= o.idx - e.retraso_precio_meses
  AND p.snapshot_id IN (SELECT snapshot_id FROM snapshot_retrospectivo)
UNION ALL
SELECT 'abastecimiento', s.product_id, s.market_id, s.month, s.snapshot_id, CAST(s.kg AS DOUBLE),
       e.escenario_id, 'supuesto', s.mes_idx + e.retraso_abastecimiento_meses
FROM supply_month s, e, o
WHERE s.mes_idx <= o.idx - e.retraso_abastecimiento_meses
  AND s.snapshot_id IN (SELECT snapshot_id FROM snapshot_retrospectivo)
ORDER BY componente, product_id, market_id, month;
