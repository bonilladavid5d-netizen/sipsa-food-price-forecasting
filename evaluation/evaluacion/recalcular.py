"""Recálculo independiente (revisión de mantenimiento v2). NO importa el núcleo de cálculo.

Desde config/protocolo.json y parametros_congelados.json deriva lo esperado (escenarios, modelos, orígenes,
series, cortes) y desde predicciones.csv recalcula, con error = predicho - observado (el campo `error`
exportado no se usa), todas las tablas publicadas:
  - metricas_por_serie.csv, metricas_resumen.csv (todos los cortes y la sensibilidad),
  - aporte_abastecimiento.csv (ambos lados MASE y MAE, delta, años y total, familias, propios y controlada),
  - las cifras del resumen (resultados/cifras_resumen.json).
Las comparaciones exigen identidad de llaves (unión externa: sin filas faltantes ni sobrantes) antes de
comparar valores.

Tolerancias: las tablas se exportan con float_format="%.10g" (10 cifras significativas, error relativo de
redondeo <= 5e-10 por valor). Un cociente o una media de valores así redondeados puede acumular un error
relativo del orden de 1e-9. Se usa rtol = 1e-7 (100 veces ese orden) y atol = 1e-9, valores muy inferiores a
cualquier diferencia de interés (las cifras se comunican con 2-4 decimales) y que rechazan cualquier
alteración real como 0 o -99.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

RAIZ = Path(__file__).resolve().parents[1]
RTOL, ATOL = 1e-7, 1e-9
MODELOS_EVAL = ["ingenuo", "estacional", "ridge_precio", "ridge_abast", "rf_precio", "rf_abast", "ridge_abast_ctrl", "rf_abast_ctrl"]
SERIE = ["product_id", "market_id"]


def _mes(i: int) -> str:
    y, m = divmod(i, 12)
    return f"{2018 + y}-{m + 1:02d}"


def _idx(m: str) -> int:
    y, mm = map(int, m.split("-"))
    return (y - 2018) * 12 + mm - 1


def _rango(a: str, b: str) -> list[str]:
    return [_mes(i) for i in range(_idx(a), _idx(b) + 1)]


class Verificador:
    def __init__(self):
        self.checks = []

    def ok(self, nombre, cond, detalle=""):
        self.checks.append({"control": nombre, "resultado": "PASS" if cond else "FAIL", "detalle": str(detalle)[:1500]})
        return cond

    def comparar(self, nombre, nuevo: pd.DataFrame, ref: pd.DataFrame, llaves: list, columnas: list):
        """Unión externa por llaves; exige mismas llaves y sin duplicados; luego compara cada columna."""
        dup_r = int(ref.duplicated(llaves).sum())
        m = nuevo.merge(ref, on=llaves, how="outer", suffixes=("_re", "_tab"), indicator=True)
        solo_re, solo_tab = int((m._merge == "left_only").sum()), int((m._merge == "right_only").sum())
        self.ok(f"{nombre}:llaves_identicas", dup_r == solo_re == solo_tab == 0,
                f"recalculadas={len(nuevo)} tabla={len(ref)} faltan_en_tabla={solo_re} sobran_en_tabla={solo_tab} duplicadas_tabla={dup_r}"
                + (f"; ej. sobrante={m[m._merge == 'right_only'][llaves].head(2).to_dict('records')}" if solo_tab else "")
                + (f"; ej. faltante={m[m._merge == 'left_only'][llaves].head(2).to_dict('records')}" if solo_re else ""))
        b = m[m._merge == "both"]
        for c in columnas:
            a = pd.to_numeric(b[c + "_re"], errors="coerce").to_numpy(float)
            t = pd.to_numeric(b[c + "_tab"], errors="coerce").to_numpy(float)
            iguales = np.isclose(a, t, rtol=RTOL, atol=ATOL) | (np.isnan(a) & np.isnan(t))
            det = f"{len(b)} filas; discrepantes={int((~iguales).sum())}"
            if (~iguales).any():
                i = int(np.argmax(~iguales))
                det += f"; ej. {b.iloc[i][llaves].to_dict()} recalculado={a[i]!r} tabla={t[i]!r}"
            self.ok(f"{nombre}:{c}", bool(iguales.all()) and len(b) == len(nuevo), det)


def _metricas_serie(ev: pd.DataFrame, por: list[str]) -> pd.DataFrame:
    return ev.groupby(por + SERIE, dropna=False).agg(
        n=("s", "size"), mase=("s", "mean"), mae_cop_kg=("abs_e", "mean"), error_firmado_cop_kg=("e", "mean"),
        error_firmado_pct=("e_pct", "mean")).reset_index()


def recalcular(res: Path | None = None, raiz: Path | None = None) -> dict:
    raiz = raiz or RAIZ
    res = res or raiz / "resultados"
    cfg = json.loads((raiz / "config/protocolo.json").read_text(encoding="utf-8"))
    cong = json.loads((res / "seleccion/parametros_congelados.json").read_text())
    v = Verificador()
    pr = pd.read_csv(res / "predicciones.csv", dtype={"origen": str, "objetivo": str})

    # 1. Cobertura y llaves esperadas, derivadas del protocolo (no de los CSV).
    escenarios = sorted(cfg["escenarios"]["retrasos_meses"])
    objetivos = _rango(*cfg["periodos"]["evaluacion_meses_objetivo"])
    origenes = [_mes(_idx(o) - 1) for o in objetivos]
    n_series = cfg["entrada"]["hechos_esperados"]["series"]
    series = sorted(set(map(tuple, pr[SERIE].to_numpy())))
    v.ok("cobertura:series_segun_protocolo", len(series) == n_series, f"{len(series)} series en predicciones; protocolo={n_series}")
    llaves = ["fase", "escenario", "modelo", "origen", "product_id", "market_id"]
    esp = {("evaluacion", e, m, o, s[0], s[1]) for e in escenarios for m in MODELOS_EVAL for o in origenes for s in series}
    obs = set(map(tuple, pr[llaves].to_numpy()))
    faltan, sobran = esp - obs, obs - esp
    dups = int(pr.duplicated(llaves).sum())
    v.ok("cobertura:predicciones_exactas_segun_protocolo", not faltan and not sobran and dups == 0,
         f"esperadas={len(esp)} ({len(escenarios)} escenarios x {len(MODELOS_EVAL)} modelos x {len(origenes)} orígenes x {len(series)} series); "
         f"presentes={len(pr)}; faltan={len(faltan)}; sobran={len(sobran)}; duplicadas={dups}"
         + (f"; modelos/escenarios con faltantes={sorted({(f[1], f[2]) for f in faltan})[:8]}" if faltan else "")
         + (f"; ej. sobrante={sorted(sobran)[:2]}" if sobran else ""))
    v.ok("cobertura:objetivo_igual_origen_mas_uno", bool((pr.objetivo.map(_idx) == pr.origen.map(_idx) + 1).all()))

    # 2. Estado de evaluación recalculado desde observado, base, referencia estacional y escala.
    obs_ok = np.isfinite(pr.observado)
    filas_ok = obs_ok & np.isfinite(pr.B) & np.isfinite(pr.p_estacional) & (pr.pares_escala >= 24) & (pr.escala_mase > 0)
    fila_ok = filas_ok.groupby([pr.escenario, pr.origen, pr.product_id, pr.market_id]).transform("all")
    estado_re = np.where(fila_ok, "evaluada", "excluida")
    v.ok("estado:recalculado_igual_al_exportado", bool((estado_re == pr.estado_evaluacion).all()),
         f"discrepantes={int((estado_re != pr.estado_evaluacion).sum())}")
    aus = pr[~obs_ok]
    v.ok("estado:objetivos_ausentes_excluidos", bool((aus.estado_evaluacion == "excluida").all() and (aus.motivo_exclusion == "objetivo_ausente").all()),
         f"{len(aus)} filas: " + ";".join(sorted(set(aus.objetivo + " " + aus["product"] + " @ " + aus.market))))
    ev = pr[estado_re == "evaluada"].copy()
    v.ok("estado:predicciones_finitas", bool(np.isfinite(ev.predicho).all()))
    iguales = True
    for e in escenarios:
        d = ev[ev.escenario == e]
        conj = {m: frozenset(zip(g.origen, g.product_id, g.market_id)) for m, g in d.groupby("modelo")}
        iguales &= len(set(conj.values())) == 1 and set(conj) == set(MODELOS_EVAL)
    v.ok("emparejado:mismo_conjunto_evaluado_en_todos_los_modelos", iguales)
    ev["e"] = ev.predicho - ev.observado  # NO se usa el campo `error` exportado
    ev["abs_e"] = ev.e.abs()
    ev["s"] = ev.abs_e / ev.escala_mase
    ev["e_pct"] = ev.e / ev.observado * 100
    ev["anio"] = ev.objetivo.str[:4]
    ev["mes_cal"] = ev.objetivo.str[5:7]

    # 3. metricas_por_serie.csv
    v.comparar("metricas_por_serie", _metricas_serie(ev, ["escenario", "modelo"]), pd.read_csv(res / "metricas_por_serie.csv"),
               ["escenario", "modelo"] + SERIE, ["n", "mase", "mae_cop_kg", "error_firmado_cop_kg", "error_firmado_pct"])

    # 4. metricas_resumen.csv (todos los cortes y la sensibilidad)
    ref = cong["referente"]
    filas = []
    cortes = [("global", None), ("anio", "anio"), ("producto", "product"), ("mercado", "market"), ("mes_calendario", "mes_cal"),
              ("aviso_objetivo", "aviso_objetivo"), ("aviso_en_ventana_abast", "aviso_en_ventana_abast")]
    for corte, col in cortes:
        for val, d in ([("todos", ev)] if col is None else list(ev.groupby(col))):
            m = _metricas_serie(d, ["escenario", "modelo"])
            for (esc, mod), g in m.groupby(["escenario", "modelo"]):
                gr = m[(m.escenario == esc) & (m.modelo == ref)].set_index(SERIE).mase
                gi = g.set_index(SERIE).mase
                comun = gi.index.intersection(gr.index)
                filas.append({"escenario": esc, "modelo": mod, "corte": corte, "valor": str(val), "series": len(g), "filas": int(g.n.sum()),
                              "mase_medio": g.mase.mean(), "mase_mediana": g.mase.median(), "error_firmado_pct_medio": g.error_firmado_pct.mean(),
                              "prop_series_mejor_que_referente": float((gi[comun] < gr[comun]).mean()) if mod != ref else np.nan})
    for (esc, mod), g in _metricas_serie(ev[~ev.aviso_en_ventana_abast.astype(bool)], ["escenario", "modelo"]).groupby(["escenario", "modelo"]):
        filas.append({"escenario": esc, "modelo": mod, "corte": "sensibilidad_sin_aviso_en_ventana_abast", "valor": "excluidas",
                      "series": len(g), "filas": int(g.n.sum()), "mase_medio": g.mase.mean(), "mase_mediana": g.mase.median(),
                      "error_firmado_pct_medio": g.error_firmado_pct.mean(), "prop_series_mejor_que_referente": np.nan})
    v.comparar("metricas_resumen", pd.DataFrame(filas), pd.read_csv(res / "metricas_resumen.csv", dtype={"valor": str}),
               ["escenario", "modelo", "corte", "valor"],
               ["series", "filas", "mase_medio", "mase_mediana", "error_firmado_pct_medio", "prop_series_mejor_que_referente"])

    # 5. aporte_abastecimiento.csv: ambos lados (MASE y MAE), delta, años y total, ambas familias, propios y controlada.
    P = cong["parametros"]
    ap, emparejado = [], True
    for esc in escenarios:
        for fam in ["ridge", "rf"]:
            for tipo, con in [("parametros_propios", f"{fam}_abast"), ("parametros_comunes_controlada", f"{fam}_abast_ctrl")]:
                for anio in ["todos", "2024", "2025"]:
                    d = ev[ev.escenario == esc] if anio == "todos" else ev[(ev.escenario == esc) & (ev.anio == anio)]
                    a = _metricas_serie(d[d.modelo == f"{fam}_precio"], []).set_index(SERIE)
                    b = _metricas_serie(d[d.modelo == con], []).set_index(SERIE)
                    emparejado &= a.index.equals(b.index) and bool((a.n == b.n).all()) and len(a) == n_series
                    for k in a.index.union(b.index):
                        ap.append({"escenario": esc, "familia": fam, "tipo": tipo, "anio": anio, "product_id": k[0], "market_id": k[1],
                                   "n": a.n.get(k, np.nan), "mase_sin_abast": a.mase.get(k, np.nan), "mase_con_abast": b.mase.get(k, np.nan),
                                   "delta_mase": b.mase.get(k, np.nan) - a.mase.get(k, np.nan),
                                   "mae_sin_abast": a.mae_cop_kg.get(k, np.nan), "mae_con_abast": b.mae_cop_kg.get(k, np.nan),
                                   "params_sin_esperado": str(P[f"{fam}_precio"]),
                                   "params_con_esperado": str(P[f"{fam}_abast"] if tipo == "parametros_propios" else P[f"{fam}_precio"])})
    v.ok("aporte_abastecimiento:emparejado_mismas_series_y_filas", emparejado,
         f"{len(escenarios)} escenarios x 2 familias x 2 tipos x 3 periodos; {n_series} series en cada uno")
    ap_re = pd.DataFrame(ap)
    ap_tab = pd.read_csv(res / "aporte_abastecimiento.csv", dtype={"anio": str})
    lla = ["escenario", "familia", "tipo", "anio"] + SERIE
    v.comparar("aporte_abastecimiento", ap_re, ap_tab, lla,
               ["n", "mase_sin_abast", "mase_con_abast", "delta_mase", "mae_sin_abast", "mae_con_abast"])
    m = ap_re.merge(ap_tab, on=lla, how="inner")
    v.ok("aporte_abastecimiento:parametros_declarados_iguales_a_congelados",
         len(m) == len(ap_re) and bool((m.params_sin == m.params_sin_esperado).all() and (m.params_con == m.params_con_esperado).all()))

    # 6. Cifras comunicadas en el resumen (resultados/cifras_resumen.json), recalculadas.
    cifras = cifras_clave(ev)
    ruta_c = res / "cifras_resumen.json"
    if ruta_c.exists():
        decl = json.loads(ruta_c.read_text())["cifras"]
        malas = {k: (decl.get(k), round(val, 2)) for k, val in cifras.items() if decl.get(k) is None or abs(decl[k] - round(val, 2)) > 1e-9}
        v.ok("resumen:cifras_comunicadas_recalculadas", not malas and set(decl) == set(cifras), f"discrepantes={malas}")
        texto = (raiz / "RESUMEN_RESULTADOS.md").read_text(encoding="utf-8") if (raiz / "RESUMEN_RESULTADOS.md").exists() else ""
        escritas = json.loads(ruta_c.read_text()).get("escritas_en_resumen", {})
        ausentes = {k: t for k, t in escritas.items() if t not in texto}
        v.ok("resumen:cifras_citadas_en_RESUMEN_RESULTADOS", bool(escritas) and not ausentes, f"no encontradas en el texto={ausentes}")
    else:
        v.ok("resumen:cifras_comunicadas_recalculadas", False, "falta resultados/cifras_resumen.json")

    fallos = [c for c in v.checks if c["resultado"] == "FAIL"]
    return {"ok": not fallos, "controles": len(v.checks), "fallos": len(fallos), "detalle_fallos": fallos[:20],
            "tolerancias": {"rtol": RTOL, "atol": ATOL}, "cifras_recalculadas": cifras, "checks": v.checks}


def cifras_clave(ev: pd.DataFrame) -> dict:
    """Cifras que se comunican en RESUMEN_RESULTADOS.md (escenario principal retro_r1), sin redondear."""
    r1 = ev[ev.escenario == "retro_r1"]
    ms, msy = _metricas_serie(r1, ["modelo"]), _metricas_serie(r1, ["modelo", "anio"])
    mase = lambda mod: ms[ms.modelo == mod].mase.mean()
    masey = lambda mod, y: msy[(msy.modelo == mod) & (msy.anio == y)].mase.mean()
    red = lambda a, b: (1 - a / b) * 100
    s = {mod: ms[ms.modelo == mod].set_index(SERIE) for mod in MODELOS_EVAL}
    y25 = {mod: msy[(msy.modelo == mod) & (msy.anio == "2025")].set_index(SERIE) for mod in ("rf_precio", "ingenuo")}
    return {
        "mase_ingenuo": mase("ingenuo"), "mase_rf_precio": mase("rf_precio"), "mase_rf_abast": mase("rf_abast"),
        "mase_ridge_precio": mase("ridge_precio"), "mase_ridge_abast": mase("ridge_abast"),
        "mase_ingenuo_2024": masey("ingenuo", "2024"), "mase_ingenuo_2025": masey("ingenuo", "2025"),
        "mase_rf_precio_2024": masey("rf_precio", "2024"), "mase_rf_precio_2025": masey("rf_precio", "2025"),
        "reduccion_mase_rf_precio_vs_ingenuo_pct_conjunta": red(mase("rf_precio"), mase("ingenuo")),
        "reduccion_mase_rf_precio_vs_ingenuo_pct_2024": red(masey("rf_precio", "2024"), masey("ingenuo", "2024")),
        "reduccion_mase_rf_precio_vs_ingenuo_pct_2025": red(masey("rf_precio", "2025"), masey("ingenuo", "2025")),
        "series_rf_precio_mejor_que_ingenuo": float((s["rf_precio"].mase < s["ingenuo"].mase).sum()),
        "series_rf_precio_mejor_que_ingenuo_2025": float((y25["rf_precio"].mase < y25["ingenuo"].mase).sum()),
        "mediana_mae_rf_precio_cop_kg": float(s["rf_precio"].mae_cop_kg.median()),
        "mediana_mae_ingenuo_cop_kg": float(s["ingenuo"].mae_cop_kg.median()),
        "cambio_mediana_mae_rf_precio_vs_ingenuo_pct": (s["rf_precio"].mae_cop_kg.median() / s["ingenuo"].mae_cop_kg.median() - 1) * 100,
        "error_pct_firmado_medio_rf_precio": float(s["rf_precio"].error_firmado_pct.mean()),
        "series_rf_precio_error_firmado_positivo_cop_kg": float((s["rf_precio"].error_firmado_cop_kg > 0).sum()),
        "cambio_mase_con_abast_rf_pct": (mase("rf_abast") / mase("rf_precio") - 1) * 100,
        "cambio_mase_con_abast_ridge_pct": (mase("ridge_abast") / mase("ridge_precio") - 1) * 100,
        "series_mejoran_con_abast_rf": float((s["rf_abast"].mase < s["rf_precio"].mase).sum()),
        "series_mejoran_con_abast_ridge": float((s["ridge_abast"].mase < s["ridge_precio"].mase).sum()),
    }


if __name__ == "__main__":
    r = recalcular()
    print(json.dumps({k: r[k] for k in ("ok", "controles", "fallos", "detalle_fallos", "cifras_recalculadas")}, ensure_ascii=False, indent=2))
