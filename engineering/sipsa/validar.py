"""Contratos que bloquean la promoción de un lote. Cada comprobación produce PASS/FAIL con detalle.
Las inyecciones de prueba se ejecutan dentro de transacciones revertidas y nunca quedan en el lote."""
from __future__ import annotations

import csv
import json
from pathlib import Path

import duckdb
import pandas as pd
import pyarrow.parquet as pq

from .construir import conectar, sql
from .normalizar import parse_date, validate_schema
import datetime as dt

from .util import ROOT, cierre_mes, read_json, sha256_file


class Contratos:
    def __init__(self):
        self.checks = []

    def check(self, nombre: str, ok: bool, detalle="") -> bool:
        self.checks.append({"check": nombre, "status": "PASS" if ok else "FAIL", "detail": str(detalle)})
        if not ok:
            print("FAIL", nombre, detalle, flush=True)
        return ok

    def informe(self) -> dict:
        return {"checks": self.checks, "passed": sum(c["status"] == "PASS" for c in self.checks),
                "failed": sum(c["status"] == "FAIL" for c in self.checks)}


def _rechaza(con, c: Contratos, nombre: str, sentencia: str, params) -> None:
    con.execute("BEGIN")
    try:
        con.execute(sentencia, params)
        ok = False
        det = "aceptado"
    except duckdb.ConstraintException as e:  # solo cuenta un rechazo por restricción, no un error de tipos
        ok = True
        det = type(e).__name__
    except duckdb.Error as e:
        ok = False
        det = f"rechazo por motivo distinto: {type(e).__name__}"
    finally:
        con.execute("ROLLBACK")
    c.check(nombre, ok, det)


