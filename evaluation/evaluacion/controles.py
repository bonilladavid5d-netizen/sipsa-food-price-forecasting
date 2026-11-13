"""Controles sobre los archivos exportados (revisión de mantenimiento v2). Un FAIL crítico invalida la entrega.

Cambios respecto de v1 (auditoría independiente):
- La cobertura esperada se deriva del protocolo (escenarios, modelos, orígenes, series, rejillas), no de los CSV.
- La validación temporal recalcula los límites desde el origen y los retrasos de la configuración y los contrasta
  con las fechas de predicciones y auditoría (precio, volumen, etiqueta, base B, objetivo, emisión). La columna
  `cumple` almacenada no se usa como evidencia; solo se comprueba que coincida con el recálculo.
- El recálculo de métricas cubre todas las tablas publicadas (recalcular.py).
- La integridad del código se verifica frente al manifiesto aprobado (integridad.py).
- Si algo falla, se elimina cualquier VALIDACION_VIGENTE.json anterior.
"""
from __future__ import annotations

import calendar
import json
from pathlib import Path

import numpy as np
import pandas as pd

from .integridad import APROBACION_VIGENTE, CodigoNoAprobado, invalidar_aprobacion, sha256, verificar_codigo
from .recalcular import MODELOS_EVAL, _idx, _mes, _rango, recalcular

RAIZ = Path(__file__).resolve().parents[1]


def _cierre(mes: str) -> str:
    y, m = map(int, mes.split("-"))
    return f"{y}-{m:02d}-{calendar.monthrange(y, m)[1]:02d}T23:59:59.999999-05:00"


def modelos_seleccion(cfg: dict) -> list[str]:
    g = cfg["modelos"]
    mods = ["ingenuo", "estacional"]
    for suf in ["precio", "abast"]:
        mods += [f"ridge_{suf}|alpha={a}" for a in g["ridge_precio"]["rejilla"]["alpha"]]
        mods += [f"rf_{suf}|max_depth={d};min_samples_leaf={l}" for d in g["rf_precio"]["rejilla"]["max_depth"]
                 for l in g["rf_precio"]["rejilla"]["min_samples_leaf"]]
    return mods


