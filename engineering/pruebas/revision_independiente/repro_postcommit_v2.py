"""Adaptación a la interfaz v2 del caso `post_commit_case` de repro_integridad.py (revisión independiente).
Mismo mecanismo: se sustituye en memoria `lote.append_jsonl` para que lance OSError solo al escribir
historial_aprobados.jsonl, DESPUÉS de promover APROBADO.json. Exige el comportamiento corregido.
Uso: python repro_postcommit_v2.py PROYECTO DATOS_DE_PRUEBA   (imprime un JSON en la última línea)
"""
import contextlib
import io
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

project, datos = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
sys.path.insert(0, str(project))
os.environ["SIPSA_DATOS"] = str(datos)
from sipsa import lote  # noqa: E402
from sipsa.util import read_json, sha256_file  # noqa: E402

def falla_historial_factory(real):
    def falla_historial(path, value):
        if Path(path).name == "historial_aprobados.jsonl":
            raise OSError("Fallo de escritura inyectado DESPUES de promover APROBADO.json")
        return real(path, value)
    return falla_historial


def main():
    # v2 usa multiprocessing "spawn": quien llame a construir() en el mismo proceso necesita esta guarda.
    antes = sha256_file(datos / "APROBADO.json")
    falla_historial = falla_historial_factory(lote.append_jsonl)

    exc = None
    with patch.object(lote, "append_jsonl", falla_historial), contextlib.redirect_stdout(io.StringIO()):
        try:
            lote.construir(trabajadores=2)
        except BaseException as e:  # noqa: BLE001
            exc = e
    ap = read_json(datos / "APROBADO.json")
    est = read_json(datos / "ejecuciones" / ap["run_id"] / "estado.json")
    integro = lote.verificar_aprobado()["ok"]
    with contextlib.redirect_stdout(io.StringIO()):
        conc = lote.conciliar()
    est2 = read_json(datos / "ejecuciones" / ap["run_id"] / "estado.json")
    hist = [json.loads(l) for l in (datos / "historial_aprobados.jsonl").read_text().splitlines()]
    print(json.dumps({"excepcion": type(exc).__name__ if exc else None, "mensaje": str(exc)[:300] if exc else None,
                      "estado": est["estado"], "puntero_cambiado": antes != sha256_file(datos / "APROBADO.json"),
                      "lote_publicado": ap["lote_id"], "lote_integro": integro, "conciliacion": conc["acciones"],
                      "tras_conciliar_estado": est2["estado"],
                      "tras_conciliar_en_historial": any(h.get("publicacion_id") == ap["publicacion_id"] for h in hist)},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
