"""Pruebas rápidas sin fuentes reales: lector de fechas, esquemas, bloqueo, escrituras atómicas,
manifiestos y política temporal. Ejecutar: .venv/bin/python -m unittest discover -s pruebas -p 'test_unitarias.py'"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sipsa import lote, util  # noqa: E402
from sipsa.normalizar import parse_date, validate_schema  # noqa: E402


class FechasYEsquemas(unittest.TestCase):
    def test_fechas(self):
        self.assertEqual(parse_date("02/01/20"), "2020-01-02")  # DD/MM/YY de 2020
        self.assertEqual(parse_date("43832"), "2020-01-02")
        for malo in ["", "2020-01-02", "43832.5", "10", "99999"]:
            with self.assertRaises((ValueError, AssertionError)):
                parse_date(malo)

    def test_esquemas(self):
        aprobados = json.loads((ROOT / "config/esquemas_aprobados.json").read_text())
        for kind, ys in aprobados.items():
            for y, cols in ys.items():
                for c in cols:
                    validate_schema(kind, int(y), c)
                    validate_schema(kind, int(y), {k: v + "  " for k, v in c.items()})  # espacios finales tolerados
        with self.assertRaises(ValueError):
            validate_schema("precios", 2025, aprobados["precios"]["2024"][0])  # esquema de otro año


class Atomicidad(unittest.TestCase):
    def test_write_atomic_reemplaza_sin_temporales(self):
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / "a.json"
            util.write_json_atomic(p, {"v": 1})
            util.write_json_atomic(p, {"v": 2})
            self.assertEqual(json.loads(p.read_text()), {"v": 2})
            self.assertEqual([x.name for x in Path(t).iterdir()], ["a.json"])

    def test_punto_fallo(self):
        os.environ["SIPSA_INYECTAR_FALLO"] = "x:y"
        try:
            util.punto_fallo("otro")
            with self.assertRaises(util.FalloInyectado):
                util.punto_fallo("x:y")
        finally:
            del os.environ["SIPSA_INYECTAR_FALLO"]


class Bloqueo(unittest.TestCase):
    def test_flock_exclusion_y_ficha(self):
        # Versión v2 (flock). Las pruebas con procesos concurrentes están en pruebas/test_bloqueo.py.
        with tempfile.TemporaryDirectory() as t:
            d = Path(t)
            a = lote.Bloqueo(d, "A")
            self.assertIsNone(a.tomar())
            with self.assertRaises(lote.EjecucionEnCurso):
                lote.Bloqueo(d, "B").tomar()
            a.soltar()
            self.assertTrue((d / ".bloqueo").exists())  # nunca se borra
            self.assertEqual(json.loads((d / ".bloqueo").read_text())["estado"], "libre")


class CierreMes(unittest.TestCase):
    def test_convencion_cierre_mes_calendario_colombia(self):
        self.assertEqual(util.cierre_mes("2023-07"), "2023-07-31T23:59:59.999999-05:00")
        self.assertEqual(util.cierre_mes("2025-12"), "2025-12-31T23:59:59.999999-05:00")
        self.assertEqual(util.cierre_mes("2024-02"), "2024-02-29T23:59:59.999999-05:00")


class Manifiesto(unittest.TestCase):
    def test_alteracion_detectada(self):
        with tempfile.TemporaryDirectory() as t:
            d = Path(t) / "lote"
            (d / "tablas").mkdir(parents=True)
            (d / "tablas/x.csv").write_text("a\n1\n")
            util.write_json_atomic(d / "MANIFIESTO.json", {"archivos": lote.manifiesto(d)})
            self.assertEqual(lote.verificar_lote(d), [])
            (d / "tablas/x.csv").write_text("a\n2\n")
            self.assertEqual(lote.verificar_lote(d), ["alterado tablas/x.csv"])
            (d / "tablas/y.csv").write_text("intruso")
            self.assertIn("no declarado tablas/y.csv", lote.verificar_lote(d))


class Politica(unittest.TestCase):
    def test_politica_versionada(self):
        pol = json.loads((ROOT / "config/politica_temporal.json").read_text())
        self.assertTrue(pol["version"])
        for e in pol["escenarios"]:
            self.assertEqual(e["base"], "supuesto")
            self.assertGreaterEqual(e["retraso_precio_meses"], 1)
            self.assertGreaterEqual(e["retraso_abastecimiento_meses"], 1)


if __name__ == "__main__":
    unittest.main()
