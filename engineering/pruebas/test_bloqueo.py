"""Regresión H2: exclusión mutua de escritores con flock (procesos reales, sin datos SIPSA).

Sincronización con Barrier/Event de multiprocessing; ninguna prueba depende de esperas arbitrarias.
Ejecutar: .venv/bin/python -m unittest -v pruebas.test_bloqueo
Evidencia: evidencia/v2/pruebas_bloqueo.json
"""
import fcntl
import json
import multiprocessing as mp
import os
import signal
import socket
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sipsa import lote  # noqa: E402

EVID = ROOT / "evidencia/v2/pruebas_bloqueo.json"
RES = []
CTX = mp.get_context("spawn")


def registrar(nombre, ok, **det):
    RES.append({"prueba": nombre, "resultado": "PASS" if ok else "FAIL", **det})
    EVID.parent.mkdir(parents=True, exist_ok=True)
    EVID.write_text(json.dumps({"plataforma": sys.platform, "python": sys.version.split()[0], "pruebas": RES},
                               ensure_ascii=False, indent=2) + "\n")


def _competidor(nombre, d, barrera, fin, cola):
    """Todos cruzan la barrera y llaman a tomar() a la vez. El ganador sostiene el bloqueo hasta `fin`."""
    b = lote.Bloqueo(Path(d), nombre)
    barrera.wait(30)
    try:
        anterior = b.tomar()
        cola.put({"nombre": nombre, "adquirio": True, "anterior": anterior and anterior.get("run_id"), "pid": os.getpid()})
        fin.wait(60)
        ficha = json.loads((Path(d) / ".bloqueo").read_text())
        cola.put({"nombre": nombre, "ficha_al_salir": ficha.get("run_id")})
        b.soltar()
    except lote.EjecucionEnCurso as e:
        cola.put({"nombre": nombre, "adquirio": False, "error": str(e)[:120]})


def _dueño_que_muere(d, listo):
    b = lote.Bloqueo(Path(d), "MUERE")
    b.tomar()
    listo.set()
    signal.pause()  # el padre lo mata con SIGKILL; nunca llama a soltar()


def _intercalado(nombre, d, a_adquirio, b_intento, liberar, cola):
    """Adaptación del orden de repro_bloqueo.py (revisión independiente) a la interfaz v2:
    B solo intenta después de que A adquirió; A sigue dentro de su sección mientras B intenta."""
    b = lote.Bloqueo(Path(d), nombre)
    if nombre == "B":
        a_adquirio.wait(30)
    try:
        anterior = b.tomar()
        cola.put({"nombre": nombre, "adquirio": True, "anterior": anterior and anterior.get("run_id")})
        if nombre == "A":
            a_adquirio.set()
            b_intento.wait(30)
            cola.put({"nombre": "A", "ficha_tras_intento_B": json.loads((Path(d) / ".bloqueo").read_text()).get("run_id"),
                      "archivo_existe": (Path(d) / ".bloqueo").exists()})
            liberar.wait(30)
        b.soltar()
    except lote.EjecucionEnCurso as e:
        cola.put({"nombre": nombre, "adquirio": False, "error": str(e)[:120]})
    finally:
        if nombre == "B":
            b_intento.set()


def _trabajador_huerfano(trab, listo, fin):
    fd = os.open(trab, os.O_RDWR | os.O_CREAT, 0o644)
    fcntl.flock(fd, fcntl.LOCK_SH)
    listo.set()
    fin.wait(60)
    os.close(fd)