def validar_lote(salida: Path, normalizados: list[dict], fuentes: list[dict]) -> dict:
    c = Contratos()
    ref = read_json(ROOT / "config/referencia_viabilidad.json")
    exc = read_json(ROOT / "config/excepciones_aprobadas.json")
    pol = read_json(ROOT / "config/politica_temporal.json")

    # 1. Detalle normalizado y perfiles heredados: mismos CSV que la viabilidad (SHA-256).
    total = {"precios": 0, "abastecimiento": 0}
    distintos = []
    for n in normalizados:
        k = f"{n['kind']}_{n['year']}"
        pdir = salida / "perfiles" / k
        perfil = json.loads((pdir / "perfil.json").read_text())
        rows = pq.ParquetFile(salida / "detalle" / n["kind"] / f"{n['year']}.parquet").metadata.num_rows
        c.check(f"parquet_filas_{k}", rows == perfil["counts"]["rows"] == ref["perfiles"][k]["rows"],
                f"parquet={rows}; perfil={perfil['counts']['rows']}; viabilidad={ref['perfiles'][k]['rows']}")
        total[n["kind"]] += rows
        for fname, h in ref["perfiles"][k]["csv_sha256"].items():
            if sha256_file(pdir / fname) != h:
                distintos.append(f"{k}/{fname}")
    c.check("perfiles_identicos_a_viabilidad", not distintos and len(normalizados) == 16,
            f"{16 * 6 - len(distintos)} de 96 CSV con SHA-256 idéntico; distintos={distintos}")
    c.check("filas_origen_totales", total == {"precios": ref["resultados"]["price_rows"], "abastecimiento": ref["resultados"]["supply_rows"]}, total)

    con = conectar(salida / "sipsa.duckdb")
    try:
        q1 = lambda s, p=None: con.execute(s, p).fetchone()[0] if p else con.execute(s).fetchone()[0]
        # 2. Integridad relacional.
        c.check("precio_observado_filas", q1("SELECT count(*) FROM precio_observado") == total["precios"])
        c.check("abastecimiento_mes_todos_filas_origen", q1("SELECT sum(source_rows) FROM abastecimiento_mes_todos") == total["abastecimiento"])
        c.check("abastecimiento_sin_deduplicar", q1("SELECT sum(source_rows) FROM supply_month") ==
                q1("""SELECT sum(a.source_rows) FROM abastecimiento_mes_todos a JOIN product_crosswalk pc
                      ON pc.component='abastecimiento' AND pc.raw_label=a.producto
                      JOIN market_crosswalk mc ON mc.component='abastecimiento' AND mc.raw_label=a.mercado"""))
        for t in ["price_month", "supply_month"]:
            c.check(f"{t}_huerfanos", q1(f"""SELECT count(*) FROM {t} x LEFT JOIN product p USING (product_id)
                                            LEFT JOIN market m USING (market_id) LEFT JOIN source_snapshot s USING (snapshot_id)
                                            WHERE p.product_id IS NULL OR m.market_id IS NULL OR s.snapshot_id IS NULL""") == 0)
        c.check("crosswalk_sin_ambiguedad", q1("""SELECT count(*) FROM (SELECT component, raw_label FROM product_crosswalk
                                                  WHERE valid_to_month IS NULL GROUP BY ALL HAVING count(DISTINCT product_id) > 1)""") == 0)
        c.check("published_at_desconocido_sigue_nulo",
                q1("SELECT count(published_at) FROM price_month") + q1("SELECT count(published_at) FROM supply_month") +
                q1("SELECT count(historical_release_at) FROM source_snapshot") == 0)
        # 3. Panel: cardinalidad, huecos esperados y equivalencia con la viabilidad.
        panel = con.execute("SELECT * EXCLUDE (kg_exacto) FROM panel_mensual").df()
        c.check("panel_2880_celdas", len(panel) == 2880 and not panel.duplicated(["month", "market_id", "product_id"]).any(), len(panel))
        c.check("panel_precios_presentes", int(panel.price_present.sum()) == ref["resultados"]["price_present"], int(panel.price_present.sum()))
        c.check("panel_abastecimiento_presente", int(panel.supply_present.sum()) == ref["resultados"]["supply_present"], int(panel.supply_present.sum()))
        huecos = sorted(map(tuple, panel.loc[~panel.price_present, ["month", "market", "product"]].values.tolist()))
        esperados = sorted((h["month"], h["market"], h["product"]) for h in exc["huecos_precio_canasta"])
        c.check("huecos_precio_son_los_aprobados", huecos == esperados, huecos)
        c.check("huecos_no_rellenados_con_cero", q1("SELECT count(*) FROM panel_mensual WHERE price = 0 OR kg = 0") == 0)
        c.check("union_no_multiplica_celdas", q1("""SELECT count(*) FROM price_month p JOIN supply_month s
                                                   USING (product_id, market_id, month)""") <= 2880)
        vref = pd.read_csv(ROOT / "config/referencia_panel_viabilidad.csv")
        m = panel.merge(vref, on=["month", "market", "product"], how="outer", suffixes=("", "_v"), validate="one_to_one", indicator=True)
        solo = int((m["_merge"] != "both").sum())
        precio_igual = ((m.price == m.price_v) | (m.price.isna() & m.price_v.isna())).all()
        kg_dif = (m.kg - m.kg_v).abs().max()
        fila_igual = ((m.price_source_row == m.source_row) | (m.price_source_row.isna() & m.source_row.isna())).all()
        filas_ab = (m.supply_source_rows == m.source_rows).all()
        aviso = (m.source_month_has_imputation_notice == m.source_month_has_imputation_notice_v).all()
        c.check("panel_igual_a_viabilidad", solo == 0 and precio_igual and kg_dif <= 1e-6 and fila_igual and filas_ab and aviso,
                f"celdas_sin_par={solo}; precios_identicos={bool(precio_igual)}; max_dif_kg={kg_dif}; "
                f"fila_origen_precio_igual={bool(fila_igual)}; filas_abastecimiento_iguales={bool(filas_ab)}; avisos_iguales={bool(aviso)}")
        c.check("avisos_imputacion_10_mercado_mes", q1("SELECT count(DISTINCT (month, market_id)) FROM panel_mensual WHERE source_month_has_imputation_notice") == 10)
        # 4. Selección de la canasta reproducida en SQL.
        cand = con.execute("SELECT * FROM candidatos_elegibles").df()
        cref = pd.read_csv(ROOT / "config/referencia_candidatos_viabilidad.csv")
        mm = cand.merge(cref, on="product", how="outer", suffixes=("", "_v"), indicator=True)
        same = (mm._merge == "both").all() and (mm.min_joint_months == mm.min_joint_months_v).all() and \
            (mm.min_price_months == mm.min_price_months_v).all() and (mm.min_supply_months == mm.min_supply_months_v).all() and \
            ((mm.training_kg - mm.training_kg_v).abs() <= 1e-3).all()
        c.check("candidatos_iguales_a_viabilidad", bool(same) and list(cand["product"]) == list(cref["product"]), f"{len(cand)} candidatos")
        canasta = set(con.execute("SELECT product FROM canasta_reproducida").df()["product"])
        config_canasta = set(r["label"] for r in csv.DictReader((ROOT / "config/equivalencias_productos.csv").open(encoding="utf-8")))
        c.check("canasta_reproducida_igual_a_equivalencias", canasta == config_canasta and len(canasta) == 10, sorted(canasta))
        c.check("productos_elegibles_un_grupo", q1("SELECT count(*) FROM candidatos_elegibles WHERE n_grupos <> 1") == 0)
        # 5. Anomalías conocidas siguen visibles, sin reparación arbitraria.
        exceso = q1("SELECT count(*) - count(DISTINCT (month, mercado, producto)) FROM llaves_repetidas_precios")
        c.check("llaves_repetidas_precios_esperadas", exceso == exc["llaves_repetidas_precios_exceso_esperado"], exceso)
        c.check("llaves_repetidas_fuera_de_canasta", q1("""SELECT count(*) FROM llaves_repetidas_precios l JOIN product_crosswalk pc
                                                         ON pc.component='precios' AND pc.raw_label=l.producto""") == 0)
        c.check("cpc_no_es_identificador", q1("SELECT max(price_varieties) FROM ambiguedad_cpc") > 1)
        # 6. Conciliación con el histórico DANE.
        rec = con.execute("SELECT * FROM conciliacion_totales").df()
        fuera = rec[~rec.within_1kg.fillna(False)]
        exc_ok = all(any(abs(r.difference_kg - e["difference_kg_esperada"]) <= e["tolerancia_kg"] and r.month == e["month"] and r.market == e["market"]
                         for e in exc["conciliacion_totales"]) for r in fuera.itertuples())
        c.check("conciliacion_288_mercado_mes", len(rec) == 288 and rec.official_tonnes.notna().all() and rec.microdata_kg.notna().all(), len(rec))
        c.check("conciliacion_solo_excepciones_aprobadas", len(fuera) == len(exc["conciliacion_totales"]) and exc_ok,
                f"dentro_1kg={int(rec.within_1kg.sum())}; fuera={fuera[['month', 'market', 'difference_kg']].to_dict('records')}")
        rv = pd.read_csv(ROOT / "config/referencia_conciliacion_viabilidad.csv")
        mr = rec.merge(rv, on=["month", "market"], suffixes=("", "_v"))
        c.check("conciliacion_igual_a_viabilidad", len(mr) == 288 and (mr.difference_kg - mr.difference_kg_v).abs().max() <= 1e-6,
                f"max_dif={(mr.difference_kg - mr.difference_kg_v).abs().max()}")
        # 7. Rechazos de integridad (transacciones revertidas).
        row = con.execute("SELECT * FROM price_month LIMIT 1").fetchone()
        ins = "INSERT INTO price_month VALUES (?,?,?,?,?,?,?,?,?,?)"
        _rechaza(con, c, "llave_precio_duplicada_rechazada", ins, list(row))
        bad = list(row); bad[2] = "2018-00"
        _rechaza(con, c, "mes_invalido_rechazado", ins, bad)
        bad = list(row); bad[2] = "2017-01"; bad[5] = -1.0
        _rechaza(con, c, "precio_negativo_rechazado", ins, bad)
        bad = list(row); bad[2] = "2017-01"; bad[0] = "NO_EXISTE"
        _rechaza(con, c, "producto_inexistente_rechazado", ins, bad)
        bad = list(row); bad[2] = "2017-01"; bad[4] = "snapshot_inexistente"
        _rechaza(con, c, "snapshot_inexistente_rechazado", ins, bad)
        cw = con.execute("SELECT * FROM product_crosswalk LIMIT 1").fetchone()
        _rechaza(con, c, "equivalencia_duplicada_rechazada", "INSERT INTO product_crosswalk VALUES (?,?,?,?,?,?,?,?,?)", list(cw))
        _rechaza(con, c, "unidad_mixta_rechazada", "INSERT INTO product VALUES (?,?,?,?,?)", ["fixture", "no es dato", "x", "COP/litro", "kg"])
        _rechaza(con, c, "escenario_sin_retraso_rechazado", "INSERT INTO politica_temporal VALUES (?,?,?,?,?,?)",
                 ["fixture", "x", 0, 1, "supuesto", "el promedio de t no puede estar disponible al cierre de t"])
        _rechaza(con, c, "escenario_presentado_como_observado_rechazado", "INSERT INTO politica_temporal VALUES (?,?,?,?,?,?)",
                 ["fixture", "x", 1, 1, "observado", "un supuesto no puede rotularse como observado"])
        # 8. Disponibilidad temporal.
        estricta = sql("consulta_asof_estricta.sql")
        n_vis = len(con.execute(estricta, {"corte": "2025-12-31T23:59:59+00:00"}).fetchall())
        c.check("estricto_no_fabrica_vintage_2025", n_vis == 0, "Las capturas de 2026-11-11 no se presentan como disponibles en 2025")
        n_fut = len(con.execute(estricta, {"corte": "2099-01-01T00:00:00+00:00"}).fetchall())
        total_celdas = q1("SELECT count(*) FROM price_month") + q1("SELECT count(*) FROM supply_month")
        c.check("estricto_ve_snapshots_actuales_despues_de_captura", n_fut == total_celdas, n_fut)
        # 8b. (v2, H1) first_seen_at proviene de la captura aprobada y verificada, y los cortes la respetan.
        ref = {f["sha256"]: f for f in fuentes}
        snaps = con.execute("""SELECT snapshot_id, sha256, strftime(retrieved_at AT TIME ZONE 'UTC', '%Y-%m-%dT%H:%M:%S.%f'),
                                      capture_sidecar_sha256, first_seen_basis FROM source_snapshot ORDER BY snapshot_id""").fetchall()
        malos = []
        for sid, sh, ts_utc, side, basis in snaps:
            f = ref.get(sh)
            esperado = dt.datetime.fromisoformat(f["retrieved_at"]).astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f") if f else None
            if not f or ts_utc != esperado or side != f["capture_sidecar_sha256"] or not basis.startswith("capturas_aprobadas.json"):
                malos.append(sid)
        c.check("first_seen_at_igual_a_captura_aprobada", len(snaps) == 17 and not malos and
                q1("SELECT count(*) FROM price_month p JOIN source_snapshot s USING (snapshot_id) WHERE p.first_seen_at <> s.retrieved_at") == 0 and
                q1("SELECT count(*) FROM supply_month p JOIN source_snapshot s USING (snapshot_id) WHERE p.first_seen_at <> s.retrieved_at") == 0,
                f"{len(snaps)} capturas; distintas={malos}")
        est_sub = estricta.rstrip().rstrip(";")
        filas_por_snap = dict(con.execute("""SELECT snapshot_id, count(*) FROM (SELECT snapshot_id FROM price_month
                                             UNION ALL SELECT snapshot_id FROM supply_month) GROUP BY ALL""").fetchall())
        fallos_borde = []
        for f in fuentes:
            sid = next(s[0] for s in snaps if s[1] == f["sha256"])
            if sid not in filas_por_snap:
                continue  # histórico agregado: no aporta celdas a los hechos
            t = dt.datetime.fromisoformat(f["retrieved_at"])
            antes = (t - dt.timedelta(microseconds=1)).isoformat()
            n_antes = q1(f"SELECT count(*) FROM ({est_sub}) WHERE snapshot_id = '{sid}'", {"corte": antes})
            n_en = q1(f"SELECT count(*) FROM ({est_sub}) WHERE snapshot_id = '{sid}'", {"corte": t.isoformat()})
            if n_antes != 0 or n_en != filas_por_snap[sid]:
                fallos_borde.append((sid, n_antes, n_en, filas_por_snap[sid]))
        c.check("estricto_cortes_1us_antes_y_en_cada_captura", not fallos_borde and len(filas_por_snap) == 16,
                f"{len(filas_por_snap)} capturas con celdas; fallos={fallos_borde}")
        tmin = min(dt.datetime.fromisoformat(f["retrieved_at"]) for f in fuentes)
        tmax = max(dt.datetime.fromisoformat(f["retrieved_at"]) for f in fuentes)
        cortes = {"antes_de_la_primera_captura": ((tmin - dt.timedelta(microseconds=1)).isoformat(), 0),
                  "revision_independiente_2026_11_05": ("2026-11-05T23:59:59+00:00", 0),
                  "cierre_mes_2026_10": (cierre_mes("2026-10"), 0),
                  "ultima_captura": (tmax.isoformat(), total_celdas),
                  "cierre_mes_2026_11": (cierre_mes("2026-11"), total_celdas)}
        obs = {k: q1(f"SELECT count(*) FROM ({est_sub})", {"corte": v[0]}) for k, v in cortes.items()}
        c.check("estricto_cortes_alrededor_de_la_captura_real", all(obs[k] == v[1] for k, v in cortes.items()),
                {k: (cortes[k][0], obs[k]) for k in cortes})
        c.check("una_version_retrospectiva_por_componente_anio",
                q1("SELECT count(*) FROM snapshot_retrospectivo") == 17 and
                q1("SELECT count(*) FROM (SELECT component, source_year FROM snapshot_retrospectivo GROUP BY ALL HAVING count(*) > 1)") == 0,
                "panel y escenarios usan exactamente una versión por componente/año")
        con.execute("BEGIN")
        try:
            pid, mid = con.execute("SELECT product_id, market_id FROM product, market LIMIT 1").fetchone()
            for sid, fecha, kg in [("fixture_old", "2024-02-10T00:00:00+00:00", 100), ("fixture_new", "2024-03-10T00:00:00+00:00", 200)]:
                con.execute("INSERT INTO source_snapshot VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                            [sid, "abastecimiento", 2024, "synthetic://prueba", (sid[-3:] * 22)[:64].ljust(64, "0"), fecha, "fixture", 1,
                             None, "fixture", "prueba", "f" * 64, "prueba", False])
                con.execute("INSERT INTO supply_month VALUES (?,?,?,?,?,?,?,?,?)", [pid, mid, "2024-01", 2024 * 12, sid, kg, 1, None, fecha])
            early = con.execute(f"SELECT valor FROM ({estricta.rstrip().rstrip(';')}) WHERE componente='abastecimiento'", {"corte": "2024-02-29T00:00:00+00:00"}).fetchall()
            later = con.execute(f"SELECT valor FROM ({estricta.rstrip().rstrip(';')}) WHERE componente='abastecimiento'", {"corte": "2024-03-31T00:00:00+00:00"}).fetchall()
            c.check("revision_posterior_no_visible_antes", early == [(100.0,)] and later == [(200.0,)], f"antes={early}; despues={later}")
            esc_n = len(con.execute(sql("consulta_escenario.sql"), {"escenario": "retro_r1", "origen": "2024-12"}).fetchall())
            fix_n = q1(f"SELECT count(*) FROM ({sql('consulta_escenario.sql').rstrip().rstrip(';')}) WHERE snapshot_id LIKE 'fixture%'",
                       {"escenario": "retro_r1", "origen": "2024-12"})
            c.check("escenario_ignora_versiones_no_vigentes", fix_n == 0, f"filas_escenario={esc_n}; filas_fixture={fix_n}")
        finally:
            con.execute("ROLLBACK")
        c.check("sin_filas_de_prueba_retenidas", q1("SELECT count(*) FROM source_snapshot WHERE snapshot_id LIKE 'fixture%'") == 0)
        esc = sql("consulta_escenario.sql")
        violaciones, total_q = 0, 0
        for e in pol["escenarios"]:
            for y in range(2018, 2026):
                for mth in range(1, 13):
                    origen = f"{y}-{mth:02d}"
                    oidx = y * 12 + mth - 1
                    df = con.execute(esc, {"escenario": e["escenario_id"], "origen": origen}).df()
                    total_q += 1
                    lim = df.componente.map({"precio": e["retraso_precio_meses"], "abastecimiento": e["retraso_abastecimiento_meses"]})
                    idx = df.month.str[:4].astype(int) * 12 + df.month.str[5:7].astype(int) - 1
                    violaciones += int((idx > oidx - lim).sum()) + int((df.base != "supuesto").sum())
                    if origen == "2023-07" and e["escenario_id"] == "retro_r1":
                        c.check("escenario_r1_corte_2023_07_maximos", df[df.componente == "precio"].month.max() == "2023-06" and
                                df[df.componente == "abastecimiento"].month.max() == "2023-06")
        c.check("escenarios_sin_informacion_futura", violaciones == 0, f"{total_q} cortes x escenario evaluados; violaciones={violaciones}")
        et = con.execute(sql("etiquetas_disponibles.sql"), {"escenario": "retro_r1", "origen": "2023-07", "h": 1}).df()
        c.check("etiquetas_entrenamiento_respetan_retraso", et.mes_objetivo.max() == "2023-06" and
                (et.ultimo_mes_precio_variables_idx <= et.mes_objetivo_idx - 2).all(), f"max_etiqueta={et.mes_objetivo.max()}")
    finally:
        con.close()
    # 9. Lector y contratos de esquema/fecha.
    c.check("fecha_texto_dia_primero", parse_date("02/01/20") == "2020-01-02")
    c.check("fecha_serial_excel", parse_date("43832") == "2020-01-02")
    try:
        parse_date("desconocida")
        ok = False
    except (ValueError, AssertionError):
        ok = True
    c.check("fecha_desconocida_rechazada", ok)
    try:
        validate_schema("precios", 2025, {"A": "Fecha", "B": "DESCONOCIDA"})
        ok = False
    except ValueError:
        ok = True
    c.check("esquema_no_aprobado_rechazado", ok)
    return c.informe()
