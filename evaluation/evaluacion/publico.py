"""Verificación de la copia pública sin series del DANE, y comparación de una reconstrucción local con lo aprobado.

Revisión de distribución Etapa 1 v2, POSTERIOR a los resultados. No cambia estimación, exportación ni métricas.

verificar_publico():
  Comprueba, sin datos de origen:
    - integridad del código, del protocolo y de la configuración;
    - huellas APROBADAS FIJAS de las tablas conservadas, registradas en revision_distribucion_etapa1_v2.json a partir
      del expediente v2, no de esta copia;
    - consistencia interna entre tablas agregadas (resumen frente a series, aporte frente a series, años, selección y
      parámetros congelados);
    - cifras del resumen recalculadas desde las tablas y citadas en el texto;
    - límites temporales de la auditoría recalculados desde la configuración.
  Lo que requiere predicciones o series del DANE se informa como "NO EJECUTADO: requiere reconstrucción local".
  Nunca se marca PASS sin ejecutar.

comparar_con_aprobado(dir_aprobado):
  Tras reconstruir localmente, recalcula las tablas APROBADAS (copiadas tal cual desde dir_aprobado) desde las
  predicciones reconstruidas, con recalcular.py completo. Compara además las tablas regeneradas con las aprobadas y
  la huella de bytes de las predicciones con la aprobada en la revisión de distribución.
"""
from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

from .integridad import DISTRIBUCION, CodigoNoAprobado, invalidar_aprobacion, sha256, verificar_codigo
from .recalcular import ATOL, MODELOS_EVAL, RTOL, _idx, _mes, _rango, recalcular

RAIZ = Path(__file__).resolve().parents[1]
NO_EJ = "NO EJECUTADO: requiere reconstrucción local"
SERIE = ["product_id", "market_id"]


class Informe:
    def __init__(self):
        self.checks = []

    def add(self, nombre, ok, detalle=""):
        self.checks.append({"control": nombre, "resultado": "PASS" if ok else "FAIL", "detalle": str(detalle)[:1200]})

    def no_ejecutado(self, nombre, requiere):
        self.checks.append({"control": nombre, "resultado": "NO_EJECUTADO", "detalle": f"{NO_EJ} ({requiere})"})

    def resumen(self):
        c = lambda r: sum(x["resultado"] == r for x in self.checks)
        return {"pasaron": c("PASS"), "fallaron": c("FAIL"), "no_ejecutados": c("NO_EJECUTADO"), "controles": self.checks}


def _cerca(a, b) -> bool:
    a, b = np.asarray(a, float), np.asarray(b, float)
    return bool(np.all(np.isclose(a, b, rtol=RTOL, atol=ATOL) | (np.isnan(a) & np.isnan(b))))


