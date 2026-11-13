"""Reconstruye localmente las tres referencias de regresión de la viabilidad que no se distribuyen públicamente
(contienen series del DANE) y exige sus huellas APROBADAS FIJAS antes de escribirlas en config/.

  config/referencia_panel_viabilidad.csv          (= tablas/panel_auditado.csv de la viabilidad)
  config/referencia_candidatos_viabilidad.csv     (= tablas/candidatos_elegibles.csv)
  config/referencia_conciliacion_viabilidad.csv   (= tablas/conciliacion_totales_dane.csv)

Procedimiento:
1. Verifica las 17 fuentes y sus metadatos de captura (sipsa.lote.verificar_fuentes).
2. Normaliza los 16 XLSX anuales en la caché del proyecto (la misma que reutiliza `sipsa.sh construir`).
3. Exige que cada perfil `datos.csv` tenga el SHA-256 aprobado en la viabilidad (config/referencia_viabilidad.json).
4. Aplica la lógica original de la viabilidad (`codigo/04_evaluar.py`, pandas; reproducida aquí sin cambios en las
   partes que generan estas tablas). Es un camino de código distinto del constructor DuckDB.
5. Exige que cada tabla tenga el SHA-256 aprobado (`tablas` en referencia_viabilidad.json). Si alguna difiere, no
   escribe nada y termina con código 1.
Las referencias no se generan desde las tablas que después se comparan: el constructor DuckDB compara su panel
con estas referencias, cuyas huellas están fijadas desde la fase de viabilidad.

Uso (desde engineering/): .venv/bin/python herramientas/reconstruir_referencias.py [--trabajadores 3]
Fuente: Departamento Administrativo Nacional de Estadística: www.dane.gov.co
"""
import argparse
import datetime
import hashlib
import json
import multiprocessing
import os
import secrets
import sys
import tempfile
import unicodedata
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
from sipsa import lote  # noqa: E402
from sipsa.util import datos_dir, huella_normalizador, raw_dir  # noqa: E402
from sipsa.xlsx_stream import Xlsx  # noqa: E402

sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
DESTINOS = {"panel_auditado.csv": "referencia_panel_viabilidad.csv", "candidatos_elegibles.csv": "referencia_candidatos_viabilidad.csv",
            "conciliacion_totales_dane.csv": "referencia_conciliacion_viabilidad.csv"}


def groupkey(s):
    return ''.join(c for c in unicodedata.normalize('NFKD', s.upper()) if not unicodedata.combining(c))


