# SIPSA: receta de datos reproducible (fase de ingeniería)

Proyecto de David Bonilla. Fase: ingeniería de datos, 11 de noviembre de 2026. Versión v2.1: v2 (corrección de H1–H3 de la revisión independiente) más el cierre de H3 en los caminos posteriores a la confirmación (D-23 a D-25). No entrena modelos ni publica resultados.

Fuente de los datos: Departamento Administrativo Nacional de Estadística (DANE), Sistema de Información de Precios y Abastecimiento del Sector Agropecuario (SIPSA).

La receta convierte las fuentes congeladas de la viabilidad (16 XLSX anuales y el histórico agregado) en un **lote de datos versionado**. Cada lote contiene:

- detalle normalizado en Parquet, con linaje `(sha256, hoja, fila)`;
- un modelo relacional en DuckDB con claves y restricciones;
- el panel auditado de 2.880 celdas;
- conciliaciones, perfiles y la información de disponibilidad temporal.

Un lote solo se publica si supera los 67 contratos de v2. La publicación tiene un único punto de confirmación, el reemplazo atómico de `datos/APROBADO.json`:
- un fallo anterior conserva el lote aprobado (código 1);
- un fallo posterior se informa como publicación con registro pendiente (código 4) y se completa con `conciliar`.

La exclusión de escritores usa `flock` del sistema operativo. La fecha de captura (`first_seen_at`) proviene de una referencia aprobada y verificada (`config/capturas_aprobadas.json`).

## Uso

Instalación. Comprobada en macOS 27.2 arm64 con Python 3.13.11:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
```

Fuentes: obtenga los 17 archivos oficiales congelados con `python herramientas/obtener_fuentes.py`. Descarga desde dane.gov.co (unos 750 MB) y exige el tamaño y el SHA-256 de `config/fuentes_congeladas.json`; con `--desde CARPETA_RAW` copia una copia local. Si el DANE revisó un archivo, la huella no coincidirá y la receta se detiene. Las tres referencias de regresión de la viabilidad contienen series del DANE y no se distribuyen. Regenérelas, con verificación de su huella aprobada, mediante `.venv/bin/python herramientas/reconstruir_referencias.py`; sin ellas, `construir` se detiene con código 3. Después, compruebe las fuentes con:

```bash
bash sipsa.sh fuentes
```

Construcción. Verifica, normaliza, construye, valida y publica:

```bash
bash sipsa.sh construir
```

Para reconstruir desde cero sin usar la caché:

```bash
bash sipsa.sh construir --sin-cache
```

Operación:

```bash
bash sipsa.sh estado
bash sipsa.sh verificar
bash sipsa.sh revertir <lote_id>
bash sipsa.sh conciliar
```

Códigos de salida de `construir` y `revertir`:
- 0: publicado y registrado. Puede ir con `ADVERTENCIA` si solo falló la ficha diagnóstica del bloqueo, que sí se libera.
- 1: fallo antes de confirmar; el lote aprobado queda intacto y la huella se comprueba.
- 3: bloqueo ocupado.
- 4: publicado con registro pendiente (historial o evento final). `estado` lo muestra y `conciliar` lo completa de forma idempotente.

Consultas temporales sobre el lote aprobado:

```bash
bash sipsa.sh consultar --escenario retro_r1 --origen 2023-07
bash sipsa.sh estricto --mes 2025-12
```

Un corte `--mes t` es el cierre del mes calendario `t` en hora de Colombia (D-17).

Pruebas:

```bash
.venv/bin/python -m unittest pruebas.test_unitarias
.venv/bin/python -m unittest -v pruebas.test_bloqueo
.venv/bin/python -m unittest -v pruebas.test_integracion_fallos
.venv/bin/python -m unittest -v pruebas.test_regresion_v2
.venv/bin/python -m unittest -v pruebas.test_cierre_v2_1
bash herramientas/reconstruccion_limpia.sh <carpeta_nueva> <ZIP_2018_2021> <ZIP_2022_2025>
```

Una construcción completa sin caché tarda unos 4 minutos en el Mac de trabajo (8 núcleos, 8 GB) y usa menos de 1 GB de memoria. Con caché tarda unos 10 segundos. El directorio `datos/` ocupa unos 1,2 GB con las fuentes enlazadas y un lote.

## Estructura

| Ruta | Contenido |
|---|---|
| `sipsa/` | Código: `normalizar.py` (XLSX → Parquet y perfiles), `construir.py` (DuckDB), `validar.py` (contratos), `lote.py` (estados, bloqueo, publicación), `cli.py`. |
| `sql/` | Esquema, transformaciones, panel, selección de la canasta, conciliación y consultas temporales. |
| `config/` | Fuentes congeladas, esquemas, equivalencias versionadas, política temporal, canales, excepciones y referencia de viabilidad. `heredado_viabilidad/` guarda la configuración original sin cambios. |
| `pruebas/` | Pruebas unitarias y de integración con fallos inyectados. |
| `herramientas/` | Reconstrucción en carpeta limpia, ejemplos por corte, contraste del servicio web y extracción de la referencia. |
| `docs/` | Arquitectura, política temporal, operación, decisiones y cambios respecto de la viabilidad. |
| `datos/` | Se crea al reconstruir: fuentes, caché, ejecuciones, lotes y `APROBADO.json`. No se publica. |
| `fuentes/metadatos_captura/` | Metadatos de captura de las 17 fuentes (URL, fecha de descarga, SHA-256); necesarios para reproducir `first_seen_at`. |
| `evidencia/` | No se publica: los logs completos de las ejecuciones se conservan en el expediente de revisión. |

Las pruebas de integración usan destinos aislados (`datos/pruebas_integracion`, `datos/pruebas_v2`) con la caché enlazada en solo lectura. No deben ejecutarse mientras otra construcción usa la caché del proyecto. Quien llame a `sipsa.lote.construir()` desde su propio script necesita la guarda `if __name__ == "__main__":`, porque los trabajadores se lanzan con `spawn`. El bloqueo solo está garantizado en un sistema de archivos local.

## Límites que se mantienen

- Las versiones de las fuentes son capturas del 11-11-2026, no versiones históricas. `published_at` e `historical_release_at` quedan nulos.
- Los escenarios `retro_*` son **supuestos** declarados de disponibilidad.
- Los 15,5 millones de ingresos no son ejemplos independientes. La unidad de análisis es producto-mercado-mes: 2.880 celdas.
- El valor predictivo incremental no es un efecto causal. SIPSA-A es un registro no probabilístico.
