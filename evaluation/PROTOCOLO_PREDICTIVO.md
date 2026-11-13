# Protocolo predictivo SIPSA (`protocolo-predictivo-v1`)

Proyecto de David Bonilla. Fuente de los datos: DANE, SIPSA. Es un protocolo **interno**, fijado antes de estimar ningún modelo con datos reales. No es una prerregistración externa.

La versión legible por máquina es `config/protocolo.json`, y prevalece sobre este texto si hubiera diferencias. La fecha y las huellas del congelamiento (protocolo, configuración, entradas y código) quedan en `resultados/registro_protocolo.json`, escrito por `python -m evaluacion congelar`. La ejecución se niega a correr si el protocolo cambió después de congelarlo.

## 1. Pregunta

¿Incorporar abastecimiento rezagado mejora el pronóstico del precio mayorista mensual frente a utilizar solo precios pasados, para los 10 productos y 3 mercados del lote aprobado?

Es una evaluación **predictiva y retrospectiva**:

- No estima efectos causales.
- No se extiende a precios minoristas, gasto de los hogares ni a toda Colombia.
- No atribuye ahorros.

## 2. Entrada

La entrada es el lote vigente del proyecto de ingeniería v2.1, leído con su mecanismo oficial:

- `APROBADO.json` y verificación SHA-256 completa del manifiesto;
- lote esperado: `lote-20261111T192146Z-0dba2228adae`;
- huella de contenido `0dba2228…`.

La lectura falla si no se cumple alguno de estos hechos:

- 2.880 celdas;
- 2.878 precios presentes;
- 2.880 volúmenes presentes;
- 30 series;
- 96 meses (2018-01 a 2025-12);
- 10 mercado-mes con aviso de imputación.

El lote no se modifica.

## 3. Objetivo, horizonte y calendario

- **Origen `t`:** cierre del mes calendario `t`, en `America/Bogota`.
- **Objetivo:** precio publicado del mes `t+1`, en COP/kg.
- **Escenario principal `retro_r1`:** al cierre de `t` se conocen precios y volúmenes hasta `t−1`. Se predice `t+1` desde una última observación de `t−1`; no se dispone del precio de `t`.
- **Sensibilidades:**
  - `retro_r2`: ambos componentes hasta `t−2`;
  - `retro_p1_a2`: precios hasta `t−1` y abastecimiento hasta `t−2`.

  Son supuestos retrospectivos, no fechas históricas observadas.
- **Periodos:**
  - historia inicial: 2018–2022;
  - **selección:** meses objetivo 2023-01 a 2023-10 (orígenes 2022-12 a 2023-09);
  - **separación no usada para seleccionar:** 2023-11 y 2023-12;
  - **evaluación final:** meses objetivo 2024-01 a 2025-12 (orígenes 2023-12 a 2025-11).
- **Refinamiento del esquema anual.** El primer objetivo de evaluación, 2024-01, se emite al cierre de 2023-12. Con retrasos de hasta 2 meses, la última etiqueta conocida entonces es 2023-10. Por eso la selección termina en el objetivo 2023-10, y todos sus errores ya habrían estado disponibles en ese origen en cualquier escenario.
- **Entrenamiento:**
  - en cada origen se reajusta con ventana expansiva;
  - un ejemplo con mes objetivo `m` solo entra si `m ≤ t − retraso_precio` y su precio fue observado;
  - sus variables se calculan en su propio origen `m−1`, con la disponibilidad del escenario;
  - imputación y estandarización se ajustan solo con esas filas;
  - los parámetros se congelan tras la selección y no se reajustan con errores de 2024–2025.

La tabla de orígenes se exporta en `auditoria_temporal.csv`.

## 4. Variables (exactas)

Notación:

- `L = t'−retraso_precio` y `S = t'−retraso_abastecimiento`, con `t' = m−1`;
- `B` es el último precio observado en `L`, `L−1` o `L−2`;
- el objetivo transformado es `y = ln(p_m/B)`, y el pronóstico, `B·exp(ŷ)`.

| Bloque | Variables |
|---|---|
| Precio (6) | `d1 = ln p_L − ln p_{L−1}`; `d2 = ln p_{L−1} − ln p_{L−2}`; `dev_ma6 = ln p_L − ln mean(p_{L−5..L})`; `dev_ma12 = ln p_L − ln mean(p_{L−11..L})`; `estacional = ln p_{m−12} − ln B`; `mov_estacional = ln p_{m−12} − ln p_{L−12}` |
| Calendario (2) | seno y coseno del mes objetivo |
| Identidades (13) | indicadoras de producto (10) y mercado (3) |
| Indicadores (2) | `falta_precio_ventana`, `base_rezagada` |
| Abastecimiento (5, solo en variantes con volumen) | `nivel_rel12 = ln q_S − ln mean(q_{S−11..S})`; `cambio_1 = ln q_S − ln q_{S−1}`; `cambio_12 = ln q_S − ln q_{S−12}`; `trim_vs_anio_ant = ln mean(q_{S−2..S}) − ln mean(q_{S−14..S−12})`; `falta_abast_ventana` |

