"""Utilidades compartidas: rutas, huellas, escrituras atómicas y registro de eventos."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import platform
import sys
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def datos_dir() -> Path:
    """Directorio de datos de trabajo. Se puede redirigir con SIPSA_DATOS (pruebas)."""
    return Path(os.environ.get("SIPSA_DATOS", ROOT / "datos")).resolve()


def raw_dir() -> Path:
    """Fuentes congeladas. Se puede redirigir con SIPSA_RAW (pruebas de fuente alterada)."""
    return Path(os.environ.get("SIPSA_RAW", datos_dir() / "raw")).resolve()


def ahora() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fsync_dir(path: Path) -> None:
    try:
        fd = os.open(str(path), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def write_atomic(path: Path, data: bytes | str) -> None:
    """Escribe en un temporal del mismo directorio, fsync y os.replace (atómico en POSIX)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, str):
        data = data.encode("utf-8")
    tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    with tmp.open("wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    fsync_dir(path.parent)


def write_json_atomic(path: Path, obj) -> None:
    write_atomic(path, json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=False) + "\n")


def append_jsonl(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(obj, ensure_ascii=False, sort_keys=True) + "\n"
    with path.open("a", encoding="utf-8") as f:
        f.write(line)
        f.flush()
        os.fsync(f.fileno())


def read_json(path: Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def huella_codigo() -> dict:
    """Huella del código, SQL y configuración que determinan los resultados."""
    files = sorted(
        [p for p in (ROOT / "sipsa").glob("*.py")]
        + [p for p in (ROOT / "sql").glob("*.sql")]
        + [p for p in (ROOT / "config").glob("*") if p.is_file()]
        + [ROOT / "requirements.lock"]
    )
    per = {str(p.relative_to(ROOT)): sha256_file(p) for p in files if p.exists()}
    total = sha256_bytes(json.dumps(per, sort_keys=True).encode())
    return {"sha256": total, "archivos": per}


def huella_normalizador() -> str:
    """Clave de caché de la normalización: lector + normalizador + esquemas aprobados."""
    parts = [ROOT / "sipsa/xlsx_stream.py", ROOT / "sipsa/normalizar.py", ROOT / "config/esquemas_aprobados.json"]
    return sha256_bytes("".join(sha256_file(p) for p in parts).encode())


def entorno() -> dict:
    pk = {}
    for name in ["pandas", "numpy", "pyarrow", "duckdb", "lxml", "openpyxl"]:
        try:
            pk[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            pk[name] = None
    return {
        "python": sys.version.split()[0],
        "implementacion": platform.python_implementation(),
        "sistema": platform.system(),
        "version_sistema": platform.release(),
        "maquina": platform.machine(),
        "paquetes": pk,
    }


class FalloInyectado(RuntimeError):
    """Fallo deliberado para pruebas de interrupción. Nunca se activa sin SIPSA_INYECTAR_FALLO."""


def punto_fallo(nombre: str) -> None:
    """Si SIPSA_INYECTAR_FALLO coincide con `nombre`, interrumpe la ejecución en ese punto."""
    objetivos = {x.strip() for x in os.environ.get("SIPSA_INYECTAR_FALLO", "").split(",") if x.strip()}
    if nombre in objetivos:  # v2.1: admite varios puntos separados por comas (fallo previo + fallo de limpieza)
        if os.environ.get("SIPSA_FALLO_MODO") == "kill":
            # Simula un corte abrupto (SIGKILL) de toda la ejecución: proceso principal y trabajadores.
            os.killpg(os.getpgid(0), 9)
        raise FalloInyectado(f"Fallo inyectado en {nombre}")


def punto_pausa(nombre: str, limite_s: float = 600.0) -> None:
    """Sincronización para pruebas (no es una espera arbitraria): si SIPSA_PAUSA == nombre, crea
    <datos>/.pausa-<nombre> con el pid y espera hasta que la prueba borre ese archivo. Límite de seguridad."""
    if os.environ.get("SIPSA_PAUSA", "") != nombre:
        return
    import time
    marca = datos_dir() / f".pausa-{nombre.replace(':', '_')}"
    write_atomic(marca, json.dumps({"pid": os.getpid(), "ppid": os.getppid(), "desde": ahora()}))
    t0 = time.monotonic()
    while marca.exists():
        if time.monotonic() - t0 > limite_s:
            raise TimeoutError(f"Pausa de prueba sin liberar: {nombre}")
        time.sleep(0.05)


ZONA_CORTE = "America/Bogota"


def cierre_mes(mes: str) -> str:
    """Convención única de corte: un corte `t` es el CIERRE DEL MES CALENDARIO t en hora de Colombia,
    es decir, el último microsegundo antes de las 00:00 del día 1 de t+1 (UTC-05:00, sin horario de verano).
    No se usa el último día hábil: con datos mensuales y retrasos medidos en meses no cambia el conjunto
    permitido y evita depender de un calendario de festivos. Devuelve ISO 8601 con desfase."""
    from zoneinfo import ZoneInfo
    y, m = map(int, mes.split("-"))
    sig = dt.datetime(y + m // 12, m % 12 + 1, 1, tzinfo=ZoneInfo(ZONA_CORTE))
    return (sig - dt.timedelta(microseconds=1)).isoformat()
