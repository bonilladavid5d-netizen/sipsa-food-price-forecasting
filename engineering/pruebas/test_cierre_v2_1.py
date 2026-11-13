"""Regresiones v2.1 (H3, cierre de publicación y liberación) — exigen el comportamiento correcto.

Parte A (sin datos SIPSA, rápida): dos lotes mínimos íntegros en un directorio temporal y la CLI real
en subproceso (`revertir`, `conciliar`, `estado`), con fallos inyectados por SIPSA_INYECTAR_FALLO.
Incluye una variante en memoria más severa que el caso de la revisión.
Parte B (datos reales, destino aislado datos/pruebas_v2_1 con caché enlazada en solo lectura):
`construir` con los mismos casos y comprobación de que la huella de contenido no cambia.

Ejecutar: .venv/bin/python -m unittest -v pruebas.test_cierre_v2_1
Evidencia: evidencia/v2_1/pruebas_cierre.json
"""
import contextlib
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sipsa import lote, util  # noqa: E402

PY = str(ROOT / ".venv/bin/python") if (ROOT / ".venv/bin/python").exists() else sys.executable  # copia extraída sin .venv
EVID = ROOT / "evidencia/v2_1/pruebas_cierre.json"
BASE_B = Path(os.environ.get("SIPSA_PRUEBAS_V2_1", ROOT / "datos/pruebas_v2_1"))
HUELLA_V2 = "0dba2228adae1e086ca005fa8c16a1676b99a6fa05a4c30225c7befd53d63ed2"
RES = []


def registrar(nombre, ok, **det):
    RES.append({"prueba": nombre, "resultado": "PASS" if ok else "FAIL", **det})
    EVID.parent.mkdir(parents=True, exist_ok=True)
    EVID.write_text(json.dumps({"plataforma": sys.platform, "python": sys.version.split()[0], "pruebas": RES},
                               ensure_ascii=False, indent=2, default=str) + "\n")


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def cli(d, *args, fallo=None, timeout=1800):
    env = {k: v for k, v in os.environ.items() if not k.startswith("SIPSA_")}
    env["SIPSA_DATOS"] = str(d)
    if fallo:
        env["SIPSA_INYECTAR_FALLO"] = fallo
    r = subprocess.run([PY, "-m", "sipsa", *args], cwd=ROOT, env=env, capture_output=True, text=True,
                       timeout=timeout, start_new_session=True)
    return r.returncode, r.stdout, r.stderr


def eventos(d):
    p = Path(d) / "registro_ejecuciones.jsonl"
    return [json.loads(l) for l in p.read_text().splitlines()] if p.exists() else []


def historial(d):
    p = Path(d) / "historial_aprobados.jsonl"
    return [json.loads(l) for l in p.read_text().splitlines()] if p.exists() else []


def crear_fixture(d: Path):
    """Igual que repro_cierre_v2.py: lote-A aprobado, lote-B íntegro disponible."""
    for nombre in ("lote-A", "lote-B"):
        p = d / "lotes" / nombre
        p.mkdir(parents=True)
        util.write_json_atomic(p / "LOTE.json", {"lote_id": nombre, "run_id": "origen-" + nombre, "huella_contenido": "fixture-" + nombre})
        (p / "contenido.txt").write_text(nombre + "\n")
        util.write_json_atomic(p / "MANIFIESTO.json", {"archivos": lote.manifiesto(p)})
    p = d / "lotes" / "lote-A"
    actual = {"lote_id": "lote-A", "ruta": "lotes/lote-A", "manifiesto_sha256": util.sha256_file(p / "MANIFIESTO.json"),
              "huella_contenido": "fixture-lote-A", "run_id": "origen-lote-A", "publicacion_id": "pub-inicial", "contexto": "publicar"}
    util.write_json_atomic(d / "APROBADO.json", actual)
    util.append_jsonl(d / "historial_aprobados.jsonl", actual)


def bloqueo_adquirible(d):
    """Otro PROCESO adquiere y libera el bloqueo (CLI `conciliar` toma el flock)."""
    rc, out, err = cli(d, "conciliar")
    return rc == 0, json.loads(out) if rc == 0 else err