Hay 23 variables sin volumen y 28 con volumen.

**Regla de ventana completa.** Las ventanas `L−12..L`, `m−12` y `S−14..S` deben existir en la malla. Se aplica igual a modelos con y sin volumen dentro de cada escenario, para que las comparaciones usen exactamente las mismas filas.

## 5. Faltantes y anomalías

- **Etiquetas ausentes:** no se rellenan. Se excluyen con motivo `objetivo_ausente`.
- **Variables con valor ausente:** quedan NaN y se imputan con la mediana de entrenamiento del origen, más un indicador de ausencia. Las columnas originales y las del modelo se guardan por separado.
- **Fila sin base `B`:** se excluye con motivo `sin_base`.
- **Fila sin `p_{m−12}`:** se excluye para todos los modelos.
- **Volúmenes:**
  - un volumen ausente nunca es cero;
  - no se eliminan extremos ni repeticiones;
  - no se ajustan discrepancias oficiales.
- **Avisos oficiales de imputación:** no son variables. Solo estratifican resultados, porque su fecha de publicación no está demostrada.

## 6. Modelos y búsqueda

Las seis alternativas son:

- ingenuo: `B`;
- estacional: `p_{m−12}`;
- Ridge sin y con volumen;
- Random Forest sin y con volumen.

Los modelos aprendidos son **conjuntos** para las 30 series, en cada familia, variante, escenario y origen.

Rejillas (seis configuraciones por familia y variante, el mismo presupuesto con y sin volumen):

- **Ridge:** `alpha ∈ {0,01; 0,1; 1; 10; 100; 1000}`.
- **Random Forest:** `max_depth ∈ {4, 8, sin límite} × min_samples_leaf ∈ {5, 20}`, con 300 árboles, `max_features = 0,5` y semilla 20261111.

**Selección (`retro_r1`, objetivos 2023-01..10):**

- se elige la configuración con menor MASE medio entre series; en empate, la más regularizada;
- el **referente** es el mejor entre ingenuo y estacional, por el mismo criterio;
- la **familia principal** es la que tiene menor MASE de selección en su variante sin volumen, y su contraste con/sin volumen es el principal.

Los parámetros se escriben en `parametros_congelados.json` antes de pronosticar 2024–2025.

## 7. Métricas

**Principal: MASE estacional (m = 12).**

- **Escala:** la media de `|p_k − p_{k−12}|` con ambos precios observados y `k ≤ t − retraso_precio`, es decir, solo la historia disponible en el origen. Es la misma para todos los modelos de esa serie y origen.
- **Escala inválida:** si hay menos de 24 pares o la escala es cero, la fila se excluye con motivo `escala_invalida`.
- **MASE de una serie:** la media de `|e|/q` sobre sus orígenes.
- **Resumen:** media simple entre las 30 series, con igual peso por serie; también la mediana.

Medidas adicionales:

- MAE en COP/kg por serie;
- error firmado en COP/kg y en %;
- diferencia de MASE con y sin volumen por serie;
- cortes por producto, mercado, año y mes;
- proporción de series en las que cada modelo mejora al referente.

No se usa MAPE como única medida ni un MAE global entre series.

## 8. Contrastes y comunicación

- **Aporte del volumen:** con volumen frente a sin volumen, sobre las mismas filas, con parámetros propios.
- **Controlado:** con volumen usando los parámetros de la variante sin volumen.
- **Etiquetas fijadas de antemano**, según el cambio relativo del MASE medio:
  - **despreciable** si es menor de 2 %;
  - **mejora consistente** si es de −2 % o más, mejora al menos 20 de 30 series y mantiene el signo en 2024, en 2025 y en la comparación controlada;
  - en otro caso, mejora pequeña, concentrada o inestable.
- **Inferencia:** no se calculan p-valores que traten series y meses como independientes. Se priorizan magnitud, proporción de series y estabilidad.

## 9. Sensibilidades (con los parámetros congelados)

1. Escenarios `retro_r2` y `retro_p1_a2`.
2. Objetivos en mercado-mes con aviso de imputación frente a objetivos sin aviso.
3. Copia derivada que excluye de la evaluación las filas cuya ventana de volumen `S−14..S` contiene un mercado-mes con aviso, con todos los modelos sobre el mismo subconjunto.

No se buscarán especificaciones nuevas.

## 10. Figuras

Habrá como máximo tres, con diseño fijado aquí:

1. **Precisión:** MASE de evaluación (`retro_r1`) por modelo, con un punto por serie y la media.
2. **Aporte del volumen:** diferencia de MASE por serie (con − sin volumen) en la familia principal, ordenada, junto a la comparación controlada.
3. **Estabilidad:** diferencia media de MASE (con − sin volumen) por año (2024, 2025) y escenario, para ambas familias. Las series ilustrativas se fijaron antes de ver errores (`config/protocolo.json`):

- plátano hartón verde en Corabastos;
- limón Tahití en Centroabastos;
- lechuga Batavia en la CMA.

## 11. Cambios posteriores al congelamiento

Cualquier cambio se registrará en `resultados/registro_cambios.md` con su motivo y con lo que ya se hubiera visto de los resultados.
