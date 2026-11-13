# Datos y procedencia

> Las series del DANE no se redistribuyen en este repositorio ([ATRIBUCION_DATOS.md](../ATRIBUCION_DATOS.md)). Las cifras de este documento son conteos y resúmenes de la auditoría.

## Fuentes oficiales congeladas

Son 17 archivos del DANE–SIPSA, descargados el 11-11-2026 y congelados por tamaño y SHA-256 en [`engineering/config/fuentes_congeladas.json`](../engineering/config/fuentes_congeladas.json):

- 8 XLSX anuales de precios mayoristas (2018–2025);
- 8 XLSX anuales de microdatos de abastecimiento (2018–2025);
- la serie histórica agregada de abastecimiento, usada solo para conciliar totales.

Los metadatos de cada captura (URL, fecha `retrieved_at`, SHA-256) están en [`engineering/fuentes/metadatos_captura/`](../engineering/fuentes/metadatos_captura/). Su huella está aprobada en [`engineering/config/capturas_aprobadas.json`](../engineering/config/capturas_aprobadas.json), y de ellos sale `first_seen_at`. La revisión independiente de datos volvió a descargar los 17 archivos desde dane.gov.co y obtuvo los mismos tamaños y SHA-256 (747.787.068 bytes en total).

**Si el DANE revisa un archivo**, su huella cambiará y `obtener_fuentes.py` se detendrá. Una versión nueva requiere incorporarla como fuente aprobada nueva; no se sustituye en silencio.

## Del origen al panel

| Etapa | Cantidad |
|---|---|
| Registros de precios leídos (todas las plazas y productos) | 439.895 |
| Registros de abastecimiento leídos, sin deduplicar | 15.494.712 |
| Panel seleccionado (10 productos × 3 mercados × 96 meses) | 2.880 combinaciones |
| Precios presentes / ausentes | 2.878 / 2 (limón Tahití, Centroabastos, 2025-04 y 2025-09) |
| Volúmenes presentes | 2.880 |

- **Precios:** cotización mayorista mensual en COP/kg.
- **Volumen:** suma mensual de kg ingresados del mismo producto y mercado. Se suma en DECIMAL exacto desde el texto original de la celda.
- **Equivalencias:** el cruce entre precio y volumen usa la etiqueta literal del producto (equivalencias versionadas). No empareja transacciones individuales ni garantiza la misma mezcla de calidades.

## Selección de la canasta

Se seleccionó con datos de 2018–2022 únicamente:

1. Correspondencia literal entre fuentes.
2. Al menos 54 de 60 meses conjuntos en cada mercado.
3. Orden por cobertura y volumen.
4. Cuotas de 5 verduras, 4 frutas y 1 tubérculo o plátano.

Hay 33 candidatos elegibles. La revisión independiente reprodujo los mismos 10 productos.

## Anomalías conservadas, no corregidas

- **Dos precios ausentes:** se conservan como ausentes y se excluyen de la evaluación.
- **Conciliación con la serie agregada del DANE:** 286 de 288 totales mercado–mes coinciden dentro de 1 kg. Corabastos en 2018-12 difiere en +260 kg y la Central Mayorista de Antioquia en 2022-07 en +300 kg; la causa no se demostró.
- **Diez mercado–mes con avisos oficiales de imputación:** no se usan como variables. Sirven para estratificar resultados.
- **Registros de abastecimiento idénticos:** no se eliminan. Coincidir en los campos publicados no prueba que sean el mismo ingreso.

## Disponibilidad temporal

Las fechas históricas en que cada dato estuvo disponible son **desconocidas**: los archivos son capturas de noviembre de 2026. Los retrasos `retro_r1` (precios y volúmenes hasta `t−1`), `retro_r2` y `retro_p1_a2` son **supuestos declarados**. El modo estricto, basado en lo realmente observado, no permite evaluar cortes históricos.