def verificar_publico(raiz: Path = RAIZ) -> dict:
    invalidar_aprobacion(raiz)  # este modo nunca deja una aprobación completa vigente
    res = raiz / "resultados"
    inf = Informe()
    cfg = json.loads((raiz / "config/protocolo.json").read_text())
    try:
        inf.add("codigo_coincide_con_manifiesto_aprobado", True, verificar_codigo(raiz))
    except CodigoNoAprobado as e:
        inf.add("codigo_coincide_con_manifiesto_aprobado", False, e)
    reg = json.loads((res / "registro_protocolo.json").read_text())
    inf.add("protocolo_y_configuracion_sin_cambios", reg["huellas"] == {
        "PROTOCOLO_PREDICTIVO.md": sha256(raiz / "PROTOCOLO_PREDICTIVO.md"), "config/protocolo.json": sha256(raiz / "config/protocolo.json")})
    dist = json.loads((raiz / DISTRIBUCION).read_text())
    malas = []
    for rel, h in dist["tablas_conservadas_aprobadas"].items():
        p = raiz / rel
        if not p.exists():
            malas.append(f"falta {rel}")
        elif sha256(p) != h:
            malas.append(f"alterada {rel}")
    inf.add("tablas_conservadas_iguales_a_las_aprobadas", not malas,
            f"{len(dist['tablas_conservadas_aprobadas'])} tablas con huella fija del expediente v2; discrepancias={malas}")

    def leer(rel, **kw):
        p = res / rel
        return pd.read_csv(p, **kw) if p.exists() else None
    ms, rs = leer("metricas_por_serie.csv"), leer("metricas_resumen.csv", dtype={"valor": str})
    ap = leer("aporte_abastecimiento.csv", dtype={"anio": str})
    if ms is None or rs is None or ap is None:
        inf.add("tablas_agregadas_presentes", False, "faltan metricas_por_serie, metricas_resumen o aporte_abastecimiento")
        return inf.resumen()
    cong = json.loads((res / "seleccion/parametros_congelados.json").read_text())
    ref = cong["referente"]
    # 1. Resumen global frente a métricas por serie (mismo cálculo: media/mediana entre series; peso igual por serie).
    g = ms.groupby(["escenario", "modelo"]).agg(mase_medio=("mase", "mean"), mase_mediana=("mase", "median"),
                                               error_firmado_pct_medio=("error_firmado_pct", "mean"), series=("mase", "size"),
                                               filas=("n", "sum")).reset_index()
    rg = rs[rs.corte == "global"].merge(g, on=["escenario", "modelo"], how="outer", suffixes=("", "_ser"), indicator=True)
    ok = (rg._merge == "both").all() and all(_cerca(rg[c], rg[c + "_ser"]) for c in ["mase_medio", "mase_mediana", "error_firmado_pct_medio", "series", "filas"])
    prop = []
    for (esc, mod), d in ms.groupby(["escenario", "modelo"]):
        if mod == ref:
            continue
        r = ms[(ms.escenario == esc) & (ms.modelo == ref)].set_index(SERIE).mase
        prop.append(((esc, mod), float((d.set_index(SERIE).mase < r).mean())))
    pg = rs[rs.corte == "global"].set_index(["escenario", "modelo"]).prop_series_mejor_que_referente
    ok &= all(_cerca(v, pg[k]) for k, v in prop)
    inf.add("consistencia:resumen_global_igual_a_series", bool(ok), f"{len(rg)} combinaciones escenario x modelo")
    # 2. Aporte (total) frente a métricas por serie; delta = con - sin.
    errores = []
    for _, r in ap[ap.anio == "todos"].iterrows():
        con = f"{r.familia}_abast" if r.tipo == "parametros_propios" else f"{r.familia}_abast_ctrl"
        a = ms[(ms.escenario == r.escenario) & (ms.modelo == f"{r.familia}_precio") & (ms.product_id == r.product_id) & (ms.market_id == r.market_id)]
        b = ms[(ms.escenario == r.escenario) & (ms.modelo == con) & (ms.product_id == r.product_id) & (ms.market_id == r.market_id)]
        if len(a) != 1 or len(b) != 1 or not _cerca([r.mase_sin_abast, r.mase_con_abast, r.mae_sin_abast, r.mae_con_abast, r.n],
                                                    [a.mase.iloc[0], b.mase.iloc[0], a.mae_cop_kg.iloc[0], b.mae_cop_kg.iloc[0], a.n.iloc[0]]):
            errores.append((r.escenario, r.familia, r.tipo, r.product_id, r.market_id))
    errores += [tuple(x) for x in ap.loc[~np.isclose(ap.delta_mase, ap.mase_con_abast - ap.mase_sin_abast, rtol=RTOL, atol=ATOL),
                                          ["escenario", "familia", "tipo", "anio"]].to_numpy()[:3]]
    esperadas = len(cfg["escenarios"]["retrasos_meses"]) * 2 * 2 * 3 * cfg["entrada"]["hechos_esperados"]["series"]
    inf.add("consistencia:aporte_igual_a_series_y_delta", not errores and len(ap) == esperadas,
            f"{len(ap)} filas (esperadas {esperadas}); discrepancias={errores[:5]}")
    # 3. Aporte por año frente al resumen anual (media entre series de la MASE anual).
    errores = []
    for (esc, fam, tipo, anio), d in ap[ap.anio != "todos"].groupby(["escenario", "familia", "tipo", "anio"]):
        con = f"{fam}_abast" if tipo == "parametros_propios" else f"{fam}_abast_ctrl"
        for mod, col in [(f"{fam}_precio", "mase_sin_abast"), (con, "mase_con_abast")]:
            v = rs[(rs.escenario == esc) & (rs.modelo == mod) & (rs.corte == "anio") & (rs.valor == anio)].mase_medio
            if len(v) != 1 or not _cerca(d[col].mean(), v.iloc[0]):
                errores.append((esc, mod, anio))
    inf.add("consistencia:aporte_anual_igual_a_resumen_anual", not errores, f"discrepancias={errores[:5]}")
    # 4. Selección: resumen frente a series y regla de elección congelada.
    sr = pd.read_csv(res / "seleccion/metricas_seleccion_resumen.csv")
    sp = pd.read_csv(res / "seleccion/metricas_seleccion_por_serie.csv")
    gs = sp.groupby("modelo").mase.agg(["mean", "median", "size"]).reset_index()
    m = sr.merge(gs, on="modelo", how="outer", indicator=True)
    ok = (m._merge == "both").all() and _cerca(m.mase_medio, m["mean"]) and _cerca(m.mase_mediana, m["median"])
    elegidos = {}
    for fv, d in sr[sr.familia_variante.str.contains("_")].groupby("familia_variante"):
        mejor = d.mase_medio.round(9).min()
        cand = d[d.mase_medio.round(9) == mejor].modelo.tolist()
        elegidos[fv] = cand
    fmt = lambda fv: f"{fv}|" + ";".join(f"{k}={v}" for k, v in cong["parametros"][fv].items())
    ok &= all(fmt(fv) in elegidos[fv] for fv in cong["parametros"])
    base = sr[sr.modelo.isin(["ingenuo", "estacional"])].sort_values("mase_medio").modelo.iloc[0]
    ok &= base == ref and min(["ridge", "rf"], key=lambda f: sr[sr.modelo == fmt(f + "_precio")].mase_medio.iloc[0]) == cong["familia_principal"]
    inf.add("consistencia:seleccion_y_parametros_congelados", bool(ok),
            f"parámetros={cong['parametros']}; referente={ref}; familia principal={cong['familia_principal']}")
    # 5. Cifras del resumen desde las tablas (no desde ellas mismas: se recalculan) y su presencia en el texto.
    r1 = ms[ms.escenario == "retro_r1"]
    s = {mod: r1[r1.modelo == mod].set_index(SERIE) for mod in MODELOS_EVAL}
    y = lambda mod, a: rs[(rs.escenario == "retro_r1") & (rs.modelo == mod) & (rs.corte == "anio") & (rs.valor == a)].mase_medio.iloc[0]
    prop25 = rs[(rs.escenario == "retro_r1") & (rs.modelo == "rf_precio") & (rs.corte == "anio") & (rs.valor == "2025")].prop_series_mejor_que_referente.iloc[0]
    red = lambda a, b: (1 - a / b) * 100
    mm = lambda mod: s[mod].mase.mean()
    t = ap[(ap.escenario == "retro_r1") & (ap.anio == "todos") & (ap.tipo == "parametros_propios")]
    calc = {
        "mase_ingenuo": mm("ingenuo"), "mase_rf_precio": mm("rf_precio"), "mase_rf_abast": mm("rf_abast"),
        "mase_ridge_precio": mm("ridge_precio"), "mase_ridge_abast": mm("ridge_abast"),
        "mase_ingenuo_2024": y("ingenuo", "2024"), "mase_ingenuo_2025": y("ingenuo", "2025"),
        "mase_rf_precio_2024": y("rf_precio", "2024"), "mase_rf_precio_2025": y("rf_precio", "2025"),
        "reduccion_mase_rf_precio_vs_ingenuo_pct_conjunta": red(mm("rf_precio"), mm("ingenuo")),
        "reduccion_mase_rf_precio_vs_ingenuo_pct_2024": red(y("rf_precio", "2024"), y("ingenuo", "2024")),
        "reduccion_mase_rf_precio_vs_ingenuo_pct_2025": red(y("rf_precio", "2025"), y("ingenuo", "2025")),
        "series_rf_precio_mejor_que_ingenuo": float((s["rf_precio"].mase < s["ingenuo"].mase).sum()),
        "series_rf_precio_mejor_que_ingenuo_2025": float(round(prop25 * 30)),
        "mediana_mae_rf_precio_cop_kg": float(s["rf_precio"].mae_cop_kg.median()), "mediana_mae_ingenuo_cop_kg": float(s["ingenuo"].mae_cop_kg.median()),
        "cambio_mediana_mae_rf_precio_vs_ingenuo_pct": (s["rf_precio"].mae_cop_kg.median() / s["ingenuo"].mae_cop_kg.median() - 1) * 100,
        "error_pct_firmado_medio_rf_precio": float(s["rf_precio"].error_firmado_pct.mean()),
        "series_rf_precio_error_firmado_positivo_cop_kg": float((s["rf_precio"].error_firmado_cop_kg > 0).sum()),
        "cambio_mase_con_abast_rf_pct": (mm("rf_abast") / mm("rf_precio") - 1) * 100,
        "cambio_mase_con_abast_ridge_pct": (mm("ridge_abast") / mm("ridge_precio") - 1) * 100,
        "series_mejoran_con_abast_rf": float((t[t.familia == "rf"].delta_mase < 0).sum()),
        "series_mejoran_con_abast_ridge": float((t[t.familia == "ridge"].delta_mase < 0).sum()),
    }
    cif = json.loads((res / "cifras_resumen.json").read_text())
    malas = {k: (cif["cifras"].get(k), round(v, 2)) for k, v in calc.items() if cif["cifras"].get(k) is None or abs(cif["cifras"][k] - round(v, 2)) > 1e-9}
    texto = (raiz / "RESUMEN_RESULTADOS.md").read_text(encoding="utf-8")
    ausentes = {k: v for k, v in cif["escritas_en_resumen"].items() if v not in texto}
    inf.add("consistencia:cifras_del_resumen_desde_tablas", not malas and set(cif["cifras"]) == set(calc), f"discrepantes={malas}")
    inf.add("consistencia:cifras_citadas_en_RESUMEN_RESULTADOS", not ausentes, f"no encontradas={ausentes}")
    # 6. Auditoría temporal: límites recalculados desde la configuración (sin predicciones).
    aud = pd.read_csv(res / "auditoria_temporal.csv", dtype={"origen": str, "objetivo": str, "max_mes_base_B": str})
    ret = cfg["escenarios"]["retrasos_meses"]
    ta = aud.origen.map(_idx)
    lp, la = aud.escenario.map(lambda e: ret[e]["precio"]), aud.escenario.map(lambda e: ret[e]["abastecimiento"])
    sel_org = [_mes(_idx(o) - 1) for o in _rango(*cfg["periodos"]["seleccion_meses_objetivo"])]
    esp = {("evaluacion", e, _mes(_idx(o) - 1)) for e in ret for o in _rango(*cfg["periodos"]["evaluacion_meses_objetivo"])} | {("seleccion", "retro_r1", o) for o in sel_org}
    ok = set(map(tuple, aud[["fase", "escenario", "origen"]].to_numpy())) == esp and bool(
        (aud.objetivo == (ta + 1).map(_mes)).all() and (aud.ultimo_mes_precio_permitido == (ta - lp).map(_mes)).all()
        and (aud.ultimo_mes_abast_permitido == (ta - la).map(_mes)).all() and (aud.max_mes_precio_usado_pronostico <= (ta - lp).map(_mes)).all()
        and (aud.max_mes_abast_usado_pronostico <= (ta - la).map(_mes)).all() and (aud.ultima_etiqueta_usada <= (ta - lp).map(_mes)).all()
        and (aud.max_mes_base_B <= (ta - lp).map(_mes)).all())
    inf.add("auditoria_temporal:limites_recalculados_desde_configuracion", ok, f"{len(aud)} filas (esperadas {len(esp)})")
    # 7. Lo que necesita las series retiradas.
    for nombre, req in [
        ("recalculo_de_todas_las_tablas_desde_predicciones", "predicciones.csv con precios observados"),
        ("cobertura_y_unicidad_de_las_predicciones", "predicciones.csv"),
        ("estado_de_exclusion_recalculado", "predicciones.csv"),
        ("temporal_por_prediccion_y_coherencia_con_auditoria", "predicciones.csv y predicciones_seleccion.csv"),
        ("pruebas_de_fuga_con_copia_derivada_del_lote", "lote de ingeniería reconstruido"),
        ("rechazos_de_fecha_2030_y_de_cobertura", "predicciones.csv"),
        ("contratos_de_ingenieria_frente_a_referencias_de_viabilidad", "referencias regeneradas con engineering/herramientas/reconstruir_referencias.py"),
    ]:
        inf.no_ejecutado(nombre, req)
    return inf.resumen()


