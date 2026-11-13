"""Orquestación de ejecuciones: bloqueo del sistema operativo, estados, staging por ejecución,
validación, punto de confirmación de la publicación y conciliación del registro.

Garantías (v2):
- Exclusión mutua: `flock(LOCK_EX)` sobre `datos/.bloqueo`, archivo que nunca se borra. El sistema operativo
  libera el bloqueo al morir el proceso; ningún proceso elimina ni sobrescribe el bloqueo de otro.
- Trabajadores: cada tarea de normalización mantiene `flock(LOCK_SH)` sobre `datos/.trabajadores`. Una nueva
  ejecución exige `LOCK_EX` momentáneo sobre ese archivo: si un trabajador huérfano sigue escribiendo, se rechaza.
- Una ejecución escribe en `datos/ejecuciones/<run_id>/` y en la caché direccionada por contenido.
- `datos/lotes/<lote_id>/` aparece de una vez (rename de un directorio completo del mismo volumen).
- PUNTO DE CONFIRMACIÓN: `os.replace` de `datos/APROBADO.json`. Antes de él, cualquier fallo conserva el lote
  aprobado anterior (código 1). Después de él la publicación está hecha: un fallo al registrar historial o estado
  se informa como PUBLICADA_REGISTRO_PENDIENTE (código 4) y `conciliar` completa el registro. Nunca se revierte
  en silencio una publicación que ya pudieron leer consumidores.
- `first_seen_at` proviene de `config/capturas_aprobadas.json`; los JSON laterales solo se aceptan si su
  SHA-256 coincide con esa referencia (y se vuelven a comprobar antes de confirmar).
"""
from __future__ import annotations

import datetime as dt
import fcntl
import json
import multiprocessing
import os
import secrets
import shutil
import socket
import stat
import time
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from .util import (ROOT, ahora, append_jsonl, datos_dir, entorno, fsync_dir, huella_codigo, huella_normalizador,
                   punto_fallo, punto_pausa, raw_dir, read_json, sha256_bytes, sha256_file, write_json_atomic)

ETAPAS = ["fuentes", "normalizar", "construir", "validar", "publicar"]
ESTADOS_ACTIVOS = ("CREADA", "EN_CURSO", "PUBLICANDO")

# Códigos de salida de la CLI
SALIDA_OK, SALIDA_FALLIDA, SALIDA_OCUPADO, SALIDA_REGISTRO_PENDIENTE = 0, 1, 3, 4


class EjecucionEnCurso(RuntimeError):
    pass


class ContratoFallido(RuntimeError):
    pass


class PublicacionConRegistroPendiente(RuntimeError):
    """La publicación se confirmó (APROBADO.json ya apunta al lote nuevo) pero falló un registro posterior."""

    def __init__(self, puntero: dict, causa: BaseException):
        super().__init__(f"Publicado {puntero['lote_id']} (publicación {puntero['publicacion_id']}); "
                         f"registro pendiente por {type(causa).__name__}: {causa}. Ejecute `sipsa conciliar`.")
        self.puntero = puntero


