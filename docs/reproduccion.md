# Reproducción

Esta copia pública **no contiene series del DANE**: ni XLSX, ni precios o volúmenes por producto, mercado y mes, ni predicciones con precios ([ATRIBUCION_DATOS.md](../ATRIBUCION_DATOS.md)). Hay dos modos.

**Entornos comprobados:**

- macOS 27.2 arm64 con Python 3.13.11: el autor.
- Linux x86_64 con Python 3.12.14: revisiones independientes, con el alcance indicado en [validacion_y_revisiones.md](validacion_y_revisiones.md).

## Modo A. Explorar y comprobar la entrega pública (sin descargar fuentes)

**Sin instalar nada:**

- Lea el [README](../README.md) y abra [`figures/`](../figures/).
- Las métricas están en [`evaluation/resultados/`](../evaluation/resultados/) y se describen en [diccionario_datos.md](diccionario_datos.md).
- Para verificar las huellas de todos los archivos, desde la raíz de la carpeta (en Linux, con `sha256sum -c`):

```bash
shasum -a 256 -c MANIFIESTO_PUBLICACION.sha256
```

**Con Python 3.12 o 3.13** (unos 2 minutos):

```bash
RAIZ="$(pwd)"          # raíz de la carpeta sipsa-food-price-forecasting
cd "$RAIZ/evaluation"
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python -m evaluacion verificar-publico
SIPSA_SOLO_SINTETICO=1 .venv/bin/python -m unittest pruebas.test_fugas
.venv/bin/python herramientas/probar_rechazos.py "$RAIZ/evaluation/.venv/bin/python" "$RAIZ/engineering" "$RAIZ/salida_rechazos_publica"
```

| Comando | Resultado esperado |
|---|---|
| `verificar-publico` | Código 0: **10 PASS, 0 FAIL, 7 NO EJECUTADO** |
| `test_fugas` | `OK`; prueba con datos **sintéticos**; la prueba con el lote queda omitida |
| `probar_rechazos.py` | 8 casos según lo esperado y 6 casos «NO EJECUTADO: requiere reconstrucción local». En P1c, `recalcular` parte de una aprobación sembrada y debe terminar con código 2 y sin ella. |

**Qué comprueba `verificar-publico`:**

- integridad del código frente al manifiesto aprobado;
- protocolo y configuración sin cambios;
- huellas fijas de las 13 tablas y figuras publicadas, tomadas del expediente aprobado;
- consistencia interna entre las tablas agregadas: resumen frente a series, aporte frente a series y años, regla de selección y parámetros congelados;
- cifras del resumen recalculadas desde las tablas y citadas en el texto;
- límites temporales recalculados desde la configuración.

**Qué no comprueba** y marca como «NO EJECUTADO: requiere reconstrucción local»:

- el recálculo de todas las tablas desde las predicciones;
- la cobertura y los límites temporales de cada predicción;
- las pruebas de fuga con el lote real;
- los contratos de ingeniería frente a las referencias de viabilidad.

**Comportamiento sin datos:**

- `python -m evaluacion controles` y `recalcular` terminan con **código 2 (incompleto)**, nunca con PASS, y retiran cualquier aprobación anterior (`resultados/controles/VALIDACION_VIGENTE.json`).
- `recalcular` retira la aprobación anterior **antes** de comprobar sus insumos, también cuando falla. Solo `controles` emite una aprobación, y solo si todo pasa. Por eso `reproducir.sh` ejecuta `recalcular` antes que `controles`.
- Los rechazos de código, configuración y tablas publicadas funcionan en este modo.

## Modo B. Reconstruir desde las fuentes oficiales y validar el análisis

**Requisitos:**

- los del modo A;
- unos 750 MB de descarga desde dane.gov.co;
- unos 2 GB de disco;
- entre 10 y 15 minutos.

Todos los pasos usan rutas absolutas a partir de `RAIZ`:

```bash
RAIZ="$(pwd)"          # raíz de la carpeta sipsa-food-price-forecasting

# 1. Ingeniería: fuentes oficiales con huella verificada, referencias de regresión y lote aprobado
cd "$RAIZ/engineering"
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python herramientas/obtener_fuentes.py              # o: --desde CARPETA_RAW con copias locales
bash sipsa.sh fuentes
.venv/bin/python herramientas/reconstruir_referencias.py
bash sipsa.sh construir
bash sipsa.sh verificar

# 2. Evaluación en una copia de trabajo (sin .venv ni cachés): regenera predicciones y tablas
cd "$RAIZ"
mkdir evaluation_reconstruida
tar -C evaluation --exclude .venv --exclude __pycache__ -cf - . | tar -C evaluation_reconstruida -xf -
cd "$RAIZ/evaluation_reconstruida"
SIPSA_PYTHON="$RAIZ/evaluation/.venv/bin/python" SIPSA_PROYECTO_INGENIERIA="$RAIZ/engineering" bash reproducir.sh

# 3. Comparación con lo aprobado y pruebas de rechazo con datos
"$RAIZ/evaluation/.venv/bin/python" -m evaluacion comparar-aprobado "$RAIZ/evaluation"
"$RAIZ/evaluation/.venv/bin/python" herramientas/probar_rechazos.py "$RAIZ/evaluation/.venv/bin/python" "$RAIZ/engineering" "$RAIZ/salida_rechazos_completa"
```

| Paso | Qué hace y qué se espera |
|---|---|
| `obtener_fuentes.py` | Descarga los 17 archivos del DANE y exige el tamaño y el SHA-256 congelados. Si el DANE revisó un archivo, se detiene. |
| `reconstruir_referencias.py` | Normaliza los 16 XLSX, exige el SHA-256 aprobado de cada perfil y aplica la lógica original de la viabilidad (pandas). Escribe las tres referencias de regresión solo si coinciden con sus huellas aprobadas fijas. Sin ellas, `construir` se detiene con código 3. |
| `construir` | Construye el lote con DuckDB, verifica 67 contratos (incluida la comparación con esas referencias) y publica un lote con huella de contenido `0dba2228adae1e086ca005fa8c16a1676b99a6fa05a4c30225c7befd53d63ed2`. |
| `reproducir.sh` | Comprueba código y protocolo antes de cargar datos. Reentrena con los parámetros congelados, regenera predicciones y tablas en la copia y ejecuta 61 controles (PASS). |
| `comparar-aprobado` | Recalcula las **tablas aprobadas publicadas**, que no se sobrescriben, desde las **predicciones reconstruidas**, con las 31 comprobaciones de `recalcular.py`. Compara también las tablas regeneradas con las aprobadas (tolerancia `rtol = 1e−7`) e informa si las predicciones coinciden byte a byte con la huella aprobada. Fuera del entorno de referencia pueden diferir en bytes; la validez se decide por el recálculo. |
| `probar_rechazos.py` (con datos) | 10 casos. El íntegro pasa; 6 alteraciones se rechazan, incluidas la fecha 2030 y la cobertura; y 3 de `recalcular`: íntegro (código 0, retira la aprobación sembrada), aporte falso y predicciones ilegibles (código 1, sin aprobación). |

`reproducir.sh` sobrescribe `resultados/` de la carpeta donde se ejecuta. Por eso se usa siempre la copia `evaluation_reconstruida/`, nunca `evaluation/`.