class A_ReversionConFixtures(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="sipsa-v2_1-")
        self.d = Path(self.tmp.name)
        crear_fixture(self.d)
        self.sha0 = sha(self.d / "APROBADO.json")

    def tearDown(self):
        self.tmp.cleanup()

    def _pid(self):
        return json.loads((self.d / "APROBADO.json").read_text())["publicacion_id"]

    def _doble_conciliacion(self):
        rc1, o1, e1 = cli(self.d, "conciliar")
        ev1, hi1 = eventos(self.d), historial(self.d)
        rc2, o2, e2 = cli(self.d, "conciliar")
        ev2, hi2 = eventos(self.d), historial(self.d)
        return {"rc1": rc1, "acciones_1": json.loads(o1)["acciones"], "rc2": rc2, "acciones_2": json.loads(o2)["acciones"],
                "eventos_sin_cambio_en_2a": ev1 == ev2, "historial_sin_cambio_en_2a": hi1 == hi2}

    def _terminales(self, pid):
        return [e for e in eventos(self.d) if e.get("publicacion_id") == pid and e.get("estado") in lote.TERMINALES_REVERSION]

    def test_1_normal(self):
        rc, out, err = cli(self.d, "revertir", "lote-B")
        est = json.loads(cli(self.d, "estado")[1])
        ver = json.loads(cli(self.d, "verificar")[1])
        pid = self._pid()
        ok = (rc == 0 and est["aprobado"] == "lote-B" and ver["ok"] and not est["registro_pendiente"]
              and [e["estado"] for e in self._terminales(pid)] == ["PUBLICADA"])
        registrar("A1_reversion_normal", ok, codigo=rc, puntero="lote-A->" + est["aprobado"], registro_pendiente=est["registro_pendiente"])
        self.assertTrue(ok, err)

    def test_2_fallo_antes_de_confirmar(self):
        rc, out, err = cli(self.d, "revertir", "lote-B", fallo="revertir:antes_de_apuntar")
        ok = rc == 1 and sha(self.d / "APROBADO.json") == self.sha0 and "sin cambios" in err
        registrar("A2_fallo_antes_de_confirmar", ok, codigo=rc, huella_puntero_igual=sha(self.d / "APROBADO.json") == self.sha0, stderr=err.strip())
        self.assertTrue(ok, err)

    def test_3_fallo_historial_tras_confirmar(self):
        rc, out, err = cli(self.d, "revertir", "lote-B", fallo="revertir:historial")
        pid = self._pid()
        est = json.loads(cli(self.d, "estado")[1])
        dc = self._doble_conciliacion()
        est2 = json.loads(cli(self.d, "estado")[1])
        ok = (rc == 4 and est["aprobado"] == "lote-B" and est["registro_pendiente"] and dc["rc1"] == 0 and dc["acciones_1"]
              and dc["acciones_2"] == [] and dc["eventos_sin_cambio_en_2a"] and dc["historial_sin_cambio_en_2a"]
              and sum(h.get("publicacion_id") == pid for h in historial(self.d)) == 1
              and [e["estado"] for e in self._terminales(pid)] == ["PUBLICADA"] and not est2["registro_pendiente"])
        registrar("A3_fallo_historial_tras_confirmar", ok, codigo=rc, stderr=err.strip(), pendiente_antes=est["registro_pendiente"],
                  conciliaciones=dc, pendiente_despues=est2["registro_pendiente"])
        self.assertTrue(ok, (err, dc))

    def test_4_fallo_evento_final_de_reversion(self):
        rc, out, err = cli(self.d, "revertir", "lote-B", fallo="revertir:evento_final")
        pid = self._pid()
        est = json.loads(cli(self.d, "estado")[1])
        dc = self._doble_conciliacion()
        est2 = json.loads(cli(self.d, "estado")[1])
        ok = (rc == 4 and "PUBLICADA_REGISTRO_PENDIENTE" in err and "sin cambios" not in err and est["aprobado"] == "lote-B"
              and est["registro_pendiente"] and not est["historial_pendiente"] and est["cierres_pendientes"]
              and dc["acciones_1"] and dc["acciones_2"] == [] and dc["eventos_sin_cambio_en_2a"]
              and [e["estado"] for e in self._terminales(pid)] == ["PUBLICADA"] and not est2["registro_pendiente"]
              and sum(h.get("publicacion_id") == pid for h in historial(self.d)) == 1)
        registrar("A4_fallo_evento_final_de_reversion", ok, codigo=rc, stderr=err.strip(), estado_antes={k: est[k] for k in
                  ("aprobado", "registro_pendiente", "historial_pendiente", "cierres_pendientes")}, conciliaciones=dc,
                  registro_pendiente_despues=est2["registro_pendiente"])
        self.assertTrue(ok, (err, est, dc))

    def test_4b_todos_los_registros_posteriores_fallan(self):
        """Más severo que la revisión: fallan el evento PUBLICADA y también el PUBLICADA_REGISTRO_PENDIENTE.
        Solo queda PUBLICANDO; la conciliación debe reconocer la publicación por el historial/puntero."""
        real = lote.append_jsonl

        def falla(path, obj):
            if Path(path).name == "registro_ejecuciones.jsonl" and obj.get("estado") in ("PUBLICADA", "PUBLICADA_REGISTRO_PENDIENTE"):
                raise OSError("FALLO_CONTROLADO_registro_posterior")
            return real(path, obj)
        err = io.StringIO()
        with patch.dict(os.environ, {"SIPSA_DATOS": str(self.d)}), patch.object(lote, "append_jsonl", falla), \
                contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            from sipsa import cli as cli_mod
            try:
                cli_mod.main(["revertir", "lote-B"])
                rc = 0
            except SystemExit as e:
                rc = e.code
        pid = self._pid()
        ult = [e["estado"] for e in eventos(self.d) if e.get("publicacion_id") == pid]
        est = json.loads(cli(self.d, "estado")[1])
        dc = self._doble_conciliacion()
        ok = (rc == 4 and ult == ["PUBLICANDO"] and est["registro_pendiente"] and dc["acciones_1"] and dc["acciones_2"] == []
              and [e["estado"] for e in self._terminales(pid)] == ["PUBLICADA"])
        registrar("A4b_fallan_todos_los_eventos_posteriores", ok, codigo=rc, eventos_antes=ult, stderr=err.getvalue().strip()[-400:],
                  pendiente_visible=est["registro_pendiente"], conciliaciones=dc)
        self.assertTrue(ok, (err.getvalue(), dc))

    def test_5_fallo_ficha_al_liberar(self):
        rc, out, err = cli(self.d, "revertir", "lote-B", fallo="liberar:ficha")
        pid = self._pid()
        est = json.loads(cli(self.d, "estado")[1])
        adq, info = bloqueo_adquirible(self.d)
        adv = [e for e in eventos(self.d) if e.get("estado") == "ADVERTENCIA_LIMPIEZA"]
        ok = (rc == 0 and "ADVERTENCIA" in err and "SÍ se liberó" in err and "sin cambios" not in err and est["aprobado"] == "lote-B"
              and not est["registro_pendiente"] and [e["estado"] for e in self._terminales(pid)] == ["PUBLICADA"] and adq and len(adv) == 1)
        registrar("A5_fallo_ficha_al_liberar_reversion", ok, codigo=rc, stderr=err.strip(), puntero=est["aprobado"],
                  bloqueo_adquirible_por_otro_proceso=adq, evento_advertencia=adv)
        self.assertTrue(ok, err)

    def test_6_fallo_previo_mas_fallo_de_limpieza(self):
        rc, out, err = cli(self.d, "revertir", "lote-B", fallo="revertir:antes_de_apuntar,liberar:ficha")
        adq, _ = bloqueo_adquirible(self.d)
        ok = (rc == 1 and sha(self.d / "APROBADO.json") == self.sha0 and "Fallo inyectado en revertir:antes_de_apuntar" in err
              and "NOTA: Limpieza" in err and adq)
        registrar("A6_fallo_previo_y_fallo_de_limpieza_reversion", ok, codigo=rc, huella_puntero_igual=sha(self.d / "APROBADO.json") == self.sha0,
                  stderr=err.strip(), bloqueo_adquirible=adq)
        self.assertTrue(ok, err)