class BloqueoFlock(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_1_adquisicion_normal_y_segundo_rechazado(self):
        a = lote.Bloqueo(self.d, "A")
        self.assertIsNone(a.tomar())
        with self.assertRaises(lote.EjecucionEnCurso):
            lote.Bloqueo(self.d, "B").tomar()
        ficha = json.loads((self.d / ".bloqueo").read_text())
        a.soltar()
        tras = json.loads((self.d / ".bloqueo").read_text())
        c = lote.Bloqueo(self.d, "C")
        ok = ficha["run_id"] == "A" and tras["estado"] == "libre" and (self.d / ".bloqueo").exists() and c.tomar() is None
        c.soltar()
        registrar("adquisicion_normal_segundo_rechazado_liberacion_limpia", ok, ficha_con_A=ficha, ficha_tras_soltar=tras)
        self.assertTrue(ok)

    def test_2_recuperaciones_simultaneas_de_bloqueo_abandonado(self):
        rondas, n, malas, detalle = 30, 4, 0, []
        for r in range(rondas):
            # Bloqueo abandonado: ficha de un dueño que no lo liberó (pid inexistente), sin flock vigente.
            (self.d / ".bloqueo").write_text(json.dumps({"run_id": "OLD", "pid": 99999999, "host": socket.gethostname(), "estado": "tomado"}))
            barrera, fin, cola = CTX.Barrier(n), CTX.Event(), CTX.Queue()
            ps = [CTX.Process(target=_competidor, args=(f"P{i}", str(self.d), barrera, fin, cola)) for i in range(n)]
            for p in ps:
                p.start()
            res = [cola.get(timeout=60) for _ in range(n)]
            fin.set()
            ganadores = [x for x in res if x["adquirio"]]
            salida = cola.get(timeout=60)
            for p in ps:
                p.join(30)
            ok_r = (len(ganadores) == 1 and ganadores[0]["anterior"] == "OLD" and salida["ficha_al_salir"] == ganadores[0]["nombre"])
            malas += not ok_r
            if r < 3 or not ok_r:
                detalle.append({"ronda": r, "ganadores": [g["nombre"] for g in ganadores], "anterior_visto": ganadores[0]["anterior"] if ganadores else None,
                                "ficha_mientras_sostiene": salida["ficha_al_salir"], "rechazados": n - len(ganadores)})
        registrar("recuperaciones_simultaneas_bloqueo_abandonado", malas == 0, rondas=rondas, procesos_por_ronda=n,
                  rondas_con_mas_o_menos_de_un_escritor=malas, ejemplos=detalle)
        self.assertEqual(malas, 0)

    def test_3_intercalado_de_la_revision_adaptado(self):
        (self.d / ".bloqueo").write_text(json.dumps({"run_id": "OLD", "pid": 99999999, "host": socket.gethostname(), "estado": "tomado"}))
        a_adq, b_int, lib, cola = CTX.Event(), CTX.Event(), CTX.Event(), CTX.Queue()
        ps = [CTX.Process(target=_intercalado, args=(n, str(self.d), a_adq, b_int, lib, cola)) for n in ("A", "B")]
        for p in ps:
            p.start()
        res = [cola.get(timeout=60) for _ in range(3)]
        lib.set()
        for p in ps:
            p.join(30)
        por = {}
        for x in res:
            por.setdefault(x["nombre"], {}).update(x)
        ok = (por["A"]["adquirio"] and por["A"]["anterior"] == "OLD" and not por["B"]["adquirio"]
              and por["A"]["ficha_tras_intento_B"] == "A" and por["A"]["archivo_existe"])
        registrar("intercalado_revision_independiente_v2", ok, resultados=por,
                  nota="B intenta mientras A está en su sección; B no adquiere ni modifica/borra el bloqueo de A")
        self.assertTrue(ok, por)

    def test_4_muerte_del_dueño_y_recuperacion(self):
        listo = CTX.Event()
        p = CTX.Process(target=_dueño_que_muere, args=(str(self.d), listo))
        p.start()
        self.assertTrue(listo.wait(30))
        with self.assertRaises(lote.EjecucionEnCurso):
            lote.Bloqueo(self.d, "ANTES").tomar()
        os.kill(p.pid, signal.SIGKILL)
        p.join(30)
        b = lote.Bloqueo(self.d, "RECUPERA")
        anterior = b.tomar()
        b.soltar()
        ok = anterior is not None and anterior["run_id"] == "MUERE" and p.exitcode == -signal.SIGKILL
        registrar("muerte_del_dueño_libera_y_se_recupera", ok, exitcode=p.exitcode, anterior_detectado=anterior)
        self.assertTrue(ok)

    def test_5_trabajador_huerfano_activo_bloquea(self):
        listo, fin = CTX.Event(), CTX.Event()
        p = CTX.Process(target=_trabajador_huerfano, args=(str(self.d / ".trabajadores"), listo, fin))
        p.start()
        self.assertTrue(listo.wait(30))
        try:
            lote.Bloqueo(self.d, "NUEVO").tomar()
            rechazado = False
        except lote.EjecucionEnCurso as e:
            rechazado = "Trabajadores" in str(e)
        principal_libre = True
        b2 = lote.Bloqueo(self.d, "SONDA")
        fin.set()
        p.join(30)
        anterior = b2.tomar()  # ya sin trabajador: debe adquirir
        b2.soltar()
        registrar("trabajador_huerfano_con_bloqueo_compartido_impide_nuevo_escritor", rechazado and principal_libre,
                  rechazado_mientras_trabaja=rechazado, adquiere_al_terminar=True)
        self.assertTrue(rechazado)


if __name__ == "__main__":
    unittest.main()
