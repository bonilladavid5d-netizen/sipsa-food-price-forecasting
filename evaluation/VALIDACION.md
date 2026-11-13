# Validación de la evaluación predictiva

> **Distribución (revisión `distribucion-etapa1-v2`).** Esta copia no incluye `predicciones.csv` ni `predicciones_seleccion.csv`, porque contienen precios del DANE. Los 61 controles y el recálculo descritos abajo requieren reconstruirlos localmente. Sin ellos, `verificar-publico` ejecuta las comprobaciones posibles y marca el resto como «NO EJECUTADO» ([`../docs/reproduccion.md`](../docs/reproduccion.md)).
>
> **Enmienda `recalcular-aprobacion`.** `python -m evaluacion recalcular` retira cualquier `VALIDACION_VIGENTE.json` anterior antes de comprobar sus insumos, y también ante un fallo o una excepción. Solo `controles` emite la aprobación. `reproducir.sh` ejecuta ahora `recalcular` antes que `controles`.

> **Copia pública.** Las rutas `evidencia_v2/…` y `resultados/logs/…` citadas abajo corresponden al expediente de revisión, que no se publica porque sus logs contienen rutas locales. Los controles, el recálculo y las pruebas de rechazo se vuelven a ejecutar con los comandos de [`../docs/reproduccion.md`](../docs/reproduccion.md). En esta copia, la integridad del código se verifica con `resultados/revision_publicacion_etapa1.json`, hija de `revision_mantenimiento_v2.json`.

## Revisión de mantenimiento v2 (posterior a los resultados)

La auditoría independiente demostró que los controles de v1 aceptaban tres alteraciones:

- un aporte falso (`mase_con_abast = 0`, `delta_mase = −99`);
- una fecha 2030-01 con `cumple = True`;
- un cambio de 300 a 1 árbol en `nucleo.py`.

En v2:

- `recalcular.py` recalcula desde `predicho − observado` todas las tablas publicadas y las cifras del resumen. Exige llaves idénticas (unión externa), cobertura completa derivada del protocolo y conjuntos emparejados, con tolerancias explícitas (`rtol = 1e−7`, `atol = 1e−9`, justificadas por la exportación a 10 cifras significativas).
- `controles.py` recalcula para cada predicción y fila de auditoría los límites desde el origen y los retrasos: precio, volumen, etiqueta, base B, objetivo y emisión. El campo `cumple` no se usa como evidencia.
- `integridad.py` detiene la ejecución si algún módulo difiere del manifiesto aprobado.

Control íntegro: 61 PASS y 0 fallos críticos (`evidencia_v2/logs/02_control_integro.log`).

Pruebas de rechazo, cada una en una copia aislada (`evidencia_v2/rechazos/`), 7/7 según lo esperado:

| Caso | Código de salida | Mensaje concreto |
|---|---|---|
| 1. Entrega íntegra | 0 | 61 PASS |
| 2. Aporte falso | 1 | discrepancias en `mase_con_abast`, `mae_con_abast` y `delta_mase` |
| 3. Fecha 2030-01 con `cumple = True` | 1 | `ultimo_precio_usado_igual_al_limite`, `precio_usado_no_supera_limite`, `booleano_cumple_igual_al_recalculo` |
| 4. `n_estimators` de 300 a 1, con `ejecutar` | 1 | «RECHAZADO antes de estimar…» en 1,6 s, sin reestimar |
| 4b. `n_estimators` de 300 a 1, con `controles` | 1 | `codigo_coincide_con_manifiesto_aprobado` |
| 5a. Falta el modelo `rf_abast_ctrl` | 1 | faltan 2.160 predicciones |
| 5b. Falta el escenario `retro_r2` | 1 | faltan 5.760 predicciones |

En todos los rechazos se elimina la `VALIDACION_VIGENTE.json` previa. La sección siguiente describe la validación de v1 y se conserva como historia.

---

## Validación v1 (historia)

Todas las comprobaciones se ejecutaron en el Mac de trabajo (macOS 27.2 arm64, Python 3.13.11; versiones en `requirements.lock`) el 11-11-2026. **No hubo revisión independiente ni ejecución en Linux de esta fase.** Las pruebas con datos sintéticos se identifican como tales y no son resultados.

## Orden de ejecución comprobado