class B_ConstruccionConDatosReales(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        clave = util.huella_normalizador()[:16]
        cache = ROOT / "datos/cache/normalizado"
        entradas = [x for x in cache.iterdir() if x.name.endswith(clave) and (x / "COMPLETO.json").exists()]
        if len(entradas) != 16:
            raise unittest.SkipTest("caché verificada incompleta para la huella actual del normalizador")
        if BASE_B.exists():
            subprocess.run(["chmod", "-R", "u+w", str(BASE_B)], check=False)
            shutil.rmtree(BASE_B)
        cls.d = BASE_B / "datos"
        (cls.d / "cache/normalizado").mkdir(parents=True)
        os.symlink(ROOT / "datos/raw", cls.d / "raw")
        for x in entradas:
            (cls.d / "cache/normalizado" / x.name).mkdir()
            for f in x.iterdir():
                os.link(f, cls.d / "cache/normalizado" / x.name / f.name)

    def _ap(self):
        p = self.d / "APROBADO.json"
        return (sha(p), json.loads(p.read_text())) if p.exists() else (None, None)

    def _est(self):
        return json.loads(cli(self.d, "estado")[1])

    def test_1_normal(self):
        rc, out, err = cli(self.d, "construir")
        s, ap = self._ap()
        est, ver = self._est(), json.loads(cli(self.d, "verificar")[1])
        e = est["ejecuciones"][-1]
        ok = rc == 0 and ap["huella_contenido"] == HUELLA_V2 and ver["ok"] and e["estado"] == "PUBLICADA" and not est["registro_pendiente"]
        registrar("B1_construccion_normal", ok, codigo=rc, lote=ap["lote_id"], huella_contenido=ap["huella_contenido"],
                  igual_a_v2=ap["huella_contenido"] == HUELLA_V2, estado=e["estado"])
        self.assertTrue(ok, err[-1500:])

    def test_2_fallo_antes_de_confirmar(self):
        s0, a0 = self._ap()
        rc, out, err = cli(self.d, "construir", fallo="publicar:antes_de_apuntar")
        s1, _ = self._ap()
        e = self._est()["ejecuciones"][-1]
        ok = rc == 1 and s1 == s0 and e["estado"] == "FALLIDA" and "sin cambios" in err
        registrar("B2_fallo_antes_de_confirmar", ok, codigo=rc, huella_puntero_igual=s1 == s0, estado=e["estado"])
        self.assertTrue(ok, err[-1500:])

    def _post(self, nombre, fallo):
        s0, a0 = self._ap()
        rc, out, err = cli(self.d, "construir", fallo=fallo)
        s1, a1 = self._ap()
        est = self._est()
        e = est["ejecuciones"][-1]
        rc1, o1, _ = cli(self.d, "conciliar")
        rc2, o2, _ = cli(self.d, "conciliar")
        est2 = self._est()
        e2 = next(x for x in est2["ejecuciones"] if x["run_id"] == e["run_id"])
        hi = [h for h in historial(self.d) if h.get("publicacion_id") == a1["publicacion_id"]]
        ok = (rc == 4 and s1 != s0 and a1["run_id"] == e["run_id"] and e["estado"] == "PUBLICADA_REGISTRO_PENDIENTE"
              and est["registro_pendiente"] and rc1 == rc2 == 0 and json.loads(o1)["acciones"] and json.loads(o2)["acciones"] == []
              and e2["estado"] == "PUBLICADA" and len(hi) == 1 and not est2["registro_pendiente"]
              and a1["huella_contenido"] == HUELLA_V2 and "sin cambios" not in err)
        registrar(nombre, ok, codigo=rc, stderr=err.strip()[-300:], puntero=f"{a0['lote_id']} -> {a1['lote_id']}",
                  estado_tras_fallo=e["estado"], registro_pendiente=est["registro_pendiente"],
                  conciliacion_1=json.loads(o1)["acciones"], conciliacion_2=json.loads(o2)["acciones"],
                  estado_final=e2["estado"], entradas_historial=len(hi), huella_contenido=a1["huella_contenido"])
        self.assertTrue(ok, err[-1500:])

    def test_3_fallo_historial_tras_confirmar(self):
        self._post("B3_fallo_historial_tras_confirmar", "publicar:historial")

    def test_4_fallo_evento_final_tras_confirmar(self):
        self._post("B4_fallo_evento_final_tras_confirmar", "publicar:evento_final")

    def test_5_fallo_ficha_al_liberar(self):
        s0, a0 = self._ap()
        rc, out, err = cli(self.d, "construir", fallo="liberar:ficha")
        s1, a1 = self._ap()
        est = self._est()
        e = est["ejecuciones"][-1]
        adq, _ = bloqueo_adquirible(self.d)
        ok = (rc == 0 and s1 != s0 and e["estado"] == "PUBLICADA" and "ADVERTENCIA" in err and "sin cambios" not in err
              and not est["registro_pendiente"] and adq and a1["huella_contenido"] == HUELLA_V2)
        registrar("B5_fallo_ficha_al_liberar_construccion", ok, codigo=rc, stderr=err.strip()[-300:], puntero=f"{a0['lote_id']} -> {a1['lote_id']}",
                  estado=e["estado"], bloqueo_adquirible_por_otro_proceso=adq)
        self.assertTrue(ok, err[-1500:])

    def test_6_fallo_previo_mas_fallo_de_limpieza(self):
        s0, _ = self._ap()
        rc, out, err = cli(self.d, "construir", fallo="construir:tras_precios,liberar:ficha")
        s1, _ = self._ap()
        e = self._est()["ejecuciones"][-1]
        adq, _ = bloqueo_adquirible(self.d)
        ok = (rc == 1 and s1 == s0 and e["estado"] == "FALLIDA" and "Fallo inyectado en construir:tras_precios" in err
              and "NOTA: Limpieza" in err and adq)
        registrar("B6_fallo_previo_y_fallo_de_limpieza_construccion", ok, codigo=rc, huella_puntero_igual=s1 == s0, estado=e["estado"],
                  stderr=err.strip()[-400:], bloqueo_adquirible=adq)
        self.assertTrue(ok, err[-1500:])


if __name__ == "__main__":
    unittest.main()
