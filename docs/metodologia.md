# Metodología

El protocolo completo, congelado antes de estimar el 11-11-2026 a las 21:30:54 UTC (registro interno, no una prerregistración externa), está en [`evaluation/PROTOCOLO_PREDICTIVO.md`](../evaluation/PROTOCOLO_PREDICTIVO.md) y [`evaluation/config/protocolo.json`](../evaluation/config/protocolo.json).

## Calendario y disponibilidad

- **Emisión:** al cierre del mes calendario `t` (`America/Bogota`). **Objetivo:** el precio de `t+1`.
- **`retro_r1`:** precios y volúmenes hasta `t−1`. Se predice `t+1` desde una última observación de `t−1`, no desde el precio contemporáneo de `t`.
- **Periodos:**
  - historia inicial: 2018–2022;
  - **selección:** objetivos 2023-01..10;
  - 2023-11 y 2023-12 quedan como separación, para que todo error usado en la selección esté disponible en el primer origen de evaluación;
  - **evaluación final:** objetivos 2024-01..2025-12, con 24 orígenes.
- **Entrenamiento:** en cada origen se reentrena con ventana expansiva y parámetros congelados. Un ejemplo solo entra si su etiqueta ya estaba disponible. Sus variables se calculan en su propio origen, e imputación y estandarización se ajustan solo con esas filas.

## Variables (23 sin abastecimiento, 28 con abastecimiento)

| Bloque | Variables |
|---|---|
| Precio | Cambios recientes, desvíos frente a medias de 6 y 12 meses, referencia estacional y su movimiento |
| Calendario | Seno y coseno del mes |
| Identidades | Producto (10) y mercado (3) |
| Indicadores | Ausencia de precio en la ventana; base rezagada |
| Abastecimiento | Nivel relativo a 12 meses, cambio mensual, cambio interanual, trimestre frente al año anterior, ausencia en la ventana |

El objetivo transformado es `ln(p_objetivo / B)`, donde `B` es el último precio observado.

## Modelos y selección

- **Alternativas:** último precio y mismo mes del año anterior como referentes; Ridge y Random Forest conjuntos para las 30 series, con y sin abastecimiento.
- **Rejillas:** 6 configuraciones por familia y variante, el mismo presupuesto con y sin volumen. Semilla 20261111.
- **Criterio de selección:** MASE medio entre series sobre los objetivos de 2023.
- **Lo seleccionado:**
  - Ridge con `alpha = 100`;
  - Random Forest con profundidad 8 y hoja mínima 5;
  - los mismos parámetros con y sin abastecimiento;
  - referente: último precio;
  - familia principal: Random Forest.

## Métricas y comunicación

- **Principal:** MASE estacional (m = 12). La escala usa solo la historia disponible en cada origen y es común a los modelos comparados; el MASE se promedia con igual peso por serie.
- **Adicionales:** MAE en COP/kg, error firmado y aporte emparejado con y sin volumen.
- **Umbral para «material»:** ±2 % de cambio relativo del MASE medio. Es un criterio práctico interno, fijado antes de estimar.
- **Inferencia:** no se calculó.

## Sensibilidades fijadas de antemano

- retrasos `retro_r2` y `retro_p1_a2`;
- objetivos en mercado–mes con aviso de imputación frente a los demás;
- subconjunto sin avisos en la ventana de volumen (140 de 718 objetivos; diagnóstico, no robustez general).
