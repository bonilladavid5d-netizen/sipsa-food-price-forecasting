"""Pruebas de rechazo de la revisión v2, cada una en una COPIA aislada (los datos y resultados originales no se tocan).

Casos:
  1 integro            controles -> código 0 y VALIDACION_VIGENTE.json presente
  2 aporte_falso       mase_con_abast=0, mae_con_abast=0, delta_mase=-99 en todo aporte_abastecimiento.csv -> código 1
  3 fecha_2030         ultimo_mes_precio_usado=2030-01 en una predicción y en su fila de auditoría, cumple=True -> código 1
  4 codigo_300_a_1     n_estimators=300 -> 1 en nucleo.py sin aprobar: `ejecutar` debe fallar ANTES de estimar -> código != 0
  5a sin_modelo        se eliminan todas las filas de rf_abast_ctrl de predicciones.csv -> código 1 (cobertura)
  5b sin_escenario     se eliminan todas las filas de retro_r2 de predicciones.csv -> código 1 (cobertura)
  6a recalcular_integro      recalcular con datos íntegros -> código 0 y la aprobación sembrada se retira (solo controles la emite)
  6b recalcular_aporte_falso recalcular con aporte_abastecimiento.csv alterado -> código 1 y sin aprobación vigente
  6c recalcular_ilegible     recalcular sin la columna `predicho` en predicciones.csv (excepción) -> código 1 y sin aprobación
Copia pública (sin predicciones): P1c recalcular sin datos parte de una aprobación sembrada y debe terminar con código 2 y sin ella.
En los casos que fallan, la copia parte con una VALIDACION_VIGENTE.json de un control íntegro previo: debe desaparecer.
Uso: python herramientas/probar_rechazos.py <python_del_entorno> <proyecto_ingenieria> <carpeta_salida>
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parents[1]
PY, ING, OUT = sys.argv[1], sys.argv[2], Path(sys.argv[3])
OUT.mkdir(parents=True, exist_ok=True)
sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
VIG = "resultados/controles/VALIDACION_VIGENTE.json"


def huellas(raiz: Path) -> dict:
    return {str(p.relative_to(raiz)): sha(p) for p in sorted(raiz.rglob("*"))
            if p.is_file() and "__pycache__" not in p.parts and "evidencia_v2" not in p.parts and p.name != "VALIDACION_VIGENTE.json"
            and not p.name.startswith("controles_ejecucion")}


def correr(copia: Path, *args):
    env = {k: v for k, v in os.environ.items() if not k.startswith("SIPSA_")}
    env["SIPSA_PROYECTO_INGENIERIA"] = ING
    t0 = time.monotonic()
    r = subprocess.run([PY, "-B", "-m", "evaluacion", *args], cwd=copia, env=env, capture_output=True, text=True, timeout=1800)
    return r.returncode, r.stdout, r.stderr, round(time.monotonic() - t0, 1)


def caso(nombre, mutar, comando, debe_pasar, esperar_en_salida, preparar_vigente=True, rc_esperado=None, vigente_esperado=True):
    with tempfile.TemporaryDirectory(prefix=f"sipsa-v2-{nombre}-") as tmp:
        c = Path(tmp) / "proy"
        shutil.copytree(RAIZ, c, ignore=shutil.ignore_patterns("__pycache__", "evidencia_v2"))
        (c / VIG).unlink(missing_ok=True)  # estado inicial controlado: sin aprobación heredada de la carpeta copiada
        if preparar_vigente:
            (c / VIG).write_text(json.dumps({"vigente": True, "nota": "aprobación antigua sembrada por la prueba"}))
        vig_inicio = (c / VIG).exists()
        antes = huellas(c)
        detalle_mut = mutar(c) if mutar else "sin cambios"
        rc, out, err, s = correr(c, *comando)
        vig = (c / VIG).exists()
        fallos = [l for l in out.splitlines() if l.startswith("FAIL")]
        texto = out + err
        hallado = [e for e in esperar_en_salida if e in texto]
        despues_pred = sha(c / "resultados/predicciones.csv") if (c / "resultados/predicciones.csv").exists() else None
        if rc_esperado is not None:  # p. ej. controles o recalcular en la copia pública: código 2 (incompleto), nunca aprobado
            ok = rc == rc_esperado and not vig and vig_inicio == preparar_vigente and len(hallado) == len(esperar_en_salida)
        elif debe_pasar:
            ok = rc == 0 and vig == vigente_esperado and vig_inicio == preparar_vigente and len(hallado) == len(esperar_en_salida)
        else:
            ok = rc != 0 and not vig and vig_inicio == preparar_vigente and len(hallado) == len(esperar_en_salida)
        reg = {"caso": nombre, "mutacion": detalle_mut, "comando": "python -m evaluacion " + " ".join(comando), "codigo_salida": rc,
               "esperado": f"código {rc_esperado} (incompleto)" if rc_esperado is not None else ("pasa (0)" if debe_pasar else "rechaza (!=0)"), "resultado_prueba": "PASS" if ok else "FAIL",
               "aprobacion_sembrada_al_iniciar": vig_inicio, "aprobacion_vigente_al_terminar": vig, "mensajes_esperados_encontrados": hallado,
               "controles_fallidos": fallos[:12], "stderr": err.strip()[-800:], "segundos": s,
               "predicciones_sin_reestimar": despues_pred == antes.get("resultados/predicciones.csv") if nombre.startswith("4_codigo") else None}
        (OUT / f"{nombre}.log").write_text(f"$ {reg['comando']}\n[exit={rc}] ({s} s)\nmutación: {detalle_mut}\n"
                                           f"aprobación sembrada al iniciar: {vig_inicio}; vigente al terminar: {vig}; prueba: {reg['resultado_prueba']}\n--- stdout ---\n{out}\n--- stderr ---\n{err}\n")
        return reg


def m_aporte(c):
    p = c / "resultados/aporte_abastecimiento.csv"
    d = pd.read_csv(p, dtype={"anio": str})
    d["mase_con_abast"], d["mae_con_abast"], d["delta_mase"] = 0.0, 0.0, -99.0
    d.to_csv(p, index=False, float_format="%.10g")
    return f"{len(d)} filas: mase_con_abast=0, mae_con_abast=0, delta_mase=-99"


def m_fecha(c):
    pp, pa = c / "resultados/predicciones.csv", c / "resultados/auditoria_temporal.csv"
    d = pd.read_csv(pp, dtype={"origen": str, "objetivo": str, "mes_base": str})
    a = pd.read_csv(pa, dtype={"origen": str, "objetivo": str, "max_mes_base_B": str})
    d.loc[0, "ultimo_mes_precio_usado"] = "2030-01"
    d.to_csv(pp, index=False, float_format="%.10g")
    msk = (a.escenario == d.loc[0, "escenario"]) & (a.origen == d.loc[0, "origen"]) & (a.fase == "evaluacion")
    assert msk.sum() == 1
    a.loc[msk, "max_mes_precio_usado_pronostico"] = "2030-01"
    assert bool(a.loc[msk, "cumple"].iloc[0]) is True
    a.to_csv(pa, index=False)
    return f"fila 0 ({d.loc[0, 'modelo']}, {d.loc[0, 'escenario']}, origen {d.loc[0, 'origen']}) y su auditoría: 2030-01; cumple sigue True"


def m_codigo(c):
    p = c / "evaluacion/nucleo.py"
    s = p.read_text()
    assert "n_estimators=300" in s
    p.write_text(s.replace("n_estimators=300", "n_estimators=1"))
    return f"nucleo.py: n_estimators=300 -> 1 (SHA-256 {sha(p)[:12]}…, manifiesto sin cambiar)"


def m_quitar(col, valor):
    def f(c):
        p = c / "resultados/predicciones.csv"
        d = pd.read_csv(p, dtype={"origen": str, "objetivo": str, "mes_base": str})
        n = int((d[col] == valor).sum())
        d[d[col] != valor].to_csv(p, index=False, float_format="%.10g")
        return f"eliminadas {n} filas con {col}={valor}"
    return f


def m_quitar_columna(col):
    def f(c):
        p = c / "resultados/predicciones.csv"
        d = pd.read_csv(p, dtype={"origen": str, "objetivo": str, "mes_base": str})
        d.drop(columns=[col]).to_csv(p, index=False, float_format="%.10g")
        return f"predicciones.csv sin la columna {col} ({len(d)} filas)"
    return f


def m_config(c):
    p = c / "config/protocolo.json"
    s = p.read_text()
    assert '"semilla": 20261111' in s
    p.write_text(s.replace('"semilla": 20261111', '"semilla": 20261112', 1))
    return "config/protocolo.json: semilla 20261111 -> 20261112"


def m_borrar(rel):
    def f(c):
        (c / rel).unlink()
        return f"eliminado {rel}"
    return f


NO_EJ = "NO EJECUTADO: requiere reconstrucción local"


def bateria_publica():
    """Copia pública sin series del DANE: rechazos posibles sin datos y casos que requieren reconstrucción."""
    res = [
        caso("P1_integro_verificar_publico", None, ["verificar-publico"], True, ["10 PASS, 0 FAIL, 7 NO EJECUTADO"], preparar_vigente=False, vigente_esperado=False),
        caso("P1b_controles_sin_datos", None, ["controles"], False, ["CONTROLES INCOMPLETOS", "NO EJECUTADO"], rc_esperado=2),
        caso("P1c_recalcular_sin_datos", None, ["recalcular"], False, [NO_EJ, "Aprobación anterior retirada"], rc_esperado=2),
        caso("P2_aporte_falso", m_aporte, ["verificar-publico"], False, ["tablas_conservadas_iguales_a_las_aprobadas", "consistencia:aporte_igual_a_series_y_delta", "RECHAZADO"]),
        caso("P3_codigo_300_a_1_ejecutar", m_codigo, ["ejecutar"], False, ["RECHAZADO antes de estimar", "evaluacion/nucleo.py (clase calculo)"]),
        caso("P3b_codigo_300_a_1_verificar_publico", m_codigo, ["verificar-publico"], False, ["codigo_coincide_con_manifiesto_aprobado", "evaluacion/nucleo.py"]),
        caso("P4_configuracion_no_aprobada", m_config, ["verificar-publico"], False, ["protocolo_y_configuracion_sin_cambios", "RECHAZADO"]),
        caso("P5_tabla_publicada_eliminada", m_borrar("resultados/metricas_resumen.csv"), ["verificar-publico"], False, ["tablas_conservadas_iguales_a_las_aprobadas", "falta resultados/metricas_resumen.csv"]),
    ]
    for nombre in ["3_fecha_2030", "5a_sin_modelo_rf_abast_ctrl", "5b_sin_escenario_retro_r2", "6a_recalcular_integro_retira_aprobacion",
                   "6b_recalcular_aporte_falso", "6c_recalcular_insumo_ilegible"]:
        res.append({"caso": nombre, "resultado_prueba": "NO_EJECUTADO", "codigo_salida": None, "aprobacion_vigente_al_terminar": None,
                    "mensajes_esperados_encontrados": [], "detalle": f"{NO_EJ}: altera predicciones.csv, que no se distribuye"})
    return res


if __name__ == "__main__" and not (RAIZ / "resultados/predicciones.csv").exists():
    original = huellas(RAIZ)
    res = bateria_publica()
    intacto = huellas(RAIZ) == original
    ejecutados = [r for r in res if r["resultado_prueba"] != "NO_EJECUTADO"]
    out = {"modo": "copia pública sin series del DANE", "casos": res, "todas_las_ejecutadas_pasan": all(r["resultado_prueba"] == "PASS" for r in ejecutados),
           "no_ejecutadas": [r["caso"] for r in res if r["resultado_prueba"] == "NO_EJECUTADO"], "proyecto_original_intacto": intacto}
    (OUT / "rechazos.json").write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n")
    for r in res:
        print(r["resultado_prueba"], r["caso"], "exit", r["codigo_salida"], r.get("mensajes_esperados_encontrados") or r.get("detalle", ""))
    print("original intacto:", intacto)
    sys.exit(0 if out["todas_las_ejecutadas_pasan"] and intacto else 1)
elif __name__ == "__main__":
    original = huellas(RAIZ)
    res = [
        caso("1_integro", None, ["controles"], True, [], preparar_vigente=False),
        caso("2_aporte_falso", m_aporte, ["controles"], False, ["aporte_abastecimiento:mase_con_abast", "aporte_abastecimiento:delta_mase", "aporte_abastecimiento:mae_con_abast", "RECHAZADO"]),
        caso("3_fecha_2030", m_fecha, ["controles"], False, ["temporal_predicciones:ultimo_precio_usado_igual_al_limite", "auditoria_temporal:precio_usado_no_supera_limite", "auditoria_temporal:booleano_cumple_igual_al_recalculo", "RECHAZADO"]),
        caso("4_codigo_300_a_1", m_codigo, ["ejecutar"], False, ["RECHAZADO antes de estimar", "evaluacion/nucleo.py (clase calculo)"]),
        caso("4b_codigo_300_a_1_controles", m_codigo, ["controles"], False, ["codigo_coincide_con_manifiesto_aprobado", "evaluacion/nucleo.py"]),
        caso("5a_sin_modelo_rf_abast_ctrl", m_quitar("modelo", "rf_abast_ctrl"), ["controles"], False, ["cobertura:predicciones_exactas_segun_protocolo", "faltan=2160", "rf_abast_ctrl"]),
        caso("5b_sin_escenario_retro_r2", m_quitar("escenario", "retro_r2"), ["controles"], False, ["cobertura:predicciones_exactas_segun_protocolo", "faltan=5760"]),
        caso("6a_recalcular_integro_retira_aprobacion", None, ["recalcular"], True, ['"ok": true', "no emite aprobación"], vigente_esperado=False),
        caso("6b_recalcular_aporte_falso", m_aporte, ["recalcular"], False, ['"ok": false', "aporte_abastecimiento:delta_mase", "RECHAZADO: el recálculo no coincide", "Aprobación anterior retirada"]),
        caso("6c_recalcular_insumo_ilegible", m_quitar_columna("predicho"), ["recalcular"], False, ["RECHAZADO: el recálculo no pudo completarse", "Aprobación anterior retirada"]),
    ]
    intacto = huellas(RAIZ) == original
    out = {"casos": res, "todas_las_pruebas_pasan": all(r["resultado_prueba"] == "PASS" for r in res),
           "proyecto_original_intacto": intacto, "nota": "cada caso en una copia temporal; las copias se eliminan al terminar"}
    (OUT / "rechazos.json").write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n")
    for r in res:
        print(r["resultado_prueba"], r["caso"], "exit", r["codigo_salida"], "vigente", r["aprobacion_vigente_al_terminar"], r["mensajes_esperados_encontrados"])
    print("original intacto:", intacto)
    sys.exit(0 if out["todas_las_pruebas_pasan"] and intacto else 1)
