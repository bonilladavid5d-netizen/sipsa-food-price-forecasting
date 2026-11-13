"""Integridad del código frente a un manifiesto APROBADO (revisión de mantenimiento v2).

- El registro de congelamiento original (resultados/registro_protocolo.json) no se modifica; su SHA-256 queda
  fijado como "padre" en resultados/revision_mantenimiento_v2.json.
- Ese manifiesto aprueba explícitamente la huella de cada módulo y clasifica cada cambio respecto del
  congelamiento: "calculo" (puede afectar predicciones), "validacion" o "presentacion".
- Cualquier módulo cuyo SHA-256 no coincida con el aprobado, o que falte o sobre, detiene la ejecución.
  No existe ningún camino automático que acepte una discrepancia: el manifiesto solo lo crea, una vez,
  herramientas/registrar_revision_mantenimiento.py y se niega a sobrescribirlo.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
MODULOS = {
    "calculo": ["evaluacion/nucleo.py", "evaluacion/ejecutar.py", "evaluacion/datos.py"],
    "validacion": ["evaluacion/controles.py", "evaluacion/recalcular.py", "evaluacion/integridad.py", "evaluacion/publico.py"],
    "presentacion": ["evaluacion/figuras.py", "evaluacion/__main__.py", "evaluacion/__init__.py"],
}
REVISION = "resultados/revision_mantenimiento_v2.json"
PUBLICACION = "resultados/revision_publicacion_etapa1.json"  # opcional; solo existe en la copia pública
DISTRIBUCION = "resultados/revision_distribucion_etapa1_v2.json"  # opcional; hija de PUBLICACION (sin series del DANE)
APROBACION_VIGENTE = "resultados/controles/VALIDACION_VIGENTE.json"


class CodigoNoAprobado(RuntimeError):
    pass


def sha256(p: Path) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def invalidar_aprobacion(raiz: Path = RAIZ) -> None:
    """Tras cualquier fallo, ninguna aprobación anterior queda vigente."""
    (raiz / APROBACION_VIGENTE).unlink(missing_ok=True)


def verificar_codigo(raiz: Path = RAIZ) -> dict:
    errores = []
    rev_p = raiz / REVISION
    if not rev_p.exists():
        raise CodigoNoAprobado(f"falta el manifiesto aprobado {REVISION}")
    rev = json.loads(rev_p.read_text())
    aprobados = rev["modulos_aprobados"]
    derivados = {}
    pub_p = raiz / PUBLICACION
    if pub_p.exists():
        # Revisión de publicación (Etapa 1): hija de la revisión de mantenimiento v2. Solo acepta derivados declarados
        # (anonimización de un campo) cuyo origen coincide con la huella registrada; no cambia el cálculo.
        pub = json.loads(pub_p.read_text())
        if pub["padre"]["revision_mantenimiento_v2_sha256"] != sha256(rev_p):
            errores.append("revision_publicacion_etapa1.json no corresponde a esta revision_mantenimiento_v2.json")
        aprobados = pub["modulos_aprobados"]
        derivados = {d["archivo"]: d for d in pub["derivados"]}
        for arch, d in derivados.items():
            # Solo los registros protegidos deben conservar su huella publicada; las salidas de ejecución
            # (ejecucion.json) se declaran por procedencia y una reconstrucción las regenera legítimamente.
            if d.get("protegido", True) and sha256(raiz / arch) != d["sha256_publicado"]:
                errores.append(f"{arch} no coincide con el derivado publicado declarado")
    dist_p = raiz / DISTRIBUCION
    dist = None
    if dist_p.exists():
        # Revisión de distribución (Etapa 1 v2): retira series del DANE de la copia pública. Debe ser hija de la revisión
        # de publicación y fija las huellas aprobadas de los archivos retirados y de las tablas que se conservan.
        dist = json.loads(dist_p.read_text())
        if not pub_p.exists() or dist["padre"]["revision_publicacion_etapa1_sha256"] != sha256(pub_p):
            errores.append("revision_distribucion_etapa1_v2.json no corresponde a esta revision_publicacion_etapa1.json")
        aprobados = dist["modulos_aprobados"]
    reg = raiz / "resultados/registro_protocolo.json"
    reg_ok = sha256(reg) == rev["padre"]["registro_protocolo_sha256"]
    d = derivados.get("resultados/registro_protocolo.json")
    reg_ok = reg_ok or (d is not None and d["sha256_origen"] == rev["padre"]["registro_protocolo_sha256"]
                        and sha256(reg) == d["sha256_publicado"])
    if not reg_ok:
        errores.append("registro_protocolo.json no coincide con el padre declarado ni con un derivado documentado")
    presentes = {str(p.relative_to(raiz)) for p in (raiz / "evaluacion").glob("*.py")}
    clasificados = {m for ms in MODULOS.values() for m in ms}
    for m in sorted(presentes - clasificados):
        errores.append(f"módulo no clasificado ni aprobado: {m}")
    for m in sorted(clasificados - presentes):
        errores.append(f"falta el módulo aprobado: {m}")
    for m in sorted(presentes & clasificados):
        actual = sha256(raiz / m)
        if aprobados.get(m) != actual:
            clase = next(c for c, ms in MODULOS.items() if m in ms)
            errores.append(f"{m} (clase {clase}) tiene SHA-256 {actual[:12]}… distinto del aprobado {str(aprobados.get(m))[:12]}…")
    if errores:
        invalidar_aprobacion(raiz)
        raise CodigoNoAprobado("Código no aprobado: " + "; ".join(errores))
    if dist is not None:
        return {"revision": dist["revision"], "padre": pub["revision"], "modulos_verificados": len(presentes),
                "huella_codigo_revision": dist["huella_codigo_revision"], "derivados_documentados": sorted(derivados)}
    if pub_p.exists():
        return {"revision": pub["revision"], "padre": rev["revision"], "modulos_verificados": len(presentes),
                "huella_codigo_revision": pub["huella_codigo_revision"], "derivados_documentados": sorted(derivados)}
    return {"revision": rev["revision"], "modulos_verificados": len(presentes), "huella_codigo_revision": rev["huella_codigo_revision"]}
