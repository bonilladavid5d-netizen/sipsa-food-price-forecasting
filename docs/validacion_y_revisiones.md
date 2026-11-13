# Validación y revisiones

Este documento separa la evidencia generada por el autor en su Mac de la comprobada de forma independiente en Linux. Ninguna revisión es una certificación institucional ni de operación productiva.

| Fase | Ejecutado por el autor (Mac, Python 3.13.11) | Comprobado independientemente (Linux, Python 3.12.14) |
|---|---|---|
| **Datos de origen** | 17 fuentes congeladas por SHA-256; lectura completa de 439.895 precios y 15.494.712 registros de abastecimiento | Nueva descarga de los 17 archivos desde dane.gov.co, con tamaños y SHA-256 idénticos. Relectura con otro lector (openpyxl) y los mismos conteos por mes, mercado y producto. |
| **Panel y selección** | Panel de 2.880 celdas idéntico a la fase de viabilidad; selección reproducida en SQL | Las 2.880 celdas coinciden con la fuente, incluidas hoja y fila. Se recuperan los mismos 10 productos usando solo 2018–2022. Conciliación 286/288 dentro de 1 kg. |
| **Ingeniería** | 67 contratos; pruebas de fallo (bloqueo, interrupción, publicación atómica, metadatos de captura); reconstrucción limpia con `TZ=UTC` y la misma huella `0dba2228…` | Reconstrucción completa desde los 16 XLSX sin caché: 67/67 contratos y la misma huella de contenido. Pruebas unitarias y de bloqueo. |
| **Evaluación predictiva** | Protocolo congelado antes de estimar; selección 2023; evaluación 2024–2025; 9 pruebas de fuga; reproducción idéntica en una carpeta nueva | Reejecución del **núcleo** de selección y evaluación desde el panel CSV auditado: 25.080 predicciones coinciden dentro de la precisión de exportación, con los mismos parámetros. Recálculo independiente de métricas y pruebas de fuga. |
| **Controles v2** | 61 controles PASS; 7 casos de rechazo según lo esperado; reejecución con el código v2 idéntica byte a byte | Controles por CLI: 61 PASS. Se rechazan las 6 alteraciones definidas y el script del auditor detecta los tres huecos de v1. Resultados idénticos a v1. |

**Lo que no se ejecutó en Linux:** la CLI completa de evaluación con el cargador DuckDB y la reconstrucción encadenada fuente → lote → evaluación. Esa cadena completa se ejecutó en el Mac.

## Controles de la evaluación (`python -m evaluacion controles`)

- **Integridad del código:** cada módulo debe coincidir con el manifiesto aprobado. En esta copia es `resultados/revision_publicacion_etapa1.json`, hija de `revision_mantenimiento_v2.json`, que a su vez es hija del registro de congelamiento.
- **Información futura:** para cada una de las 25.080 predicciones y las 82 filas de auditoría se recalculan los límites desde el origen y los retrasos del protocolo, y se contrastan con precio, volumen, etiqueta, base B, objetivo y emisión.
- **Cobertura:** debe estar exactamente lo que define el protocolo; falta de modelos, escenarios, orígenes o series hace fallar el control.
- **Recálculo:** todas las tablas publicadas y las cifras del resumen se recalculan desde `predicho − observado`, con llaves idénticas y tolerancias `rtol = 1e−7`, `atol = 1e−9`.

## Historial de correcciones

1. **Ingeniería v2 y v2.1.** Se protegieron los metadatos de captura, se cambió el bloqueo a `flock` y se definió un punto único de confirmación de la publicación.
2. **Evaluación v2.** El recálculo pasó a cubrir todo el aporte del abastecimiento; la validación temporal pasó a recalcular los límites; se añadió la integridad del código frente a un manifiesto aprobado.

En los tres casos de la evaluación v2, los datos, modelos, parámetros y predicciones no cambiaron. Las revisiones de mantenimiento y publicación son **posteriores** a los resultados y no se presentan como congelamientos previos.

## Distribución pública (revisión `distribucion-etapa1-v2`)

Para no redistribuir series del DANE, la copia pública retira cinco archivos:

- las predicciones de evaluación y de selección;
- las tres referencias de viabilidad con precios y volúmenes.

Sus huellas aprobadas quedan registradas en `evaluation/resultados/revision_distribucion_etapa1_v2.json`, una revisión posterior a los resultados e hija por SHA-256 de la revisión de publicación. El registro de congelamiento original no se modifica.

- **Sin datos:** `verificar-publico` comprueba lo que se puede comprobar y marca el resto como «NO EJECUTADO». `controles` y `recalcular` terminan con código 2.
- **Con reconstrucción local:**
  - `reconstruir_referencias.py` regenera las referencias y exige sus huellas aprobadas de la viabilidad;
  - `comparar-aprobado` recalcula las tablas aprobadas publicadas desde las predicciones reconstruidas;
  - los 61 controles y los 10 casos de rechazo vuelven a ejecutarse completos.
- **Enmienda `recalcular-aprobacion`** (registrada en la misma revisión, con la huella del archivo anterior): `recalcular` retira cualquier aprobación anterior antes de comprobar sus insumos y ante cualquier fallo. Solo `controles` emite aprobación. Cambian `evaluacion/__main__.py`, el orden de `reproducir.sh` y las pruebas de rechazo; no cambian el núcleo, `recalcular.py` ni los resultados.

## Límites de esta evidencia

- La protección del código es interna (huellas dentro del propio paquete). No es una firma externa.
- Las marcas de tiempo del congelamiento son registros internos, no una prueba independiente de cuándo se vieron los resultados.
- Las pruebas de rechazo son dirigidas, no exhaustivas.
