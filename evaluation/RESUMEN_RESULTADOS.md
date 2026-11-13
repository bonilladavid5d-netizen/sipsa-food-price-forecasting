# Resumen de resultados: evaluación predictiva SIPSA (revisión v2)

David Bonilla · 11 de noviembre de 2026 · Fuente de los datos: DANE, SIPSA. Evaluación retrospectiva con protocolo interno congelado antes de estimar. La revisión v2 corrige controles y redacción; las predicciones no cambian.

## Pregunta

¿Mejora el pronóstico del precio mayorista mensual (10 productos × 3 mercados) si al historial de precios se añade abastecimiento rezagado?

Se pronostica al cierre del mes `t` para `t+1`; en `retro_r1` hay precios y volúmenes hasta `t−1`. Se evalúan 718 de 720 objetivos de 2024–2025 (dos ausentes en la fuente, sin imputar).

## Mejor comparación

MASE estacional medio, con peso igual por serie (menor es mejor):

| Modelo | MASE 2024–25 | 2024 | 2025 | Series mejores que el referente |
|---|---|---|---|---|
| Último precio (referente elegido en 2023) | 1,070 | 1,121 | 1,017 | — |
| Mismo mes del año anterior | 1,297 | 1,422 | 1,170 | 12/30 |
| Ridge (precios) | 0,961 | 0,986 | 0,938 | 19/30 |
| **Random Forest (precios)**, familia principal | **0,934** | 0,953 | 0,915 | **21/30** |
| Random Forest (+ abastecimiento) | 0,939 | 0,965 | 0,913 | 21/30 |
| Ridge (+ abastecimiento) | 0,964 | 0,990 | 0,940 | 19/30 |

Random Forest con precios y calendario reduce el MASE medio frente al último precio un **12,67 %** en el conjunto de 2024–2025: **14,97 %** en 2024 y **10,00 %** en 2025. También mejora en los otros escenarios (`retro_r2`: 1,072 frente a 1,262). El alcance es parcial:

- en 2025 supera al referente en 17 de 30 series;
- la **mediana del MAE por serie empeora**: 497,44 frente a 481,73 COP/kg (+3,26 %). El MASE y el MAE ponderan distinto las series;
- el **error porcentual firmado medio** es +6,92 %. Indica sobreestimación en promedio, pero no en todas las series: el error firmado medio en COP/kg es positivo en 20 de 30.

## Aporte del abastecimiento

Con estas variables, modelos y escenarios, **el abastecimiento no aportó una mejora material observada**:

- **Random Forest:** el MASE cambia +0,47 % (0,9345 frente a 0,9389). Mejora 13 de 30 series; por año, +0,011 en 2024 y −0,002 en 2025.
- **Ridge:** el MASE cambia +0,31 % y mejora 9 de 30 series.
- Se eligieron los mismos parámetros con y sin volumen: la comparación controlada coincide.
- Escenarios alternativos: Random Forest −0,25 % (`retro_r2`) y +0,44 % (`retro_p1_a2`); Ridge +0,44 % y +0,31 %.

Todo queda dentro de ±2 %, un **criterio práctico interno**, no una prueba de equivalencia estadística ni un umbral económico. No demuestra que el abastecimiento carezca de información en otros modelos o frecuencias.

## Heterogeneidad

El volumen ayudó más en banano criollo y piña gold en Centroabastos (−0,045 y −0,028), con mejoras que dependen de un año. Frente al último precio, los modelos ganan en guayaba pera, limón Tahití, arveja y habichuela, y pierden en banano criollo y plátano hartón verde.

## Sensibilidades

- Objetivos con aviso de imputación (50): 0,883 con volumen y 0,885 sin volumen.
- Sin avisos en la ventana de volumen (140 de 718, subconjunto seleccionado, no robustez general): 1,160 frente a 1,151.

## Verificación

- **Linux (revisión independiente):** se reejecutó el núcleo desde el panel CSV auditado; no la CLI completa, el cargador DuckDB ni la reconstrucción de fuentes. Las 25.080 predicciones coinciden dentro de la precisión de exportación, con los mismos parámetros.
- **Mac (v2):** controles reforzados; tablas y cifras recalculadas desde las predicciones; una reejecución con el código v2 reproduce las mismas predicciones.

## Límites

- Disponibilidad **supuesta**: no hay fechas históricas de publicación verificadas.
- **No se calculó inferencia estadística** (ni intervalos ni pruebas); se informan magnitudes, proporciones de series y estabilidad.
- No es causal, no se extiende a precios minoristas, hogares ni todo el país, y no estima ahorros (falta una regla de compra).

## Recomendación

1. Piloto mensual con el modelo conjunto **sin abastecimiento**, comparado contra el último precio por serie.
2. No incorporar el volumen con estas variables salvo evidencia prospectiva.
3. Antes de usarlo en compras: vigilar el sesgo, definir una regla de decisión con costos y capturar datos fechados.