def _pid_vivo(pid: int) -> bool:
    """Solo diagnóstico (comando `estado`); la exclusión la garantiza flock, no esta función."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _leer_fd(fd: int) -> dict:
    try:
        data = os.pread(fd, 1 << 16, 0)
        return json.loads(data) if data.strip() else {}
    except Exception:
        return {}


def _escribir_fd(fd: int, obj: dict) -> None:
    data = json.dumps(obj, ensure_ascii=False).encode()
    os.ftruncate(fd, 0)
    os.pwrite(fd, data, 0)
    os.fsync(fd)


class Bloqueo:
    """Exclusión mutua de escritores con flock(2) (macOS y Linux, sistema de archivos local).

    - Adquisición: LOCK_EX | LOCK_NB. Si otro proceso lo tiene, EjecucionEnCurso; el archivo no se toca.
    - Recuperación: un bloqueo de un proceso muerto ya fue liberado por el sistema operativo; quien lo adquiere
      lee la ficha del dueño anterior *mientras lo sostiene* (solo diagnóstico).
    - Liberación: solo el dueño, sobre su propio descriptor; el archivo nunca se borra.
    - Trabajadores huérfanos: se exige LOCK_EX momentáneo sobre `.trabajadores` (los trabajadores sostienen LOCK_SH).
    """

    def __init__(self, d: Path, run_id: str):
        self.path, self.trab, self.run_id, self.fd = d / ".bloqueo", d / ".trabajadores", run_id, None
        self.anterior: dict | None = None

    @property
    def tomado(self) -> bool:
        return self.fd is not None

    def tomar(self) -> dict | None:
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o644)  # O_CLOEXEC por defecto (PEP 446)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            info = _leer_fd(fd)
            os.close(fd)
            raise EjecucionEnCurso(f"Otra ejecución tiene el bloqueo: {info}")
        try:
            tfd = os.open(self.trab, os.O_RDWR | os.O_CREAT, 0o644)
            try:
                fcntl.flock(tfd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise EjecucionEnCurso("Trabajadores de una ejecución anterior siguen activos (bloqueo compartido "
                                       "en .trabajadores); se rechaza para no escribir en paralelo")
            finally:
                os.close(tfd)  # cerrar libera el LOCK_EX momentáneo si se obtuvo
            previo = _leer_fd(fd)
            self.anterior = previo if previo.get("run_id") and previo.get("estado") != "libre" else None
            _escribir_fd(fd, {"run_id": self.run_id, "pid": os.getpid(), "host": socket.gethostname(),
                              "desde": ahora(), "estado": "tomado"})
        except BaseException:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
            raise
        self.fd = fd
        return self.anterior

    def soltar(self) -> Exception | None:
        """Libera SIEMPRE el flock y cierra el descriptor. La ficha "libre" es diagnóstica: si no se puede
        escribir, el error se devuelve (no se lanza) para que el llamador lo informe sin ocultar la
        excepción principal ni contradecir una publicación ya confirmada (v2.1)."""
        if self.fd is None:
            return None
        err = None
        try:
            punto_fallo("liberar:ficha")
            _escribir_fd(self.fd, {"estado": "libre", "ultimo_run_id": self.run_id, "liberado": ahora()})
        except Exception as e:  # noqa: BLE001 - diagnóstico; la liberación no depende de esto
            err = e
        finally:
            try:
                fcntl.flock(self.fd, fcntl.LOCK_UN)
            finally:
                os.close(self.fd)  # cerrar el descriptor también libera el flock
                self.fd = None
        return err


class Estado:
    def __init__(self, run_dir: Path, registro: Path, run_id: str):
        self.path, self.registro, self.run_id = run_dir / "estado.json", registro, run_id
        self.data = {"run_id": run_id, "estado": "CREADA", "etapa": None, "inicio": ahora(), "eventos": []}

    def evento(self, estado: str, etapa: str | None = None, **extra) -> None:
        self.data.update({"estado": estado, "etapa": etapa, "actualizado": ahora(), **extra})
        ev = {"run_id": self.run_id, "ts": ahora(), "estado": estado, "etapa": etapa, **{k: v for k, v in extra.items() if k != "eventos"}}
        self.data["eventos"].append(ev)
        write_json_atomic(self.path, self.data)
        append_jsonl(self.registro, ev)
        print(f"[{ev['ts']}] {self.run_id} {estado} {etapa or ''}", flush=True)


# ---------------------------------------------------------------- fuentes y metadatos de captura

def verificar_fuentes() -> list[dict]:
    """Verifica XLSX (tamaño y SHA-256) y sus JSON laterales de captura contra la referencia aprobada.
    Devuelve las fuentes con `retrieved_at` tomado de `config/capturas_aprobadas.json` (no del archivo)."""
    fuentes = read_json(ROOT / "config/fuentes_congeladas.json")
    ref = read_json(ROOT / "config/capturas_aprobadas.json")
    capt = {c["local_path"]: c for c in ref["capturas"]}
    fallos, salida = [], []
    for f in fuentes:
        p = raw_dir() / Path(f["local_path"]).relative_to("raw")
        if not p.exists():
            fallos.append(f"falta {f['local_path']}")
            continue
        if p.stat().st_size != f["bytes"] or sha256_file(p) != f["sha256"]:
            fallos.append(f"huella distinta {f['local_path']}")
            continue
        c = capt.get(f["local_path"])
        if c is None or c["source_sha256"] != f["sha256"]:
            fallos.append(f"sin captura aprobada {f['local_path']}")
            continue
        s = raw_dir() / Path(c["sidecar_path"]).relative_to("raw")
        if not s.exists():
            fallos.append(f"falta metadato de captura {c['sidecar_path']}")
            continue
        if sha256_file(s) != c["sidecar_sha256"]:
            fallos.append(f"metadato de captura no aprobado {c['sidecar_path']}")
            continue
        salida.append({**f, "retrieved_at": c["retrieved_at"], "capture_sidecar_path": c["sidecar_path"],
                       "capture_sidecar_sha256": c["sidecar_sha256"], "capturas_version": ref["version"]})
    if fallos:
        raise ContratoFallido("Fuentes no aprobadas: " + "; ".join(fallos))
    return salida


# ---------------------------------------------------------------- normalización en paralelo

def _tarea_normalizar(args):
    """Corre en un proceso trabajador (contexto spawn). Sostiene LOCK_SH sobre .trabajadores mientras escribe
    y aborta si su proceso padre murió (lo comprueba después de tomar el bloqueo y durante la lectura)."""
    from . import normalizar
    kind, year, sha, cache, clave, run_id, env, padre, trab = args
    os.environ.update(env)
    fd = os.open(trab, os.O_RDWR | os.O_CREAT, 0o644)
    fcntl.flock(fd, fcntl.LOCK_SH)
    try:
        normalizar.PADRE = padre
        normalizar.comprobar_padre()
        return normalizar.normalizar_en_cache(kind, year, sha, Path(cache), clave, run_id)
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def manifiesto(carpeta: Path) -> dict:
    archivos = {}
    for p in sorted(carpeta.rglob("*")):
        if p.is_file() and p.name != "MANIFIESTO.json":
            archivos[str(p.relative_to(carpeta))] = {"sha256": sha256_file(p), "bytes": p.stat().st_size}
    return archivos


def huella_contenido(carpeta: Path) -> str:
    """Huella reproducible del contenido: tablas exportadas, perfiles y detalle Parquet.
    Excluye sipsa.duckdb (formato binario no determinista) y metadatos de la ejecución."""
    partes = {}
    for sub in ["tablas", "perfiles", "detalle"]:
        for p in sorted((carpeta / sub).rglob("*")):
            if p.is_file() and not (p.name == "perfil.json"):
                partes[str(p.relative_to(carpeta))] = sha256_file(p)
            elif p.name == "perfil.json":
                d = json.loads(p.read_text())
                d.pop("duration_seconds", None)
                partes[str(p.relative_to(carpeta))] = sha256_bytes(json.dumps(d, sort_keys=True).encode())
    return sha256_bytes(json.dumps(partes, sort_keys=True).encode())


def _archivos_solo_lectura(carpeta: Path) -> None:
    for p in carpeta.rglob("*"):
        if p.is_file():
            p.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)


def _directorios_solo_lectura(carpeta: Path) -> None:
    # Después de mover: en macOS rename() de un directorio exige permiso de escritura sobre él.
    for p in sorted([x for x in carpeta.rglob("*") if x.is_dir()], reverse=True) + [carpeta]:
        p.chmod(0o555)


# ---------------------------------------------------------------- confirmación y conciliación

def _historial(d: Path) -> list[dict]:
    p = d / "historial_aprobados.jsonl"
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            out.append({"linea_ilegible": line[:200]})  # se conserva el rastro, no se reescribe
    return out


def _append_seguro(path: Path, obj: dict) -> Exception | None:
    """Anexa un evento de registro sin dejar que su fallo oculte la excepción en curso."""
    try:
        append_jsonl(path, obj)
        return None
    except Exception as e:  # noqa: BLE001
        print(f"No se pudo registrar {obj.get('estado')} en {path.name}: {type(e).__name__}: {e}", flush=True)
        return e


def _cerrar_bloqueo(lock: "Bloqueo", d: Path, exc_principal: BaseException | None, advertencias: list) -> None:
    """Libera el bloqueo (siempre) y clasifica un fallo de la ficha diagnóstica:
    - con una excepción en curso: se adjunta como nota; la causa principal se conserva y no se reemplaza;
    - tras una operación exitosa: advertencia visible (en el resultado, stderr y registro), sin cambiar el
      resultado de la publicación, que ya está confirmada y registrada. Decisión D-23."""
    err = lock.soltar()
    if err is None:
        return
    msg = (f"Limpieza: no se pudo escribir la ficha diagnóstica del bloqueo ({type(err).__name__}: {err}); "
           f"el bloqueo SÍ se liberó")
    if exc_principal is not None:
        exc_principal.add_note(msg)
    else:
        advertencias.append(msg)
    _append_seguro(d / "registro_ejecuciones.jsonl", {"run_id": lock.run_id, "ts": ahora(), "estado": "ADVERTENCIA_LIMPIEZA",
                                                      "etapa": "liberar", "detalle": msg})


def _registrar_historial(d: Path, puntero: dict, **extra) -> bool:
    """Idempotente por publicacion_id. Devuelve True si añadió la entrada."""
    if any(h.get("publicacion_id") == puntero["publicacion_id"] for h in _historial(d)):
        return False
    punto_fallo(f"{puntero['contexto']}:historial")
    append_jsonl(d / "historial_aprobados.jsonl", {**puntero, **extra})
    return True


def _confirmar(d: Path, puntero: dict, finalizar=None) -> None:
    """Ejecuta el punto de confirmación y TODOS los registros posteriores (historial y evento final `finalizar`).
    Antes del os.replace: excepción normal (el puntero anterior sigue vigente).
    Después: cualquier fallo es PublicacionConRegistroPendiente."""
    ctx = puntero["contexto"]
    punto_fallo(f"{ctx}:antes_de_apuntar")
    try:
        write_json_atomic(d / "APROBADO.json", puntero)  # <-- PUNTO DE CONFIRMACIÓN
    except BaseException:
        if _puntero_es(d, puntero):  # el reemplazo ocurrió aunque algo posterior falló
            raise PublicacionConRegistroPendiente(puntero, RuntimeError("fallo tras os.replace"))
        raise
    try:
        punto_fallo(f"{ctx}:tras_apuntar")
        _registrar_historial(d, puntero)
        if finalizar is not None:
            punto_fallo(f"{ctx}:evento_final")
            finalizar()
    except BaseException as e:
        raise PublicacionConRegistroPendiente(puntero, e) from e


def _puntero_es(d: Path, puntero: dict) -> bool:
    try:
        return read_json(d / "APROBADO.json").get("publicacion_id") == puntero["publicacion_id"]
    except Exception:
        return False


def conciliar(d: Path | None = None) -> dict:
    """Concilia registro y estados con la publicación efectiva. Requiere el bloqueo (lo toma si no se pasa d).
    - Ejecución activa sin dueño vivo: si APROBADO.json apunta a ella, se confirmó -> PUBLICADA (conciliada);
      si no, ABANDONADA (su lote, si existe, queda huérfano y no aprobado).
    - PUBLICADA_REGISTRO_PENDIENTE -> PUBLICADA tras completar el historial.
    - El puntero vigente siempre queda registrado en historial_aprobados.jsonl."""
    propio = d is None
    d = d or datos_dir()
    lock = None
    exc_principal, advertencias = None, []
    if propio:
        lock = Bloqueo(d, "conciliar-" + secrets.token_hex(3))
        lock.tomar()
    try:
        acciones = []
        ap = read_json(d / "APROBADO.json") if (d / "APROBADO.json").exists() else None
        if ap and ap.get("publicacion_id") and _registrar_historial(d, ap, conciliado=ahora()):
            acciones.append({"accion": "historial_completado", "publicacion_id": ap["publicacion_id"], "lote_id": ap["lote_id"]})
            append_jsonl(d / "registro_ejecuciones.jsonl", {"run_id": _rid(ap["publicacion_id"]), "ts": ahora(), "estado": "REGISTRO_CONCILIADO",
                                                            "etapa": "publicar", "publicacion_id": ap["publicacion_id"]})
        publicadas = {h.get("publicacion_id") for h in _historial(d)}
        # v2.1: reversiones cuyo último evento no es terminal (el estado vive en registro_ejecuciones.jsonl).
        for rid, ult in _reversiones_pendientes(d).items():
            pid = ult.get("publicacion_id") or f"pub-{rid}"
            confirmada = pid in publicadas or (bool(ap) and ap.get("publicacion_id") == pid)
            nuevo = "PUBLICADA" if confirmada else "ABANDONADA"
            append_jsonl(d / "registro_ejecuciones.jsonl", {"run_id": rid, "ts": ahora(), "estado": nuevo, "etapa": "conciliar",
                                                            "estado_previo": ult.get("estado"), "publicacion_id": pid,
                                                            "lote_id": ult.get("lote_id"), "conciliado": True})
            acciones.append({"accion": f"{ult.get('estado')}->{nuevo}", "run_id": rid, "publicacion_id": pid})
        for p in sorted((d / "ejecuciones").glob("*/estado.json")) if (d / "ejecuciones").exists() else []:
            info = read_json(p)
            est = info.get("estado")
            confirmado = ((bool(ap) and ap.get("run_id") == info["run_id"] and ap.get("contexto") == "publicar")
                          or f"pub-{info['run_id']}" in publicadas)
            nuevo = None
            if est in ESTADOS_ACTIVOS:
                nuevo = "PUBLICADA" if confirmado else "ABANDONADA"
            elif est == "PUBLICADA_REGISTRO_PENDIENTE":
                nuevo = "PUBLICADA"
            if nuevo:
                info.update({"estado_previo": est, "estado": nuevo, "conciliado": ahora()})
                if confirmado:
                    info.update({"lote_id": ap["lote_id"], "publicacion_id": ap["publicacion_id"]})
                info.setdefault("eventos", []).append({"ts": ahora(), "estado": nuevo, "etapa": "conciliar", "previo": est})
                write_json_atomic(p, info)
                append_jsonl(d / "registro_ejecuciones.jsonl", {"run_id": info["run_id"], "ts": ahora(), "estado": nuevo,
                                                                "etapa": "conciliar", "estado_previo": est})
                acciones.append({"accion": f"{est}->{nuevo}", "run_id": info["run_id"]})
        return {"acciones": acciones, "aprobado": ap and ap["lote_id"], "advertencias": advertencias}
    except BaseException as e:
        exc_principal = e
        raise
    finally:
        if lock:
            _cerrar_bloqueo(lock, d, exc_principal, advertencias)


TERMINALES_REVERSION = ("PUBLICADA", "FALLIDA", "ABANDONADA")


def _rid(publicacion_id: str) -> str:
    return publicacion_id[4:] if publicacion_id.startswith("pub-") else publicacion_id


def _reversiones_pendientes(d: Path) -> dict:
    """run_id de reversión -> último evento, para las que no tienen un evento terminal."""
    p = d / "registro_ejecuciones.jsonl"
    ultimo = {}
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            rid = str(ev.get("run_id", ""))
            # Eventos auxiliares (no cambian el estado de la reversión): advertencias y conciliación de historial.
            if rid.startswith("revertir-") and ev.get("estado") not in ("ADVERTENCIA_LIMPIEZA", "REGISTRO_CONCILIADO"):
                ultimo[rid] = ev
    return {r: ev for r, ev in ultimo.items() if ev.get("estado") not in TERMINALES_REVERSION}


# ---------------------------------------------------------------- construcción

def construir(sin_cache: bool = False, trabajadores: int | None = None) -> dict:
    from .construir import construir_lote
    from .validar import validar_lote

    d = datos_dir()
    for sub in ["ejecuciones", "lotes", "cache/normalizado"]:
        (d / sub).mkdir(parents=True, exist_ok=True)
    run_id = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + secrets.token_hex(3)
    run_dir = d / "ejecuciones" / run_id
    salida = run_dir / "salida"
    lock = Bloqueo(d, run_id)
    anterior = lock.tomar()  # Si falla, no se crea nada.
    estado = None
    confirmado = False
    exc_principal, advertencias = None, []
    try:
        conc = conciliar(d)  # bajo el bloqueo: estados y registro de ejecuciones previas
        punto_pausa("construir:bloqueo_tomado")
        run_dir.mkdir()
        estado = Estado(run_dir, d / "registro_ejecuciones.jsonl", run_id)
        aprobado_antes = read_json(d / "APROBADO.json") if (d / "APROBADO.json").exists() else None
        codigo = huella_codigo()
        t0 = time.monotonic()
        estado.evento("EN_CURSO", "fuentes", bloqueo_anterior=anterior, conciliacion=conc["acciones"])
        fuentes = verificar_fuentes()
        write_json_atomic(run_dir / "entradas.json", {
            "run_id": run_id, "inicio": ahora(), "codigo": codigo, "entorno": entorno(), "sin_cache": sin_cache,
            "raw": str(raw_dir()), "aprobado_al_iniciar": aprobado_antes and aprobado_antes["lote_id"],
            "bloqueo_anterior_no_liberado": anterior, "conciliacion_previa": conc["acciones"],
            "capturas": [{k: f[k] for k in ("local_path", "sha256", "capture_sidecar_path", "capture_sidecar_sha256",
                                            "retrieved_at", "capturas_version")} for f in fuentes]})
        punto_fallo("fuentes")

        estado.evento("EN_CURSO", "normalizar")
        clave = huella_normalizador()
        # Con el bloqueo y sin trabajadores activos, cualquier temporal pertenece a una ejecución terminada.
        for tmp in (d / "cache" / "normalizado").glob(".tmp-*"):
            shutil.rmtree(tmp, ignore_errors=True)
            estado.evento("EN_CURSO", "normalizar", temporal_descartado=tmp.name)
        cache = (run_dir / "normalizado_sin_cache") if sin_cache else (d / "cache" / "normalizado")
        cache.mkdir(parents=True, exist_ok=True)
        anuales = sorted([f for f in fuentes if f["year"]], key=lambda f: (-f["bytes"], f["tipo"], f["year"]))
        env = {k: v for k, v in os.environ.items() if k.startswith("SIPSA_")}
        n = trabajadores or int(os.environ.get("SIPSA_TRABAJADORES", "3"))
        normalizados = []
        # spawn en todas las plataformas: los trabajadores no heredan el descriptor del bloqueo principal.
        pool = ProcessPoolExecutor(max_workers=n, mp_context=multiprocessing.get_context("spawn"))
        try:
            futs = [pool.submit(_tarea_normalizar, (f["tipo"], f["year"], f["sha256"], str(cache), clave, run_id, env,
                                                    os.getpid(), str(lock.trab))) for f in anuales]
            for fu in as_completed(futs):
                r = fu.result()
                normalizados.append(r)
                print("NORMALIZADO", r["kind"], r["year"], "reutilizado" if r["reutilizado"] else f"{r.get('segundos')} s", flush=True)
        except BaseException:
            pool.shutdown(wait=True, cancel_futures=True)  # no deja trabajadores escribiendo tras el fallo
            raise
        pool.shutdown(wait=True)
        normalizados.sort(key=lambda r: (r["kind"], r["year"]))
        estado.evento("EN_CURSO", "normalizar_completo", reutilizados=sum(r["reutilizado"] for r in normalizados))

        estado.evento("EN_CURSO", "construir")
        salida.mkdir()
        conteos = construir_lote(salida, normalizados, fuentes)

        estado.evento("EN_CURSO", "validar")
        if os.environ.get("SIPSA_INYECTAR_FALLO") == "validar:corromper_panel":
            from .construir import conectar, ejecutar_script, sql
            con = conectar(salida / "sipsa.duckdb")
            con.execute("UPDATE price_month SET price = price + 1 WHERE month = '2023-05' AND product_id = 'P01'")
            con.execute("DROP TABLE panel_mensual")
            ejecutar_script(con, sql("panel.sql"))
            con.close()
        informe = validar_lote(salida, normalizados, fuentes)
        write_json_atomic(salida / "validacion.json", {**informe, "conteos": conteos})
        if informe["failed"]:
            raise ContratoFallido(f"{informe['failed']} contratos fallidos: " +
                                  ", ".join(c["check"] for c in informe["checks"] if c["status"] == "FAIL"))

        estado.evento("EN_CURSO", "publicar")
        punto_pausa("publicar:antes_de_reverificar")
        # Reverificación de fuentes y capturas inmediatamente antes de confirmar (cambio durante la ejecución).
        if verificar_fuentes() != fuentes:
            raise ContratoFallido("Las fuentes o sus metadatos de captura cambiaron durante la ejecución")
        hc = huella_contenido(salida)
        lote_id = f"lote-{run_id[:16]}-{hc[:12]}"
        shutil.copyfile(run_dir / "entradas.json", salida / "entradas.json")
        write_json_atomic(salida / "LOTE.json", {"lote_id": lote_id, "run_id": run_id, "huella_contenido": hc,
                                                 "codigo_sha256": codigo["sha256"], "creado": ahora(),
                                                 "segundos": round(time.monotonic() - t0, 1),
                                                 "reutilizo_cache": any(r["reutilizado"] for r in normalizados),
                                                 "contratos": {"passed": informe["passed"], "failed": informe["failed"]}})
        man = manifiesto(salida)
        write_json_atomic(salida / "MANIFIESTO.json", {"lote_id": lote_id, "archivos": man})
        man_sha = sha256_file(salida / "MANIFIESTO.json")
        _archivos_solo_lectura(salida)
        destino = d / "lotes" / lote_id
        os.rename(salida, destino)  # atómico: mismo volumen
        _directorios_solo_lectura(destino)
        fsync_dir(d / "lotes")
        puntero = {"lote_id": lote_id, "ruta": f"lotes/{lote_id}", "manifiesto_sha256": man_sha, "huella_contenido": hc,
                   "run_id": run_id, "publicacion_id": f"pub-{run_id}", "contexto": "publicar", "promovido": ahora(),
                   "anterior": aprobado_antes and aprobado_antes["lote_id"]}
        estado.evento("PUBLICANDO", "publicar", lote_id=lote_id, publicacion_id=puntero["publicacion_id"])
        try:
            _confirmar(d, puntero, finalizar=lambda: estado.evento(
                "PUBLICADA", "publicar", lote_id=lote_id, huella_contenido=hc, publicacion_id=puntero["publicacion_id"]))
        except PublicacionConRegistroPendiente:
            confirmado = True
            raise
        confirmado = True
        if sin_cache:
            shutil.rmtree(cache, ignore_errors=True)  # el lote conserva enlaces duros al detalle
        return {**puntero, "advertencias": advertencias}  # la lista se completa al liberar el bloqueo
    except PublicacionConRegistroPendiente as e:
        exc_principal = e
        _evento_seguro(estado, "PUBLICADA_REGISTRO_PENDIENTE", "publicar", error=str(e), lote_id=e.puntero["lote_id"],
                       publicacion_id=e.puntero["publicacion_id"])
        raise
    except BaseException as e:
        if estado is not None:
            if confirmado or (estado.data.get("publicacion_id") and _puntero_es(d, {"publicacion_id": estado.data["publicacion_id"]})):
                # Defensa: un fallo tras la confirmación nunca se informa como FALLIDA.
                _evento_seguro(estado, "PUBLICADA_REGISTRO_PENDIENTE", "publicar", error=f"{type(e).__name__}: {e}")
                exc_principal = PublicacionConRegistroPendiente(read_json(d / "APROBADO.json"), e)
                raise exc_principal from e
            _evento_seguro(estado, "FALLIDA", estado.data.get("etapa"), error=f"{type(e).__name__}: {e}",
                           traza=traceback.format_exc()[-4000:])
        exc_principal = e
        raise
    finally:
        _cerrar_bloqueo(lock, d, exc_principal, advertencias)


def _evento_seguro(estado: Estado | None, *args, **kw) -> None:
    if estado is None:
        return
    try:
        estado.evento(*args, **kw)
    except BaseException as ex:  # el registro puede ser lo que falla; el código de salida ya lo comunica
        print(f"No se pudo registrar el estado {args[0]}: {type(ex).__name__}: {ex}", flush=True)


def aprobado() -> dict:
    d = datos_dir()
    p = d / "APROBADO.json"
    if not p.exists():
        raise FileNotFoundError("No hay un lote aprobado")
    return read_json(p)


def verificar_lote(lote_dir: Path, completo: bool = True, sin_hash_prefijos: tuple = ()) -> list[str]:
    """completo=False solo compara tamaños. sin_hash_prefijos permite omitir el SHA-256 de archivos que
    el consumidor no lee (p. ej. el detalle Parquet al consultar sipsa.duckdb)."""
    errores = []
    man = read_json(lote_dir / "MANIFIESTO.json")
    for rel, info in man["archivos"].items():
        p = lote_dir / rel
        con_hash = completo and not rel.startswith(sin_hash_prefijos)
        if not p.exists():
            errores.append(f"falta {rel}")
        elif p.stat().st_size != info["bytes"] or (con_hash and sha256_file(p) != info["sha256"]):
            errores.append(f"alterado {rel}")
    extra = [str(p.relative_to(lote_dir)) for p in lote_dir.rglob("*") if p.is_file()
             and p.name != "MANIFIESTO.json" and str(p.relative_to(lote_dir)) not in man["archivos"]]
    errores += [f"no declarado {x}" for x in extra]
    return errores


def verificar_aprobado(completo: bool = True, sin_hash_prefijos: tuple = ()) -> dict:
    d = datos_dir()
    ap = aprobado()
    lote_dir = d / ap["ruta"]
    errores = []
    if sha256_file(lote_dir / "MANIFIESTO.json") != ap["manifiesto_sha256"]:
        errores.append("MANIFIESTO.json no coincide con el puntero")
    errores += verificar_lote(lote_dir, completo, sin_hash_prefijos)
    return {"lote_id": ap["lote_id"], "errores": errores, "ok": not errores}


def revertir(lote_id: str) -> dict:
    """Vuelve a apuntar a un lote anterior íntegro (verificado) sin reconstruir. Mismo punto de confirmación."""
    d = datos_dir()
    rid = "revertir-" + dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + secrets.token_hex(3)
    lock = Bloqueo(d, rid)
    lock.tomar()
    reg = d / "registro_ejecuciones.jsonl"
    exc_principal, advertencias = None, []
    try:
        conciliar(d)
        lote_dir = d / "lotes" / lote_id
        lote = read_json(lote_dir / "LOTE.json")
        errores = verificar_lote(lote_dir)
        if errores:
            raise ContratoFallido(f"Lote {lote_id} no íntegro: {errores[:5]}")
        antes = aprobado()
        puntero = {"lote_id": lote_id, "ruta": f"lotes/{lote_id}", "manifiesto_sha256": sha256_file(lote_dir / "MANIFIESTO.json"),
                   "huella_contenido": lote["huella_contenido"], "run_id": lote["run_id"], "publicacion_id": f"pub-{rid}",
                   "contexto": "revertir", "promovido": ahora(), "anterior": antes["lote_id"], "motivo": "reversión manual"}
        append_jsonl(reg, {"run_id": rid, "ts": ahora(), "estado": "PUBLICANDO", "etapa": "revertir", "lote_id": lote_id,
                           "publicacion_id": puntero["publicacion_id"]})
        try:
            # v2.1: el evento final PUBLICADA forma parte del tramo posterior a la confirmación.
            _confirmar(d, puntero, finalizar=lambda: append_jsonl(reg, {
                "run_id": rid, "ts": ahora(), "estado": "PUBLICADA", "etapa": "revertir", "lote_id": lote_id,
                "publicacion_id": puntero["publicacion_id"]}))
        except PublicacionConRegistroPendiente:
            _append_seguro(reg, {"run_id": rid, "ts": ahora(), "estado": "PUBLICADA_REGISTRO_PENDIENTE", "etapa": "revertir",
                                 "lote_id": lote_id, "publicacion_id": puntero["publicacion_id"]})
            raise
        except BaseException as e:
            _append_seguro(reg, {"run_id": rid, "ts": ahora(), "estado": "FALLIDA", "etapa": "revertir", "lote_id": lote_id,
                                 "publicacion_id": puntero["publicacion_id"], "error": f"{type(e).__name__}: {e}"})
            raise
        return {**puntero, "advertencias": advertencias}
    except BaseException as e:
        exc_principal = e
        raise
    finally:
        _cerrar_bloqueo(lock, d, exc_principal, advertencias)


def resumen_estado() -> dict:
    """Solo lectura. No toma el bloqueo; la vitalidad es diagnóstica (ficha del bloqueo + PID)."""
    d = datos_dir()
    ap = read_json(d / "APROBADO.json") if (d / "APROBADO.json").exists() else None
    try:
        dueño = json.loads((d / ".bloqueo").read_text()) if (d / ".bloqueo").exists() else {}
    except Exception:
        dueño = {}
    runs = []
    for p in sorted((d / "ejecuciones").glob("*/estado.json")) if (d / "ejecuciones").exists() else []:
        info = read_json(p)
        est = info.get("estado")
        if est in ESTADOS_ACTIVOS:
            vivo = (dueño.get("estado") == "tomado" and dueño.get("run_id") == info["run_id"]
                    and dueño.get("host") == socket.gethostname() and _pid_vivo(int(dueño.get("pid", 0) or 0)))
            if not vivo:
                est = f"INTERRUMPIDA ({est}; se concilia en la próxima ejecución)"
        runs.append({"run_id": info["run_id"], "estado": est, "etapa": info.get("etapa"),
                     "lote_id": info.get("lote_id"), "error": (info.get("error") or "")[:200]})
    lotes = sorted(p.name for p in (d / "lotes").glob("lote-*")) if (d / "lotes").exists() else []
    hist = _historial(d)
    referenciados = {h.get("lote_id") for h in hist} | ({ap["lote_id"]} if ap else set())
    historial_pendiente = bool(ap and ap.get("publicacion_id") and
                               not any(h.get("publicacion_id") == ap["publicacion_id"] for h in hist))
    cierres = [{"run_id": r["run_id"], "estado": r["estado"]} for r in runs if r["estado"] == "PUBLICADA_REGISTRO_PENDIENTE"]
    cierres += [{"run_id": rid, "estado": ev.get("estado"), "publicacion_id": ev.get("publicacion_id")}
                for rid, ev in _reversiones_pendientes(d).items()]
    return {"aprobado": ap and ap["lote_id"], "publicacion_id": ap and ap.get("publicacion_id"),
            "registro_pendiente": historial_pendiente or bool(cierres),
            "historial_pendiente": historial_pendiente, "cierres_pendientes": cierres,
            "bloqueo": dueño, "ejecuciones": runs, "lotes": lotes,
            "lotes_huerfanos": [x for x in lotes if x not in referenciados]}
