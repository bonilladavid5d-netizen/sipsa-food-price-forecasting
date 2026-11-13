"""Registra UNA vez la enmienda `recalcular-aprobacion` en resultados/revision_distribucion_etapa1_v2.json.

Enmienda posterior a los resultados dentro de la revisión de distribución (no es un nuevo congelamiento). No toca
registro_protocolo.json, revision_mantenimiento_v2.json ni revision_publicacion_etapa1.json, y exige que el padre
siga siendo el mismo. Solo acepta el cambio declarado en evaluacion/__main__.py; cualquier otro módulo alterado, o el
núcleo distinto del aprobado, la detiene. Conserva el historial: guarda la huella del archivo de revisión anterior, la
huella de código anterior y las huellas antes/después de cada archivo cambiado. Se niega a aplicarse dos veces.
Uso: python herramientas/enmendar_revision_distribucion.py <sha256_reproducir_sh_anterior> <sha256_probar_rechazos_anterior>
"""
import datetime as dt, hashlib, json, sys
from pathlib import Path
RAIZ = Path(__file__).resolve().parents[1]
sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
ID = "recalcular-aprobacion"
dst = RAIZ / "resultados/revision_distribucion_etapa1_v2.json"
pub_p = RAIZ / "resultados/revision_publicacion_etapa1.json"
antes_bytes = dst.read_bytes()
d = json.loads(antes_bytes)
if any(e["enmienda"] == ID for e in d.get("enmiendas", [])):
    raise SystemExit(f"la enmienda {ID} ya está registrada: no se reaplica")
assert d["padre"]["revision_publicacion_etapa1_sha256"] == sha(pub_p), "el padre de la revisión de distribución cambió"
pub = json.loads(pub_p.read_text())
PERMITIDOS = {"evaluacion/__main__.py": "presentacion/CLI: `recalcular` retira cualquier VALIDACION_VIGENTE.json anterior antes de "
              "comprobar los insumos, y de nuevo ante un fallo del recálculo (código 1) o una excepción (código 1); sin datos termina "
              "con código 2 y sin aprobación. No emite aprobación: solo `controles` lo hace. recalcular.py no cambia."}
nuevos = {m: sha(RAIZ / m) for m in d["modulos_aprobados"]}
cambios = []
for m, h in nuevos.items():
    if h != d["modulos_aprobados"][m]:
        assert m in PERMITIDOS, f"{m} cambió sin estar declarado en la enmienda"
        cambios.append({"modulo": m, "sha256_antes": d["modulos_aprobados"][m], "sha256_despues": h, "justificacion": PERMITIDOS[m]})
assert [c["modulo"] for c in cambios] == list(PERMITIDOS), f"cambios inesperados: {cambios}"
for m in ("evaluacion/nucleo.py", "evaluacion/recalcular.py", "evaluacion/controles.py", "evaluacion/ejecutar.py", "evaluacion/datos.py"):
    assert nuevos[m] == pub["modulos_aprobados"][m], f"{m} difiere del aprobado en la revisión de publicación"
for f, h in d["tablas_conservadas_aprobadas"].items():
    assert sha(RAIZ / f) == h, f"{f} cambió"
huella_antes = d["huella_codigo_revision"]
d["modulos_aprobados"] = nuevos
d["huella_codigo_revision"] = hashlib.sha256(json.dumps(nuevos, sort_keys=True).encode()).hexdigest()
d.setdefault("enmiendas", []).append({
    "enmienda": ID, "creado_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
    "naturaleza": "Corrección de validación posterior a los resultados. No cambia datos, estimación, exportación, métricas, figuras ni conclusiones; no se reentrenó.",
    "sha256_revision_distribucion_antes": hashlib.sha256(antes_bytes).hexdigest(),
    "huella_codigo_revision_antes": huella_antes, "huella_codigo_revision_despues": d["huella_codigo_revision"],
    "zip_publicable_anterior_sha256": "52522cf4e7b83e9eadb887b9512bce058147abf83241e8dd818d3d1bbf625c72",
    "modulos": cambios,
    "otros_archivos": [
        {"archivo": "evaluation/reproducir.sh", "clase": "ejecucion_empaquetado", "sha256_antes": sys.argv[1], "sha256_despues": sha(RAIZ / "reproducir.sh"),
         "cambio": "`recalcular` se ejecuta antes de `controles`, para que la aprobación final la emita `controles` y no quede retirada por el recálculo."},
        {"archivo": "evaluation/herramientas/probar_rechazos.py", "clase": "herramienta_validacion", "sha256_antes": sys.argv[2], "sha256_despues": sha(RAIZ / "herramientas/probar_rechazos.py"),
         "cambio": "P1c siembra una aprobación previa y exige código 2 sin aprobación al terminar; casos 6a-6c de recálculo con datos (íntegro, aporte falso, insumo ilegible); se registra si la aprobación estaba sembrada."},
    ],
    "sin_cambios": ["registro_protocolo.json (congelamiento original)", "revision_mantenimiento_v2.json", "revision_publicacion_etapa1.json",
                    "nucleo.py", "recalcular.py", "controles.py", "ejecutar.py", "datos.py", "tablas conservadas y figuras"],
})
dst.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n")
print(json.dumps({"enmienda": ID, "modulos": [c["modulo"] for c in cambios], "huella_codigo": [huella_antes[:16], d["huella_codigo_revision"][:16]],
                  "sha256_revision": [hashlib.sha256(antes_bytes).hexdigest()[:16], sha(dst)[:16]]}, ensure_ascii=False))
