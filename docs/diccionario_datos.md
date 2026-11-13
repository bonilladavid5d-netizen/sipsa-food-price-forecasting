# Diccionario de datos

Las tablas están en [`evaluation/resultados/`](../evaluation/resultados/).

- Meses en formato `AAAA-MM`; precios en COP/kg; volúmenes en kg.
- Los decimales se exportan con 10 cifras significativas.
- Escenarios: `retro_r1` (principal: precios y volúmenes hasta `t−1`), `retro_r2` (ambos hasta `t−2`) y `retro_p1_a2` (precios hasta `t−1` y volumen hasta `t−2`).

**Modelos:**

| Código | Modelo |
|---|---|
| `ingenuo` | último precio conocido |
| `estacional` | mismo mes del año anterior |
| `ridge_precio` / `rf_precio` | Ridge o Random Forest con historia de precios, calendario e identidades |
| `ridge_abast` / `rf_abast` | lo mismo más 5 variables de abastecimiento |
| `*_abast_ctrl` | comparación controlada: con abastecimiento y los parámetros de la variante sin abastecimiento |

## `predicciones.csv`: 17.280 filas (3 escenarios × 8 modelos × 24 orígenes × 30 series)

> **No se distribuye.** Contiene precios del DANE: `observado`, `B` y `p_estacional`; `predicho − error` reproduce el precio observado, y los pronósticos ingenuo y estacional son precios anteriores. Se genera localmente en el modo B de [reproduccion.md](reproduccion.md). Lo mismo vale para `seleccion/predicciones_seleccion.csv`, con 7.800 filas de 2023. La huella aprobada de ambos archivos está en `evaluation/resultados/revision_distribucion_etapa1_v2.json`.

| Columna | Significado |
|---|---|
| `modelo`, `config` | Modelo y parámetros congelados |
| `escenario`, `fase` | Escenario de disponibilidad; `evaluacion` |
| `origen`, `emision` | Mes `t` y su cierre en hora de Colombia, cuando se emite el pronóstico |
| `objetivo` | Mes pronosticado (`t+1`) |
| `product_id`, `market_id`, `product`, `market` | Identidad de la serie |
| `observado`, `predicho` | Precio publicado por el DANE y precio pronosticado (COP/kg) |
| `estado_evaluacion`, `motivo_exclusion` | `evaluada` o `excluida`; motivo, por ejemplo `objetivo_ausente` |
| `error` | `predicho − observado`. Los verificadores lo recalculan y no confían en esta columna. |
| `escala_mase`, `pares_escala` | Escala MASE estacional con la historia disponible en el origen y número de pares usados |
| `error_abs_escalado` | `|error| / escala_mase` |
| `B`, `mes_base` | Último precio observado usado como base y su mes |
| `p_estacional` | Precio del mismo mes del año anterior |
| `ultimo_mes_precio_usado`, `ultimo_mes_abast_usado` | Último mes de precio y de volumen usados por las variables |
| `n_entrenamiento`, `ultima_etiqueta_entrenamiento` | Filas de entrenamiento del origen y último mes objetivo con etiqueta |
| `aviso_objetivo`, `aviso_en_ventana_abast` | Aviso oficial de imputación en el mes objetivo o en la ventana de volumen. Solo estratifica. |

## Métricas

| Archivo | Contenido |
|---|---|
| `metricas_por_serie.csv` (720 filas) | Por escenario, modelo y serie: `n`, `mase`, `mae_cop_kg`, `error_firmado_cop_kg` y `error_firmado_pct` (media de `error/observado × 100`) |
| `metricas_resumen.csv` (792 filas) | Por escenario, modelo y `corte` (`global`, `anio`, `producto`, `mercado`, `mes_calendario`, `aviso_objetivo`, `aviso_en_ventana_abast`, `sensibilidad_sin_aviso_en_ventana_abast`): media y mediana del MASE entre series, error firmado medio en % y proporción de series mejores que el referente |
| `aporte_abastecimiento.csv` (1.080 filas) | Por escenario, familia, `tipo` (`parametros_propios` o `parametros_comunes_controlada`), `anio` (`todos`, `2024`, `2025`) y serie: MASE y MAE con y sin abastecimiento, `delta_mase` (con − sin; negativo significa que el volumen ayuda) y parámetros |
| `cifras_resumen.json` | Cifras citadas en el resumen, recalculadas desde las predicciones |

## Auditoría y flujo

| Archivo | Contenido |
|---|---|
| `auditoria_temporal.csv` (82 filas) | Por escenario, fase y origen: límites permitidos (precio, volumen, etiqueta) y meses efectivamente usados. Los verificadores recalculan los límites; `cumple` no se usa como evidencia. |
| `flujo_observaciones.csv` | Conteos desde la malla de 2.880 celdas hasta entrenamiento y evaluación, con filas perdidas por ventanas y etiquetas ausentes |
| `seleccion/` | Selección con objetivos 2023-01..10: métricas por configuración y `parametros_congelados.json`. Las 7.800 predicciones de selección se generan localmente. |
| `registro_protocolo.json`, `revision_mantenimiento_v2.json`, `revision_publicacion_etapa1.json`, `revision_distribucion_etapa1_v2.json` | Congelamiento del protocolo y revisiones posteriores vinculadas por SHA-256. La última fija las huellas de las tablas publicadas y de los archivos retirados. |

## Referencias de ingeniería (no se distribuyen)

Los contratos de ingeniería comparan el lote reconstruido con tres referencias de la fase de viabilidad:

| Referencia | Contenido |
|---|---|
| `referencia_panel_viabilidad.csv` | 2.880 celdas con `price`, `kg` y procedencia |
| `referencia_conciliacion_viabilidad.csv` | 288 totales mercado–mes con `official_tonnes` y `microdata_kg` |
| `referencia_candidatos_viabilidad.csv` | Cobertura y `training_kg` por producto |

Contienen series del DANE, así que no se distribuyen. `engineering/herramientas/reconstruir_referencias.py` las regenera desde las fuentes oficiales con la lógica original de la viabilidad, y solo las escribe si su SHA-256 coincide con el aprobado en `engineering/config/referencia_viabilidad.json`.
