"""Normalización completa de un XLSX anual a Parquet (detalle fila a fila) más los
perfiles heredados de la viabilidad.

- No se deduplica ningún registro. Filas idénticas de abastecimiento NO son viajes duplicados demostrados.
- Cada fila conserva su linaje técnico (sha256 de la fuente, hoja, fila) y el valor textual original.
- Los CSV `datos.csv`, `esquemas.csv`, `notas.csv`, `incidencias.csv`, `repeticiones_ejemplos.csv` y
  `dias_mercado.csv` se generan con la misma lógica de `03_perfilar.py` (viabilidad) para poder comparar
  sus SHA-256 con los aprobados en esa fase.
- La escritura ocurre en un directorio temporal; solo un directorio completo, con marcador COMPLETO.json,
  se considera reutilizable.
"""
from __future__ import annotations

import csv
import datetime
import hashlib
import json
import math
import os
import re
import shutil
import time
from collections import Counter
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from .util import ROOT, punto_fallo, punto_pausa, raw_dir, sha256_file, write_json_atomic
from .xlsx_stream import Xlsx

LOTE_PARQUET = 250_000
PADRE: int | None = None  # pid del proceso que lanzó al trabajador (lo fija lote._tarea_normalizar)


def comprobar_padre() -> None:
    """Un trabajador cuyo proceso padre murió deja de escribir: se aborta y se borra su temporal."""
    if PADRE is not None and os.getppid() != PADRE:
        raise RuntimeError(f"Proceso padre {PADRE} terminado; el trabajador {os.getpid()} aborta sin publicar")

ESQUEMA_PRECIOS = pa.schema([
    ("source_sha256", pa.string()), ("source_sheet", pa.string()), ("source_row", pa.int32()),
    ("date", pa.date32()), ("month", pa.string()), ("year", pa.int16()),
    ("grupo", pa.string()), ("producto", pa.string()), ("mercado", pa.string()),
    ("raw_cpc", pa.string()), ("precio_raw", pa.string()), ("precio", pa.float64()),
])
ESQUEMA_ABASTECIMIENTO = pa.schema([
    ("source_sha256", pa.string()), ("source_sheet", pa.string()), ("source_row", pa.int32()),
    ("date", pa.date32()), ("month", pa.string()), ("year", pa.int16()),
    ("mercado", pa.string()), ("cod_depto_proc", pa.string()), ("cod_municipio_proc", pa.string()),
    ("depto_proc", pa.string()), ("municipio_proc", pa.string()), ("grupo", pa.string()),
    ("raw_cpc", pa.string()), ("producto", pa.string()), ("kg_raw", pa.string()), ("kg", pa.float64()),
])
# Encabezados alternativos aprobados por función (cambio de esquema 2024).
ROLES_ABASTECIMIENTO = {
    "cod_depto_proc": ["Código Departamento", "Divipola Depto Proc."],
    "cod_municipio_proc": ["Código Municipio", "Divipola Municipio / ISO 3166-1 País Proc."],
    "depto_proc": ["Departamento Proc."],
    "municipio_proc": ["Municipio Proc.", "Municipio de Colombia / País Proc."],
}


def parse_date(ds: str) -> str:
    """Igual que en viabilidad: DD/MM/YY textual (2020) o serial Excel; cualquier otra cosa falla."""
    if re.fullmatch(r"\d{2}/\d{2}/\d{2}", ds):
        return datetime.datetime.strptime(ds, "%d/%m/%y").date().isoformat()
    f = float(ds)
    assert 40000 <= f <= 50000 and f == int(f)
    return (datetime.date(1899, 12, 30) + datetime.timedelta(days=int(f))).isoformat()


def validate_schema(kind: str, year: int, columns: dict) -> None:
    approved = json.loads((ROOT / "config/esquemas_aprobados.json").read_text())
    observed = {k: v.strip() for k, v in columns.items()}
    if observed not in approved.get(kind, {}).get(str(year), []):
        raise ValueError(f"Unapproved schema: {kind} {year}")


