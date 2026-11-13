# Operación y recuperación

## Ciclo normal

1. Con `bash sipsa.sh fuentes`, compruebe que las 17 fuentes conservan tamaño y SHA-256.
2. Ejecute `bash sipsa.sh construir`. Códigos de salida (v2), que también aplican a `revertir`:
   - **0**: publicado y registrado.
   - **1**: fallo **antes** del punto de confirmación. `APROBADO.json` no cambió y la ejecución queda `FALLIDA`.
   - **3**: rechazado porque otra ejecución, o trabajadores huérfanos de una ejecución muerta, sostienen el bloqueo. No se creó nada.
   - **4**: fallo **después** del punto de confirmación. `APROBADO.json` **ya** apunta al lote nuevo, íntegro y visible para los consumidores. Falló el registro (historial o estado). La ejecución queda `PUBLICADA_REGISTRO_PENDIENTE`; ejecute `bash sipsa.sh conciliar`, o deje que lo haga la próxima ejecución.
3. Revise el resultado con `bash sipsa.sh estado`. Muestra el lote aprobado, las ejecuciones con su estado y etapa, y los lotes huérfanos.
4. Compruebe el lote aprobado con `bash sipsa.sh verificar`. Recalcula el SHA-256 de todos sus archivos.

## Qué hacer ante cada fallo

| Situación | Qué queda | Acción |
|---|---|---|
| `FALLIDA` en `fuentes` | Nada nuevo. `APROBADO.json` sin cambios | Una fuente cambió o falta. No se reemplaza: una revisión del DANE se incorpora como **nueva** entrada aprobada en `fuentes_congeladas.json`, conservando la anterior. |
| `FALLIDA` en `normalizar` | Los temporales `.tmp-*` de la caché se descartan en la siguiente ejecución | Leer el error, que puede indicar esquema no aprobado, fecha no interpretable u hoja vacía. Si el esquema es legítimo, aprobarlo en `esquemas_aprobados.json`; eso cambia la huella del normalizador y fuerza a releer. |
| `FALLIDA` en `construir` | `ejecuciones/<run_id>/salida/` parcial, nunca promovido | Diagnóstico con el log y `estado.json`. Se puede borrar el staging. |
| `FALLIDA` en `validar` | `salida/validacion.json` con los contratos `FAIL` | Revisar la anomalía. Si es legítima y conocida, registrarla como excepción versionada; si no, corregir la causa. |
| Lote huérfano (fallo tras mover y antes de apuntar) | `lotes/<id>` completo y verificable, pero no aprobado | Ejecutar `revertir <id>` si se revisó y se quiere aprobar, o volver a construir. |
| `kill -9`, apagado o corte de energía antes de confirmar | El sistema operativo liberó el `flock`; la ficha de `.bloqueo` sigue diciendo "tomado" y el estado queda `EN_CURSO` (`estado` lo muestra como `INTERRUMPIDA`) | Basta ejecutar `construir`. Bajo el bloqueo, `conciliar` marca la ejecución `ABANDONADA` y se reutiliza la caché completa. |
| Muerte **después** de confirmar (estado `PUBLICANDO`) | `APROBADO.json` apunta al lote nuevo y el historial no tiene la entrada | `conciliar` (automático o manual) reconoce la publicación: estado `PUBLICADA` y entrada de historial con `conciliado`. |
| Código 4 (`PUBLICADA_REGISTRO_PENDIENTE`) | Publicación efectiva; falta el historial o el evento/estado final, también en `revertir` (v2.1) | `bash sipsa.sh conciliar`. `estado` lo muestra en `registro_pendiente`, `historial_pendiente` y `cierres_pendientes`. La conciliación es idempotente: una segunda pasada no añade nada. No se revierte en silencio; si se quiere volver atrás, `revertir` deja su propio rastro. |
| `ADVERTENCIA: Limpieza…` con código 0 (v2.1) | La operación se publicó y registró; falló solo la escritura de la ficha diagnóstica del bloqueo, que **sí** se liberó | Nada que recuperar. Queda el evento `ADVERTENCIA_LIMPIEZA`; la próxima adquisición sobrescribe la ficha. |
| `NOTA: Limpieza…` junto a otro error | La causa principal es el error mostrado y la clasificación (1 o 4) es la suya | Atender la causa principal. |
| Muere el proceso principal mientras un trabajador escribe | El trabajador sigue vivo con `LOCK_SH` sobre `.trabajadores`; un nuevo `construir` sale con código 3 | El trabajador detecta que su padre murió, borra su temporal y termina. Después, `construir` funciona con normalidad. |
| Metadato de captura (`raw/**/*.json`) alterado | Código 1 en `fuentes`: "metadato de captura no aprobado" | Restaurar el original desde el ZIP congelado. Una captura nueva legítima requiere una nueva versión de `capturas_aprobadas.json`. |
| Lote aprobado alterado en disco | `verificar` falla y las consultas se rechazan | `revertir <lote_id_anterior>` o volver a construir. |

**Bloqueo (v2).** `datos/.bloqueo` se adquiere con `flock(LOCK_EX|LOCK_NB)` y **nunca se borra**: no hace falta ni se debe borrarlo a mano. El sistema operativo libera el bloqueo al terminar el proceso dueño. Su contenido JSON (dueño, pid, desde) es diagnóstico. Solo vale en un sistema de archivos local (APFS, ext4); no se garantiza en NFS ni en carpetas sincronizadas.

## Fallos inyectables (solo pruebas)

`SIPSA_INYECTAR_FALLO` acepta los valores `fuentes`, `normalizar:<tipo>:<año>`, `construir:tras_precios`, `construir:tras_commit`, `validar:corromper_panel`, `publicar:antes_de_apuntar`, `publicar:tras_apuntar`, `publicar:historial`, `revertir:antes_de_apuntar`, `revertir:tras_apuntar`, `revertir:historial`, `publicar:evento_final`, `revertir:evento_final` y `liberar:ficha`. Desde v2.1 se pueden combinar varios separados por comas. `SIPSA_PAUSA=<punto>` detiene la ejecución en `construir:bloqueo_tomado`, `normalizar:<tipo>:<año>` o `publicar:antes_de_reverificar` hasta que la prueba borre `datos/.pausa-<punto>`. Es sincronización entre procesos para las pruebas, no una espera fija. Con `SIPSA_FALLO_MODO=kill` el fallo es un SIGKILL a todo el grupo de procesos. Ejecútelo solo en una sesión propia, como hacen las pruebas con `start_new_session`. Sin estas variables no existe ningún efecto.

## Retención

Los lotes son inmutables y de solo lectura. Para liberar espacio se pueden borrar lotes que no figuren en `APROBADO.json` después de dar escritura a sus directorios con `chmod -R u+w`. El historial en `historial_aprobados.jsonl` se conserva. La caché se puede borrar entera: la siguiente ejecución vuelve a normalizar en unos 4 minutos.
