"""Regresiones de integración v2 (H1 metadatos de captura, H2 muerte del padre con trabajadores vivos,
H3 punto de confirmación) con las fuentes reales y la CLI en subproceso.

Destino aislado: SIPSA_PRUEBAS_V2 (por defecto datos/pruebas_v2). Fuentes originales enlazadas en solo
lectura; la caché se copia con enlaces duros (archivos 0444, nunca se modifican) desde la caché del proyecto,
que debe estar completa y sin procesos activos. Las alteraciones se hacen en fixtures propias.
Ejecutar: .venv/bin/python -m unittest -v pruebas.test_regresion_v2
Evidencia: evidencia/v2/pruebas_regresion.json
"""
import fcntl
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
sys.path.insert(0, str(ROOT))
from sipsa.util import huella_normalizador  # noqa: E402

PY = str(ROOT / ".venv/bin/python")
BASE = Path(os.environ.get("SIPSA_PRUEBAS_V2", ROOT / "datos/pruebas_v2"))
RAW = ROOT / "datos/raw"
EVID = ROOT / "evidencia/v2/pruebas_regresion.json"
RES = []


def sha(p):
    import hashlib
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def registrar(nombre, ok, **det):
    RES.append({"prueba": nombre, "resultado": "PASS" if ok else "FAIL", **det})
    EVID.parent.mkdir(parents=True, exist_ok=True)
    EVID.write_text(json.dumps({"alcance": "Mac; fuentes reales; destino aislado; CLI en subproceso", "pruebas": RES},
                               ensure_ascii=False, indent=2, default=str) + "\n")


def env_base(datos, extra=None):
    env = {k: v for k, v in os.environ.items() if not k.startswith("SIPSA_")}
    env.update({"SIPSA_DATOS": str(datos), "SIPSA_TRABAJADORES": "3", **(extra or {})})
    return env


def cli(datos, *args, extra=None, timeout=3600):
    t0 = time.monotonic()
    r = subprocess.run([PY, "-m", "sipsa", *args], cwd=ROOT, env=env_base(datos, extra), capture_output=True, text=True,
                       timeout=timeout, start_new_session=True)
    return r.returncode, r.stdout, r.stderr, round(time.monotonic() - t0, 1)


def esperar_archivo(p: Path, proc=None, limite=600):
    """Espera a un evento producido por el proceso bajo prueba (archivo de pausa); falla si el proceso termina."""
    t0 = time.monotonic()
    while not p.exists():
        if proc is not None and proc.poll() is not None:
            raise AssertionError(f"el proceso terminó antes de llegar a la pausa: {proc.returncode}")
        if time.monotonic() - t0 > limite:
            raise AssertionError(f"pausa no alcanzada: {p}")
        time.sleep(0.05)
    return json.loads(p.read_text())


def fixture_raw(nombre, modificar=None):
    """Copia de raw/ con enlaces simbólicos a los originales; solo los archivos indicados se copian de verdad."""
    dst = BASE / nombre
    if dst.exists():
        shutil.rmtree(dst)
    for p in RAW.rglob("*"):
        rel = p.relative_to(RAW)
        q = dst / rel
        if p.is_dir():
            q.mkdir(parents=True, exist_ok=True)
            continue
        q.parent.mkdir(parents=True, exist_ok=True)
        if modificar and str(rel) in modificar:
            q.write_bytes(p.read_bytes())  # copia real (el original no se toca)
        else:
            q.symlink_to(p)
    return dst


