# Cambios respecto de la viabilidad

La entrega de viabilidad (`SIPSA_VIABILIDAD_ENTREGA.zip`, SHA-256 `8faec76e…5792`) se extrajo sin modificarla en `../insumos/viabilidad/`. Sus 162 archivos verificaron contra su manifiesto. Lo mismo ocurrió con las dos copias de fuentes (16 + 24 archivos).

## Lo que se mantiene igual (comprobado)

| Resultado de viabilidad | Resultado de esta fase |
|---|---|
| 439.895 precios y 15.494.712 ingresos de abastecimiento | Iguales, fila a fila en Parquet |
| 96 CSV de perfiles anuales (`datos.csv`, `esquemas.csv`, etc.) | Los 96 con **SHA-256 idéntico**, generados en macOS y Python 3.13 |
| Panel de 2.880 celdas: 2.878 precios y 2.880 abastecimientos | Idéntico: precios exactos, diferencia máxima de kg 0,0, misma fila de origen, mismos avisos |
| 33 candidatos y canasta de 10 productos | Reproducidos en SQL, mismo orden |
| 286/288 conciliaciones dentro de 1 kg; +260 kg y +300 kg | Iguales (diferencia máxima con viabilidad 1,5e-8 kg) |
| 8 excesos de llaves repetidas fuera de la canasta | Iguales; ahora son excepción aprobada explícita |
| Estricto: 0 filas con corte 2025 | Igual |
| 22 comprobaciones de contratos | Ampliadas a 62 (todas pasan) |

## Lo que cambia

| Tema | Viabilidad | Ingeniería | Motivo |
|---|---|---|---|
| Plataforma comprobada | Linux, Python 3.12.14 | macOS 27.2 arm64, Python 3.13.11; mismos pandas, lxml y openpyxl; más pyarrow 26.0.1 y duckdb 2.0.0 | Prueba en el Mac de trabajo (D-12) |
| Motor | SQLite, prototipo del panel | DuckDB + Parquet con el detalle completo | D-01 |
| Suma de kg | Flotante en orden de lectura | DECIMAL exacto desde el texto | D-02; mismo resultado en las 2.880 celdas |
| Receta | 5 scripts secuenciales que escriben en sitio | Una CLI con estados, staging, bloqueo, caché, validación y publicación atómica | Prioridad 2 |
| Equivalencias | `equiv-v1` sin vigencia | `equiv-v2` con grupo, vigencia y decisión | D-04 |
| Política temporal | Consulta estricta y escenario descrito en texto | Política versionada con 3 escenarios en tablas y SQL, ejemplos por corte y contrato contra información futura | Prioridad 1 |
| Servicio web | WSDL con HTTP 500 | WSDL accesible; contraste realizado; no se incorpora | D-15 |
| Excepciones | Descritas en texto | `excepciones_aprobadas.json`; cualquier anomalía nueva bloquea | D-11 |

## Hallazgos de esta fase que no estaban en la viabilidad

1. **El servicio SOAP no documenta disponibilidad**: `fechaCreacion` viene vacío. Además tiene meses de abastecimiento con cargas parciales y una discrepancia de precios en 2025-08.
2. **En macOS no se puede mover un directorio de solo lectura.** La primera publicación falló de verdad por esto. No se promovió nada y la ejecución quedó `FALLIDA` (`evidencia/01_construccion_inicial.log`). Se corrigió el orden: se mueve y después se protege.
3. Dos defectos encontrados por las pruebas y corregidos. El comando `estado` mostraba `EN_CURSO` para un proceso muerto. Las consultas solo comparaban tamaños y aceptaban un lote alterado sin cambio de tamaño.

## v2 (corrección acotada tras la revisión independiente)

Los datos de la viabilidad se mantienen sin cambios en las 2.880 celdas, los dos precios ausentes, las conciliaciones 286/288, los 96 CSV de perfiles y los 16 Parquet. Los Parquet son idénticos byte a byte a los de v1.

La huella de contenido cambia de `1b7cfb4be8b3…` a `0dba2228adae…` solo por dos tablas de metadatos (`evidencia/v2/comparacion_viabilidad_y_v1.json`):

- `tablas/fuentes.csv`: tres columnas nuevas (`capture_sidecar_sha256`, `first_seen_basis`, `retro_vigente`). Las columnas comunes, incluido `retrieved_at`, son idénticas.
- `tablas/politica_temporal.csv`: la etiqueta `version` pasa de `politica-temporal-v1` a `politica-temporal-v2`.

Los 16 `perfil.json` difieren solo en `duration_seconds`, que la huella excluye.

Los cambios de código están en `docs/DECISIONES.md`, D-17 a D-22.

## v2.1 (cierre de H3)

Solo cambian el manejo de excepciones posterior a la confirmación, la liberación del bloqueo, la conciliación de reversiones y la CLI (`sipsa/lote.py`, `sipsa/cli.py`, `sipsa/util.py`). Fuentes, canasta, reglas temporales, transformaciones, SQL y normalización no cambian.

El lote construido con v2.1 reutilizó la caché verificada: la huella del normalizador sigue en `1a963494…`. Tiene la **misma huella de contenido** `0dba2228…` que v2, y sus 139 archivos de contenido y 11 tablas son idénticos byte a byte (`evidencia/v2_1/comparacion_viabilidad_y_v2.json`). Solo cambia la huella de código: de `eb1ae44f…` a `1b34e68b…`.
