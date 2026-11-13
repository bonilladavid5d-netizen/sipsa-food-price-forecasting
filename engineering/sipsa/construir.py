"""Construcción del lote en DuckDB a partir del detalle normalizado (Parquet) y la configuración versionada."""
from __future__ import annotations

import csv
import datetime
import json
import os
import shutil
from pathlib import Path

import duckdb

from .util import ROOT, ZONA_CORTE, punto_fallo, raw_dir, read_json
from .xlsx_stream import Xlsx

SQL = ROOT / "sql"


def sql(nombre: str) -> str:
    return (SQL / nombre).read_text(encoding="utf-8")


def ejecutar_script(con, texto: str, params: dict | None = None) -> None:
    """Ejecuta un archivo SQL sentencia a sentencia, pasando solo los parámetros $nombre que usa cada una."""
    import re
    params = params or {}
    # Los archivos SQL del proyecto no contienen '--' ni ';' dentro de literales.
    sin_comentarios = "\n".join(re.sub(r"--.*$", "", l) for l in texto.splitlines())
    for stmt in (x.strip() for x in sin_comentarios.split(";")):
        if not stmt:
            continue
        usados = {k: v for k, v in params.items() if re.search(r"\$" + k + r"\b", stmt)}
        con.execute(stmt, usados) if usados else con.execute(stmt)


def conectar(path: Path, read_only: bool = False) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(str(path), read_only=read_only)
    con.execute("SET threads = 4")
    con.execute("SET memory_limit = '2GB'")
    con.execute("SET preserve_insertion_order = true")
    # Convención explícita (no depende de la zona del sistema): meses y cortes en hora de Colombia.
    con.execute(f"SET TimeZone = '{ZONA_CORTE}'")
    return con


def _historico_oficial(markets: list[str]) -> list[tuple]:
    """Lectura del histórico agregado del DANE (misma lógica que 04_evaluar.py de viabilidad)."""
    x = Xlsx(raw_dir() / "historico_abastecimiento.xlsx")
    try:
        monthly = next(t for sn, t in x.sheets if "Serie mensual" in sn)
        out, header = [], {}
        for rn, v in x.rows(monthly):
            if v.get("A") == "Fecha":
                header = {val: col for col, val in v.items()}
                continue
            if not header:
                continue
            try:
                date = (datetime.date(1899, 12, 30) + datetime.timedelta(days=int(float(v.get("A", ""))))).isoformat()[:7]
            except (ValueError, OverflowError):
                continue
            if "2018-01" <= date <= "2025-12":
                for m in markets:
                    out.append((date, m, float(v[header[m]]), rn))
        return out
    finally:
        x.close()