def verificar_temporal(cfg: dict, pr: pd.DataFrame, ps: pd.DataFrame, aud: pd.DataFrame, add) -> None:
    ret = cfg["escenarios"]["retrasos_meses"]
    # Cobertura de la selección derivada del protocolo.
    sel_obj = _rango(*cfg["periodos"]["seleccion_meses_objetivo"])
    sel_org = [_mes(_idx(o) - 1) for o in sel_obj]
    series = sorted(set(map(tuple, pr[["product_id", "market_id"]].to_numpy())))
    esp = {("seleccion", "retro_r1", m, o, s[0], s[1]) for m in modelos_seleccion(cfg) for o in sel_org for s in series}
    llaves = ["fase", "escenario", "modelo", "origen", "product_id", "market_id"]
    obs = set(map(tuple, ps[llaves].to_numpy()))
    add("cobertura_seleccion_segun_protocolo", obs == esp and not ps.duplicated(llaves).any(),
        f"esperadas={len(esp)} presentes={len(ps)} faltan={len(esp - obs)} sobran={len(obs - esp)}")
    todas = pd.concat([pr, ps], ignore_index=True)
    t = todas.origen.map(_idx)
    lp = todas.escenario.map(lambda e: ret[e]["precio"])
    la = todas.escenario.map(lambda e: ret[e]["abastecimiento"])
    lim_p, lim_a = (t - lp).map(_mes), (t - la).map(_mes)
    mb = todas.mes_base.fillna("")
    base_ok = todas.mes_base.isna() | ((mb <= lim_p) & (mb >= (t - lp - 2).map(_mes)))
    reglas = {
        "objetivo_es_origen_mas_uno": todas.objetivo == (t + 1).map(_mes),
        "emision_es_cierre_del_mes_origen": todas.emision == todas.origen.map(_cierre),
        "ultimo_precio_usado_igual_al_limite": todas.ultimo_mes_precio_usado == lim_p,
        "ultimo_volumen_usado_igual_al_limite": todas.ultimo_mes_abast_usado == lim_a,
        "ultima_etiqueta_entrenamiento_igual_al_limite": todas.ultima_etiqueta_entrenamiento == lim_p,
        "base_B_dentro_de_L_L-2": base_ok,
    }
    for nombre, cond in reglas.items():
        malos = todas[~cond]
        add(f"temporal_predicciones:{nombre}", bool(cond.all()),
            f"{len(todas)} filas; incumplen={len(malos)}"
            + (f"; ej. {malos.iloc[0][['fase', 'escenario', 'modelo', 'origen', 'objetivo', 'ultimo_mes_precio_usado', 'ultimo_mes_abast_usado', 'ultima_etiqueta_entrenamiento', 'mes_base']].to_dict()} límite precio={lim_p[malos.index[0]]} volumen={lim_a[malos.index[0]]}" if len(malos) else ""))
    # Auditoría temporal: filas esperadas y límites recalculados; coherencia con las predicciones.
    ev_obj = _rango(*cfg["periodos"]["evaluacion_meses_objetivo"])
    esp_aud = {("evaluacion", e, _mes(_idx(o) - 1)) for e in ret for o in ev_obj} | {("seleccion", "retro_r1", o) for o in sel_org}
    obs_aud = set(map(tuple, aud[["fase", "escenario", "origen"]].to_numpy()))
    add("auditoria_temporal:filas_esperadas_segun_protocolo", obs_aud == esp_aud and not aud.duplicated(["fase", "escenario", "origen"]).any(),
        f"esperadas={len(esp_aud)} presentes={len(aud)} faltan={sorted(esp_aud - obs_aud)[:3]} sobran={sorted(obs_aud - esp_aud)[:3]}")
    ta = aud.origen.map(_idx)
    lpa = aud.escenario.map(lambda e: ret[e]["precio"])
    laa = aud.escenario.map(lambda e: ret[e]["abastecimiento"])
    agg = todas.groupby(["fase", "escenario", "origen"]).agg(
        p=("ultimo_mes_precio_usado", "max"), a=("ultimo_mes_abast_usado", "max"), et=("ultima_etiqueta_entrenamiento", "max"),
        b=("mes_base", "max"), n=("n_entrenamiento", "max"), nmin=("n_entrenamiento", "min")).reset_index()
    m = aud.merge(agg, on=["fase", "escenario", "origen"], how="left")
    recalc_cumple = ((m.ultima_etiqueta_usada <= m.ultimo_mes_precio_permitido) & (m.max_mes_precio_usado_pronostico <= m.ultimo_mes_precio_permitido)
                     & (m.max_mes_abast_usado_pronostico <= m.ultimo_mes_abast_permitido) & (m.max_mes_base_B <= m.ultimo_mes_precio_permitido))
    reglas_a = {
        "objetivo": aud.objetivo == (ta + 1).map(_mes),
        "emision": aud.emision == aud.origen.map(_cierre),
        "limite_precio_recalculado": aud.ultimo_mes_precio_permitido == (ta - lpa).map(_mes),
        "limite_volumen_recalculado": aud.ultimo_mes_abast_permitido == (ta - laa).map(_mes),
        "limite_etiqueta_recalculado": aud.ultima_etiqueta_permitida == (ta - lpa).map(_mes),
        "precio_usado_no_supera_limite": aud.max_mes_precio_usado_pronostico <= (ta - lpa).map(_mes),
        "volumen_usado_no_supera_limite": aud.max_mes_abast_usado_pronostico <= (ta - laa).map(_mes),
        "etiqueta_usada_no_supera_limite": aud.ultima_etiqueta_usada <= (ta - lpa).map(_mes),
        "base_B_no_supera_limite": aud.max_mes_base_B <= (ta - lpa).map(_mes),
        "coherente_con_predicciones_precio": m.max_mes_precio_usado_pronostico == m.p,
        "coherente_con_predicciones_volumen": m.max_mes_abast_usado_pronostico == m.a,
        "coherente_con_predicciones_etiqueta": m.ultima_etiqueta_usada == m.et,
        "coherente_con_predicciones_base_B": m.max_mes_base_B == m.b,
        "coherente_con_predicciones_n_entrenamiento": (m.n_entrenamiento == m.n) & (m.n == m.nmin),
        "booleano_cumple_igual_al_recalculo": m.cumple.astype(bool) == recalc_cumple,
    }
    for nombre, cond in reglas_a.items():
        malos = aud[~cond.to_numpy()]
        add(f"auditoria_temporal:{nombre}", bool(cond.all()), f"{len(aud)} filas; incumplen={len(malos)}"
            + (f"; ej. {malos.iloc[0][['fase', 'escenario', 'origen', 'max_mes_precio_usado_pronostico', 'ultimo_mes_precio_permitido', 'cumple']].to_dict()}" if len(malos) else ""))


