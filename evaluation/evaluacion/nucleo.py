"""Núcleo de la evaluación: calendario, variables, modelos y métricas según config/protocolo.json.

Garantías por construcción:
- Las variables de un ejemplo con mes objetivo m se calculan con `p[: L+1]` y `q[: S+1]`, cortes que
  no contienen meses posteriores a lo permitido en su propio origen m-1.
- En cada origen t, solo entran al entrenamiento ejemplos con m <= t - retraso_precio y precio observado.
- Imputación, estandarización y modelos se ajustan solo con esas filas; la escala MASE usa precios <= t - retraso_precio.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler

MES0 = (2018, 1)
PRECIO = ["d1", "d2", "dev_ma6", "dev_ma12", "estacional", "mov_estacional"]
CALENDARIO = ["mes_sin", "mes_cos"]
INDICADORES = ["falta_precio_ventana", "base_rezagada"]
ABAST = ["nivel_rel12", "cambio_1", "cambio_12", "trim_vs_anio_ant", "falta_abast_ventana"]


def idx(mes: str) -> int:
    y, m = map(int, mes.split("-"))
    return (y - MES0[0]) * 12 + (m - MES0[1])


def mes(i: int) -> str:
    y, m = divmod(i + MES0[1] - 1, 12)
    return f"{MES0[0] + y}-{m + 1:02d}"


@dataclass
class Panel:
    """Matrices serie x mes (NaN = ausente). Las series siguen el orden (product_id, market_id)."""
    series: pd.DataFrame  # product_id, market_id, product, market
    P: np.ndarray
    Q: np.ndarray
    aviso: np.ndarray  # bool serie x mes (aviso oficial del mercado-mes)

    @classmethod
    def desde_df(cls, df: pd.DataFrame) -> "Panel":
        df = df.sort_values(["product_id", "market_id", "month"])
        series = df[["product_id", "market_id", "product", "market"]].drop_duplicates().reset_index(drop=True)
        meses = sorted(df.month.unique())
        assert meses[0] == "2018-01" and len(meses) == idx(meses[-1]) + 1
        n, T = len(series), len(meses)
        piv = lambda c: df.pivot_table(index=["product_id", "market_id"], columns="month", values=c, aggfunc="first", dropna=False) \
            .reindex(index=pd.MultiIndex.from_frame(series[["product_id", "market_id"]]), columns=meses)
        P = piv("price").to_numpy(dtype=float)
        Q = piv("kg").to_numpy(dtype=float)
        A = piv("aviso_imputacion").fillna(False).to_numpy(dtype=bool)
        assert P.shape == (n, T)
        return cls(series, P, Q, A)

    @property
    def T(self) -> int:
        return self.P.shape[1]


def _ln(x):
    return math.log(x) if (x is not None and np.isfinite(x) and x > 0) else np.nan


def variables_ejemplo(p_hasta_L: np.ndarray, q_hasta_S: np.ndarray, m: int, lp: int, la: int) -> dict | None:
    """Variables del ejemplo con mes objetivo m. Recibe SOLO los precios hasta L=m-1-lp y volúmenes hasta S=m-1-la.
    Devuelve None si la ventana requerida no existe en la malla."""
    L, S = m - 1 - lp, m - 1 - la
    assert len(p_hasta_L) == L + 1 and len(q_hasta_S) == S + 1, "corte incorrecto"
    if L - 12 < 0 or S - 14 < 0 or m - 12 < 0:
        return None
    p, q = p_hasta_L, q_hasta_S
    base_mes = next((k for k in (L, L - 1, L - 2) if np.isfinite(p[k])), None)
    B = p[base_mes] if base_mes is not None else np.nan
    lnp = lambda k: _ln(p[k])
    lnmean = lambda a: _ln(np.mean(a)) if np.all(np.isfinite(a)) else np.nan
    v = {
        "d1": lnp(L) - lnp(L - 1),
        "d2": lnp(L - 1) - lnp(L - 2),
        "dev_ma6": lnp(L) - lnmean(p[L - 5:L + 1]),
        "dev_ma12": lnp(L) - lnmean(p[L - 11:L + 1]),
        "estacional": lnp(m - 12) - _ln(B),
        "mov_estacional": lnp(m - 12) - lnp(L - 12),
        "mes_sin": math.sin(2 * math.pi * ((m % 12) + 1) / 12),
        "mes_cos": math.cos(2 * math.pi * ((m % 12) + 1) / 12),
        "falta_precio_ventana": float(not (np.all(np.isfinite(p[L - 12:L + 1])) and np.isfinite(p[m - 12]))),
        "base_rezagada": float(base_mes != L),
        "nivel_rel12": _ln(q[S]) - lnmean(q[S - 11:S + 1]),
        "cambio_1": _ln(q[S]) - _ln(q[S - 1]),
        "cambio_12": _ln(q[S]) - _ln(q[S - 12]),
        "trim_vs_anio_ant": lnmean(q[S - 2:S + 1]) - lnmean(q[S - 14:S - 11]),
        "falta_abast_ventana": float(not np.all(np.isfinite(q[S - 14:S + 1]))),
        "B": B, "mes_base": mes(base_mes) if base_mes is not None else None,
        "p_estacional": p[m - 12],
        "ultimo_mes_precio_usado": mes(L), "ultimo_mes_abast_usado": mes(S),
        "mes_precio_mas_antiguo": mes(L - 12), "mes_abast_mas_antiguo": mes(S - 14),
    }
    return v


def tabla_ejemplos(panel: Panel, lp: int, la: int) -> pd.DataFrame:
    """Todos los ejemplos (serie, mes objetivo) con ventana completa. Las variables de cada fila dependen solo
    de su propio origen m-1 (no del origen de entrenamiento), por eso se calculan una vez."""
    filas = []
    for s in range(len(panel.series)):
        for m in range(panel.T):
            L, S = m - 1 - lp, m - 1 - la
            if L < 0 or S < 0:
                continue
            v = variables_ejemplo(panel.P[s, :L + 1].copy(), panel.Q[s, :S + 1].copy(), m, lp, la)
            if v is None:
                continue
            y_obs = panel.P[s, m]
            v.update({"serie": s, "m": m, "objetivo": mes(m), "origen_propio": mes(m - 1),
                      "product_id": panel.series.product_id[s], "market_id": panel.series.market_id[s],
                      "product": panel.series["product"][s], "market": panel.series.market[s],
                      "observado": y_obs, "y": _ln(y_obs) - _ln(v["B"]) if np.isfinite(y_obs) else np.nan,
                      "aviso_objetivo": bool(panel.aviso[s, m]),
                      "aviso_en_ventana_abast": bool(panel.aviso[s, S - 14:S + 1].any())})
            filas.append(v)
    df = pd.DataFrame(filas)
    for pid in sorted(panel.series.product_id.unique()):
        df[f"prod_{pid}"] = (df.product_id == pid).astype(float)
    for mid in sorted(panel.series.market_id.unique()):
        df[f"merc_{mid}"] = (df.market_id == mid).astype(float)
    return df


def columnas(df: pd.DataFrame, con_abast: bool) -> list[str]:
    ident = [c for c in df.columns if c.startswith("prod_") or c.startswith("merc_")]
    return PRECIO + CALENDARIO + ident + INDICADORES + (ABAST if con_abast else [])


def escala_mase(p_hasta: np.ndarray) -> tuple[float, int]:
    """Media de |p_k - p_{k-12}| con ambos observados, usando solo los precios recibidos (historia disponible)."""
    a, b = p_hasta[12:], p_hasta[:-12]
    ok = np.isfinite(a) & np.isfinite(b)
    n = int(ok.sum())
    return (float(np.mean(np.abs(a[ok] - b[ok]))) if n else np.nan), n


def ajustar_predecir(familia: str, params: dict, Xtr: pd.DataFrame, ytr: np.ndarray, Xte: pd.DataFrame, semilla: int) -> np.ndarray:
    imp = SimpleImputer(strategy="median", keep_empty_features=True).fit(Xtr)
    A, Bm = imp.transform(Xtr), imp.transform(Xte)
    if familia == "ridge":
        sc = StandardScaler().fit(A)
        mod = Ridge(alpha=params["alpha"]).fit(sc.transform(A), ytr)
        return mod.predict(sc.transform(Bm))
    mod = RandomForestRegressor(n_estimators=300, max_features=0.5, bootstrap=True, max_depth=params["max_depth"],
                                min_samples_leaf=params["min_samples_leaf"], random_state=semilla, n_jobs=1).fit(A, ytr)
    return mod.predict(Bm)


def pronosticar_origen(panel: Panel, ej: pd.DataFrame, t: int, lp: int, modelos: dict, semilla: int) -> pd.DataFrame:
    """Pronósticos de todos los modelos para el objetivo t+1 emitidos al cierre de t.
    `modelos`: nombre -> (familia, params, con_abast) para modelos aprendidos."""
    m_obj = t + 1
    te = ej[ej.m == m_obj].copy()
    tr = ej[(ej.m <= t - lp) & np.isfinite(ej.y)]
    if tr.empty:
        raise RuntimeError(f"sin entrenamiento en origen {mes(t)}")
    assert tr.m.max() <= t - lp
    out = []
    base = te[["serie", "m", "objetivo", "product_id", "market_id", "product", "market", "observado", "B", "mes_base", "p_estacional",
               "ultimo_mes_precio_usado", "ultimo_mes_abast_usado", "aviso_objetivo", "aviso_en_ventana_abast"]].copy()
    base["origen"] = mes(t)
    base["n_entrenamiento"] = len(tr)
    base["ultima_etiqueta_entrenamiento"] = mes(int(tr.m.max()))
    escalas = [escala_mase(panel.P[s, :t - lp + 1]) for s in base.serie]
    base["escala_mase"] = [e[0] for e in escalas]
    base["pares_escala"] = [e[1] for e in escalas]
    for nombre in ["ingenuo", "estacional"]:
        b = base.copy()
        b["modelo"], b["config"] = nombre, ""
        b["predicho"] = b.B if nombre == "ingenuo" else b.p_estacional
        out.append(b)
    for nombre, (familia, params, con_abast) in modelos.items():
        cols = columnas(ej, con_abast)
        yhat = ajustar_predecir(familia, params, tr[cols], tr.y.to_numpy(), te[cols], semilla)
        b = base.copy()
        b["modelo"], b["config"] = nombre, json_params(params)
        b["predicho"] = te.B.to_numpy() * np.exp(yhat)
        out.append(b)
    return pd.concat(out, ignore_index=True)


def json_params(p: dict) -> str:
    return ";".join(f"{k}={v}" for k, v in sorted(p.items()))


def estado_filas(pred: pd.DataFrame) -> pd.DataFrame:
    """Marca exclusiones a nivel de fila (serie, origen) iguales para TODOS los modelos (comparaciones emparejadas)."""
    pred = pred.copy()
    motivo = pd.Series("", index=pred.index)
    motivo[~np.isfinite(pred.observado)] = "objetivo_ausente"
    motivo[(motivo == "") & ~np.isfinite(pred.B)] = "sin_base"
    motivo[(motivo == "") & ~np.isfinite(pred.p_estacional)] = "sin_referencia_estacional"
    motivo[(motivo == "") & ((pred.pares_escala < 24) | ~(pred.escala_mase > 0))] = "escala_invalida"
    clave = ["escenario", "origen", "serie"] if "escenario" in pred else ["origen", "serie"]
    mot_fila = motivo.groupby([pred[c] for c in clave]).transform(lambda s: next((x for x in s if x), ""))
    pred["motivo_exclusion"] = mot_fila
    pred["estado_evaluacion"] = np.where(mot_fila == "", "evaluada", "excluida")
    pred["error"] = pred.predicho - pred.observado
    pred["error_abs_escalado"] = np.where(pred.estado_evaluacion == "evaluada", np.abs(pred.error) / pred.escala_mase, np.nan)
    return pred


def metricas_serie(pred: pd.DataFrame, por: list[str]) -> pd.DataFrame:
    ev = pred[pred.estado_evaluacion == "evaluada"]
    g = ev.groupby(por + ["product_id", "market_id", "product", "market"], dropna=False)
    return g.apply(lambda d: pd.Series({
        "n": len(d), "mase": d.error_abs_escalado.mean(), "mae_cop_kg": d.error.abs().mean(),
        "error_firmado_cop_kg": d.error.mean(), "error_firmado_pct": (d.error / d.observado).mean() * 100}),
        include_groups=False).reset_index()