class RegresionV2(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        clave = huella_normalizador()[:16]
        cache = ROOT / "datos/cache/normalizado"
        entradas = [d for d in cache.iterdir() if d.name.endswith(clave) and (d / "COMPLETO.json").exists()]
        if len(entradas) != 16:
            raise unittest.SkipTest("Construya primero el proyecto con el código actual (caché v2 incompleta)")
        if BASE.exists():
            subprocess.run(["chmod", "-R", "u+w", str(BASE)], check=False)
            shutil.rmtree(BASE)
        cls.datos = BASE / "datos"
        (cls.datos / "cache/normalizado").mkdir(parents=True)
        os.symlink(RAW, cls.datos / "raw")
        for d in entradas:
            nd = cls.datos / "cache/normalizado" / d.name
            nd.mkdir()
            for f in d.iterdir():
                os.link(f, nd / f.name)
        rc, out, err, s = cli(cls.datos, "construir")
        assert rc == 0, err[-3000:]
        cls.base = json.loads((cls.datos / "APROBADO.json").read_text())

    # ------------------------------------------------------------------ utilidades
    def puntero(self):
        p = self.datos / "APROBADO.json"
        return sha(p), json.loads(p.read_text())

    def estado(self):
        return json.loads(cli(self.datos, "estado")[1])

    def historial(self):
        p = self.datos / "historial_aprobados.jsonl"
        return [json.loads(l) for l in p.read_text().splitlines()] if p.exists() else []

    def estricto(self, corte):
        rc, out, err, _ = cli(self.datos, "estricto", "--corte", corte)
        self.assertEqual(rc, 0, err)
        return int(out.splitlines()[1].split()[0])

    def ultima_ejecucion(self):
        return self.estado()["ejecuciones"][-1]

    # ------------------------------------------------------------------ H1
    def test_h1_1_cortes_alrededor_de_la_captura_real(self):
        caps = json.loads((ROOT / "config/capturas_aprobadas.json").read_text())["capturas"]
        import datetime as dt
        t = {c["local_path"]: dt.datetime.fromisoformat(c["retrieved_at"]) for c in caps}
        tmin, tmax = min(t.values()), max(t.values())
        us = dt.timedelta(microseconds=1)
        p19 = t["raw/precios/2019.xlsx"]
        casos = {
            "1us_antes_de_la_primera_captura": ((tmin - us).isoformat(), 0),
            "corte_de_la_revision_2026-11-05T23:59:59Z": ("2026-11-05T23:59:59+00:00", 0),
            "1us_antes_de_precios_2019": ((p19 - us).isoformat(), None),
            "exactamente_precios_2019": (p19.isoformat(), None),
            "exactamente_la_ultima_captura": (tmax.isoformat(), 5758),
            "cierre_mes_2026-10": ("--mes 2026-10", 0),
            "cierre_mes_2026-11": ("--mes 2026-11", 5758),
        }
        obs = {}
        for k, (corte, _) in casos.items():
            if corte.startswith("--mes"):
                rc, out, err, _ = cli(self.datos, "estricto", "--mes", corte.split()[1])
                obs[k] = int(out.splitlines()[1].split()[0])
            else:
                obs[k] = self.estricto(corte)
        # precios 2019 aporta 360 celdas: exactamente esas aparecen al pasar por su instante de captura.
        ok = (all(obs[k] == v for k, (_, v) in casos.items() if v is not None)
              and obs["exactamente_precios_2019"] - obs["1us_antes_de_precios_2019"] == 360)
        registrar("h1_cortes_alrededor_de_la_captura_real", ok, cortes={k: casos[k][0] for k in casos}, filas=obs)
        self.assertTrue(ok, obs)

    def _rechazo_fuente(self, nombre, raw_fixture, texto_error):
        antes_sha, antes = self.puntero()
        lotes_antes = set(self.estado()["lotes"])
        rc, out, err, s = cli(self.datos, "construir", extra={"SIPSA_RAW": str(raw_fixture)})
        e = self.ultima_ejecucion()
        despues_sha, _ = self.puntero()
        filas_2026_11_05 = self.estricto("2026-11-05T23:59:59+00:00")
        ok = (rc == 1 and despues_sha == antes_sha and e["estado"] == "FALLIDA" and texto_error in e["error"]
              and set(self.estado()["lotes"]) == lotes_antes and filas_2026_11_05 == 0)
        registrar(nombre, ok, codigo_salida=rc, estado=e["estado"], etapa=e["etapa"], error=e["error"],
                  aprobado_sin_cambios=despues_sha == antes_sha, filas_estrictas_2026_11_05=filas_2026_11_05)
        self.assertTrue(ok, (rc, e, err[-1500:]))

    def test_h1_2_fecha_de_captura_alterada_se_rechaza(self):
        raw = fixture_raw("raw_fecha_alterada", {"precios/2019.json"})
        m = json.loads((raw / "precios/2019.json").read_text())
        self.assertEqual(m["retrieved_at"], "2026-11-11T15:02:04.953482+00:00")
        m["retrieved_at"] = "2026-11-01T00:00:00+00:00"  # mismo cambio que la revisión independiente
        (raw / "precios/2019.json").write_text(json.dumps(m, ensure_ascii=False, indent=2))
        self._rechazo_fuente("h1_fecha_de_captura_alterada_rechazada", raw, "metadato de captura no aprobado raw/precios/2019.json")
        self.assertEqual(json.loads((RAW / "precios/2019.json").read_text())["retrieved_at"], "2026-11-11T15:02:04.953482+00:00")

    def test_h1_3_otro_campo_del_metadato_alterado_se_rechaza(self):
        raw = fixture_raw("raw_url_alterada", {"abastecimiento/2024.json"})
        m = json.loads((raw / "abastecimiento/2024.json").read_text())
        m["url"] = m["url"] + "?v=2"
        (raw / "abastecimiento/2024.json").write_text(json.dumps(m, ensure_ascii=False, indent=2))
        self._rechazo_fuente("h1_otro_campo_del_metadato_alterado_rechazado", raw, "metadato de captura no aprobado raw/abastecimiento/2024.json")

    def test_h1_4_cambio_durante_la_ejecucion_se_rechaza_antes_de_confirmar(self):
        raw = fixture_raw("raw_cambio_en_curso", {"precios/2019.json"})
        antes_sha, _ = self.puntero()
        lotes_antes = set(self.estado()["lotes"])
        proc = subprocess.Popen([PY, "-m", "sipsa", "construir"], cwd=ROOT, start_new_session=True, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True,
                                env=env_base(self.datos, {"SIPSA_RAW": str(raw), "SIPSA_PAUSA": "publicar:antes_de_reverificar"}))
        marca = self.datos / ".pausa-publicar_antes_de_reverificar"
        esperar_archivo(marca, proc)
        m = json.loads((raw / "precios/2019.json").read_text())
        m["retrieved_at"] = "2026-11-01T00:00:00+00:00"
        (raw / "precios/2019.json").write_text(json.dumps(m, ensure_ascii=False, indent=2))
        marca.unlink()
        out, err = proc.communicate(timeout=600)
        e = self.ultima_ejecucion()
        ok = (proc.returncode == 1 and self.puntero()[0] == antes_sha and "metadato de captura no aprobado" in e["error"]
              and set(self.estado()["lotes"]) == lotes_antes)
        registrar("h1_cambio_de_metadato_durante_la_ejecucion_rechazado_antes_de_confirmar", ok, codigo_salida=proc.returncode,
                  estado=e["estado"], etapa=e["etapa"], error=e["error"])
        self.assertTrue(ok, err[-1500:])

    # ------------------------------------------------------------------ H3
    def test_h3_1_fallo_antes_del_punto_de_confirmacion(self):
        antes_sha, antes = self.puntero()
        hist_antes = len(self.historial())
        rc, out, err, s = cli(self.datos, "construir", extra={"SIPSA_INYECTAR_FALLO": "publicar:antes_de_apuntar"})
        est = self.estado()
        e = est["ejecuciones"][-1]
        ok = (rc == 1 and self.puntero()[0] == antes_sha and e["estado"] == "FALLIDA" and len(self.historial()) == hist_antes
              and len(est["lotes_huerfanos"]) >= 1 and not est["registro_pendiente"])
        registrar("h3_fallo_justo_antes_del_cambio_de_puntero", ok, codigo_salida=rc, estado=e["estado"], etapa=e["etapa"],
                  aprobado=est["aprobado"], lotes_huerfanos=est["lotes_huerfanos"], historial_sin_cambios=len(self.historial()) == hist_antes)
        self.assertTrue(ok, err[-1500:])

    def test_h3_2_fallo_al_escribir_historial_tras_confirmar(self):
        antes_sha, antes = self.puntero()
        rc, out, err, s = cli(self.datos, "construir", extra={"SIPSA_INYECTAR_FALLO": "publicar:historial"})
        _, nuevo = self.puntero()
        est = self.estado()
        e = est["ejecuciones"][-1]
        en_hist = any(h.get("publicacion_id") == nuevo.get("publicacion_id") for h in self.historial())
        rc2, out2, err2, _ = cli(self.datos, "conciliar")
        est2 = self.estado()
        e2 = next(x for x in est2["ejecuciones"] if x["run_id"] == e["run_id"])
        en_hist2 = [h for h in self.historial() if h.get("publicacion_id") == nuevo.get("publicacion_id")]
        ver = json.loads(cli(self.datos, "verificar")[1])
        ok = (rc == 4 and nuevo["lote_id"] != antes["lote_id"] and nuevo["run_id"] == e["run_id"]
              and e["estado"] == "PUBLICADA_REGISTRO_PENDIENTE" and not en_hist and est["registro_pendiente"]
              and rc2 == 0 and e2["estado"] == "PUBLICADA" and len(en_hist2) == 1 and "conciliado" in en_hist2[0]
              and not est2["registro_pendiente"] and ver["ok"] and "PUBLICADA_REGISTRO_PENDIENTE" in err)
        registrar("h3_fallo_de_historial_justo_despues_del_cambio_de_puntero", ok, codigo_salida=rc, mensaje=err.strip()[-400:],
                  aprobado_antes=antes["lote_id"], aprobado_despues=nuevo["lote_id"], estado_tras_fallo=e["estado"],
                  historial_tenia_la_publicacion=en_hist, registro_pendiente_visible=est["registro_pendiente"],
                  conciliar_codigo=rc2, conciliar_salida=json.loads(out2), estado_tras_conciliar=e2["estado"],
                  historial_tras_conciliar=en_hist2, lote_nuevo_integro=ver["ok"])
        self.assertTrue(ok, (rc, err[-1500:], out2))

    def test_h3_3_mecanismo_exacto_de_la_revision(self):
        """Mismo mecanismo que repro_integridad.post_commit_case: OSError al anexar historial (en memoria)."""
        script = ROOT / "pruebas/revision_independiente/repro_postcommit_v2.py"
        r = subprocess.run([PY, str(script), str(ROOT), str(self.datos)], cwd=ROOT, env=env_base(self.datos),
                           capture_output=True, text=True, timeout=1200, start_new_session=True)
        res = json.loads(r.stdout.strip().splitlines()[-1])
        ok = (res["excepcion"] == "PublicacionConRegistroPendiente" and res["estado"] == "PUBLICADA_REGISTRO_PENDIENTE"
              and res["puntero_cambiado"] and res["lote_integro"] and res["tras_conciliar_estado"] == "PUBLICADA"
              and res["tras_conciliar_en_historial"])
        registrar("h3_mecanismo_de_la_revision_independiente_oserror_en_historial", ok, **res)
        self.assertTrue(ok, r.stderr[-1500:])

    def test_h3_4_muerte_tras_confirmar_se_concilia(self):
        antes_sha, antes = self.puntero()
        rc, out, err, s = cli(self.datos, "construir", extra={"SIPSA_INYECTAR_FALLO": "publicar:tras_apuntar", "SIPSA_FALLO_MODO": "kill"})
        _, tras = self.puntero()
        e = self.ultima_ejecucion()
        rc2, out2, err2, _ = cli(self.datos, "construir")
        est2 = self.estado()
        e_muerta = next(x for x in est2["ejecuciones"] if x["run_id"] == e["run_id"])
        hist = self.historial()
        ok = (rc == -signal.SIGKILL and tras["run_id"] == e["run_id"] and e["estado"].startswith("INTERRUMPIDA (PUBLICANDO")
              and rc2 == 0 and e_muerta["estado"] == "PUBLICADA"
              and any(h.get("publicacion_id") == tras["publicacion_id"] and "conciliado" in h for h in hist)
              and est2["ejecuciones"][-1]["estado"] == "PUBLICADA")
        registrar("h3_kill_9_justo_despues_del_cambio_de_puntero_y_conciliacion", ok, codigo_salida_kill=rc,
                  puntero_tras_kill=tras["lote_id"], estado_tras_kill=e["estado"], codigo_siguiente_construccion=rc2,
                  estado_final_ejecucion_matada=e_muerta["estado"], aprobado_final=est2["aprobado"])
        self.assertTrue(ok, err2[-1500:])

    def test_h3_5_reversion_antes_y_despues_del_punto_de_confirmacion(self):
        _, actual = self.puntero()
        objetivo = self.base["lote_id"]
        self.assertNotEqual(actual["lote_id"], objetivo)
        s0, _ = self.puntero()
        rc1, _, err1, _ = cli(self.datos, "revertir", objetivo, extra={"SIPSA_INYECTAR_FALLO": "revertir:antes_de_apuntar"})
        s1, p1 = self.puntero()
        rc2, out2, err2, _ = cli(self.datos, "revertir", objetivo, extra={"SIPSA_INYECTAR_FALLO": "revertir:historial"})
        s2, p2 = self.puntero()
        pend = self.estado()["registro_pendiente"]
        rc3, out3, _, _ = cli(self.datos, "conciliar")
        hist = [h for h in self.historial() if h.get("publicacion_id") == p2.get("publicacion_id")]
        reg = [json.loads(l) for l in (self.datos / "registro_ejecuciones.jsonl").read_text().splitlines()]
        rev = [r for r in reg if str(r.get("run_id", "")).startswith("revertir-")][-4:]
        ok = (rc1 == 1 and s1 == s0 and rc2 == 4 and p2["lote_id"] == objetivo and p2["contexto"] == "revertir" and pend
              and rc3 == 0 and len(hist) == 1 and not self.estado()["registro_pendiente"])
        registrar("h3_reversion_antes_y_despues_del_cambio_de_puntero", ok, codigo_fallo_antes=rc1, puntero_sin_cambios_antes=s1 == s0,
                  codigo_fallo_despues=rc2, puntero_tras_fallo_despues=p2["lote_id"], registro_pendiente=pend,
                  conciliar_codigo=rc3, historial_tras_conciliar=hist, eventos=rev)
        self.assertTrue(ok, (err1[-800:], err2[-800:]))

    # ------------------------------------------------------------------ H2 (integración)
    def test_h2_muerte_del_padre_con_trabajador_escribiendo(self):
        cache = self.datos / "cache/normalizado"
        objetivo = next(cache.glob(f"abastecimiento_2021_*"))
        shutil.rmtree(objetivo)  # solo enlaces del destino de prueba
        antes_sha, antes = self.puntero()
        proc = subprocess.Popen([PY, "-m", "sipsa", "construir"], cwd=ROOT, start_new_session=True, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True,
                                env=env_base(self.datos, {"SIPSA_PAUSA": "normalizar:abastecimiento:2021"}))
        marca = self.datos / ".pausa-normalizar_abastecimiento_2021"
        info = esperar_archivo(marca, proc)
        padre, trabajador = info["ppid"], info["pid"]
        self.assertEqual(padre, proc.pid)
        temporales = [x.name for x in cache.glob(".tmp-*")]
        os.kill(padre, signal.SIGKILL)  # solo el padre: el trabajador sigue vivo y sostiene LOCK_SH
        proc.wait(60)
        trabajador_vivo = _vivo(trabajador)
        rc2, out2, err2, _ = cli(self.datos, "construir")  # debe rechazarse: trabajador huérfano activo
        marca.unlink()  # el trabajador continúa, detecta que su padre murió y aborta
        fd = os.open(self.datos / ".trabajadores", os.O_RDWR)
        signal.alarm(300)
        fcntl.flock(fd, fcntl.LOCK_EX)  # sincronización: espera a que el trabajador suelte su LOCK_SH
        signal.alarm(0)
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
        temporales_tras = [x.name for x in cache.glob(".tmp-*")]
        entrada_huerfana = list(cache.glob("abastecimiento_2021_*"))
        rc3, out3, err3, s3 = cli(self.datos, "construir")
        est = self.estado()
        muerta = next(x for x in est["ejecuciones"] if x["estado"] == "ABANDONADA" or x["estado"].startswith("INTERRUMPIDA"))
        _, final = self.puntero()
        ok = (proc.returncode == -signal.SIGKILL and trabajador_vivo and len(temporales) == 1 and rc2 == 3
              and "Trabajadores" in err2 and temporales_tras == [] and entrada_huerfana == [] and rc3 == 0
              and muerta["estado"] == "ABANDONADA" and final["huella_contenido"] == self.base["huella_contenido"])
        registrar("h2_muerte_del_padre_con_trabajador_vivo_escribiendo", ok, padre_matado=proc.returncode, trabajador_vivo_tras_matar_padre=trabajador_vivo,
                  temporal_en_escritura=temporales, segundo_escritor_codigo=rc2, segundo_escritor_mensaje=err2.strip()[-250:],
                  temporales_tras_abortar=temporales_tras, entrada_de_cache_creada_por_huerfano=[x.name for x in entrada_huerfana],
                  recuperacion_codigo=rc3, recuperacion_segundos=s3, ejecucion_muerta=muerta, misma_huella_que_base=final["huella_contenido"] == self.base["huella_contenido"])
        self.assertTrue(ok, err3[-1500:])


def _vivo(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


if __name__ == "__main__":
    unittest.main()