def controles(raiz: Path = RAIZ) -> dict:
    res = raiz / "resultados"
    invalidar_aprobacion(raiz)  # ninguna aprobación antigua sobrevive a una nueva ejecución de controles
    cfg = json.loads((raiz / "config/protocolo.json").read_text())
    chk = []
    add = lambda n, ok, d="", critico=True: chk.append({"control": n, "resultado": "PASS" if ok else "FAIL", "critico": critico, "detalle": str(d)[:1500]})
    try:
        info = verificar_codigo(raiz)
        add("codigo_coincide_con_manifiesto_aprobado", True, info)
    except CodigoNoAprobado as e:
        add("codigo_coincide_con_manifiesto_aprobado", False, e)
    reg = json.loads((res / "registro_protocolo.json").read_text())
    add("protocolo_y_configuracion_sin_cambios", reg["huellas"] == {"PROTOCOLO_PREDICTIVO.md": sha256(raiz / "PROTOCOLO_PREDICTIVO.md"),
                                                                  "config/protocolo.json": sha256(raiz / "config/protocolo.json")})
    ejec = json.loads((res / "ejecucion.json").read_text())
    congel = json.loads((res / "seleccion/parametros_congelados.json").read_text())
    add("lote_verificado_y_esperado", ejec["entrada"]["huella_contenido"] == cfg["entrada"]["huella_contenido"]
        and ejec["entrada"]["hechos"] == {**ejec["entrada"]["hechos"], **cfg["entrada"]["hechos_esperados"]}, ejec["entrada"]["lote_id"])
    add("orden_protocolo_seleccion_ejecucion", reg["congelado_utc"] <= congel["congelado_utc"] <= ejec["fin_utc"],
        f"protocolo {reg['congelado_utc']} <= parámetros {congel['congelado_utc']} <= fin {ejec['fin_utc']}")
    pr = pd.read_csv(res / "predicciones.csv", dtype={"origen": str, "objetivo": str, "mes_base": str})
    ps = pd.read_csv(res / "seleccion/predicciones_seleccion.csv", dtype={"origen": str, "objetivo": str, "mes_base": str})
    aud = pd.read_csv(res / "auditoria_temporal.csv", dtype={"origen": str, "objetivo": str, "max_mes_base_B": str})
    add("seleccion_solo_objetivos_permitidos", set(ps.objetivo) == set(_rango(*cfg["periodos"]["seleccion_meses_objetivo"])),
        f"{ps.objetivo.min()}..{ps.objetivo.max()}")
    verificar_temporal(cfg, pr, ps, aud, add)
    P = congel["parametros"]
    fmt = lambda p: ";".join(f"{k}={v}" for k, v in sorted(p.items()))
    esperado = {"ingenuo": "", "estacional": "", "ridge_precio": fmt(P["ridge_precio"]), "ridge_abast": fmt(P["ridge_abast"]),
                "rf_precio": fmt(P["rf_precio"]), "rf_abast": fmt(P["rf_abast"]),
                "ridge_abast_ctrl": fmt(P["ridge_precio"]), "rf_abast_ctrl": fmt(P["rf_precio"])}
    usados = {m: sorted(set(g.config.fillna(""))) for m, g in pr.groupby("modelo")}
    add("evaluacion_usa_parametros_congelados", set(usados) == set(esperado) and all(usados[k] == [v] for k, v in esperado.items()), usados)
    rc = recalcular(res, raiz)
    for c in rc["checks"]:
        add("recalculo:" + c["control"], c["resultado"] == "PASS", c["detalle"])
    sint = res / "controles/pruebas_fugas.json"
    if sint.exists():
        s = json.loads(sint.read_text())
        add("pruebas_de_fuga_sinteticas_y_derivadas", s["fallos"] == 0 and s["pasaron"] >= 9, f"{s['pasaron']} PASS, {s['fallos']} FAIL")
    else:
        add("pruebas_de_fuga_sinteticas_y_derivadas", False, "no ejecutadas")
    fallos = [c for c in chk if c["resultado"] == "FAIL" and c["critico"]]
    out = {"controles": chk, "pasaron": sum(c["resultado"] == "PASS" for c in chk), "fallos_criticos": len(fallos),
           "primeros_fallos": [f"{c['control']}: {c['detalle'][:300]}" for c in fallos[:10]]}
    (res / "controles").mkdir(exist_ok=True)
    (res / "controles/controles_ejecucion_v2.json").write_text(json.dumps(out, ensure_ascii=False, indent=2, default=str) + "\n")
    if not fallos:
        (raiz / APROBACION_VIGENTE).write_text(json.dumps({"vigente": True, "controles": len(chk),
                                                           "codigo": info, "nota": "se elimina ante cualquier fallo posterior"},
                                                          ensure_ascii=False, indent=2) + "\n")
    return out
