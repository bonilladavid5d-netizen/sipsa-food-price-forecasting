"""Pruebas de integración con las fuentes reales y fallos dirigidos.

Cada prueba ejecuta la CLI real en un subproceso sobre un directorio de datos aislado
(SIPSA_DATOS), que enlaza las fuentes congeladas y la caché de normalización del proyecto.
Requiere haber construido al menos una vez el proyecto (caché completa de los 16 archivos).

Ejecutar: .venv/bin/python -m unittest -v pruebas.test_integracion_fallos
Evidencia: evidencia/pruebas_fallos.json
"""
import json
import os
import shutil
import signal
import subprocess
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = str(ROOT / ".venv/bin/python")
BASE = Path(os.environ.get("SIPSA_PRUEBAS_DIR", ROOT / "datos/pruebas_integracion"))
EVID = ROOT / "evidencia/v2/pruebas_fallos_v1_suite_sobre_v2.json"  # la evidencia v1 se conserva en evidencia/pruebas_fallos.json
RESULTADOS = []


def sha(p: Path) -> str:
    import hashlib
    return hashlib.sha256(p.read_bytes()).hexdigest()


def cli(datos: Path, *args, env_extra=None, timeout=3600):
    env = {k: v for k, v in os.environ.items() if not k.startswith("SIPSA_")}
    env.update({"SIPSA_DATOS": str(datos), "SIPSA_TRABAJADORES": "3", **(env_extra or {})})
    t0 = time.monotonic()
    r = subprocess.run([PY, "-m", "sipsa", *args], cwd=ROOT, env=env, capture_output=True, text=True, timeout=timeout,
                       start_new_session=True)  # grupo propio: un SIGKILL de grupo no alcanza al ejecutor de pruebas
    return r.returncode, r.stdout, r.stderr, round(time.monotonic() - t0, 1)


def estado(datos: Path) -> dict:
    return json.loads(cli(datos, "estado")[1])


def registrar(nombre, ok, **detalle):
    RESULTADOS.append({"prueba": nombre, "resultado": "PASS" if ok else "FAIL", **detalle})
    EVID.parent.mkdir(exist_ok=True)
    EVID.write_text(json.dumps({"alcance": "fuentes reales congeladas; directorio de datos aislado; CLI en subproceso",
                                "pruebas": RESULTADOS}, ensure_ascii=False, indent=2) + "\n")


