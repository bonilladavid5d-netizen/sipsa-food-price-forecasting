"""Compara el lote aprobado actual (v2) con la viabilidad y con el último lote v1.
Uso: python herramientas/comparar_versiones.py <ruta_lote_anterior> [salida.json]
Salida: evidencia/v2/comparacion_viabilidad_y_v1.json
Solo lee; no ajusta datos. Las diferencias de huella se explican archivo por archivo.
"""
import hashlib
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
ap = json.loads((ROOT / "datos/APROBADO.json").read_text())
v2 = ROOT / "datos" / ap["ruta"]
v1 = Path(sys.argv[1]).resolve()
ref = json.loads((ROOT / "config/referencia_viabilidad.json").read_text())
out = {"lote_v2": ap["lote_id"], "huella_v2": ap["huella_contenido"], "lote_v1": v1.name,
       "huella_v1": json.loads((v1 / "LOTE.json").read_text())["huella_contenido"]}

# 1. Contra la viabilidad
panel = pd.read_csv(v2 / "tablas/panel_mensual.csv")
vref = pd.read_csv(ROOT / "config/referencia_panel_viabilidad.csv")
m = panel.merge(vref, on=["month", "market", "product"], how="outer", suffixes=("", "_v"), indicator=True)
faltan = panel.loc[~panel.price_present, ["month", "market", "product"]].to_dict("records")
rec = pd.read_csv(v2 / "tablas/conciliacion_totales.csv")
rv = pd.read_csv(ROOT / "config/referencia_conciliacion_viabilidad.csv")
mr = rec.merge(rv, on=["month", "market"], suffixes=("", "_v"))
perfiles_iguales = sum(sha(v2 / "perfiles" / k / f) == h for k, d in ref["perfiles"].items() for f, h in d["csv_sha256"].items())
out["contra_viabilidad"] = {
    "celdas_panel": len(panel), "celdas_emparejadas": int((m._merge == "both").sum()),
    "precios_presentes": int(panel.price_present.sum()), "abastecimiento_presente": int(panel.supply_present.sum()),
    "precios_identicos": bool(((m.price == m.price_v) | (m.price.isna() & m.price_v.isna())).all()),
    "max_dif_kg": float((m.kg - m.kg_v).abs().max()), "precios_ausentes": faltan,
    "fila_origen_precio_igual": bool(((m.price_source_row == m.source_row) | (m.price_source_row.isna() & m.source_row.isna())).all()),
    "conciliacion_filas": len(rec), "conciliacion_dentro_1kg": int(rec.within_1kg.sum()),
    "conciliacion_fuera": rec.loc[~rec.within_1kg, ["month", "market", "difference_kg"]].to_dict("records"),
    "conciliacion_max_dif_vs_viabilidad_kg": float((mr.difference_kg - mr.difference_kg_v).abs().max()),
    "perfiles_csv_identicos": f"{perfiles_iguales} de 96",
}

# 2. Contra el lote v1, archivo por archivo (excluye binario DuckDB y metadatos de ejecución)
def archivos(d):
    return {str(p.relative_to(d)): sha(p) for sub in ["tablas", "perfiles", "detalle"] for p in sorted((d / sub).rglob("*")) if p.is_file()}
a1, a2 = archivos(v1), archivos(v2)
dif = sorted(k for k in set(a1) | set(a2) if a1.get(k) != a2.get(k))
expl = {}
for k in dif:
    if k.endswith("perfil.json"):
        x, y = json.loads((v1 / k).read_text()), json.loads((v2 / k).read_text())
        x.pop("duration_seconds"); y.pop("duration_seconds")
        expl[k] = "solo duration_seconds (excluida de la huella)" if x == y else "CONTENIDO DISTINTO"
    elif k.endswith(".csv") and (v1 / k).exists() and (v2 / k).exists():
        x, y = pd.read_csv(v1 / k, dtype=str), pd.read_csv(v2 / k, dtype=str)
        nuevas = [c for c in y.columns if c not in x.columns]
        comunes = [c for c in x.columns if c in y.columns]
        iguales = x[comunes].equals(y[comunes]) and len(x) == len(y)
        cambiadas = [c for c in comunes if not x[c].equals(y[c])]
        expl[k] = {"filas_v1": len(x), "filas_v2": len(y), "columnas_nuevas": nuevas, "columnas_comunes_identicas": iguales,
                   "columnas_con_valores_distintos": cambiadas,
                   "valores_distintos": {c: sorted(set(zip(x[c], y[c])))[:3] for c in cambiadas}}
    else:
        expl[k] = "presente solo en una versión" if (k in a1) != (k in a2) else "binario distinto"
out["contra_v1"] = {"archivos_comparados": len(set(a1) | set(a2)), "archivos_identicos": len(set(a1) & set(a2)) - len(dif),
                    "archivos_distintos": dif, "explicacion": expl,
                    "detalle_parquet_identico": all(a1[k] == a2.get(k) for k in a1 if k.startswith("detalle/"))}
dst = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "evidencia/v2/comparacion_viabilidad_y_v1.json"
dst.write_text(json.dumps(out, ensure_ascii=False, indent=2, default=str) + "\n")
print(json.dumps(out, ensure_ascii=False, indent=2, default=str)[:6000])
