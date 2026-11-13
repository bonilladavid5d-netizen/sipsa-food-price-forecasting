"""Orquestación: congelar protocolo, seleccionar (2023-01..10), congelar parámetros, evaluar (2024-2025),
sensibilidades y tablas. Orden estricto: la evaluación lee los parámetros solo desde el archivo congelado."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import platform
import sys
from importlib import metadata
from pathlib import Path

import numpy as np
import pandas as pd

from . import nucleo as N
from .datos import RAIZ, cargar_lote, proyecto_ingenieria, sha256

RES = RAIZ / "resultados"


def cfg() -> dict:
    return json.loads((RAIZ / "config/protocolo.json").read_text(encoding="utf-8"))


def ahora() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def huella_codigo() -> dict:
    arch = sorted((RAIZ / "evaluacion").glob("*.py"))
    per = {str(p.relative_to(RAIZ)): sha256(p) for p in arch}
    return {"sha256": hashlib.sha256(json.dumps(per, sort_keys=True).encode()).hexdigest(), "archivos": per}


def entorno() -> dict:
    pk = {n: metadata.version(n) for n in ["numpy", "pandas", "scikit-learn", "duckdb", "pyarrow", "matplotlib", "scipy"]}
    return {"python": sys.version.split()[0], "sistema": platform.system(), "version": platform.release(),
            "maquina": platform.machine(), "paquetes": pk}


def huellas_protocolo() -> dict:
    return {"PROTOCOLO_PREDICTIVO.md": sha256(RAIZ / "PROTOCOLO_PREDICTIVO.md"),
            "config/protocolo.json": sha256(RAIZ / "config/protocolo.json")}


def congelar() -> dict:
    reg = RES / "registro_protocolo.json"
    if reg.exists():
        raise SystemExit("El protocolo ya está congelado; un cambio debe registrarse en resultados/registro_cambios.md")
    _, info = cargar_lote(verificar=True)
    out = {"congelado_utc": ahora(), "protocolo": cfg()["version"], "huellas": huellas_protocolo(), "entrada": info,
           "codigo_al_congelar": huella_codigo(), "entorno": entorno(),
           "nota": "Antes de este registro solo se ejecutaron pruebas con datos sintéticos; ningún modelo se ajustó con datos reales."}
    RES.mkdir(parents=True, exist_ok=True)
    reg.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n")
    return out


def _comprobar_congelado():
    reg = RES / "registro_protocolo.json"
    if not reg.exists():
        raise SystemExit("Protocolo no congelado: ejecute `python -m evaluacion congelar` primero")
    r = json.loads(reg.read_text())
    if r["huellas"] != huellas_protocolo():
        raise SystemExit("El protocolo o su configuración cambiaron después del congelamiento")
    # Revisión de mantenimiento v2: los módulos de cálculo, validación y presentación deben coincidir con el
    # manifiesto aprobado vinculado a este registro. Se comprueba ANTES de cargar datos o estimar.
    from .integridad import CodigoNoAprobado, verificar_codigo
    try:
        verificar_codigo(RAIZ)
    except CodigoNoAprobado as e:
        raise SystemExit(f"RECHAZADO antes de estimar. {e}")
    return r


def _cierre(mes_txt: str) -> str:
    sys.path.insert(0, str(proyecto_ingenieria()))
    from sipsa.util import cierre_mes
    return cierre_mes(mes_txt)


def _modelos_seleccion(c: dict) -> dict:
    mods = {}
    for abast, suf in [(False, "precio"), (True, "abast")]:
        for a in c["modelos"]["ridge_precio"]["rejilla"]["alpha"]:
            mods[f"ridge_{suf}|alpha={a}"] = ("ridge", {"alpha": a}, abast)
        for d in c["modelos"]["rf_precio"]["rejilla"]["max_depth"]:
            for leaf in c["modelos"]["rf_precio"]["rejilla"]["min_samples_leaf"]:
                mods[f"rf_{suf}|max_depth={d};min_samples_leaf={leaf}"] = ("rf", {"max_depth": d, "min_samples_leaf": leaf}, abast)
    return mods


def _regularizacion(familia: str, params: dict) -> tuple:
    """Orden para desempates: más regularizado primero."""
    if familia == "ridge":
        return (-params["alpha"],)
    d = params["max_depth"] if params["max_depth"] is not None else 10 ** 6
    return (d, -params["min_samples_leaf"])


def seleccionar(panel: N.Panel, c: dict, semilla: int) -> dict:
    lp = c["escenarios"]["retrasos_meses"]["retro_r1"]["precio"]
    la = c["escenarios"]["retrasos_meses"]["retro_r1"]["abastecimiento"]
    ej = N.tabla_ejemplos(panel, lp, la)
    ini, fin = (N.idx(x) for x in c["periodos"]["seleccion_meses_objetivo"])
    mods = _modelos_seleccion(c)
    preds = []
    for m in range(ini, fin + 1):
        p = N.pronosticar_origen(panel, ej, m - 1, lp, mods, semilla)
        p["escenario"] = "retro_r1"
        preds.append(p)
    pred = N.estado_filas(pd.concat(preds, ignore_index=True))
    pred["fase"] = "seleccion"
    ms = N.metricas_serie(pred, ["modelo"])
    resumen = ms.groupby("modelo").agg(mase_medio=("mase", "mean"), mase_mediana=("mase", "median"), series=("mase", "size")).reset_index()
    resumen["familia_variante"] = resumen.modelo.str.split("|").str[0]
    elegido = {}
    for fv, g in resumen.groupby("familia_variante"):
        if fv in ("ingenuo", "estacional"):
            continue
        familia = fv.split("_")[0]
        cand = []
        for _, r in g.iterrows():
            nombre = r.modelo
            params = mods[nombre][1]
            cand.append((round(r.mase_medio, 9), _regularizacion(familia, params), nombre, params))
        cand.sort(key=lambda x: (x[0], x[1]))
        elegido[fv] = {"familia": familia, "params": cand[0][3], "mase_seleccion": cand[0][0], "modelo_config": cand[0][2]}
    ref = resumen[resumen.familia_variante.isin(["ingenuo", "estacional"])].sort_values("mase_medio").iloc[0]
    fam = min(["ridge", "rf"], key=lambda f: elegido[f"{f}_precio"]["mase_seleccion"])
    congelado = {"congelado_utc": ahora(), "escenario_seleccion": "retro_r1",
                 "objetivos_seleccion": c["periodos"]["seleccion_meses_objetivo"],
                 "parametros": {k: v["params"] for k, v in elegido.items()},
                 "mase_seleccion": {k: v["mase_seleccion"] for k, v in elegido.items()},
                 "referente": ref.modelo, "mase_referente_seleccion": float(ref.mase_medio),
                 "mase_ingenuo_seleccion": float(resumen.loc[resumen.modelo == "ingenuo", "mase_medio"].iloc[0]),
                 "mase_estacional_seleccion": float(resumen.loc[resumen.modelo == "estacional", "mase_medio"].iloc[0]),
                 "familia_principal": fam,
                 "nota": "Escrito antes de calcular cualquier pronóstico con objetivo en 2024-2025."}
    d = RES / "seleccion"
    d.mkdir(parents=True, exist_ok=True)
    _exportar_predicciones(pred, d / "predicciones_seleccion.csv")
    ms.to_csv(d / "metricas_seleccion_por_serie.csv", index=False)
    resumen.sort_values(["familia_variante", "mase_medio"]).to_csv(d / "metricas_seleccion_resumen.csv", index=False)
    (d / "parametros_congelados.json").write_text(json.dumps(congelado, ensure_ascii=False, indent=2) + "\n")
    return congelado


COLS_PRED = ["modelo", "config", "escenario", "fase", "origen", "emision", "objetivo", "product_id", "market_id", "product", "market",
             "observado", "predicho", "estado_evaluacion", "motivo_exclusion", "error", "escala_mase", "pares_escala",
             "error_abs_escalado", "B", "mes_base", "p_estacional", "ultimo_mes_precio_usado", "ultimo_mes_abast_usado",
             "n_entrenamiento", "ultima_etiqueta_entrenamiento", "aviso_objetivo", "aviso_en_ventana_abast"]


def _exportar_predicciones(pred: pd.DataFrame, ruta: Path):
    pred = pred.copy()
    if "emision" not in pred:
        cache = {o: _cierre(o) for o in pred.origen.unique()}
        pred["emision"] = pred.origen.map(cache)
    pred = pred.sort_values(["fase", "escenario", "modelo", "origen", "product_id", "market_id"])
    pred[COLS_PRED].to_csv(ruta, index=False, float_format="%.10g")


def evaluar(panel: N.Panel, c: dict, congelado: dict, semilla: int) -> pd.DataFrame:
    P = congelado["parametros"]
    mods = {"ridge_precio": ("ridge", P["ridge_precio"], False), "ridge_abast": ("ridge", P["ridge_abast"], True),
            "rf_precio": ("rf", P["rf_precio"], False), "rf_abast": ("rf", P["rf_abast"], True),
            # comparación controlada: con abastecimiento y los parámetros de la variante sin abastecimiento
            "ridge_abast_ctrl": ("ridge", P["ridge_precio"], True), "rf_abast_ctrl": ("rf", P["rf_precio"], True)}
    ini, fin = (N.idx(x) for x in c["periodos"]["evaluacion_meses_objetivo"])
    todas = []
    for esc, r in c["escenarios"]["retrasos_meses"].items():
        ej = N.tabla_ejemplos(panel, r["precio"], r["abastecimiento"])
        for m in range(ini, fin + 1):
            p = N.pronosticar_origen(panel, ej, m - 1, r["precio"], mods, semilla)
            p["escenario"] = esc
            todas.append(p)
        print("evaluado", esc, flush=True)
    pred = N.estado_filas(pd.concat(todas, ignore_index=True))
    pred["fase"] = "evaluacion"
    return pred


def flujo(panel: N.Panel, c: dict, pred_eval: pd.DataFrame, pred_sel: pd.DataFrame) -> pd.DataFrame:
    filas = [{"escenario": "todos", "etapa": "malla_producto_mercado_mes", "n": int(panel.P.size)},
             {"escenario": "todos", "etapa": "con_precio_observado", "n": int(np.isfinite(panel.P).sum())},
             {"escenario": "todos", "etapa": "con_abastecimiento_observado", "n": int(np.isfinite(panel.Q).sum())}]
    for esc, r in c["escenarios"]["retrasos_meses"].items():
        ej = N.tabla_ejemplos(panel, r["precio"], r["abastecimiento"])
        filas += [
            {"escenario": esc, "etapa": "ejemplos_con_ventana_completa", "n": len(ej), "detalle": f"objetivos {ej.objetivo.min()}..{ej.objetivo.max()}"},
            {"escenario": esc, "etapa": "perdidos_por_ventanas_y_rezagos", "n": int(panel.P.size - len(ej)),
             "detalle": f"meses objetivo anteriores a {ej.objetivo.min()} (ventanas L-12..L, m-12, S-14..S)"},
            {"escenario": esc, "etapa": "ejemplos_con_etiqueta_observada", "n": int(np.isfinite(ej.y).sum())},
            {"escenario": esc, "etapa": "ejemplos_sin_etiqueta", "n": int((~np.isfinite(ej.y)).sum()),
             "detalle": ";".join(ej.loc[~np.isfinite(ej.y), "objetivo"] + " " + ej.loc[~np.isfinite(ej.y), "product"] + " @ " + ej.loc[~np.isfinite(ej.y), "market"])}]
        for fase, pr in [("seleccion", pred_sel), ("evaluacion", pred_eval)]:
            d = pr[(pr.escenario == esc) & (pr.modelo == "ingenuo")]
            if d.empty:
                continue
            filas += [{"escenario": esc, "etapa": f"{fase}_filas_pronosticadas", "n": len(d)},
                      {"escenario": esc, "etapa": f"{fase}_filas_evaluadas", "n": int((d.estado_evaluacion == "evaluada").sum())}]
            for mot, k in d[d.estado_evaluacion == "excluida"].motivo_exclusion.value_counts().items():
                det = ";".join(d.loc[d.motivo_exclusion == mot, "objetivo"] + " " + d.loc[d.motivo_exclusion == mot, "product"] + " @ " + d.loc[d.motivo_exclusion == mot, "market"])
                filas.append({"escenario": esc, "etapa": f"{fase}_excluidas_{mot}", "n": int(k), "detalle": det})
            filas += [{"escenario": esc, "etapa": f"{fase}_entrenamiento_primer_origen", "n": int(d.n_entrenamiento.iloc[d.origen.argmin()])},
                      {"escenario": esc, "etapa": f"{fase}_entrenamiento_ultimo_origen", "n": int(d.n_entrenamiento.iloc[d.origen.argmax()])}]
    return pd.DataFrame(filas)


def auditoria_temporal(c: dict, pred: pd.DataFrame) -> pd.DataFrame:
    filas = []
    for (esc, fase, origen), d in pred[pred.modelo == "ingenuo"].groupby(["escenario", "fase", "origen"]):
        r = c["escenarios"]["retrasos_meses"][esc]
        t = N.idx(origen)
        lim_p, lim_a = N.mes(t - r["precio"]), N.mes(t - r["abastecimiento"])
        filas.append({"escenario": esc, "fase": fase, "origen": origen, "emision": d.emision.iloc[0], "objetivo": N.mes(t + 1),
                      "ultimo_mes_precio_permitido": lim_p, "ultimo_mes_abast_permitido": lim_a,
                      "ultima_etiqueta_permitida": lim_p, "ultima_etiqueta_usada": d.ultima_etiqueta_entrenamiento.max(),
                      "max_mes_precio_usado_pronostico": d.ultimo_mes_precio_usado.max(),
                      "max_mes_abast_usado_pronostico": d.ultimo_mes_abast_usado.max(),
                      "max_mes_base_B": d.mes_base.dropna().max(), "n_entrenamiento": int(d.n_entrenamiento.iloc[0]),
                      "cumple": bool(d.ultima_etiqueta_entrenamiento.max() <= lim_p and d.ultimo_mes_precio_usado.max() <= lim_p
                                     and d.ultimo_mes_abast_usado.max() <= lim_a and d.mes_base.dropna().max() <= lim_p)})
    return pd.DataFrame(filas)


def tablas_metricas(pred: pd.DataFrame, congelado: dict) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    ev = pred.copy()
    ev["anio"] = ev.objetivo.str[:4]
    ev["mes_cal"] = ev.objetivo.str[5:7]
    ms = N.metricas_serie(ev, ["escenario", "modelo"])
    ref = congelado["referente"]
    filas = []
    cortes = [("global", None), ("anio", "anio"), ("producto", "product"), ("mercado", "market"), ("mes_calendario", "mes_cal"),
              ("aviso_objetivo", "aviso_objetivo"), ("aviso_en_ventana_abast", "aviso_en_ventana_abast")]
    for corte, col in cortes:
        grupos = [("todos", ev)] if col is None else list(ev.groupby(col))
        for val, d in grupos:
            m = N.metricas_serie(d, ["escenario", "modelo"])
            for (esc, mod), g in m.groupby(["escenario", "modelo"]):
                gr = m[(m.escenario == esc) & (m.modelo == ref)].set_index(["product_id", "market_id"]).mase
                gi = g.set_index(["product_id", "market_id"]).mase
                comun = gi.index.intersection(gr.index)
                filas.append({"escenario": esc, "modelo": mod, "corte": corte, "valor": str(val), "series": len(g), "filas": int(g.n.sum()),
                              "mase_medio": g.mase.mean(), "mase_mediana": g.mase.median(),
                              "error_firmado_pct_medio": g.error_firmado_pct.mean(),
                              "prop_series_mejor_que_referente": float((gi[comun] < gr[comun]).mean()) if mod != ref else np.nan})
    # Sensibilidad: copia derivada excluyendo filas con aviso en la ventana de abastecimiento (todos los modelos igual).
    sub = ev[~ev.aviso_en_ventana_abast.astype(bool)]
    m = N.metricas_serie(sub, ["escenario", "modelo"])
    for (esc, mod), g in m.groupby(["escenario", "modelo"]):
        filas.append({"escenario": esc, "modelo": mod, "corte": "sensibilidad_sin_aviso_en_ventana_abast", "valor": "excluidas",
                      "series": len(g), "filas": int(g.n.sum()), "mase_medio": g.mase.mean(), "mase_mediana": g.mase.median(),
                      "error_firmado_pct_medio": g.error_firmado_pct.mean(), "prop_series_mejor_que_referente": np.nan})
    resumen = pd.DataFrame(filas)
    # Aporte del abastecimiento (emparejado por serie).
    ap = []
    for esc in ev.escenario.unique():
        for fam in ["ridge", "rf"]:
            for tipo, con in [("parametros_propios", f"{fam}_abast"), ("parametros_comunes_controlada", f"{fam}_abast_ctrl")]:
                for anio in ["todos", "2024", "2025"]:
                    d = ev[(ev.escenario == esc)] if anio == "todos" else ev[(ev.escenario == esc) & (ev.anio == anio)]
                    m = N.metricas_serie(d[d.modelo.isin([f"{fam}_precio", con])], ["modelo"])
                    a = m[m.modelo == f"{fam}_precio"].set_index(["product_id", "market_id", "product", "market"])
                    b = m[m.modelo == con].set_index(["product_id", "market_id", "product", "market"])
                    assert a.index.equals(b.index) and (a.n == b.n).all(), "conjuntos no emparejados"
                    for k in a.index:
                        ap.append({"escenario": esc, "familia": fam, "tipo": tipo, "anio": anio, "product_id": k[0], "market_id": k[1],
                                   "product": k[2], "market": k[3], "n": int(a.loc[k, "n"]),
                                   "mase_sin_abast": a.loc[k, "mase"], "mase_con_abast": b.loc[k, "mase"],
                                   "delta_mase": b.loc[k, "mase"] - a.loc[k, "mase"],
                                   "mae_sin_abast": a.loc[k, "mae_cop_kg"], "mae_con_abast": b.loc[k, "mae_cop_kg"],
                                   "params_sin": congelado["parametros"][f"{fam}_precio"],
                                   "params_con": congelado["parametros"][f"{fam}_abast"] if tipo == "parametros_propios" else congelado["parametros"][f"{fam}_precio"]})
    return ms, resumen, pd.DataFrame(ap)


def ejecutar() -> dict:
    reg = _comprobar_congelado()
    c = cfg()
    semilla = c["modelos"]["semilla"]
    df, info = cargar_lote(verificar=True)
    panel = N.Panel.desde_df(df)
    inicio = ahora()
    congelado = seleccionar(panel, c, semilla)
    # La evaluación toma los parámetros desde el archivo congelado (no desde memoria).
    congelado = json.loads((RES / "seleccion/parametros_congelados.json").read_text())
    pred = evaluar(panel, c, congelado, semilla)
    cache = {o: _cierre(o) for o in pred.origen.unique()}
    pred["emision"] = pred.origen.map(cache)
    _exportar_predicciones(pred, RES / "predicciones.csv")
    pred_sel = pd.read_csv(RES / "seleccion/predicciones_seleccion.csv")
    ms, resumen, ap = tablas_metricas(pred, congelado)
    ms.to_csv(RES / "metricas_por_serie.csv", index=False, float_format="%.10g")
    resumen.to_csv(RES / "metricas_resumen.csv", index=False, float_format="%.10g")
    ap.to_csv(RES / "aporte_abastecimiento.csv", index=False, float_format="%.10g")
    flujo(panel, c, pred, pred_sel).to_csv(RES / "flujo_observaciones.csv", index=False)
    aud = pd.concat([auditoria_temporal(c, pred), auditoria_temporal(c, pred_sel)], ignore_index=True)
    aud.to_csv(RES / "auditoria_temporal.csv", index=False)
    ejecucion = {"inicio_utc": inicio, "fin_utc": ahora(), "entrada": info, "codigo": huella_codigo(), "entorno": entorno(),
                 "protocolo_congelado_utc": reg["congelado_utc"], "parametros_congelados_utc": congelado["congelado_utc"]}
    (RES / "ejecucion.json").write_text(json.dumps(ejecucion, ensure_ascii=False, indent=2) + "\n")
    return ejecucion