def tablas_viabilidad(perfiles: dict, out: Path) -> None:
    """Partes de 04_evaluar.py (viabilidad) que producen panel, candidatos y conciliación. Sin cambios de lógica."""
    cfg = json.loads((RAIZ / 'config/heredado_viabilidad/alcance.json').read_text()); markets = cfg['markets']
    allp = pd.concat([pd.read_csv(perfiles[('precios', y)] / 'datos.csv', dtype={'raw_cpc': str}) for y in cfg['years']], ignore_index=True)
    alls = pd.concat([pd.read_csv(perfiles[('abastecimiento', y)] / 'datos.csv', dtype={'raw_cpc': str}) for y in cfg['years']], ignore_index=True)
    allp['group_key'] = allp['group'].map(groupkey); alls['group_key'] = alls['group'].map(groupkey)
    p = allp[allp.market.isin(markets) & allp.group_key.isin(cfg['groups'])].copy()
    s = alls[alls.market.isin(markets) & alls.group_key.isin(cfg['groups'])].copy()
    assert not p.duplicated(['month', 'market', 'product']).any(), 'Candidate fresh-price keys duplicated'
    sm = s.groupby(['month', 'market', 'product'], as_index=False).agg(kg=('kg', lambda a: a.sum(min_count=len(a))), source_rows=('source_rows', 'sum'), invalid_value_rows=('invalid_value_rows', 'sum'), nonpositive_rows=('nonpositive_rows', 'sum'))
    assert not sm.duplicated(['month', 'market', 'product']).any()
    pt = p[p.month <= cfg['selection_training_end']]; st = sm[sm.month <= cfg['selection_training_end']]
    joint = pt[['month', 'market', 'product']].merge(st, on=['month', 'market', 'product'], how='inner', validate='one_to_one')
    products = sorted(set(pt['product']) | set(st['product']))
    records = []
    for product in products:
        for market in markets:
            a = pt[(pt['product'] == product) & (pt.market == market)]; b = st[(st['product'] == product) & (st.market == market)]; j = joint[(joint['product'] == product) & (joint.market == market)]
            records.append({'product': product, 'market': market, 'price_training_months': a.month.nunique(), 'supply_training_months': b.month.nunique(), 'joint_training_months': j.month.nunique(), 'supply_training_kg': b.kg.sum() if len(b) else None})
    cov = pd.DataFrame(records)
    eligible = cov.groupby('product', as_index=False).agg(min_price_months=('price_training_months', 'min'), min_supply_months=('supply_training_months', 'min'), min_joint_months=('joint_training_months', 'min'), training_kg=('supply_training_kg', 'sum'))
    eligible = eligible[eligible.min_joint_months >= cfg['min_training_months_each_market_each_source']]
    groups = pt.groupby('product').group_key.agg(lambda a: sorted(set(a)))
    assert all(len(groups.get(prod, [])) == 1 for prod in eligible['product'])
    eligible['group'] = eligible['product'].map(lambda prod: groups[prod][0])
    eligible = eligible.sort_values(['min_joint_months', 'training_kg', 'product'], ascending=[False, False, True])
    eligible.to_csv(out / 'candidatos_elegibles.csv', index=False)
    quotas = cfg['basket_quotas']
    chosen = pd.concat([eligible[eligible['group'] == g].head(n) for g, n in quotas.items()], ignore_index=True)
    assert len(chosen) == 10
    names = chosen['product'].tolist()
    grid = pd.MultiIndex.from_product([pd.period_range('2018-01', '2025-12', freq='M').astype(str), markets, names], names=['month', 'market', 'product']).to_frame(index=False)
    panel = grid.merge(p[p['product'].isin(names)], how='left', on=['month', 'market', 'product'], validate='one_to_one').merge(sm, how='left', on=['month', 'market', 'product'], validate='one_to_one')
    assert len(panel) == 2880
    panel['price_present'] = panel.price.notna(); panel['supply_present'] = panel.kg.notna()
    panel['historical_available_at'] = None; panel['vintage_status'] = 'current_snapshot'
    notices = pd.read_csv(RAIZ / 'config/heredado_viabilidad/avisos_imputacion.csv')
    assert not notices.duplicated(['month', 'market']).any()
    notice_keys = set(zip(notices.month, notices.market))
    panel['source_month_has_imputation_notice'] = [(m, k) in notice_keys for m, k in zip(panel.month, panel.market)]
    panel.to_csv(out / 'panel_auditado.csv', index=False)
    x = Xlsx(raw_dir() / 'historico_abastecimiento.xlsx'); monthly = next(t for sn, t in x.sheets if 'Serie mensual' in sn)
    official = []; header = {}
    for rn, v in x.rows(monthly):
        if v.get('A') == 'Fecha': header = {val: col for col, val in v.items()}; continue
        if not header: continue
        try: date = (datetime.date(1899, 12, 30) + datetime.timedelta(days=int(float(v.get('A', ''))))).isoformat()[:7]
        except (ValueError, OverflowError): continue
        if '2018-01' <= date <= '2025-12':
            for m in markets: official.append({'month': date, 'market': m, 'official_tonnes': float(v[header[m]]), 'source_row': rn})
    x.close()
    totals = alls[alls.market.isin(markets)].groupby(['month', 'market'], as_index=False).kg.sum(min_count=1).rename(columns={'kg': 'microdata_kg'})
    rec = pd.DataFrame(official).merge(totals, on=['month', 'market'], how='outer', validate='one_to_one')
    rec['difference_kg'] = rec.microdata_kg - rec.official_tonnes * 1000
    rec['relative_difference'] = rec.difference_kg / (rec.official_tonnes * 1000)
    rec['within_1kg'] = rec.difference_kg.abs() <= 1
    rec.to_csv(out / 'conciliacion_totales_dane.csv', index=False)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trabajadores", type=int, default=3)
    a = ap.parse_args()
    ref = json.loads((RAIZ / "config/referencia_viabilidad.json").read_text())
    fuentes = lote.verificar_fuentes()
    d = datos_dir()
    (d / "cache/normalizado").mkdir(parents=True, exist_ok=True)
    run_id = "referencias-" + secrets.token_hex(3)
    bloqueo = lote.Bloqueo(d, run_id)
    bloqueo.tomar()
    try:
        clave = huella_normalizador()
        env = {k: v for k, v in os.environ.items() if k.startswith("SIPSA_")}
        anuales = sorted([f for f in fuentes if f["year"]], key=lambda f: (-f["bytes"], f["tipo"], f["year"]))
        perfiles = {}
        with ProcessPoolExecutor(max_workers=a.trabajadores, mp_context=multiprocessing.get_context("spawn")) as pool:
            futs = [pool.submit(lote._tarea_normalizar, (f["tipo"], f["year"], f["sha256"], str(d / "cache/normalizado"), clave, run_id, env,
                                                         os.getpid(), str(bloqueo.trab))) for f in anuales]
            for fu in as_completed(futs):
                r = fu.result()
                perfiles[(r["kind"], r["year"])] = Path(r["dir"])
                print("NORMALIZADO", r["kind"], r["year"], "reutilizado" if r["reutilizado"] else "leído", flush=True)
        malos = [f"{k}_{y}" for (k, y), p in perfiles.items() if sha(p / "datos.csv") != ref["perfiles"][f"{k}_{y}"]["data_sha256"]]
        if malos:
            raise SystemExit(f"Perfiles distintos de los aprobados en la viabilidad: {malos}")
        with tempfile.TemporaryDirectory(prefix="sipsa-referencias-") as tmp:
            t = Path(tmp)
            tablas_viabilidad(perfiles, t)
            resultado = {n: (sha(t / n), ref["tablas"][n]) for n in DESTINOS}
            malas = {n: v for n, v in resultado.items() if v[0] != v[1]}
            if malas:
                raise SystemExit(f"Referencias reconstruidas con huella distinta de la aprobada (no se escriben): {malas}")
            for n, destino in DESTINOS.items():
                (RAIZ / "config" / destino).write_bytes((t / n).read_bytes())
                print(f"OK   config/{destino:42s} SHA-256 aprobado {resultado[n][1][:16]}…")
    finally:
        bloqueo.soltar()
    print("Referencias reconstruidas y verificadas contra las huellas aprobadas de la viabilidad.")


if __name__ == "__main__":
    main()
