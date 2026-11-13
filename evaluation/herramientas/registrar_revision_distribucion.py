"""Crea UNA vez resultados/revision_distribucion_etapa1_v2.json en la copia pública.

Revisión de distribución POSTERIOR a los resultados. Hija, por SHA-256, de revision_publicacion_etapa1.json.
- retirados: archivos que contienen series del DANE (precios o volúmenes) y no se distribuyen. Se registra la huella
  del archivo aprobado en el expediente privado y cómo reconstruirlo localmente.
- tablas_conservadas_aprobadas: huellas fijas de las tablas que sí se publican, tomadas del expediente v2 (no de
  esta copia), y comparadas con la copia.
- modulos_aprobados: iguales a la revisión de publicación salvo los cambios declarados.
Se niega a sobrescribir.
Uso: python herramientas/registrar_revision_distribucion.py <sipsa_evaluacion_v2> <sipsa_datos>
"""
import datetime as dt, hashlib, json, sys
from pathlib import Path
RAIZ = Path(__file__).resolve().parents[1]
EV2, ING = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
dst = RAIZ / "resultados/revision_distribucion_etapa1_v2.json"
if dst.exists():
    raise SystemExit("revision_distribucion_etapa1_v2.json ya existe: no se sobrescribe")
pub_p = RAIZ / "resultados/revision_publicacion_etapa1.json"
pub = json.loads(pub_p.read_text())
RETIRADOS = {
    "evaluation/resultados/predicciones.csv": (EV2 / "resultados/predicciones.csv",
        "precios observados, base B, referencia estacional y pronósticos ingenuo/estacional (reproducen precios); observado = predicho - error",
        "modo B: reconstruir el lote de ingeniería y ejecutar evaluation/reproducir.sh en una copia de trabajo"),
    "evaluation/resultados/seleccion/predicciones_seleccion.csv": (EV2 / "resultados/seleccion/predicciones_seleccion.csv",
        "mismas columnas de precios para los objetivos de 2023", "igual que predicciones.csv"),
    "engineering/config/referencia_panel_viabilidad.csv": (ING / "config/referencia_panel_viabilidad.csv",
        "panel de 2.880 celdas con price (COP/kg) y kg mensuales", "engineering/herramientas/reconstruir_referencias.py"),
    "engineering/config/referencia_conciliacion_viabilidad.csv": (ING / "config/referencia_conciliacion_viabilidad.csv",
        "288 totales mercado-mes: official_tonnes y microdata_kg", "engineering/herramientas/reconstruir_referencias.py"),
    "engineering/config/referencia_candidatos_viabilidad.csv": (ING / "config/referencia_candidatos_viabilidad.csv",
        "kg acumulados 2018-2022 por producto (training_kg) y cobertura", "engineering/herramientas/reconstruir_referencias.py"),
}
retirados = {}
for rel, (orig, motivo, ruta) in RETIRADOS.items():
    assert not (RAIZ.parent / rel).exists(), f"{rel} sigue en la copia pública"
    retirados[rel] = {"sha256_aprobado": sha(orig), "bytes": orig.stat().st_size, "motivo": motivo, "reconstruccion": ruta,
                      "original_conservado_en": f"expediente privado: {orig.parent.name}/{orig.name} y su ZIP aprobado"}
CONSERVADAS = ["metricas_por_serie.csv", "metricas_resumen.csv", "aporte_abastecimiento.csv", "auditoria_temporal.csv",
               "flujo_observaciones.csv", "cifras_resumen.json", "seleccion/metricas_seleccion_por_serie.csv",
               "seleccion/metricas_seleccion_resumen.csv", "seleccion/parametros_congelados.json", "controles/pruebas_fugas.json",
               "figuras/fig1_precision_por_modelo.png", "figuras/fig2_aporte_abastecimiento_por_serie.png", "figuras/fig3_estabilidad_aporte.png"]
tablas = {}
for f in CONSERVADAS:
    h = sha(EV2 / "resultados" / f)
    assert h == sha(RAIZ / "resultados" / f), f"{f} difiere del expediente v2"
    tablas[f"resultados/{f}"] = h
mods = {m: sha(RAIZ / m) for m in pub["modulos_aprobados"]}
mods["evaluacion/publico.py"] = sha(RAIZ / "evaluacion/publico.py")
cambios = []
JUST = {"evaluacion/integridad.py": "validacion: añade el eslabón revision_distribucion y clasifica publico.py",
        "evaluacion/publico.py": "validacion (nuevo): verificación pública sin series del DANE y comparación de una reconstrucción local con lo aprobado",
        "evaluacion/__main__.py": "presentacion/CLI: comandos verificar-publico y comparar-aprobado; controles y recalcular informan NO EJECUTADO sin datos (código 2)"}
for m, h in mods.items():
    if h != pub["modulos_aprobados"].get(m):
        assert m in JUST, f"{m} cambió sin justificación"
        cambios.append({"modulo": m, "sha256_anterior": pub["modulos_aprobados"].get(m), "sha256_distribucion": h, "justificacion": JUST[m]})
assert mods["evaluacion/nucleo.py"] == pub["modulos_aprobados"]["evaluacion/nucleo.py"]
out = {"revision": "distribucion-etapa1-v2", "creado_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
       "naturaleza": "Revisión de distribución posterior a los resultados: retira de la copia pública las series del DANE y adapta la verificación. No cambia datos, estimación, exportación, métricas ni conclusiones.",
       "padre": {"revision": pub["revision"], "revision_publicacion_etapa1_sha256": sha(pub_p),
                 "zip_publicable_anterior_sha256": "47df535564ed1bc20c56b15ff77a356c4fb6621da7148a3c5374fb92bc1cbd0b"},
       "retirados": retirados, "tablas_conservadas_aprobadas": tablas, "modulos_aprobados": mods,
       "huella_codigo_revision": hashlib.sha256(json.dumps(mods, sort_keys=True).encode()).hexdigest(), "cambios": cambios}
dst.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n")
print(json.dumps({"revision": out["revision"], "retirados": list(retirados), "tablas": len(tablas), "cambios": [c["modulo"] for c in cambios]}, ensure_ascii=False, indent=1))