def writecsv(path: Path, rows, fields=None) -> None:
    rows = list(rows)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields or list(rows[0]) if rows else fields or ["empty"])
        w.writeheader()
        w.writerows(rows)


class _ParquetSink:
    def __init__(self, path: Path, schema: pa.Schema):
        self.schema = schema
        self.names = schema.names
        self.buf = {n: [] for n in self.names}
        self.n = 0
        self.total = 0
        self.writer = pq.ParquetWriter(str(path), schema, compression="zstd", compression_level=3,
                                       use_dictionary=True, write_statistics=True)

    def add(self, row: tuple) -> None:
        for n, v in zip(self.names, row):
            self.buf[n].append(v)
        self.n += 1
        if self.n >= LOTE_PARQUET:
            self.flush()

    def flush(self) -> None:
        if self.n:
            tbl = pa.Table.from_pydict(self.buf, schema=self.schema)
            self.writer.write_table(tbl, row_group_size=LOTE_PARQUET)
            self.total += self.n
            self.buf = {n: [] for n in self.names}
            self.n = 0

    def close(self) -> None:
        self.flush()
        self.writer.close()


def normalizar_archivo(kind: str, year: int, destino: Path, expected_sha: str) -> dict:
    """Lee un archivo completo y escribe sus salidas en `destino` (debe no existir).
    Devuelve el perfil. Falla ante huella distinta, esquema no aprobado, fecha no interpretable u hoja vacía."""
    start = time.monotonic()
    path = raw_dir() / kind / f"{year}.xlsx"
    meta = json.loads(path.with_suffix(".json").read_text())
    real = sha256_file(path)
    if real != expected_sha or meta["sha256"] != expected_sha:
        raise ValueError(f"Source hash mismatch: {kind} {year}")
    destino.mkdir(parents=True)
    sink = _ParquetSink(destino / "detalle.parquet", ESQUEMA_PRECIOS if kind == "precios" else ESQUEMA_ABASTECIMIENTO)
    x = Xlsx(path)
    rowsout, notes, schemas, errors, duplicates = [], [], [], [], []
    dates: dict[str, str] = {}
    dobj: dict[str, datetime.date] = {}
    counts, markets, products, monthcounts, daily = Counter(), Counter(), Counter(), Counter(), Counter()
    seen = set()
    dups = 0
    min_date, max_date = "9999", "0000"
    agg: dict = {}
    raw_decimals = Counter()
    try:
        for sn, target in x.sheets:
            header = None
            n = 0
            sheet_data = False
            roles = {}
            for rn, v in x.rows(target):
                if not v:
                    continue
                if "Fecha" in v.values() and (("Producto" in v.values()) if kind == "precios" else ("Alimento" in v.values())):
                    validate_schema(kind, year, v)
                    header = {value.strip(): col for col, value in v.items()}
                    sheet_data = True
                    schemas.append({"source": kind, "year": year, "sheet": sn, "header_row": rn,
                                    "columns": json.dumps(v, ensure_ascii=False)})
                    if kind != "precios":
                        roles = {}
                        for role, names in ROLES_ABASTECIMIENTO.items():
                            cols = [header[nm] for nm in names if nm in header]
                            if len(cols) != 1:
                                raise ValueError(f"Ambiguous/missing role {role}: {kind} {year} {sn}")
                            roles[role] = cols[0]
                    continue
                if header is None:
                    if not ("CPC" in sn or "Correlativa" in sn):
                        notes.append({"source": kind, "year": year, "sheet": sn, "row": rn, "text": " | ".join(v.values())})
                    continue
                dc = header["Fecha"]
                ds = v.get(dc, "")
                try:
                    if ds not in dates:
                        dates[ds] = parse_date(ds)
                        dobj[ds] = datetime.date.fromisoformat(dates[ds])
                    date = dates[ds]
                except (ValueError, AssertionError, OverflowError):
                    if len(v) > 2 and any(v.get(c, "") for c in header.values() if c != dc):
                        raise ValueError(f"Unparsed data row: {kind} {year} {sn} row {rn}, date={ds!r}")
                    notes.append({"source": kind, "year": year, "sheet": sn, "row": rn, "text": " | ".join(v.values())})
                    continue
                n += 1
                counts["rows"] += 1
                if counts["rows"] == 50_000:
                    punto_fallo(f"normalizar:{kind}:{year}")
                    punto_pausa(f"normalizar:{kind}:{year}")
                if counts["rows"] % 100_000 == 0:
                    comprobar_padre()
                month = date[:7]
                if not date.startswith(str(year)):
                    counts["wrong_year"] += 1
                min_date = min(min_date, date)
                max_date = max(max_date, date)
                if kind == "precios":
                    market = v.get(header.get("Mercado", header.get("Fuente")), "")
                    product = v.get(header["Producto"], "")
                    group = v.get(header["Grupo"], "")
                    valcol = next(c for h, c in header.items() if h.startswith("Precio"))
                else:
                    market = v.get("A", "")
                    product = v.get(header["Alimento"], "")
                    group = v.get(header["Grupo"], "")
                    valcol = header["Cant Kg"]
                rawvalue = v.get(valcol, "")
                cpc = v.get(header.get("Código CPC", ""), "")
                try:
                    value = float(rawvalue)
                    assert math.isfinite(value)
                except (ValueError, AssertionError):
                    counts["invalid_value"] += 1
                    value = None
                    errors.append({"source": kind, "year": year, "sheet": sn, "row": rn, "issue": "invalid_value", "raw": rawvalue})
                if value is not None and value <= 0:
                    counts["nonpositive_value"] += 1
                if not market or not product:
                    counts["missing_key"] += 1
                counts["cpc_present"] += bool(cpc)
                markets[market] += 1
                products[product] += 1
                monthcounts[month] += 1
                daily[(market, date)] += 1
                dec = len(rawvalue.split(".", 1)[1]) if "." in rawvalue and "e" not in rawvalue.lower() else (99 if "e" in rawvalue.lower() else 0)
                raw_decimals[dec] += 1
                record = "\x1f".join(v.get(c, "") for c in header.values())
                rh = hashlib.sha256(record.encode()).digest()[:16]
                if rh in seen:
                    dups += 1
                    if len(duplicates) < 20:
                        duplicates.append({"source": kind, "year": year, "sheet": sn, "row": rn, "market": market, "product": product,
                                           "date": date, "reason": "identical_observed_fields_not_proof_of_duplicate_ingress"})
                seen.add(rh)
                if kind == "precios":
                    rowsout.append({"year": year, "month": month, "date": date, "group": group, "product": product, "market": market,
                                    "price": value, "raw_cpc": cpc, "source_file": meta["local_path"], "source_sha256": meta["sha256"],
                                    "source_sheet": sn, "source_row": rn})
                    sink.add((expected_sha, sn, rn, dobj[ds], month, year, group, product, market, cpc or None, rawvalue, value))
                else:
                    key = (month, market, product, group, cpc)
                    if key not in agg:
                        agg[key] = [0.0, 0, 0, 0, set(), set()]
                    a = agg[key]
                    a[0] += value if value is not None else 0
                    a[1] += 1
                    a[2] += value is None
                    a[3] += int(value is not None and value <= 0)
                    a[4].add(date)
                    a[5].add(sn)
                    sink.add((expected_sha, sn, rn, dobj[ds], month, year, market, v.get(roles["cod_depto_proc"]),
                              v.get(roles["cod_municipio_proc"]), v.get(roles["depto_proc"]), v.get(roles["municipio_proc"]),
                              group, cpc or None, product, rawvalue, value))
            if sheet_data:
                assert n > 0, f"Empty data sheet {kind} {year} {sn}"
                print(kind, year, sn, n, flush=True)
        sink.close()
    finally:
        x.close()
    assert schemas and counts["rows"] > 0, f"No recognized data in {kind} {year}"
    if sink.total != counts["rows"]:
        raise AssertionError(f"Parquet rows {sink.total} != source rows {counts['rows']}")
    out = destino
    if kind != "precios":
        rowsout = [{"year": year, "month": k[0], "market": k[1], "product": k[2], "group": k[3], "raw_cpc": k[4],
                    "kg": round(a[0], 6) if a[2] == 0 else None, "source_rows": a[1], "invalid_value_rows": a[2],
                    "nonpositive_rows": a[3], "observed_days": len(a[4]), "source_file": meta["local_path"],
                    "source_sha256": meta["sha256"], "source_sheets": ";".join(sorted(a[5]))} for k, a in sorted(agg.items())]
    writecsv(out / "datos.csv", rowsout)
    writecsv(out / "esquemas.csv", schemas)
    writecsv(out / "incidencias.csv", errors, ["source", "year", "sheet", "row", "issue", "raw"])
    writecsv(out / "notas.csv", notes, ["source", "year", "sheet", "row", "text"])
    writecsv(out / "repeticiones_ejemplos.csv", duplicates, ["source", "year", "sheet", "row", "market", "product", "date", "reason"])
    writecsv(out / "dias_mercado.csv", ({"market": k[0], "date": k[1], "rows": c} for k, c in sorted(daily.items())))
    report = {"source": kind, "year": year, "counts": dict(counts), "identical_row_occurrences_after_first": dups,
              "unique_observed_row_signatures": len(seen), "markets": dict(markets), "products": dict(products),
              "monthly_source_rows": dict(sorted(monthcounts.items())), "min_date": min_date, "max_date": max_date,
              "schemas": len(schemas), "output_rows": len(rowsout), "nondata_incidents": len(errors),
              "source_sha256": meta["sha256"], "data_sha256": sha256_file(out / "datos.csv"),
              "parquet_rows": sink.total, "raw_value_decimal_places": {str(k): v for k, v in sorted(raw_decimals.items())},
              "duration_seconds": round(time.monotonic() - start, 2)}
    (out / "perfil.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    return report


def marcador_valido(d: Path) -> bool:
    m = d / "COMPLETO.json"
    if not m.exists():
        return False
    try:
        info = json.loads(m.read_text())
        return all(sha256_file(d / f) == h for f, h in info["archivos"].items())
    except Exception:
        return False


def normalizar_en_cache(kind: str, year: int, expected_sha: str, cache_root: Path, clave_codigo: str, run_id: str) -> dict:
    """Normaliza en un temporal y lo promueve a la caché solo si termina completo.
    La caché está direccionada por (huella de fuente, huella del normalizador)."""
    final = cache_root / f"{kind}_{year}_{expected_sha[:16]}_{clave_codigo[:16]}"
    if final.exists() and marcador_valido(final):
        return {"kind": kind, "year": year, "dir": str(final), "reutilizado": True}
    if final.exists():  # Incompleto o alterado: nunca se reutiliza.
        shutil.rmtree(final)
    tmp = cache_root / f".tmp-{final.name}-{run_id}-{os.getpid()}"
    if tmp.exists():
        shutil.rmtree(tmp)
    try:
        report = normalizar_archivo(kind, year, tmp, expected_sha)
        archivos = {p.name: sha256_file(p) for p in sorted(tmp.iterdir()) if p.is_file()}
        write_json_atomic(tmp / "COMPLETO.json", {"kind": kind, "year": year, "source_sha256": expected_sha,
                                                  "clave_normalizador": clave_codigo, "run_id": run_id,
                                                  "parquet_rows": report["parquet_rows"], "archivos": archivos})
        for p in tmp.iterdir():
            p.chmod(0o444)
        os.rename(tmp, final)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    return {"kind": kind, "year": year, "dir": str(final), "reutilizado": False, "segundos": report["duration_seconds"]}