1. Pruebas de fuga **sintéticas** antes de congelar: 6/6 PASS. El archivo se regeneró después; véase `resultados/registro_cambios.md`, n.º 1.
2. Prueba de humo de toda la cadena **solo con datos sintéticos**, en un directorio temporal, sin datos reales.
3. Congelamiento del protocolo: `resultados/registro_protocolo.json`, 2026-11-11T21:30:54Z. Incluye las huellas del protocolo, de la configuración, de las entradas y del código.
4. Ejecución real (`resultados/logs/01_ejecutar.log`):
   - selección con objetivos 2023-01..10;
   - parámetros congelados a las 21:32:08Z, antes de cualquier pronóstico de 2024–2025;
   - evaluación con los parámetros leídos desde el archivo congelado;
   - fin a las 21:35:10Z.
5. Pruebas de fuga sintéticas y sobre una copia derivada del lote (`02b_fugas.log`), controles (`03_controles.log`), recálculo y figuras.
6. Reproducción en una carpeta nueva con entorno nuevo (`04_reproduccion_carpeta_nueva.log`).

## Controles y resultados

| Control | Resultado | Evidencia |
|---|---|---|
| Integridad del lote de entrada | PASS | `lote.verificar_aprobado(completo=True)` sobre `lote-20261111T192146Z-0dba2228adae`; huella `0dba2228…`; 2.880 celdas, 2.878 precios, 2.880 volúmenes, 30 series, 96 meses, 10 mercado-mes con aviso; SHA-256 de `panel_mensual.csv` igual al del manifiesto. El lote no se modificó. |
| Orden protocolo → parámetros → evaluación | PASS | Marcas de tiempo en `controles_ejecucion.json` |
| La selección usa solo objetivos 2023-01..10 | PASS | `predicciones_seleccion.csv` |
| Sin información futura en variables, etiquetas y base | PASS | `auditoria_temporal.csv`, 82 orígenes × escenario. En cada origen: último precio, volumen, base y etiqueta usados ≤ límite permitido. |
| Sin información futura en preprocesamiento y modelos (sintético y copia derivada) | **9/9 PASS** | `controles/pruebas_fugas.json`, con orígenes 2023-06 y 2025-05 (sintéticos) y 2024-06 (copia derivada), en los tres escenarios |
| Una predicción por modelo, escenario, serie y origen | PASS | 17.280 filas de evaluación y 7.800 de selección, sin duplicados |
| Cobertura completa | PASS | 24 orígenes × 30 series × 8 modelos por escenario |
| Mismo conjunto evaluado en todos los modelos | PASS | Por escenario |
| Objetivos ausentes excluidos y explícitos | PASS | 48 filas (2 objetivos × 8 modelos × 3 escenarios), motivo `objetivo_ausente` |
| Evaluación con los parámetros congelados | PASS | `config` de cada fila igual a `parametros_congelados.json` |
| Métricas recalculables desde `predicciones.csv` | PASS | Diferencia máxima: 1,0e-9 en MASE por serie, 4,6e-7 COP/kg en MAE y 3,7e-10 en la media global |
| Aporte emparejado | PASS | 30 series en cada escenario, familia, tipo y año; el código exige el mismo `n` por serie en ambos modelos |
| Reproducibilidad | PASS | Carpeta nueva y entorno nuevo: los 10 archivos de resultados son idénticos byte a byte. Los parámetros congelados coinciden salvo la fecha (`controles/reproduccion_carpeta_nueva.json`). |

En la prueba de fuga se multiplicaron por factores aleatorios de 0,2 a 5:

- todos los precios posteriores a `t0 − retraso_precio`;
- todos los volúmenes posteriores a `t0 − retraso_abastecimiento`.

Las variables de todas las filas usadas (entrenamiento y pronóstico), las etiquetas de entrenamiento, la escala MASE y los pronósticos de Ridge y RF, con y sin volumen, quedaron idénticos.

**Controles negativos** (prueban que la prueba no es vacía):

- alterar el último precio permitido cambia los pronósticos;
- alterar el último volumen permitido cambia solo los modelos con volumen.

## Límites de la validación

- **Disponibilidad:** comprueba la disponibilidad **supuesta** de cada escenario, no fechas históricas reales de publicación.
- **Pruebas de fuga:** cubren el código de variables, entrenamiento y pronóstico en tres orígenes, no todos. La auditoría temporal cubre los 82.
- **Significancia:** no se calcularon p-valores, porque series y meses no son independientes.
- **Sensibilidad sin avisos en la ventana de volumen:** deja 140 de 718 filas, un subconjunto pequeño y no representativo.
- **Auditoría externa no leída:** `SIPSA_AUDITORIA_DATOS_Y_APTITUD.zip` no estaba disponible. Los hechos que el encargo le atribuye se comprobaron directamente contra el lote aprobado.
