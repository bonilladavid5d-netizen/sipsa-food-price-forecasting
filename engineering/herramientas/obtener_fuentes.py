"""Obtiene las 17 fuentes oficiales congeladas del DANE (SIPSA) y las coloca en datos/raw/ con sus metadatos de captura.

Para cada fuente de config/fuentes_congeladas.json:
  1. descarga el XLSX desde su URL oficial (o lo copia desde --desde CARPETA_RAW, p. ej. los ZIP congelados extraídos);
  2. exige el tamaño y el SHA-256 congelados; si difieren, el DANE pudo haber revisado el archivo: se rechaza, no se usa;
  3. copia el JSON de captura desde fuentes/metadatos_captura/ y exige su SHA-256 (config/capturas_aprobadas.json).
No modifica nada si una huella no coincide. Requiere ~750 MB libres.
Uso: python herramientas/obtener_fuentes.py [--desde CARPETA_RAW]
Fuente: Departamento Administrativo Nacional de Estadística: www.dane.gov.co
"""
import argparse, hashlib, json, shutil, sys, urllib.request
from pathlib import Path
RAIZ = Path(__file__).resolve().parents[1]
sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()


def obtener(f, destino: Path, desde: Path | None) -> str:
    if destino.exists() and destino.stat().st_size == f["bytes"] and sha(destino) == f["sha256"]:
        return "ya presente"
    tmp = destino.with_suffix(".part")
    destino.parent.mkdir(parents=True, exist_ok=True)
    if desde:
        shutil.copyfile(desde / Path(f["local_path"]).relative_to("raw"), tmp)
    else:
        req = urllib.request.Request(f["url"], headers={"User-Agent": "sipsa-food-price-forecasting/1.0"})
        with urllib.request.urlopen(req, timeout=120) as r, tmp.open("wb") as out:
            shutil.copyfileobj(r, out, 1 << 20)
    if tmp.stat().st_size != f["bytes"] or sha(tmp) != f["sha256"]:
        tmp.unlink()
        raise ValueError(f"{f['local_path']}: tamaño o SHA-256 distintos de la versión congelada (posible revisión del DANE); no se usa")
    tmp.rename(destino)
    return "obtenida y verificada"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--desde", type=Path, help="carpeta raw/ local con los XLSX (en vez de descargar)")
    a = ap.parse_args()
    fuentes = json.loads((RAIZ / "config/fuentes_congeladas.json").read_text())
    capturas = {c["local_path"]: c for c in json.loads((RAIZ / "config/capturas_aprobadas.json").read_text())["capturas"]}
    raw = RAIZ / "datos/raw"
    fallos = 0
    for f in fuentes:
        rel = Path(f["local_path"]).relative_to("raw")
        try:
            estado = obtener(f, raw / rel, a.desde.resolve() if a.desde else None)
            c = capturas[f["local_path"]]
            meta_src = RAIZ / "fuentes/metadatos_captura" / Path(c["sidecar_path"]).relative_to("raw")
            if sha(meta_src) != c["sidecar_sha256"]:
                raise ValueError(f"{meta_src.name}: metadato de captura distinto del aprobado")
            shutil.copyfile(meta_src, raw / Path(c["sidecar_path"]).relative_to("raw"))
            print(f"OK   {f['local_path']:40s} {f['bytes']:>11,d} bytes  {estado}")
        except Exception as e:
            fallos += 1
            print(f"FALLA {f['local_path']}: {e}", file=sys.stderr)
    print(f"{len(fuentes) - fallos} de {len(fuentes)} fuentes verificadas en {raw}")
    sys.exit(1 if fallos else 0)


if __name__ == "__main__":
    main()
