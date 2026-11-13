"""Crea UNA vez resultados/revision_mantenimiento_v2.json: manifiesto aprobado del código de la revisión v2.

Se ejecuta después de observar resultados (no es un congelamiento previo). Conserva el registro original como
padre (SHA-256), lista cada módulo con su huella en el congelamiento, en la ejecución v1 y en v2, y exige una
justificación y una clase para cada módulo modificado. Se niega a sobrescribir un manifiesto existente y a
registrar un módulo de cálculo cambiado sin justificación.
Uso: python herramientas/registrar_revision_mantenimiento.py
"""
import hashlib, json, datetime as dt, sys
from pathlib import Path
RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
from evaluacion.integridad import MODULOS, REVISION
sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
destino = RAIZ / REVISION
if destino.exists():
    raise SystemExit(f"{REVISION} ya existe: no se sobrescribe. Una nueva revisión requiere un archivo nuevo y justificado.")
reg_p = RAIZ / "resultados/registro_protocolo.json"
reg = json.loads(reg_p.read_text())
eje = json.loads((RAIZ / "resultados/ejecucion.json").read_text())
JUSTIFICACION = {
    "evaluacion/ejecutar.py": ("calculo", "Solo _comprobar_congelado(): además del protocolo verifica el manifiesto de código antes de cargar datos o estimar (hallazgo 3). No cambia selección, estimación ni tablas; se demuestra reejecutando y comparando las predicciones."),
    "evaluacion/datos.py": ("calculo", "Variable SIPSA_PROYECTO_INGENIERIA para ubicar el proyecto de ingeniería al reproducir (cambio n.º 3 del registro v1, ya presente en la entrega v1). No cambia la lectura ni los controles de integridad del lote."),
    "evaluacion/controles.py": ("validacion", "Hallazgo 2: límites temporales recalculados desde origen y retrasos; cobertura derivada del protocolo; integración del recálculo completo y de la integridad de código; invalidación de aprobaciones antiguas."),
    "evaluacion/recalcular.py": ("validacion", "Hallazgo 1: recálculo de todas las tablas y cifras del resumen desde predicho-observado, con llaves exactas y tolerancias explícitas."),
    "evaluacion/integridad.py": ("validacion", "Hallazgo 3: verificación de módulos contra este manifiesto aprobado."),
    "evaluacion/figuras.py": ("presentacion", "Legibilidad de figuras (cambio n.º 2 del registro v1, ya presente en la entrega v1); el archivo no existía al congelar."),
    "evaluacion/__main__.py": ("presentacion", "Mensajes de la CLI: resumen y causa concreta del rechazo."),
}
congel = reg["codigo_al_congelar"]["archivos"]
v1 = eje["codigo"]["archivos"]
modulos, cambios = {}, []
for clase, ms in MODULOS.items():
    for m in ms:
        h = sha(RAIZ / m)
        modulos[m] = h
        if h != congel.get(m) or h != v1.get(m):
            if m not in JUSTIFICACION or JUSTIFICACION[m][0] != clase:
                raise SystemExit(f"{m} cambió y no tiene justificación de clase {clase}")
            cambios.append({"modulo": m, "clase": clase, "sha256_congelamiento": congel.get(m), "sha256_ejecucion_v1": v1.get(m),
                            "sha256_v2": h, "justificacion": JUSTIFICACION[m][1]})
assert modulos["evaluacion/nucleo.py"] == congel["evaluacion/nucleo.py"] == v1["evaluacion/nucleo.py"], "nucleo.py debe ser el congelado"
out = {
    "revision": "mantenimiento-v2",
    "creado_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
    "naturaleza": "Revisión de mantenimiento POSTERIOR a observar los resultados de 2024-2025. No es un congelamiento previo ni modifica el registro original.",
    "padre": {"registro_protocolo_sha256": sha(reg_p), "congelado_utc": reg["congelado_utc"],
              "huella_codigo_congelamiento": reg["codigo_al_congelar"]["sha256"], "huella_codigo_ejecucion_v1": eje["codigo"]["sha256"],
              "zip_v1_sha256": "4828ec5e6d8c6fb4fe5ce02a895411737a83df60556b3fd26116cea17418da01"},
    "modulos_aprobados": modulos,
    "huella_codigo_revision": hashlib.sha256(json.dumps(modulos, sort_keys=True).encode()).hexdigest(),
    "cambios": cambios,
    "sin_cambios": [m for m in modulos if m not in {c["modulo"] for c in cambios}],
    "efecto_esperado_en_resultados": "ninguno: nucleo.py idéntico al congelado; los cambios de ejecutar.py y datos.py no tocan selección, estimación ni exportación",
}
destino.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n")
print(json.dumps({k: out[k] for k in ("revision", "huella_codigo_revision", "sin_cambios")}, ensure_ascii=False, indent=2))
for c in cambios: print(c["clase"], c["modulo"])