def construir_lote(salida: Path, normalizados: list[dict], fuentes: list[dict]) -> dict:
    """Crea salida/sipsa.duckdb, enlaza el detalle Parquet y exporta tablas de revisión. Devuelve conteos."""
    cfg = read_json(ROOT / "config/alcance.json")
    exc = read_json(ROOT / "config/excepciones_aprobadas.json")
    pol = read_json(ROOT / "config/politica_temporal.json")
    det = salida / "detalle"
    perf = salida / "perfiles"
    for n in normalizados:
        d = Path(n["dir"])
        dest = det / n["kind"]
        dest.mkdir(parents=True, exist_ok=True)
        # Enlace duro: el lote es autocontenido sin duplicar 300 MB; la caché es inmutable (0444).
        os.link(d / "detalle.parquet", dest / f"{n['year']}.parquet")
        pdir = perf / f"{n['kind']}_{n['year']}"
        pdir.mkdir(parents=True)
        for f in d.iterdir():
            if f.suffix in (".csv", ".json") and f.name != "COMPLETO.json":
                shutil.copyfile(f, pdir / f.name)
    db = salida / "sipsa.duckdb"
    con = conectar(db)
    try:
        con.execute("BEGIN")
        ejecutar_script(con, sql("esquema.sql"))
        snap_by = {}
        for f in fuentes:
            # retrieved_at proviene de config/capturas_aprobadas.json, verificada en lote.verificar_fuentes()
            # junto con el SHA-256 del JSON lateral. El constructor ya no lee fechas de archivos sin verificar.
            sid = f"{f['tipo']}_{f['year'] if f['year'] else 'agregado'}_{f['sha256'][:12]}"
            snap_by[(f["tipo"], f["year"])] = sid
            con.execute("INSERT INTO source_snapshot VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        [sid, f["tipo"], f["year"], f["url"], f["sha256"], f["retrieved_at"], f["local_path"], f["bytes"],
                         None, "current_snapshot_not_historical_vintage", "fuentes_congeladas.json",
                         f["capture_sidecar_sha256"], f"capturas_aprobadas.json:{f['capturas_version']}", True])
        # Referencias versionadas
        prods = list(csv.DictReader((ROOT / "config/equivalencias_productos.csv").open(encoding="utf-8")))
        for pid in dict.fromkeys(r["product_id"] for r in prods):
            r = next(x for x in prods if x["product_id"] == pid)
            con.execute("INSERT INTO product VALUES (?,?,?,?,?)", [pid, r["label"], r["grupo"], "COP/kg", "kg"])
        for r in prods:
            con.execute("INSERT INTO product_crosswalk VALUES (?,?,?,?,?,?,?,?,?)",
                        [r["component"], r["raw_label"], r["product_id"], r["rule"], r["cpc_observed"] or None, r["version"],
                         r["valid_from_month"], r["valid_to_month"] or None, r["decision"]])
        mks = list(csv.DictReader((ROOT / "config/equivalencias_mercados.csv").open(encoding="utf-8")))
        for mid in dict.fromkeys(r["market_id"] for r in mks):
            r = next(x for x in mks if x["market_id"] == mid)
            con.execute("INSERT INTO market VALUES (?,?)", [mid, r["label"]])
        for r in mks:
            con.execute("INSERT INTO market_crosswalk VALUES (?,?,?,?,?,?,?,?)",
                        [r["component"], r["raw_label"], r["market_id"], r["rule"], r["version"], r["valid_from_month"],
                         r["valid_to_month"] or None, r["decision"]])
        mlabel = {r["label"]: r["market_id"] for r in mks}
        for r in csv.DictReader((ROOT / "config/avisos_imputacion.csv").open(encoding="utf-8")):
            con.execute("INSERT INTO aviso_imputacion VALUES (?,?,?,?,?)",
                        [r["month"], mlabel[r["market"]], r["source_sheet"], int(r["source_row"]), r["scope"]])
        for e in pol["escenarios"]:
            con.execute("INSERT INTO politica_temporal VALUES (?,?,?,?,?,?)",
                        [e["escenario_id"], pol["version"], e["retraso_precio_meses"], e["retraso_abastecimiento_meses"], e["base"], e["descripcion"]])
        for r in csv.DictReader((ROOT / "config/canales_disponibilidad.csv").open(encoding="utf-8")):
            con.execute("INSERT INTO canal_disponibilidad VALUES (?,?,?,?,?,?,?)", list(r.values()))
        con.execute("INSERT INTO lote_info VALUES ('modelo', 'sipsa-lote-v1'), ('politica_temporal', ?), ('alcance', ?)",
                    [pol["version"], cfg["version"]])
        # Detalle normalizado como vistas sobre Parquet (rutas relativas al lote).
        pfiles = sorted(str(p) for p in (det / "precios").glob("*.parquet"))
        afiles = sorted(str(p) for p in (det / "abastecimiento").glob("*.parquet"))
        con.execute(f"CREATE TEMP VIEW det_precios AS SELECT * FROM read_parquet({pfiles!r})")
        con.execute(f"CREATE TEMP VIEW det_abastecimiento AS SELECT * FROM read_parquet({afiles!r})")
        con.execute("""INSERT INTO precio_observado
                       SELECT s.snapshot_id, d.source_sheet, d.source_row, d.month, d.grupo, d.producto, d.mercado,
                              d.raw_cpc, d.precio_raw, d.precio
                       FROM det_precios d JOIN source_snapshot s ON s.sha256 = d.source_sha256 AND s.component = 'precios'
                       ORDER BY s.snapshot_id, d.source_sheet, d.source_row""")
        punto_fallo("construir:tras_precios")
        ejecutar_script(con, sql("transformaciones.sql"))
        # Alcance para la selección y la conciliación
        con.execute("CREATE TABLE alcance_mercado (label TEXT PRIMARY KEY)")
        con.executemany("INSERT INTO alcance_mercado VALUES (?)", [[m] for m in cfg["markets"]])
        con.execute("CREATE TABLE alcance_grupo (group_key TEXT PRIMARY KEY, cuota INTEGER NOT NULL)")
        for g in cfg["groups"]:
            con.execute("INSERT INTO alcance_grupo VALUES (?,?)", [g, cfg["basket_quotas"][g]])
        ejecutar_script(con, sql("seleccion_canasta.sql"), {"fin_entrenamiento": cfg["selection_training_end"],
                                                   "min_meses": cfg["min_training_months_each_market_each_source"]})
        ejecutar_script(con, sql("panel.sql"))
        con.execute("CREATE TEMP TABLE historico_oficial (month TEXT, market TEXT, official_tonnes DOUBLE, source_row INTEGER)")
        con.executemany("INSERT INTO historico_oficial VALUES (?,?,?,?)", _historico_oficial(cfg["markets"]))
        con.execute("CREATE TEMP TABLE excepcion_conciliacion (month TEXT, market TEXT)")
        con.executemany("INSERT INTO excepcion_conciliacion VALUES (?,?)",
                        [[e["month"], e["market"]] for e in exc["conciliacion_totales"]])
        ejecutar_script(con, sql("conciliacion.sql"))
        # Diagnósticos heredados: llaves repetidas de precio y ambigüedad CPC.
        con.execute("""CREATE TABLE llaves_repetidas_precios AS
                       SELECT p.* FROM precio_observado p
                       JOIN (SELECT month, mercado, producto FROM precio_observado GROUP BY ALL HAVING count(*) > 1) d
                       USING (month, mercado, producto)
                       ORDER BY month, mercado, producto, snapshot_id, source_sheet, source_row""")
        con.execute("""CREATE TABLE ambiguedad_cpc AS
                       SELECT raw_cpc, count(DISTINCT producto) AS price_varieties,
                              string_agg(DISTINCT producto, '; ' ORDER BY producto) AS examples
                       FROM precio_observado WHERE month LIKE '2025-%' GROUP BY raw_cpc ORDER BY raw_cpc""")
        con.execute("COMMIT")
        punto_fallo("construir:tras_commit")
        exportar_tablas(con, salida / "tablas")
        conteos = {t: con.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in
                   ["source_snapshot", "product", "market", "product_crosswalk", "precio_observado", "abastecimiento_mes_todos",
                    "price_month", "supply_month", "panel_mensual", "conciliacion_totales", "candidatos_elegibles",
                    "canasta_reproducida", "llaves_repetidas_precios"]}
        con.execute("CHECKPOINT")
        return conteos
    finally:
        con.close()


