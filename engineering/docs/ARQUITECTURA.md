# Arquitectura del lote de datos

## Flujo de una ejecución

```
fuentes congeladas (datos/raw, SHA-256 aprobados)
   │  etapa fuentes: tamaño + SHA-256 de 17 archivos contra config/fuentes_congeladas.json
   │                 + SHA-256 de sus 17 JSON de captura contra config/capturas_aprobadas.json (v2)
   ▼
caché direccionada por contenido  datos/cache/normalizado/<tipo>_<año>_<sha fuente>_<sha normalizador>/
   │  etapa normalizar: 16 XLSX en paralelo → detalle.parquet + perfiles heredados + COMPLETO.json
   ▼
staging de la ejecución  datos/ejecuciones/<run_id>/salida/
   │  etapa construir: sipsa.duckdb (esquema, referencias, hechos, panel, conciliación) + tablas CSV
   │  etapa validar: 67 contratos (v2; 62 en v1) → validacion.json (cualquier FAIL detiene la ejecución)
   ▼
etapa publicar: reverificación de fuentes y capturas → MANIFIESTO.json → solo lectura
   │            → rename atómico a datos/lotes/<lote_id>/ → estado PUBLICANDO
   │            → os.replace de datos/APROBADO.json   ◀── PUNTO DE CONFIRMACIÓN (v2)
   │            → historial_aprobados.jsonl → estado PUBLICADA
   │              (un fallo aquí: código 4, PUBLICADA_REGISTRO_PENDIENTE; `conciliar` completa el registro)
   ▼
consumidores: leen solo a través de APROBADO.json y verifican el manifiesto antes de consultar
```

Cada transición de estado se escribe en `ejecuciones/<run_id>/estado.json`, mediante reemplazo atómico, y en `registro_ejecuciones.jsonl`, en modo solo anexión con fsync. Los estados posibles son `EN_CURSO` (con su etapa), `PUBLICANDO`, `PUBLICADA`, `PUBLICADA_REGISTRO_PENDIENTE`, `FALLIDA` y `ABANDONADA`. Al inicio de cada `construir`, `revertir` o `conciliar`, con el bloqueo tomado, se concilian las ejecuciones sin dueño vivo:
- si `APROBADO.json` apunta a una de ellas, se confirmó y pasa a `PUBLICADA`, con la entrada de historial marcada `conciliado`;
- si no, pasa a `ABANDONADA`.

## Garantías y cómo se comprueban

| Garantía | Mecanismo | Prueba |
|---|---|---|
| Una ejecución fallida **antes de confirmar** no sustituye el lote aprobado | El puntero solo cambia después de validar, reverificar y mover el lote completo | `test_02`–`test_06`: `APROBADO.json` con el mismo SHA-256 y lote íntegro tras cada fallo |
| Los datos corruptos no se publican | Contratos contra la referencia de viabilidad, la cardinalidad y las excepciones aprobadas | `test_03`: precio alterado → `panel_igual_a_viabilidad` FAIL |
| Una fuente no aprobada no entra | SHA-256 y tamaño antes de leer | `test_04`: un byte alterado en `precios/2019.xlsx` → FALLIDA en `fuentes` |
| Un lote nunca aparece a medias | `rename` de un directorio completo en el mismo volumen | `test_05`: fallo tras mover y antes de apuntar → lote huérfano visible, no aprobado |
| La recuperación tras un corte abrupto funciona | `flock` liberado por el sistema operativo al morir el proceso (v2; v1 usaba la ficha con PID); temporales de caché descartados; caché solo con `COMPLETO.json` | `test_06`: `kill -9` del grupo de procesos a mitad de un archivo → recuperación publica la misma huella |
| No hay escritores concurrentes (v2) | `flock(LOCK_EX)` sobre `datos/.bloqueo`, que nunca se borra; `LOCK_SH` de los trabajadores sobre `.trabajadores` | `test_bloqueo`: 30 rondas × 4 recuperaciones simultáneas con un solo ganador, intercalado de la revisión, muerte del dueño, trabajador huérfano; `test_regresion_v2`: muerte del padre con un trabajador escribiendo |
| Disponibilidad observada verificable (v2) | `first_seen_at` = `retrieved_at` de `capturas_aprobadas.json`; JSON laterales verificados por SHA-256 antes de construir y antes de confirmar | `test_regresion_v2`: fecha alterada → código 1; otro campo alterado → código 1; cambio durante la ejecución → código 1; cortes 1 µs antes y en cada captura |
| Publicación y registro coherentes (v2) | Punto de confirmación único y `conciliar` idempotente por `publicacion_id` | `test_regresion_v2`: fallo antes del puntero → 1; historial fallido después → 4 y conciliación; `kill -9` tras el puntero → conciliado; reversión antes y después |
| Un lote alterado no se consume | Manifiesto SHA-256 y verificación previa a cada consulta | `test_08`: alteración detectada, consulta rechazada y reversión |
| Reproducibilidad | Sumas DECIMAL, orden determinista y huella de contenido | Misma huella en todas las ejecuciones del proyecto y de las pruebas, y en una carpeta limpia con entorno nuevo y sin caché |

## Modelo relacional (`sql/esquema.sql`)

- `source_snapshot`: 17 capturas con URL, SHA-256, bytes, `retrieved_at` y `historical_release_at` (NULL).
- `product`, `market`: identidades estables. `product_crosswalk` y `market_crosswalk` llevan versión, vigencia y decisión.
- `precio_observado`: 439.895 precios publicados de todas las plazas, con fila de origen. Sin llave única por diseño, porque existen 8 llaves repetidas fuera de la canasta.
- `abastecimiento_mes_todos`: 286.989 agregados mensuales de todos los alimentos y plazas. Son sumas exactas en DECIMAL de 15.494.712 ingresos, sin deduplicar.
- `price_month`, `supply_month`: hechos de la canasta con PK `(producto, mercado, mes, snapshot)`, FK, `CHECK` de precio positivo, mes válido y unidades, más `first_seen_at` y `published_at` (NULL).
- `panel_mensual`: malla completa de 2.880 celdas. Los huecos quedan NULL, nunca cero.
- `politica_temporal`, `canal_disponibilidad`, `aviso_imputacion`, `conciliacion_totales`, `candidatos_elegibles`, `canasta_reproducida`, `llaves_repetidas_precios`, `ambiguedad_cpc`.

El detalle fila a fila vive en `detalle/<tipo>/<año>.parquet`. Para consultarlo desde DuckDB:

```sql
SELECT mercado, producto, sum(CAST(kg_raw AS DECIMAL(38,10))) AS kg
FROM read_parquet('datos/lotes/<lote_id>/detalle/abastecimiento/*.parquet')
WHERE month = '2024-05' GROUP BY ALL;
```

## Proporción

DuckDB y Parquet en una sola máquina bastan para 15,5 millones de filas y un panel de 2.880 celdas. No se introducen servidor, orquestador ni nube. Postgres, Airflow, Spark y Kubernetes siguen sin ser requisitos de este estudio.
