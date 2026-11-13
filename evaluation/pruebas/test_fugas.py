"""Pruebas de ausencia de información futura.

S: datos SINTÉTICOS (no son resultados reales).
D: copia DERIVADA en memoria del panel aprobado (el lote no se modifica); solo comprueba invariancia, no resultados.

En el origen t0 se alteran todos los precios con mes > t0 - retraso_precio y todos los volúmenes con mes >
t0 - retraso_abastecimiento. Deben quedar idénticas las variables de todas las filas usadas (entrenamiento y
pronóstico), la escala MASE y los pronósticos de todos los modelos. Control negativo: alterar el último valor
permitido SÍ debe cambiar el pronóstico (la prueba no es vacía).

Ejecutar: .venv/bin/python -m unittest -v pruebas.test_fugas         (S y D)
          SIPSA_SOLO_SINTETICO=1 ... (solo S; se usó antes de congelar el protocolo)
"""
import json
import os
import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
from evaluacion import nucleo as N  # noqa: E402

RES = []
ESC = {"retro_r1": (1, 1), "retro_r2": (2, 2), "retro_p1_a2": (1, 2)}
MODELOS = {"ridge_precio": ("ridge", {"alpha": 1.0}, False), "ridge_abast": ("ridge", {"alpha": 1.0}, True),
           "rf_precio": ("rf", {"max_depth": 4, "min_samples_leaf": 5}, False), "rf_abast": ("rf", {"max_depth": 4, "min_samples_leaf": 5}, True)}
FEATS = N.PRECIO + N.CALENDARIO + N.INDICADORES + N.ABAST + ["B", "p_estacional", "y"]


def panel_sintetico(semilla=7) -> pd.DataFrame:
    rng = np.random.default_rng(semilla)
    filas = []
    for pi, prod in enumerate(["PX1", "PX2"]):
        for mi, merc in enumerate(["MX1", "MX2", "MX3"]):
            lp = np.log(1000 * (pi + 1)) + np.cumsum(rng.normal(0, 0.05, 96)) + 0.1 * np.sin(np.arange(96) * 2 * np.pi / 12)
            lq = np.log(1e6) + rng.normal(0, 0.2, 96)
            for t in range(96):
                filas.append({"month": N.mes(t), "product_id": prod, "market_id": merc, "product": f"sintetico {prod}",
                              "market": f"sintetico {merc}", "price": float(np.exp(lp[t])), "kg": float(np.exp(lq[t])),
                              "aviso_imputacion": False})
    df = pd.DataFrame(filas)
    df.loc[(df.product_id == "PX1") & (df.market_id == "MX2") & (df.month == "2021-05"), "price"] = np.nan  # un faltante
    return df


def corrida(panel, t0, lp, la):
    ej = N.tabla_ejemplos(panel, lp, la)
    pred = N.pronosticar_origen(panel, ej, t0, lp, MODELOS, 20261111)
    usadas = ej[(ej.m <= t0 - lp) | (ej.m == t0 + 1)].sort_values(["serie", "m"])
    return usadas, pred.sort_values(["modelo", "serie"])


def comprobar(nombre, df, t0_txt):
    t0 = N.idx(t0_txt)
    for esc, (lp, la) in ESC.items():
        base = N.Panel.desde_df(df)
        u0, p0 = corrida(base, t0, lp, la)
        alt = N.Panel.desde_df(df)
        rng = np.random.default_rng(1)
        alt.P[:, t0 - lp + 1:] *= rng.uniform(0.2, 5.0, alt.P[:, t0 - lp + 1:].shape)
        alt.Q[:, t0 - la + 1:] *= rng.uniform(0.2, 5.0, alt.Q[:, t0 - la + 1:].shape)
        u1, p1 = corrida(alt, t0, lp, la)
        cols_u = [c for c in FEATS if c != "y"]
        # La etiqueta y de la fila a pronosticar (m=t0+1) depende del futuro por definición; no es entrada del modelo.
        tr0, tr1 = u0[u0.m <= t0 - lp], u1[u1.m <= t0 - lp]
        iguales_var = (u0[cols_u].reset_index(drop=True).equals(u1[cols_u].reset_index(drop=True))
                       and tr0.y.reset_index(drop=True).equals(tr1.y.reset_index(drop=True)))
        iguales_pred = np.array_equal(p0.predicho.to_numpy(), p1.predicho.to_numpy(), equal_nan=True)
        iguales_escala = np.array_equal(p0.escala_mase.to_numpy(), p1.escala_mase.to_numpy(), equal_nan=True)
        neg = N.Panel.desde_df(df)
        neg.P[:, t0 - lp] *= 1.5  # último precio permitido
        _, pn = corrida(neg, t0, lp, la)
        cambia = not np.allclose(p0.predicho.to_numpy(), pn.predicho.to_numpy(), equal_nan=True)
        neg2 = N.Panel.desde_df(df)
        neg2.Q[:, t0 - la] *= 3.0  # último volumen permitido: debe cambiar solo modelos con abastecimiento
        _, pn2 = corrida(neg2, t0, lp, la)
        con = p0.modelo.str.endswith("abast").to_numpy()
        cambia_abast = (not np.allclose(p0.predicho[con], pn2.predicho[con])) and np.allclose(p0.predicho[~con], pn2.predicho[~con])
        ok = iguales_var and iguales_pred and iguales_escala and cambia and cambia_abast
        RES.append({"prueba": f"{nombre}:{esc}", "datos": nombre, "origen": t0_txt, "resultado": "PASS" if ok else "FAIL",
                    "valores_futuros_alterados": {"precios_desde": N.mes(t0 - lp + 1), "volumenes_desde": N.mes(t0 - la + 1)},
                    "variables_identicas": iguales_var, "pronosticos_identicos": iguales_pred, "escala_identica": iguales_escala,
                    "control_negativo_precio_limite_cambia": cambia, "control_negativo_volumen_limite_cambia_solo_abast": bool(cambia_abast),
                    "filas_entrenamiento": int((u0.m <= t0 - lp).sum()), "ultima_etiqueta": N.mes(int(u0[u0.m <= t0 - lp].m.max()))})
        assert ok, RES[-1]


class Fugas(unittest.TestCase):
    def test_sintetico(self):
        comprobar("sintetico", panel_sintetico(), "2023-06")
        comprobar("sintetico", panel_sintetico(), "2025-05")

    @unittest.skipIf(os.environ.get("SIPSA_SOLO_SINTETICO") == "1", "solo sintético")
    def test_copia_derivada_del_lote(self):
        from evaluacion.datos import cargar_lote
        df, info = cargar_lote(verificar=True)
        copia = df.copy()  # copia en memoria; el lote en disco no se toca
        comprobar("copia_derivada_lote", copia, "2024-06")
        df2, info2 = cargar_lote(verificar=True)
        self.assertEqual(info["huella_contenido"], info2["huella_contenido"])
        self.assertTrue(df.equals(df2))


def tearDownModule():
    d = RAIZ / "resultados/controles"
    d.mkdir(parents=True, exist_ok=True)
    nombre = "pruebas_fugas_presinteticas.json" if os.environ.get("SIPSA_SOLO_SINTETICO") == "1" else "pruebas_fugas.json"
    (d / nombre).write_text(json.dumps({"pasaron": sum(r["resultado"] == "PASS" for r in RES),
                                        "fallos": sum(r["resultado"] == "FAIL" for r in RES), "pruebas": RES},
                                       ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    unittest.main()
