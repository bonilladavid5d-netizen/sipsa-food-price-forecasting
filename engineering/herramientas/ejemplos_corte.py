"""Ejemplos concretos: qué información puede usar un pronóstico emitido al cierre de un mes,
según cada escenario de la política temporal y el modo estricto. Lee solo el lote APROBADO.
Salida: evidencia/ejemplos_disponibilidad_corte.csv"""
import csv, json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sipsa.cli import _abrir_aprobado
from sipsa.construir import sql
con, ap = _abrir_aprobado()
pol = json.loads((ROOT / "config/politica_temporal.json").read_text())
inicio_micro = pol["inicio_documentado_canal"]["abastecimiento_microdato"]
filas = []
for origen in ["2019-06", "2020-12", "2023-07", "2024-01", "2025-11"]:
    y, m = map(int, origen.split("-")); objetivo = f"{y + (m // 12)}-{m % 12 + 1:02d}"
    for e in con.execute("SELECT escenario_id FROM politica_temporal ORDER BY escenario_id").fetchall():
        df = con.execute(sql("consulta_escenario.sql"), {"escenario": e[0], "origen": origen}).df()
        et = con.execute(sql("etiquetas_disponibles.sql"), {"escenario": e[0], "origen": origen, "h": 1}).df()
        p, s = df[df.componente == "precio"], df[df.componente == "abastecimiento"]
        filas.append({"lote_id": ap["lote_id"], "corte_cierre_de": origen, "mes_objetivo": objetivo, "modo": e[0], "base": "supuesto",
                      "ultimo_mes_precio": p.month.max(), "ultimo_mes_abastecimiento": s.month.max(),
                      "ultima_etiqueta_entrenamiento": et.mes_objetivo.max(), "celdas_precio": len(p), "celdas_abastecimiento": len(s),
                      "abastecimiento_antes_de_difusion_documentada": int((s.month < inicio_micro).sum()),
                      "corte_estricto": None, "nota": "precio de " + objetivo + " nunca disponible; el promedio de " + origen + " tampoco"})
    from sipsa.util import cierre_mes
    corte = cierre_mes(origen)  # v2: convención única de cierre del mes calendario (hora de Colombia)
    n = len(con.execute(sql("consulta_asof_estricta.sql"), {"corte": corte}).fetchall())
    filas.append({"lote_id": ap["lote_id"], "corte_cierre_de": origen, "mes_objetivo": objetivo, "modo": "estricto_observado",
                  "base": "observado", "ultimo_mes_precio": None, "ultimo_mes_abastecimiento": None, "ultima_etiqueta_entrenamiento": None,
                  "celdas_precio": n, "celdas_abastecimiento": 0, "abastecimiento_antes_de_difusion_documentada": 0,
                  "corte_estricto": corte, "nota": "sin capturas observadas antes de 2026-11-11: el modo estricto no permite este corte"})
con.close()
out = ROOT / "evidencia/v2/ejemplos_disponibilidad_corte.csv"  # la versión v1 se conserva en evidencia/
with out.open("w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=list(filas[0])); w.writeheader(); w.writerows(filas)
for r in filas: print(r["corte_cierre_de"], r["modo"], r["ultimo_mes_precio"], r["ultimo_mes_abastecimiento"], r["ultima_etiqueta_entrenamiento"], r["celdas_precio"], r["abastecimiento_antes_de_difusion_documentada"])
