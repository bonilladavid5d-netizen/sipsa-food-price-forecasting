# SIPSA: evaluación predictiva retrospectiva

> **Copia pública sin series del DANE.** Para comprobar sin datos, use `python -m evaluacion verificar-publico`. `controles` y `recalcular` requieren reconstrucción local (modo B de [`../docs/reproduccion.md`](../docs/reproduccion.md)) y, sin ella, terminan con código 2 (incompleto).

Proyecto de David Bonilla. Fuente de los datos: Departamento Administrativo Nacional de Estadística (DANE), SIPSA. La entrada es el lote aprobado del proyecto de ingeniería v2.1, `lote-20261111T192146Z-0dba2228adae`.

Lea primero `RESUMEN_RESULTADOS.md`; después `PROTOCOLO_PREDICTIVO.md` y `VALIDACION.md`. Los estados internos de cada entrega y los logs completos se conservan en el expediente de revisión, no en esta copia pública.

La revisión v2 refuerza los controles después de observar los resultados:

- **Recálculo completo:** `evaluacion/recalcular.py` recalcula todas las tablas y cifras desde las predicciones.
- **Validación temporal y de cobertura:** `evaluacion/controles.py` las deriva del protocolo.
- **Integridad del código:** `evaluacion/integridad.py` la verifica frente a `resultados/revision_mantenimiento_v2.json`.

No cambia datos, modelos, parámetros ni predicciones. Las pruebas de rechazo están en `herramientas/probar_rechazos.py`; sus logs originales están en el expediente de revisión y se regeneran con `../docs/reproduccion.md`.

| Archivo | Contenido |
|---|---|
| `PROTOCOLO_PREDICTIVO.md`, `config/protocolo.json` | Protocolo congelado y su configuración legible por máquina |
| `resultados/registro_protocolo.json` | Fecha y huellas del congelamiento: protocolo, entradas, código y entorno |
| `resultados/registro_cambios.md` | Cambios posteriores al congelamiento |
| `resultados/seleccion/` | Validación 2023-01..10: métricas por configuración y `parametros_congelados.json`. Las predicciones de selección se generan localmente. |
| `resultados/predicciones.csv` | **No se distribuye** (contiene precios del DANE). Se regenera con `reproducir.sh` en una copia de trabajo, y su huella aprobada está en `resultados/revision_distribucion_etapa1_v2.json`. |
| `resultados/metricas_por_serie.csv`, `resultados/metricas_resumen.csv` | Métricas por serie, y por corte (global, año, producto, mercado, mes, avisos y sensibilidad) |
| `resultados/aporte_abastecimiento.csv` | Comparaciones emparejadas con y sin volumen, con parámetros propios y controladas, por año |
| `resultados/auditoria_temporal.csv` | Límites de información y meses efectivamente usados en cada origen |
| `resultados/flujo_observaciones.csv` | Conteos desde la malla hasta entrenamiento y evaluación |
| `resultados/figuras/` | Tres figuras: precisión, aporte por serie y estabilidad |
| `resultados/controles/pruebas_fugas.json` | Resultado de las pruebas de fuga (9/9) |
| `resultados/revision_publicacion_etapa1.json` | Revisión de publicación: dos registros con la ruta local anonimizada (huellas de origen declaradas) |
| `evaluacion/`, `pruebas/` | Código y pruebas |
| `requirements.lock`, `resultados/ejecucion.json` | Dependencias y entorno usados |
| `resultados/revision_mantenimiento_v2.json` | Manifiesto aprobado del código v2, vinculado al congelamiento original (padre) |
| `resultados/cifras_resumen.json` | Cifras citadas en el resumen, recalculadas desde las predicciones |


## Reproducción

Requiere el proyecto de ingeniería con su lote aprobado. En esta copia pública es `../engineering`, que `reproducir.sh` usa por defecto; se puede indicar con `SIPSA_PROYECTO_INGENIERIA`. Véase `../docs/reproduccion.md`.

```bash
SIPSA_PROYECTO_INGENIERIA=/ruta/a/engineering bash reproducir.sh
```

El script crea el entorno desde `requirements.lock` si no existe. Después ejecuta la selección y la evaluación, las pruebas de fuga, los controles, el recálculo y las figuras. Con el registro de congelamiento incluido, se niega a correr si el protocolo cambió. Una ejecución completa tarda unos 5 minutos en el Mac de trabajo.
