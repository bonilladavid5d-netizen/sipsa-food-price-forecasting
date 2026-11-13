# Cambios de la copia pública respecto de las entregas aprobadas

Esta copia se construyó copiando desde la evaluación predictiva v2 (`SIPSA_EVALUACION_PREDICTIVA_REVISION_v2.zip`, SHA-256 `63745a0c…`) y desde el proyecto de ingeniería v2.1 (lote `lote-20261111T192146Z-0dba2228adae`). Los originales, sus registros y sus ZIP se conservan intactos en el expediente de revisión.

**Recuento:**

| Clase | Archivos |
|---|---|
| Idénticos byte a byte a su origen | 102 |
| Derivados declarados | 2 |
| Código de validación | 3 |
| Ejecución o empaquetado | 2 |
| Herramientas de validación | 6 |
| Documentos adaptados | 5 |
| Nuevos (incluidos los dos resúmenes) | 12 |

**No se distribuyen:**

- las 5 tablas con series del DANE (ver [cambios_respecto_paquete_revisado.md](cambios_respecto_paquete_revisado.md));
- logs con rutas locales y estados internos;
- scripts de los auditores;
- XLSX, Parquet, DuckDB, entornos y cachés.

**Sin cambios:**

- métricas, aporte, auditoría temporal, flujo, selección y figuras;
- protocolo, configuración, `nucleo.py`, `ejecutar.py`, `datos.py`, `controles.py` y `recalcular.py`;
- el código de cálculo de ingeniería.

## Archivos que no son copias idénticas

| Archivo | Clase | Cambio o propósito |
|---|---|---|
| `.gitignore` | nuevo | Exclusiones locales |
| `ATRIBUCION_DATOS.md` | nuevo | Atribución DANE y condiciones de distribución |
| `README.md` | nuevo | Presentación pública |
| `docs/datos_y_procedencia.md` | nuevo | Documentación |
| `docs/diccionario_datos.md` | nuevo | Documentación |
| `docs/metodologia.md` | nuevo | Documentación |
| `docs/reproduccion.md` | nuevo | Modos A y B |
| `docs/validacion_y_revisiones.md` | nuevo | Documentación |
| `engineering/README.md` | adaptado_documentacion | Receta de fuentes y referencias. |
| `engineering/docs/ARQUITECTURA.md` | adaptado_documentacion | 67 contratos y flock (auditoría de datos). |
| `engineering/docs/DECISIONES.md` | adaptado_documentacion | D-09 sustituida por D-19. |
| `engineering/herramientas/obtener_fuentes.py` | herramienta_validacion | Obtiene las 17 fuentes oficiales y exige tamaño y SHA-256 congelados. |
| `engineering/herramientas/reconstruir_referencias.py` | herramienta_validacion | Regenera las 3 referencias de viabilidad y exige sus huellas aprobadas fijas. |
| `engineering/sipsa.sh` | ejecucion_empaquetado | construir se detiene con código 3 si faltan las referencias de regresión no distribuidas. |
| `evaluation/README.md` | adaptado_documentacion | Copia pública sin series del DANE; rutas y modos. |
| `evaluation/VALIDACION.md` | adaptado_documentacion | Notas de publicación y de distribución. |
| `evaluation/evaluacion/__main__.py` | validacion_codigo | CLI: verificar-publico y comparar-aprobado; controles y recalcular informan NO EJECUTADO sin datos (código 2); recalcular retira cualquier aprobación anterior antes de comprobar insumos y ante fallos. |
| `evaluation/evaluacion/integridad.py` | validacion_codigo | Eslabones de publicación y distribución; clasifica publico.py. |
| `evaluation/evaluacion/publico.py` | validacion_codigo | Nuevo: verificación pública sin series del DANE y comparación de una reconstrucción con lo aprobado. |
| `evaluation/herramientas/enmendar_revision_distribucion.py` | herramienta_validacion | Registra una vez la enmienda recalcular-aprobacion en la revisión de distribución. |
| `evaluation/herramientas/probar_rechazos.py` | herramienta_validacion | Batería de rechazos según el modo: pública sin datos o completa tras reconstruir; casos de aprobación de recalcular. |
| `evaluation/herramientas/registrar_revision_distribucion.py` | herramienta_validacion | Crea la revisión de distribución (una sola vez). |
| `evaluation/herramientas/registrar_revision_publicacion.py` | herramienta_validacion | Crea la revisión de publicación (una sola vez). |
| `evaluation/reproducir.sh` | ejecucion_empaquetado | Resuelve SIPSA_PROYECTO_INGENIERIA (por defecto ../engineering); recalcular antes de controles. Cambia el arranque y el orden del script, no el estimador. |
| `evaluation/resultados/ejecucion.json` | derivado | Anonimización del mismo campo; salida de ejecución declarada por procedencia. |
| `evaluation/resultados/registro_protocolo.json` | derivado | Anonimización de entrada.proyecto_ingenieria; declarado en revision_publicacion_etapa1.json (registro protegido). |
| `evaluation/resultados/revision_distribucion_etapa1_v2.json` | nuevo | Revisión de distribución |
| `evaluation/resultados/revision_publicacion_etapa1.json` | nuevo | Revisión de publicación |
