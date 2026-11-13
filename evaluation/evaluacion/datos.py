"""Lectura del lote aprobado SOLO mediante el mecanismo oficial del proyecto de ingeniería
(datos/APROBADO.json + verificación SHA-256 completa del manifiesto). No modifica el lote."""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parents[1]


def _cfg() -> dict:
    return json.loads((RAIZ / "config/protocolo.json").read_text(encoding="utf-8"))


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with Path(p).open("rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def proyecto_ingenieria() -> Path:
    """Ruta del proyecto de ingeniería. SIPSA_PROYECTO_INGENIERIA permite reproducir desde otra carpeta;
    la integridad se comprueba igual (huella de contenido y hechos esperados del protocolo)."""
    cfg = _cfg()
    if os.environ.get("SIPSA_PROYECTO_INGENIERIA"):
        return Path(os.environ["SIPSA_PROYECTO_INGENIERIA"]).resolve()
    return (RAIZ / cfg["entrada"]["proyecto_ingenieria_relativo"]).resolve()


class IntegridadFallida(RuntimeError):
    pass


def cargar_lote(verificar: bool = True) -> tuple[pd.DataFrame, dict]:
    """Devuelve (panel, info). Falla si el lote no es íntegro o no coincide con el esperado en el protocolo."""
    cfg = _cfg()
    proy = proyecto_ingenieria()
    os.environ.setdefault("SIPSA_DATOS", str(proy / "datos"))
    if str(proy) not in sys.path:
        sys.path.insert(0, str(proy))
    from sipsa import lote  # mecanismo oficial
    from sipsa.construir import conectar

    ap = lote.aprobado()
    esperado = cfg["entrada"]
    errores = []
    if verificar:
        v = lote.verificar_aprobado(completo=True)
        if not v["ok"]:
            errores.append(f"verificación del lote: {v['errores'][:5]}")
    if ap["huella_contenido"] != esperado["huella_contenido"]:
        errores.append(f"huella de contenido {ap['huella_contenido']} != {esperado['huella_contenido']}")
    lote_dir = Path(os.environ["SIPSA_DATOS"]) / ap["ruta"]
    con = conectar(lote_dir / "sipsa.duckdb", read_only=True)
    try:
        panel = con.execute("""SELECT month, market_id, market, product_id, product, grupo, price, kg,
                                      price_present, supply_present, source_month_has_imputation_notice AS aviso_imputacion
                               FROM panel_mensual ORDER BY product_id, market_id, month""").df()
    finally:
        con.close()
    man = json.loads((lote_dir / "MANIFIESTO.json").read_text())["archivos"]
    panel_csv_sha = man["tablas/panel_mensual.csv"]["sha256"]
    if verificar and sha256(lote_dir / "tablas/panel_mensual.csv") != panel_csv_sha:
        errores.append("tablas/panel_mensual.csv no coincide con el manifiesto")
    hechos = {"celdas": len(panel), "precios_presentes": int(panel.price_present.sum()),
              "abastecimiento_presente": int(panel.supply_present.sum()),
              "series": int(panel.groupby(["product_id", "market_id"]).ngroups),
              "meses": int(panel.month.nunique()), "mes_min": panel.month.min(), "mes_max": panel.month.max(),
              "mercado_mes_con_aviso": int(panel.loc[panel.aviso_imputacion, ["month", "market_id"]].drop_duplicates().shape[0]),
              "precios_ausentes": panel.loc[~panel.price_present, ["month", "market", "product"]].to_dict("records")}
    for k, v in esperado["hechos_esperados"].items():
        if hechos.get(k) != v:
            errores.append(f"{k}: observado {hechos.get(k)} != esperado {v}")
    if errores:
        raise IntegridadFallida("; ".join(errores))
    info = {"lote_id": ap["lote_id"], "publicacion_id": ap.get("publicacion_id"), "huella_contenido": ap["huella_contenido"],
            "manifiesto_sha256": ap["manifiesto_sha256"], "panel_csv_sha256": panel_csv_sha,
            "proyecto_ingenieria": str(proy), "hechos": hechos}
    return panel, info
