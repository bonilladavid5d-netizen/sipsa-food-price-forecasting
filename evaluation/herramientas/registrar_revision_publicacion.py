"""Crea UNA vez resultados/revision_publicacion_etapa1.json en la copia pública.

Revisión de publicación POSTERIOR a los resultados y a las revisiones independientes. Hija, por SHA-256, de
resultados/revision_mantenimiento_v2.json (que se publica sin cambios). Declara:
  - derivados: archivos protegidos cuya huella cambia solo por anonimizar la ruta local del proyecto de
    ingeniería (campo entrada.proyecto_ingenieria), con la huella del original de v2 y la publicada;
  - modulos_aprobados: iguales a v2 salvo evaluacion/integridad.py (acepta derivados documentados).
Se niega a sobrescribir y a aprobar cualquier otro cambio de módulos.
Uso: python herramientas/registrar_revision_publicacion.py <carpeta_evaluacion_v2_original>
"""
import datetime as dt, hashlib, json, sys
from pathlib import Path
RAIZ = Path(__file__).resolve().parents[1]
ORIG = Path(sys.argv[1]).resolve()
sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
dst = RAIZ / "resultados/revision_publicacion_etapa1.json"
if dst.exists():
    raise SystemExit("revision_publicacion_etapa1.json ya existe: no se sobrescribe")
mant_p = RAIZ / "resultados/revision_mantenimiento_v2.json"
assert sha(mant_p) == sha(ORIG / "resultados/revision_mantenimiento_v2.json"), "la revisión v2 debe publicarse sin cambios"
mant = json.loads(mant_p.read_text())
derivados = []
for arch in ["resultados/registro_protocolo.json", "resultados/ejecucion.json"]:
    o, p = json.loads((ORIG / arch).read_text()), json.loads((RAIZ / arch).read_text())
    assert o["entrada"].pop("proyecto_ingenieria") != p["entrada"].pop("proyecto_ingenieria") == "<PROYECTO_INGENIERIA>"
    assert o == p, f"{arch}: solo puede diferir el campo anonimizado"
    derivados.append({"archivo": arch, "protegido": arch == "resultados/registro_protocolo.json",
                      "nota": "registro protegido: debe conservar la huella publicada" if arch == "resultados/registro_protocolo.json"
                              else "salida de ejecución: declarada por procedencia; `reproducir.sh` la regenera",
                      "sha256_origen": sha(ORIG / arch), "sha256_publicado": sha(RAIZ / arch),
                      "transformacion": "entrada.proyecto_ingenieria: ruta absoluta local -> \"<PROYECTO_INGENIERIA>\"; resto del archivo idéntico byte a byte",
                      "original_conservado_en": f"sipsa_evaluacion_v2/{arch} y SIPSA_EVALUACION_PREDICTIVA_REVISION_v2.zip (expediente de revisión)"})
mods = {}
for m in mant["modulos_aprobados"]:
    mods[m] = sha(RAIZ / m)
    if m != "evaluacion/integridad.py":
        assert mods[m] == mant["modulos_aprobados"][m], f"{m} cambió: no aprobado en esta revisión"
assert mods["evaluacion/integridad.py"] != mant["modulos_aprobados"]["evaluacion/integridad.py"]
out = {"revision": "publicacion-etapa1", "creado_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
       "naturaleza": "Revisión de publicación posterior a los resultados y a las revisiones independientes; no es un congelamiento previo. No cambia datos, código de cálculo ni resultados.",
       "padre": {"revision": mant["revision"], "revision_mantenimiento_v2_sha256": sha(mant_p),
                 "registro_protocolo_original_sha256": mant["padre"]["registro_protocolo_sha256"],
                 "zip_v2_sha256": "63745a0c0376c120a22d542699887ff0cb4b72c749edac259be60cfdb2bc712a"},
       "derivados": derivados,
       "modulos_aprobados": mods,
       "huella_codigo_revision": hashlib.sha256(json.dumps(mods, sort_keys=True).encode()).hexdigest(),
       "cambios": [{"modulo": "evaluacion/integridad.py", "clase": "validacion", "sha256_v2": mant["modulos_aprobados"]["evaluacion/integridad.py"],
                    "sha256_publicacion": mods["evaluacion/integridad.py"],
                    "justificacion": "Acepta como padre un registro derivado solo si está declarado aquí con la huella de origen del registro original; verifica la huella publicada de cada derivado y usa estos módulos aprobados."}]}
dst.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n")
print(json.dumps({"revision": out["revision"], "huella_codigo_revision": out["huella_codigo_revision"], "derivados": [d["archivo"] for d in derivados]}, ensure_ascii=False, indent=1))