def comparar_con_aprobado(dir_aprobado: Path, raiz: Path = RAIZ) -> dict:
    """Ejecutar en la copia de trabajo reconstruida. `dir_aprobado` es la carpeta evaluation/ de la entrega pública."""
    dir_aprobado = Path(dir_aprobado).resolve()
    inf = Informe()
    res, res_ap = raiz / "resultados", dir_aprobado / "resultados"
    dist = json.loads((dir_aprobado / DISTRIBUCION).read_text())
    for rel in ["predicciones.csv", "seleccion/predicciones_seleccion.csv"]:
        if not (res / rel).exists():
            inf.no_ejecutado(f"reconstruccion:{rel}", "ejecutar primero reproducir.sh en esta copia")
            return inf.resumen()
    # Tablas aprobadas intactas (huellas fijas).
    malas = [rel for rel, h in dist["tablas_conservadas_aprobadas"].items() if sha256(dir_aprobado / rel) != h]
    inf.add("aprobado:tablas_con_huella_fija", not malas, f"alteradas={malas}")
    with tempfile.TemporaryDirectory(prefix="sipsa-comparar-") as tmp:
        t = Path(tmp)
        shutil.copytree(res_ap, t / "resultados", ignore=shutil.ignore_patterns("controles"))
        for rel in ["predicciones.csv", "seleccion/predicciones_seleccion.csv"]:
            shutil.copyfile(res / rel, t / "resultados" / rel)
        (t / "config").mkdir()
        shutil.copyfile(dir_aprobado / "config/protocolo.json", t / "config/protocolo.json")
        shutil.copyfile(dir_aprobado / "RESUMEN_RESULTADOS.md", t / "RESUMEN_RESULTADOS.md")
        rc = recalcular(t / "resultados", t)
    for c in rc["checks"]:
        inf.add("recalculo_desde_predicciones_reconstruidas_frente_a_tablas_aprobadas:" + c["control"], c["resultado"] == "PASS", c["detalle"])
    for rel, h in dist["tablas_conservadas_aprobadas"].items():
        rel_r = Path(rel).relative_to("resultados") if rel.startswith("resultados/") else None
        if rel_r is None or not (res / rel_r).exists() or not rel.endswith(".csv"):
            continue
        a, b = pd.read_csv(res / rel_r), pd.read_csv(dir_aprobado / rel)
        num = [c for c in a.columns if pd.api.types.is_numeric_dtype(a[c])]
        ok = list(a.columns) == list(b.columns) and len(a) == len(b) and a.drop(columns=num).fillna("").astype(str).equals(b.drop(columns=num).fillna("").astype(str)) \
            and all(_cerca(a[c], b[c]) for c in num)
        inf.add(f"tabla_regenerada_igual_a_aprobada:{rel}", ok, "bytes idénticos" if sha256(res / rel_r) == h else "igual dentro de rtol=1e-7 (bytes distintos)")
    for rel, info in dist["retirados"].items():
        if rel.startswith("evaluation/resultados/"):
            p = res / Path(rel).relative_to("evaluation/resultados")
            iguales = p.exists() and sha256(p) == info["sha256_aprobado"]
            inf.checks.append({"control": f"huella_de_bytes:{rel}", "resultado": "PASS" if iguales else "INFORMATIVO",
                               "detalle": "idéntica byte a byte a la aprobada" if iguales else
                               "bytes distintos de la versión aprobada (posible en otro sistema operativo o versión); la validez se decide por el recálculo frente a las tablas aprobadas"})
    return inf.resumen()