class FallosDirigidos(unittest.TestCase):
    datos: Path

    @classmethod
    def setUpClass(cls):
        cache = ROOT / "datos/cache/normalizado"
        sys.path.insert(0, str(ROOT))
        from sipsa.util import huella_normalizador
        clave = huella_normalizador()[:16]
        completos = [d for d in cache.iterdir() if d.name.endswith(clave) and (d / "COMPLETO.json").exists()] if cache.exists() else []
        if len(completos) < 16:
            raise unittest.SkipTest("Primero ejecute `python -m sipsa construir` (caché incompleta)")
        if BASE.exists():
            subprocess.run(["chmod", "-R", "u+w", str(BASE)], check=False)
            shutil.rmtree(BASE)
        cls.datos = BASE / "datos"
        (cls.datos / "cache/normalizado").mkdir(parents=True)
        os.symlink(ROOT / "datos/raw", cls.datos / "raw")
        for d in completos:  # enlaces duros: sin duplicar 300 MB, la caché es de solo lectura
            nd = cls.datos / "cache/normalizado" / d.name
            nd.mkdir()
            for f in d.iterdir():
                os.link(f, nd / f.name)

    def aprobado(self):
        p = self.datos / "APROBADO.json"
        return (sha(p), json.loads(p.read_text())) if p.exists() else (None, None)

    def assert_aprobado_intacto(self, antes_sha, antes):
        despues_sha, despues = self.aprobado()
        self.assertEqual(despues_sha, antes_sha, "APROBADO.json cambió tras una ejecución fallida")
        rc, out, _, _ = cli(self.datos, "verificar")
        self.assertEqual(rc, 0, out)
        return json.loads(out)

    def test_01_lote_base(self):
        rc, out, err, s = cli(self.datos, "construir")
        self.assertEqual(rc, 0, err[-3000:])
        h, ap = self.aprobado()
        type(self).base = ap
        registrar("lote_base_con_cache", rc == 0, lote=ap["lote_id"], huella=ap["huella_contenido"], segundos=s)

    def _fallo(self, nombre, env, etapa_esperada, extra_check=None):
        antes_sha, antes = self.aprobado()
        lotes_antes = set(estado(self.datos)["lotes"])
        rc, out, err, s = cli(self.datos, "construir", env_extra=env)
        self.assertNotEqual(rc, 0)
        est = estado(self.datos)
        ultima = est["ejecuciones"][-1]
        ver = self.assert_aprobado_intacto(antes_sha, antes)
        nuevos = set(est["lotes"]) - lotes_antes
        detalle = {"codigo_salida": rc, "estado_ejecucion": ultima["estado"], "etapa": ultima["etapa"],
                   "error": ultima["error"], "aprobado_antes": antes["lote_id"], "aprobado_despues": est["aprobado"],
                   "verificacion_lote_aprobado": ver["ok"], "lotes_nuevos": sorted(nuevos), "segundos": s}
        if extra_check:
            detalle.update(extra_check(est, nuevos, err))
        ok = rc != 0 and est["aprobado"] == antes["lote_id"] and ver["ok"]
        registrar(nombre, ok, **detalle)
        self.assertTrue(ok, detalle)
        if etapa_esperada:
            self.assertIn(etapa_esperada, str(ultima["etapa"]))
        return detalle

    def test_02_fallo_en_construccion(self):
        d = self._fallo("fallo_inyectado_en_construccion", {"SIPSA_INYECTAR_FALLO": "construir:tras_precios"}, "construir")
        self.assertEqual(d["estado_ejecucion"], "FALLIDA")
        self.assertEqual(d["lotes_nuevos"], [])

    def test_03_contrato_detecta_dato_corrupto(self):
        def chk(est, nuevos, err):
            run = est["ejecuciones"][-1]["run_id"]
            val = json.loads((self.datos / "ejecuciones" / run / "salida/validacion.json").read_text())
            fallidos = [c["check"] for c in val["checks"] if c["status"] == "FAIL"]
            return {"contratos_fallidos": fallidos}
        d = self._fallo("contrato_rechaza_precio_alterado", {"SIPSA_INYECTAR_FALLO": "validar:corromper_panel"}, "validar", chk)
        self.assertIn("panel_igual_a_viabilidad", d["contratos_fallidos"])
        self.assertEqual(d["lotes_nuevos"], [])

    def test_04_fuente_alterada(self):
        raw_mal = BASE / "raw_alterada"
        if raw_mal.exists():
            shutil.rmtree(raw_mal)
        shutil.copytree(ROOT / "datos/raw", raw_mal, symlinks=False, copy_function=os.link)
        objetivo = raw_mal / "precios/2019.xlsx"
        data = bytearray(objetivo.read_bytes())
        objetivo.unlink()  # rompe el enlace duro antes de escribir: el original no se toca
        data[len(data) // 2] ^= 0x01
        objetivo.write_bytes(bytes(data))
        d = self._fallo("fuente_con_un_byte_alterado", {"SIPSA_RAW": str(raw_mal)}, "fuentes")
        self.assertIn("huella distinta raw/precios/2019.xlsx", d["error"])
        shutil.rmtree(raw_mal)

    def test_05_interrupcion_antes_de_apuntar(self):
        def chk(est, nuevos, err):
            return {"lotes_huerfanos": est["lotes_huerfanos"]}
        d = self._fallo("interrupcion_tras_mover_lote_antes_de_apuntar", {"SIPSA_INYECTAR_FALLO": "publicar:antes_de_apuntar"}, "publicar", chk)
        self.assertEqual(len(d["lotes_nuevos"]), 1)
        self.assertIn(d["lotes_nuevos"][0], d["lotes_huerfanos"])

    def test_06_kill_9_del_proceso_principal_y_recuperacion(self):
        antes_sha, antes = self.aprobado()
        # Se elimina una entrada de caché para obligar a normalizar de nuevo durante la recuperación.
        objetivo = next((self.datos / "cache/normalizado").glob("precios_2018_*"))
        shutil.rmtree(objetivo)
        rc, out, err, s = cli(self.datos, "construir", env_extra={"SIPSA_INYECTAR_FALLO": "normalizar:precios:2018", "SIPSA_FALLO_MODO": "kill"})
        temporales = [x.name for x in (self.datos / "cache/normalizado").glob(".tmp-*")]
        self.assertEqual(rc, -signal.SIGKILL)
        # v2: el archivo de bloqueo nunca se borra; tras el kill su ficha sigue "tomado" por la ejecución muerta,
        # pero el sistema operativo ya liberó el flock.
        ficha = json.loads((self.datos / ".bloqueo").read_text())
        bloqueo_queda = ficha.get("estado") == "tomado"
        est = estado(self.datos)
        ultima = est["ejecuciones"][-1]
        self.assert_aprobado_intacto(antes_sha, antes)
        # Recuperación: nueva ejecución normal. Debe detectar el bloqueo huérfano, normalizar lo que falta,
        # publicar y producir la misma huella de contenido que el lote base.
        rc2, out2, err2, s2 = cli(self.datos, "construir")
        est2 = estado(self.datos)
        _, nuevo = self.aprobado()
        abandonada = next(e for e in est2["ejecuciones"] if e["run_id"] == ultima["run_id"])
        reg = [json.loads(l) for l in (self.datos / "registro_ejecuciones.jsonl").read_text().splitlines()]
        ok = (rc == -signal.SIGKILL and bloqueo_queda and ultima["estado"].startswith("INTERRUMPIDA") and rc2 == 0
              and abandonada["estado"] == "ABANDONADA" and nuevo["huella_contenido"] == self.base["huella_contenido"]
              and nuevo["lote_id"] != antes["lote_id"])
        ok = ok and len(temporales) == 1 and not list((self.datos / "cache/normalizado").glob(".tmp-*"))
        registrar("kill_9_durante_normalizacion_y_recuperacion", ok, codigo_salida_kill=rc, temporal_incompleto_tras_kill=temporales, bloqueo_huerfano_tras_kill=bloqueo_queda,
                  estado_tras_kill=ultima["estado"], aprobado_tras_kill=est["aprobado"], codigo_salida_recuperacion=rc2,
                  estado_final_ejecucion_matada=abandonada["estado"], lote_recuperado=nuevo["lote_id"],
                  misma_huella_que_base=nuevo["huella_contenido"] == self.base["huella_contenido"],
                  eventos_abandono=[r for r in reg if r.get("estado") == "ABANDONADA"], segundos_recuperacion=s2)
        self.assertTrue(ok, err2[-2000:])
        type(self).recuperado = nuevo

    def test_07_ejecucion_concurrente_rechazada(self):
        env = {k: v for k, v in os.environ.items() if not k.startswith("SIPSA_")}
        # v2: el archivo .bloqueo siempre existe; la primera ejecución se detiene con el bloqueo tomado
        # (punto de pausa sincronizado) mientras se lanza la segunda, y luego se libera.
        env.update({"SIPSA_DATOS": str(self.datos), "SIPSA_PAUSA": "construir:bloqueo_tomado"})
        p = subprocess.Popen([PY, "-m", "sipsa", "construir"], cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        marca = self.datos / ".pausa-construir_bloqueo_tomado"
        for _ in range(6000):
            if marca.exists() or p.poll() is not None:
                break
            time.sleep(0.05)
        rc, out, err, s = cli(self.datos, "construir")
        marca.unlink(missing_ok=True)
        out1, err1 = p.communicate(timeout=3600)
        ok = rc == 3 and "Otra ejecución tiene el bloqueo" in err and p.returncode == 0
        registrar("segunda_ejecucion_concurrente_rechazada", ok, codigo_salida_segunda=rc, mensaje=err.strip()[-300:],
                  codigo_salida_primera=p.returncode)
        self.assertTrue(ok, err + err1[-2000:])

    def test_08_alteracion_de_lote_y_reversion(self):
        _, ap = self.aprobado()
        lote = self.datos / ap["ruta"]
        f = lote / "tablas/panel_mensual.csv"
        os.chmod(f.parent, 0o755)
        os.chmod(f, 0o644)
        original = f.read_bytes()
        f.write_bytes(original.replace(b"2023-05", b"2023-06", 1))
        rc, out, _, _ = cli(self.datos, "verificar")
        rcq, outq, errq, _ = cli(self.datos, "consultar", "--escenario", "retro_r1", "--origen", "2023-07")
        detectado = rc == 1 and "alterado tablas/panel_mensual.csv" in out
        # Reversión al lote base, que sigue íntegro.
        rcr, outr, errr, _ = cli(self.datos, "revertir", self.base["lote_id"])
        rcv, outv, _, _ = cli(self.datos, "verificar")
        _, ap2 = self.aprobado()
        f.write_bytes(original)
        os.chmod(f, 0o444)
        os.chmod(f.parent, 0o555)
        ok = detectado and rcq != 0 and rcr == 0 and rcv == 0 and ap2["lote_id"] == self.base["lote_id"]
        registrar("alteracion_detectada_y_reversion", ok, verificacion_tras_alterar=json.loads(out),
                  consulta_rechazada=rcq != 0, revertido_a=ap2["lote_id"], verificacion_tras_revertir=json.loads(outv)["ok"])
        self.assertTrue(ok)

    def test_09_consultas_temporales(self):
        rc, out, err, _ = cli(self.datos, "consultar", "--escenario", "retro_r1", "--origen", "2023-07")
        rc2, out2, err2, _ = cli(self.datos, "estricto", "--corte", "2025-12-31T23:59:59+00:00")
        rc3, out3, err3, _ = cli(self.datos, "estricto", "--corte", "2026-12-01T00:00:00+00:00")
        filas = lambda o: int(o.splitlines()[1].split()[0])  # v2: la primera línea informa el corte
        ok = rc == rc2 == rc3 == 0 and "2023-06" in out and filas(out2) == 0 and filas(out3) > 0
        registrar("consultas_temporales_cli", ok, escenario_r1_2023_07=out.strip(), estricto_2025=out2.strip(), estricto_2026_12=out3.strip())
        self.assertTrue(ok, out + out2 + out3)


if __name__ == "__main__":
    unittest.main()