TABLAS_EXPORTADAS = {
    "panel_mensual.csv": "SELECT * EXCLUDE (kg_exacto) FROM panel_mensual ORDER BY month, market_id, product_id",
    "conciliacion_totales.csv": "SELECT * FROM conciliacion_totales ORDER BY month, market",
    "candidatos_elegibles.csv": "SELECT * FROM candidatos_elegibles ORDER BY min_joint_months DESC, training_kg DESC, product",
    "canasta_reproducida.csv": "SELECT * FROM canasta_reproducida ORDER BY group_key, min_joint_months DESC, training_kg DESC, product",
    "llaves_repetidas_precios.csv": "SELECT * FROM llaves_repetidas_precios",
    "ambiguedad_cpc.csv": "SELECT * FROM ambiguedad_cpc",
    "cobertura_series.csv": """SELECT product_id, product, market_id, market, count(*) AS expected_months,
                                      count(*) FILTER (WHERE price_present) AS price_months,
                                      count(*) FILTER (WHERE supply_present) AS supply_months
                               FROM panel_mensual GROUP BY ALL ORDER BY product_id, market_id""",
    "huecos_canasta.csv": """SELECT month, market, product, price_present, supply_present FROM panel_mensual
                             WHERE NOT price_present OR NOT supply_present ORDER BY month, market, product""",
    "fuentes.csv": "SELECT * FROM source_snapshot ORDER BY component, source_year",
    "politica_temporal.csv": "SELECT * FROM politica_temporal ORDER BY escenario_id",
    "canales_disponibilidad.csv": "SELECT * FROM canal_disponibilidad ORDER BY canal",
}


def exportar_tablas(con, carpeta: Path) -> None:
    carpeta.mkdir(parents=True, exist_ok=True)
    for nombre, q in TABLAS_EXPORTADAS.items():
        df = con.execute(q).df()
        df.to_csv(carpeta / nombre, index=False, lineterminator="\n")
