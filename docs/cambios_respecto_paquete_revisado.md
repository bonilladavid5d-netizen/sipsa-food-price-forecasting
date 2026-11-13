# Diferencias frente al paquete revisado

Paquete anterior: `SIPSA_ETAPA1_PUBLICABLE.zip`, SHA-256 `47df535564ed1bc20c56b15ff77a356c4fb6621da7148a3c5374fb92bc1cbd0b`. Esta revisión (`distribucion-etapa1-v2`) cambia la distribución de datos y la guía de reproducción. **No cambia estimación, exportación, métricas, figuras ni conclusiones.**

## Retirados (5): contienen series del DANE

| Archivo | Contenido | Reconstrucción local |
|---|---|---|
| `engineering/config/referencia_candidatos_viabilidad.csv` | kg acumulados 2018-2022 por producto (training_kg) y cobertura | engineering/herramientas/reconstruir_referencias.py |
| `engineering/config/referencia_conciliacion_viabilidad.csv` | 288 totales mercado-mes: official_tonnes y microdata_kg | engineering/herramientas/reconstruir_referencias.py |
| `engineering/config/referencia_panel_viabilidad.csv` | panel de 2.880 celdas con price (COP/kg) y kg mensuales | engineering/herramientas/reconstruir_referencias.py |
| `evaluation/resultados/predicciones.csv` | precios observados, base B, referencia estacional y pronósticos ingenuo/estacional (reproducen precios); observado = predicho - error | modo B: reconstruir el lote de ingeniería y ejecutar evaluation/reproducir.sh en una copia de trabajo |
| `evaluation/resultados/seleccion/predicciones_seleccion.csv` | mismas columnas de precios para los objetivos de 2023 | igual que predicciones.csv |

Sus huellas aprobadas están en `evaluation/resultados/revision_distribucion_etapa1_v2.json`. Los originales se conservan sin cambios en el expediente privado y no se publican por ninguna otra vía.

## Añadidos (5)

| Archivo | Clase | Propósito |
|---|---|---|
| `engineering/herramientas/reconstruir_referencias.py` | herramienta_validacion | Regenera las 3 referencias de viabilidad y exige sus huellas aprobadas fijas. |
| `evaluation/evaluacion/publico.py` | validacion_codigo | Nuevo: verificación pública sin series del DANE y comparación de una reconstrucción con lo aprobado. |
| `evaluation/herramientas/enmendar_revision_distribucion.py` | herramienta_validacion | Registra una vez la enmienda recalcular-aprobacion en la revisión de distribución. |
| `evaluation/herramientas/registrar_revision_distribucion.py` | herramienta_validacion | Crea la revisión de distribución (una sola vez). |
| `evaluation/resultados/revision_distribucion_etapa1_v2.json` | nuevo | Revisión de distribución |

## Modificados (14)

| Archivo | Clase | Cambio |
|---|---|---|
| `ATRIBUCION_DATOS.md` | documentación | Atribución DANE y condiciones de distribución |
| `README.md` | documentación | Presentación pública |
| `docs/datos_y_procedencia.md` | documentación | Documentación |
| `docs/diccionario_datos.md` | documentación | Documentación |
| `docs/reproduccion.md` | documentación | Modos A y B |
| `docs/validacion_y_revisiones.md` | documentación | Documentación |
| `engineering/README.md` | adaptado_documentacion | Receta de fuentes y referencias. |
| `engineering/sipsa.sh` | ejecucion_empaquetado | construir se detiene con código 3 si faltan las referencias de regresión no distribuidas. |
| `evaluation/README.md` | adaptado_documentacion | Copia pública sin series del DANE; rutas y modos. |
| `evaluation/VALIDACION.md` | adaptado_documentacion | Notas de publicación y de distribución. |
| `evaluation/evaluacion/__main__.py` | validacion_codigo | CLI: verificar-publico y comparar-aprobado; controles y recalcular informan NO EJECUTADO sin datos (código 2); recalcular retira cualquier aprobación anterior antes de comprobar insumos y ante fallos. |
| `evaluation/evaluacion/integridad.py` | validacion_codigo | Eslabones de publicación y distribución; clasifica publico.py. |
| `evaluation/herramientas/probar_rechazos.py` | herramienta_validacion | Batería de rechazos según el modo: pública sin datos o completa tras reconstruir; casos de aprobación de recalcular. |
| `evaluation/reproducir.sh` | ejecucion_empaquetado | Resuelve SIPSA_PROYECTO_INGENIERIA (por defecto ../engineering); recalcular antes de controles. Cambia el arranque y el orden del script, no el estimador. |

## Reclasificados

| Archivo | Clase en el paquete anterior | Clase ahora |
|---|---|---|
| `engineering/herramientas/obtener_fuentes.py` | nuevo | herramienta_validacion |
| `engineering/sipsa.sh` | copia_identica | ejecucion_empaquetado |
| `evaluation/evaluacion/__main__.py` | copia_identica | validacion_codigo |
| `evaluation/evaluacion/integridad.py` | derivado | validacion_codigo |
| `evaluation/herramientas/probar_rechazos.py` | copia_identica | herramienta_validacion |
| `evaluation/herramientas/registrar_revision_publicacion.py` | nuevo | herramienta_validacion |
| `evaluation/reproducir.sh` | adaptado_documentacion | ejecucion_empaquetado |

Los documentos de la carpeta `docs/` y el README se actualizaron para explicar los modos A (sin datos) y B (reconstrucción local). Se corrigió la secuencia de rutas de la guía y se reclasificó `evaluation/reproducir.sh` como cambio de ejecución/empaquetado.

## Enmienda `recalcular-aprobacion` (frente a `SIPSA_ETAPA1_PUBLICABLE_v2.zip`, `52522cf4…`)

`recalcular` retira cualquier aprobación anterior antes de comprobar sus insumos y ante cualquier fallo; solo `controles` la emite. Registrada en `revision_distribucion_etapa1_v2.json` (`enmiendas`), con la huella del archivo de revisión anterior y las huellas antes y después. No cambian el núcleo, `recalcular.py`, las tablas, las figuras ni el congelamiento original.

| Archivo | Clase | Cambio |
|---|---|---|
| `docs/reproduccion.md` | documentación | Modos A y B |
| `docs/validacion_y_revisiones.md` | documentación | Documentación |
| `evaluation/VALIDACION.md` | adaptado_documentacion | Notas de publicación y de distribución. |
| `evaluation/evaluacion/__main__.py` | validacion_codigo | CLI: verificar-publico y comparar-aprobado; controles y recalcular informan NO EJECUTADO sin datos (código 2); recalcular retira cualquier aprobación anterior antes de comprobar insumos y ante fallos. |
| `evaluation/herramientas/enmendar_revision_distribucion.py` | herramienta_validacion | Registra una vez la enmienda recalcular-aprobacion en la revisión de distribución. |
| `evaluation/herramientas/probar_rechazos.py` | herramienta_validacion | Batería de rechazos según el modo: pública sin datos o completa tras reconstruir; casos de aprobación de recalcular. |
| `evaluation/reproducir.sh` | ejecucion_empaquetado | Resuelve SIPSA_PROYECTO_INGENIERIA (por defecto ../engineering); recalcular antes de controles. Cambia el arranque y el orden del script, no el estimador. |
| `evaluation/resultados/revision_distribucion_etapa1_v2.json` | nuevo | Revisión de distribución |
