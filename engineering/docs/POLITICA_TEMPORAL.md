# Política temporal `politica-temporal-v2`

Un corte `t` es un pronóstico emitido **al cierre del mes calendario t** para el precio mensual de `t+h`.

**Convención única (v2, D-17).** El cierre del mes calendario `t` es el último microsegundo antes de las 00:00 del día 1 de `t+1`, en hora de Colombia (`America/Bogota`, UTC−05:00). Por ejemplo, `cierre_mes("2023-07") = 2023-07-31T23:59:59.999999-05:00`. Reemplaza la mención heredada de "último día hábil": con datos mensuales y retrasos en meses no cambia el conjunto permitido, y evita un calendario de festivos. DuckDB trabaja con `TimeZone = America/Bogota` fijado, no con la zona del sistema. Para cortes estrictos use `sipsa estricto --mes YYYY-MM`. Las fechas desconocidas siguen siendo desconocidas: ningún lote rellena `published_at` ni `historical_release_at`.

## Dos políticas separadas

1. **Estricta observada** (`sql/consulta_asof_estricta.sql`). Solo usa versiones que este sistema capturó (`first_seen_at`) antes del instante de corte. Desde v2, `first_seen_at` es el `retrieved_at` de `config/capturas_aprobadas.json`. Esa referencia procede de los JSON laterales verificados contra el manifiesto de los ZIP congelados, y un JSON alterado bloquea la ejecución. Hay contratos con cortes 1 µs antes y exactamente en cada una de las 16 capturas con celdas. Las 17 capturas son del 11-11-2026, así que cualquier corte anterior devuelve cero filas. Ese resultado es el correcto. Esta política servirá para evaluaciones prospectivas reales cuando haya capturas periódicas.
2. **Escenarios retrospectivos supuestos** (`sql/consulta_escenario.sql`). No usan `first_seen_at` y operan sobre **una única versión por componente/año** (`snapshot_retrospectivo`, D-22). Retrasos declarados y versionados en `config/politica_temporal.json`, también presentes en la tabla `politica_temporal`. La base rechaza un escenario con retraso 0 o rotulado como `observado`.

| Escenario | Precio disponible hasta | Abastecimiento hasta | Uso previsto |
|---|---|---|---|
| `retro_r1` | t-1 | t-1 | Escenario inicial de la viabilidad |
| `retro_r2` | t-2 | t-2 | Sensibilidad conservadora |
| `retro_p1_a2` | t-1 | t-2 | El microdato de abastecimiento llega después que el boletín de precios |

Las etiquetas de entrenamiento siguen la misma regla (`sql/etiquetas_disponibles.sql`): al cierre de t solo se puede entrenar con precios objetivo de meses ≤ t − retraso_precio. Las variables de cada ejemplo respetan el retraso desde su propio origen. Un contrato recorre los 96 cortes de 2018-2025 en los tres escenarios (288 consultas) y no encuentra información futura.

## Ejemplos concretos (`evidencia/ejemplos_disponibilidad_corte.csv`)

| Cierre de | Objetivo | Escenario | Último precio | Último abastecimiento | Última etiqueta |
|---|---|---|---|---|---|
| 2023-07 | 2023-08 | `retro_r1` | 2023-06 | 2023-06 | 2023-06 |
| 2023-07 | 2023-08 | `retro_p1_a2` | 2023-06 | 2023-05 | 2023-06 |
| 2023-07 | 2023-08 | `retro_r2` | 2023-05 | 2023-05 | 2023-05 |
| 2023-07 | 2023-08 | estricto | — (0 filas) | — | — |
| 2025-11 | 2025-12 | `retro_r1` | 2025-10 | 2025-10 | 2025-10 |

En ningún escenario están disponibles el promedio del mes de corte ni el del mes objetivo. Las 360 celdas de abastecimiento de 2018 quedan marcadas: la difusión de microdatos solo está documentada desde 2019.

## Tabla de disponibilidad por canal (`config/canales_disponibilidad.csv`)

| Canal | Regla documentada | Estado tras esta fase |
|---|---|---|
| Boletín mensual de precios | Día hábil posterior al IPC (Metodología SIPSA-P 2022, p. 16) | Regla, no fecha por archivo |
| Boletín mensual de abastecimiento | Día 20 del mes siguiente o hábil posterior (SIPSA-A 2023, p. 22) | Regla, no fecha por archivo |
| Microdato anual de abastecimiento | Difusión desde 2019 (SIPSA-A 2023, p. 8) | Inicio documentado; sin calendario por versión |
| Serie histórica de precios (XLSX) | Sin calendario recuperado | Captura actual, sin vintage |
| Servicio web SOAP, precios y abastecimiento | Día 8 y día 10 de cada mes (guía SOAP) | **Accesible el 11-11-2026**, sin fechas por registro y no equivalente al XLSX (ver abajo) |

## Comprobación del servicio web (nuevo en esta fase)

En viabilidad el WSDL devolvía HTTP 500. El 11-11-2026 a las 17:20 UTC respondió HTTP 200 por http y https. El servicio exige SOAP 1.2 (`application/soap+xml`); con SOAP 1.1 responde 415. Se hizo una sola consulta de lectura a cada operación mensual: `promediosSipsaMesMadr` (199.004 registros, 59,6 MB) y `promedioAbasSipsaMesMadr` (167.685 registros, 40,9 MB). Las respuestas se guardan con su SHA-256 en `evidencia/servicio_web/`. El resultado del contraste está en `contraste_servicio_web.json` y el detalle por celda en `contraste_celdas.csv`:

- **No aporta fechas de disponibilidad.** El XSD declara `fechaCreacion`, pero no viene con valor en ninguno de los 366.689 registros.
- **Ventana parcial.** Los precios cubren de 2023-02 a 2026-10 (41 meses) y el abastecimiento de 2020-02 a 2026-09 (58 meses, con huecos).
- **Precios.** 899 de 959 celdas comparables de la canasta son idénticas al XLSX. En 2024-12 el servicio trae dos registros por celda (30 celdas). En 2025-08 los valores difieren hasta un 9,4 % en 29 celdas, y en 2025-07 en una. Puede ser una revisión o un cálculo distinto; no se sabe cuál de las dos.
- **Abastecimiento.** 1.295 de 1.521 celdas coinciden dentro de 0,5 t. Las 226 restantes se concentran en meses completos (2023-04, 2023-08, 2023-12, 2024-04, 2024-08, 2024-12, 2025-04) con valores de 0–1 t frente a cientos o miles de toneladas en el microdato. Parecen cargas parciales.

**Decisión D-15.** El servicio no se incorpora al panel ni como fuente de fechas. Es candidato a canal de **captura prospectiva**, guardando cada respuesta fechada. Antes habría que resolver los duplicados, las cargas parciales y la diferencia de 2025-08. Un mes del servicio no se usará sin conciliarlo primero contra el microdato.
