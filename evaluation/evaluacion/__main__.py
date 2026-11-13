"""CLI: python -m evaluacion {congelar|ejecutar|controles|recalcular|figuras|verificar-publico|comparar-aprobado <dir>}"""
import json
import sys

cmd = sys.argv[1] if len(sys.argv) > 1 else ""
if cmd == "congelar":
    from .ejecutar import congelar
    print(json.dumps(congelar(), ensure_ascii=False, indent=2)[:1500])
elif cmd == "ejecutar":
    from .ejecutar import ejecutar
    print(json.dumps(ejecutar(), ensure_ascii=False, indent=2)[:1500])
elif cmd == "verificar-publico":
    from .publico import verificar_publico
    r = verificar_publico()
    for c in r["controles"]:
        print(c["resultado"], c["control"], c["detalle"][:200])
    print(f"RESUMEN VERIFICACIÓN PÚBLICA: {r['pasaron']} PASS, {r['fallaron']} FAIL, {r['no_ejecutados']} NO EJECUTADO (requieren reconstrucción local)")
    if r["fallaron"]:
        print("RECHAZADO:", " | ".join(f"{c['control']}: {c['detalle'][:200]}" for c in r["controles"] if c["resultado"] == "FAIL"), file=sys.stderr)
    sys.exit(1 if r["fallaron"] else 0)
elif cmd == "comparar-aprobado":
    from pathlib import Path
    from .publico import comparar_con_aprobado
    if len(sys.argv) < 3:
        raise SystemExit("uso: python -m evaluacion comparar-aprobado <carpeta evaluation/ de la entrega pública>")
    r = comparar_con_aprobado(Path(sys.argv[2]))
    for c in r["controles"]:
        print(c["resultado"], c["control"], c["detalle"][:200])
    print(f"RESUMEN COMPARACIÓN CON LO APROBADO: {r['pasaron']} PASS, {r['fallaron']} FAIL, {r['no_ejecutados']} NO EJECUTADO")
    sys.exit(1 if r["fallaron"] else (2 if r["no_ejecutados"] else 0))
elif cmd == "controles" and not __import__("pathlib").Path(__file__).resolve().parents[1].joinpath("resultados/predicciones.csv").exists():
    # Copia pública sin series del DANE: los controles completos requieren reconstrucción local.
    from .publico import verificar_publico
    r = verificar_publico()
    for c in r["controles"]:
        print(c["resultado"], c["control"], c["detalle"][:200])
    print(f"CONTROLES INCOMPLETOS: faltan resultados/predicciones.csv y predicciones_seleccion.csv (no se distribuyen). "
          f"{r['pasaron']} PASS, {r['fallaron']} FAIL, {r['no_ejecutados']} NO EJECUTADO. Reconstruya localmente (docs/reproduccion.md, modo B).", file=sys.stderr)
    sys.exit(1 if r["fallaron"] else 2)
elif cmd == "controles":
    from .controles import controles
    r = controles()
    for c in r["controles"]:
        print(c["resultado"], c["control"], c["detalle"][:200])
    print(f"RESUMEN: {r['pasaron']} PASS, {r['fallos_criticos']} fallos críticos")
    if r["fallos_criticos"]:
        print("RECHAZADO:", " | ".join(r["primeros_fallos"]), file=sys.stderr)
    sys.exit(1 if r["fallos_criticos"] else 0)
elif cmd == "recalcular":
    # Revisión de distribución v2 (enmienda recalcular-aprobacion): cualquier aprobación anterior se retira ANTES de
    # comprobar los insumos, de modo que ni la falta de datos (código 2), ni un fallo del recálculo (código 1), ni una
    # excepción la dejan vigente. Solo `controles` emite VALIDACION_VIGENTE.json, y solo si todo pasa.
    from pathlib import Path
    from .integridad import invalidar_aprobacion
    invalidar_aprobacion()
    if not Path(__file__).resolve().parents[1].joinpath("resultados/predicciones.csv").exists():
        print("NO EJECUTADO: requiere reconstrucción local. El recálculo parte de resultados/predicciones.csv, que contiene precios del DANE "
              "y no se distribuye. Use `verificar-publico` en esta copia o reconstruya (docs/reproduccion.md, modo B). "
              "Aprobación anterior retirada.", file=sys.stderr)
        sys.exit(2)
    from .recalcular import recalcular
    try:
        r = recalcular()
    except BaseException as e:
        invalidar_aprobacion()
        print(f"RECHAZADO: el recálculo no pudo completarse ({type(e).__name__}: {e}). Aprobación anterior retirada.", file=sys.stderr)
        sys.exit(1)
    print(json.dumps({k: r[k] for k in ("ok", "controles", "fallos", "detalle_fallos", "tolerancias", "cifras_recalculadas")}, ensure_ascii=False, indent=2))
    if not r["ok"]:
        invalidar_aprobacion()
        print("RECHAZADO: el recálculo no coincide con las tablas exportadas. Aprobación anterior retirada.", file=sys.stderr)
    else:
        print("Recálculo OK. Este comando no emite aprobación: ejecute `python -m evaluacion controles`.", file=sys.stderr)
    sys.exit(0 if r["ok"] else 1)
elif cmd == "figuras":
    from .figuras import figuras
    figuras()
else:
    raise SystemExit(__doc__)
