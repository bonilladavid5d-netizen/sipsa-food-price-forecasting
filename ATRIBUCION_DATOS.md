# Atribución y condiciones de uso de los datos

**Fuente: Departamento Administrativo Nacional de Estadística: [www.dane.gov.co](https://www.dane.gov.co)**

Los datos de origen pertenecen al Sistema de Información de Precios y Abastecimiento del Sector Agropecuario (SIPSA) del DANE:

- series históricas de precios mayoristas (SIPSA-P);
- microdatos anuales de abastecimiento (SIPSA-A), 2018–2025;
- la serie histórica agregada de abastecimiento, usada como contraste.

Las transformaciones, los análisis y las conclusiones de este repositorio son responsabilidad exclusiva de su autor, David Bonilla. Este proyecto **no está afiliado al DANE ni cuenta con su respaldo**.

## Este repositorio no redistribuye las series del DANE

Las condiciones identificadas, consultadas el 12-11-2026, son estas:

| Documento | Condición relevante |
|---|---|
| [Catálogo SIPSA-P 2013–2024 (precios mayoristas)](https://microdatos.dane.gov.co/index.php/catalog/776), sección «Requisito de cita» | Autoriza el uso citando la fuente, pero prohíbe «la copia o reproducción de los datos en cualquier medio electrónico» que permita su disponibilidad a múltiples usuarios sin «el previo visto bueno del DANE por medio escrito». |
| [Catálogo SIPSA-A 2013–2017 (abastecimiento)](https://microdatos.dane.gov.co/catalog/645), sección «Requisito de cita» | Contiene la misma restricción. |
| [Términos y condiciones del portal DANE](https://www.dane.gov.co/index.php/terminos-y-condiciones) | Autorizan el «uso, aprovechamiento, transformación y análisis de la información» con cita textual de la fuente. |

Los archivos usados se descargaron de las páginas de series históricas del portal DANE, no de esos catálogos. Cubren 2018–2025, mientras que los catálogos citados abarcan 2013–2024 y 2013–2017. Aun así, son las mismas operaciones estadísticas. No se identificó una autorización específica que permita redistribuirlas.

Por eso este repositorio **no incluye**:

- los archivos XLSX del DANE;
- tablas con precios o volúmenes por producto, mercado y mes;
- tablas que permitan reconstruirlos de forma trivial.

No basta con quitar una columna: el precio observado se recupera como `predicho − error`, y los pronósticos ingenuo y estacional reproducen precios anteriores. Las tablas completas se conservan en el expediente privado del autor y no se publican por ninguna otra vía.

## Qué sí se incluye

- **Código, metodología y documentación.**
- **Métricas agregadas por serie y por corte:** MASE, MAE medio y error firmado medio sobre 24 meses, comparaciones con y sin abastecimiento.
- **Figuras.**
- **Auditoría temporal y conteos.**
- **Metadatos propios del proyecto:** URL, fechas de descarga y SHA-256 de cada fuente; esquemas; equivalencias de nombres; referencias a los avisos oficiales de imputación (mes, mercado, hoja y fila de la nota).
- **Huellas SHA-256** de los archivos retirados, para comprobar una reconstrucción local.

Las series se obtienen directamente del DANE con `engineering/herramientas/obtener_fuentes.py`, que verifica la versión exacta por tamaño y SHA-256. Después se reconstruyen localmente; véase [docs/reproduccion.md](docs/reproduccion.md).

Ninguna licencia de este repositorio se extiende a los datos del DANE. Quien los reutilice debe revisar las condiciones vigentes y citar la fuente.
