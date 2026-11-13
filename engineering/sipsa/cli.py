"""Interfaz de línea de comandos.

  python -m sipsa construir [--sin-cache] [--trabajadores N]
  python -m sipsa estado
  python -m sipsa verificar [--rapido]
  python -m sipsa fuentes
  python -m sipsa revertir <lote_id>
  python -m sipsa consultar --escenario retro_r1 --origen 2023-07 [--salida archivo.csv]
  python -m sipsa estricto --corte 2025-12-31T23:59:59+00:00 | --mes 2025-12
  python -m sipsa conciliar

Códigos de salida de `construir` y `revertir`:
  0  publicado y registrado
  1  fallo ANTES del punto de confirmación: APROBADO.json no cambió
  3  rechazado: otra ejecución (o trabajadores huérfanos) tiene el bloqueo
  4  publicado (APROBADO.json YA apunta al lote nuevo) pero el registro quedó pendiente: ejecute `conciliar`
     (v2.1: incluye el fallo del evento final; y por defensa, cualquier error si la huella del puntero cambió)
Un fallo que solo afecta a la ficha diagnóstica del bloqueo tras una operación exitosa se informa como
ADVERTENCIA (código 0; el bloqueo sí se liberó). Si hay otra excepción en curso, se añade como NOTA sin ocultarla.
"""
from __future__ import annotations

import argparse
import json
import sys

from . import lote


def _abrir_aprobado():
    from .construir import conectar
    from .util import datos_dir
    # Verifica con SHA-256 todo lo que lee la consulta (sipsa.duckdb, tablas, metadatos); el detalle Parquet
    # solo por tamaño. `sipsa verificar` comprueba el lote completo.
    v = lote.verificar_aprobado(completo=True, sin_hash_prefijos=("detalle/",))
    if not v["ok"]:
        raise SystemExit(f"Lote aprobado no íntegro: {v['errores'][:5]}")
    ap = lote.aprobado()
    return conectar(datos_dir() / ap["ruta"] / "sipsa.duckdb", read_only=True), ap


def _huella_puntero() -> str | None:
    from .util import datos_dir, sha256_file
    p = datos_dir() / "APROBADO.json"
    try:
        return sha256_file(p) if p.exists() else None
    except OSError:
        return None


def _notas(ex: BaseException) -> None:
    for n in getattr(ex, "__notes__", []):
        print("NOTA:", n, file=sys.stderr)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="sipsa")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("construir")
    c.add_argument("--sin-cache", action="store_true")
    c.add_argument("--trabajadores", type=int)
    sub.add_parser("estado")
    sub.add_parser("conciliar")
    v = sub.add_parser("verificar")
    v.add_argument("--rapido", action="store_true", help="solo tamaños, sin recalcular SHA-256")
    sub.add_parser("fuentes")
    r = sub.add_parser("revertir")
    r.add_argument("lote_id")
    q = sub.add_parser("consultar")
    q.add_argument("--escenario", required=True)
    q.add_argument("--origen", required=True)
    q.add_argument("--salida")
    e = sub.add_parser("estricto")
    g = e.add_mutually_exclusive_group(required=True)
    g.add_argument("--corte", help="instante ISO 8601 con desfase")
    g.add_argument("--mes", help="YYYY-MM: cierre del mes calendario en hora de Colombia")
    a = ap.parse_args(argv)

    if a.cmd in ("construir", "revertir"):
        antes = _huella_puntero()
        try:
            res = (lote.construir(sin_cache=a.sin_cache, trabajadores=a.trabajadores) if a.cmd == "construir"
                   else lote.revertir(a.lote_id))
        except lote.EjecucionEnCurso as ex:
            print("RECHAZADA:", ex, file=sys.stderr)
            _notas(ex)
            sys.exit(lote.SALIDA_OCUPADO)
        except lote.PublicacionConRegistroPendiente as ex:
            print("PUBLICADA_REGISTRO_PENDIENTE:", ex, file=sys.stderr)
            _notas(ex)
            print(json.dumps(ex.puntero, ensure_ascii=False, indent=2))
            sys.exit(lote.SALIDA_REGISTRO_PENDIENTE)
        except Exception as ex:
            despues = _huella_puntero()
            if despues != antes:
                # Defensa v2.1: si el puntero cambió, nunca se informa "sin cambios" (no se revierte en silencio).
                print(f"PUBLICADA_REGISTRO_PENDIENTE (el puntero cambió durante la operación; error posterior "
                      f"{type(ex).__name__}: {ex}). Ejecute `sipsa conciliar`.", file=sys.stderr)
                _notas(ex)
                sys.exit(lote.SALIDA_REGISTRO_PENDIENTE)
            print("FALLIDA antes de confirmar; APROBADO.json sin cambios (huella comprobada):", type(ex).__name__, ex, file=sys.stderr)
            _notas(ex)
            sys.exit(lote.SALIDA_FALLIDA)
        for adv in res.get("advertencias", []):
            print("ADVERTENCIA:", adv, file=sys.stderr)
        print(json.dumps(res, ensure_ascii=False, indent=2))
    elif a.cmd == "conciliar":
        try:
            r = lote.conciliar()
            for adv in r.get("advertencias", []):
                print("ADVERTENCIA:", adv, file=sys.stderr)
            print(json.dumps(r, ensure_ascii=False, indent=2))
        except lote.EjecucionEnCurso as ex:
            print("RECHAZADA:", ex, file=sys.stderr)
            sys.exit(lote.SALIDA_OCUPADO)
    elif a.cmd == "estado":
        print(json.dumps(lote.resumen_estado(), ensure_ascii=False, indent=2))
    elif a.cmd == "verificar":
        res = lote.verificar_aprobado(completo=not a.rapido)
        print(json.dumps(res, ensure_ascii=False, indent=2))
        sys.exit(0 if res["ok"] else 1)
    elif a.cmd == "fuentes":
        try:
            fu = lote.verificar_fuentes()
        except lote.ContratoFallido as ex:
            print("FALLIDA:", ex, file=sys.stderr)
            sys.exit(1)
        print(f"OK {len(fu)} fuentes con SHA-256 y tamaño aprobados")
    elif a.cmd in ("consultar", "estricto"):
        from .construir import sql
        con, apr = _abrir_aprobado()
        try:
            if a.cmd == "consultar":
                df = con.execute(sql("consulta_escenario.sql"), {"escenario": a.escenario, "origen": a.origen}).df()
            else:
                from .util import cierre_mes
                corte = a.corte or cierre_mes(a.mes)
                print(f"corte estricto: {corte}")
                df = con.execute(sql("consulta_asof_estricta.sql"), {"corte": corte}).df()
        finally:
            con.close()
        df.insert(0, "lote_id", apr["lote_id"])
        if getattr(a, "salida", None):
            df.to_csv(a.salida, index=False)
        print(f"{len(df)} filas del lote {apr['lote_id']}")
        if len(df):
            print(df.groupby("componente").month.agg(["min", "max", "count"]).to_string())


if __name__ == "__main__":
    main()
