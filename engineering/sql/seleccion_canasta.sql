-- Reproducción en SQL de la regla de selección de la viabilidad (solo cobertura y volumen 2018-2022).
-- Parámetros: $fin_entrenamiento ('2022-12'), $min_meses (54). Mercados y grupos vienen de alcance_mercado / alcance_grupo.
CREATE TABLE candidatos_elegibles AS
WITH p AS (
  SELECT DISTINCT month, mercado, producto, upper(strip_accents(grupo)) AS group_key
  FROM precio_observado
  WHERE mercado IN (SELECT label FROM alcance_mercado)
    AND upper(strip_accents(grupo)) IN (SELECT group_key FROM alcance_grupo)
    AND month <= $fin_entrenamiento
), s AS (
  SELECT month, mercado, producto, sum(kg) AS kg
  FROM abastecimiento_mes_todos
  WHERE mercado IN (SELECT label FROM alcance_mercado)
    AND upper(strip_accents(grupo)) IN (SELECT group_key FROM alcance_grupo)
    AND month <= $fin_entrenamiento
  GROUP BY ALL
), productos AS (
  SELECT producto FROM p UNION SELECT producto FROM s
), cobertura AS (
  SELECT pr.producto, m.label AS mercado,
         (SELECT count(DISTINCT month) FROM p WHERE p.producto = pr.producto AND p.mercado = m.label) AS price_training_months,
         (SELECT count(DISTINCT month) FROM s WHERE s.producto = pr.producto AND s.mercado = m.label) AS supply_training_months,
         (SELECT count(DISTINCT p.month) FROM p JOIN s USING (month, mercado, producto)
           WHERE p.producto = pr.producto AND p.mercado = m.label) AS joint_training_months,
         (SELECT sum(kg) FROM s WHERE s.producto = pr.producto AND s.mercado = m.label) AS supply_training_kg
  FROM productos pr CROSS JOIN alcance_mercado m
), grupos AS (
  SELECT producto, min(group_key) AS group_key, count(DISTINCT group_key) AS n_grupos FROM p GROUP BY producto
)
SELECT c.producto AS product, min(price_training_months) AS min_price_months, min(supply_training_months) AS min_supply_months,
       min(joint_training_months) AS min_joint_months, sum(supply_training_kg) AS training_kg,
       any_value(g.group_key) AS group_key, any_value(g.n_grupos) AS n_grupos
FROM cobertura c LEFT JOIN grupos g USING (producto)
GROUP BY c.producto
HAVING min(joint_training_months) >= $min_meses
ORDER BY min_joint_months DESC, training_kg DESC, product ASC;

CREATE TABLE canasta_reproducida AS
SELECT product, group_key, min_joint_months, training_kg
FROM (
  SELECT e.*, row_number() OVER (PARTITION BY e.group_key ORDER BY min_joint_months DESC, training_kg DESC, product ASC) AS rk
  FROM candidatos_elegibles e
) x JOIN alcance_grupo USING (group_key)
WHERE rk <= cuota;
