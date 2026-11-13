"""Contraste acotado del servicio web SOAP del SIPSA con el lote aprobado (no entra al panel).

Entradas: respuestas guardadas de `promediosSipsaMesMadr` y `promedioAbasSipsaMesMadr`
(evidencia/servicio_web/*.xml) y el lote vigente (datos/APROBADO.json).
Salida: evidencia/servicio_web/contraste_servicio_web.json y contraste_celdas.csv.

Pregunta: ¿el servicio contiene los mismos meses, productos y valores que el XLSX para la canasta,
y expone alguna fecha que pueda documentar disponibilidad histórica?
"""
import collections
import csv
import hashlib
import json
import sys
from pathlib import Path

import duckdb
from lxml import etree as E

ROOT = Path(__file__).resolve().parents[1]
SW = ROOT / "evidencia/servicio_web"


def registros(path: Path):
    for _, el in E.iterparse(str(path), events=("end",), tag="return"):
        yield {c.tag: c.text for c in el}
        el.clear()
        while el.getprevious() is not None:
            del el.getparent()[0]


def main():
    ap = json.loads((ROOT / "datos/APROBADO.json").read_text())
    con = duckdb.connect(str(ROOT / "datos" / ap["ruta"] / "sipsa.duckdb"), read_only=True)
    panel = con.execute("SELECT month, market, product, price, kg FROM panel_mensual").df()
    con.close()
    pk = {(r.month, r.market, r.product): r for r in panel.itertuples()}
    mercados, productos = set(panel.market), set(panel["product"])
    out = {"lote_id": ap["lote_id"], "operaciones": {}}
    filas = []
    for op, valor, comp in [("promediosSipsaMesMadr", "promedioKg", "precio"), ("promedioAbasSipsaMesMadr", "cantidadTon", "abastecimiento")]:
        p = SW / f"{op}.xml"
        meta = {"archivo": p.name, "bytes": p.stat().st_size, "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
                "consultado_utc": (SW / f"{op}.consultado").read_text().strip()}
        n = 0
        campos = collections.Counter()
        meses = collections.Counter()
        claves = collections.Counter()
        canasta = {}
        for r in registros(p):
            n += 1
            campos.update(k for k, v in r.items() if v not in (None, ""))
            mes = (r.get("fechaMesIni") or "")[:7]
            meses[mes] += 1
            key = (mes, r.get("fuenNombre"), r.get("artiNombre"))
            claves[key] += 1
            if key[1] in mercados and key[2] in productos and "2018-01" <= mes <= "2025-12":
                canasta.setdefault(key, []).append(float(r[valor]) if r.get(valor) else None)
        comparadas = iguales = solo_servicio = 0
        dif_max = 0.0
        for key, vals in sorted(canasta.items()):
            cell = pk.get(key)
            ref = None if cell is None else (cell.price if comp == "precio" else (cell.kg / 1000 if cell.kg == cell.kg else None))
            v = vals[0] if len(vals) == 1 else None
            if ref is None or ref != ref:
                solo_servicio += 1
                estado = "solo_servicio"
            else:
                comparadas += 1
                d = abs(v - ref) if v is not None else None
                ok = d is not None and (d == 0 if comp == "precio" else d < 0.5)  # toneladas enteras en el servicio
                iguales += ok
                dif_max = max(dif_max, d or 0)
                estado = "igual" if ok else "distinto"
            filas.append({"componente": comp, "month": key[0], "market": key[1], "product": key[2], "servicio": v,
                          "registros_servicio": len(vals), "lote": ref, "estado": estado})
        celdas_lote = sum(1 for (m, mk, pr), r in pk.items() if (r.price == r.price if comp == "precio" else r.kg == r.kg))
        meta.update({"registros": n, "campos_con_valor": dict(campos), "mes_min": min(meses), "mes_max": max(meses),
                     "meses_distintos": len(meses), "claves_repetidas": sum(1 for c in claves.values() if c > 1),
                     "celdas_canasta_en_servicio_2018_2025": len(canasta), "celdas_canasta_en_lote": celdas_lote,
                     "comparadas": comparadas, "iguales": iguales, "solo_en_servicio": solo_servicio,
                     "diferencia_absoluta_maxima": dif_max,
                     "regla_igualdad": "precio exacto COP/kg" if comp == "precio" else "|toneladas servicio - kg lote/1000| < 0,5"})
        out["operaciones"][op] = meta
    out["conclusion_fechas"] = ("fechaCreacion no aparece con valor en ningún registro" if not any(
        "fechaCreacion" in m["campos_con_valor"] for m in out["operaciones"].values()) else
        "fechaCreacion presente en algunos registros; revisar semántica antes de usarla")
    with (SW / "contraste_celdas.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(filas[0]))
        w.writeheader()
        w.writerows(filas)
    (SW / "contraste_servicio_web.json").write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    sys.exit(main())
