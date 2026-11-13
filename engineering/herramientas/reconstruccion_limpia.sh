#!/usr/bin/env bash
# Reconstrucción desde cero en una carpeta limpia: código y configuración copiados, entorno virtual
# nuevo instalado desde requirements.lock, fuentes extraídas de los dos ZIP congelados y
# normalización completa sin caché. Compara la huella de contenido con el lote aprobado del proyecto.
#
# Uso: bash herramientas/reconstruccion_limpia.sh <carpeta_destino_vacia> <ZIP_2018_2021> <ZIP_2022_2025>
set -euo pipefail
PROY="$(cd "$(dirname "$0")/.." && pwd)"
DEST="$1"
Z1="$(cd "$(dirname "$2")" && pwd)/$(basename "$2")"
Z2="$(cd "$(dirname "$3")" && pwd)/$(basename "$3")"
PYBASE="${SIPSA_PYTHON_BASE:-python3}"
[ -e "$DEST" ] && { echo "El destino ya existe: $DEST" >&2; exit 2; }
mkdir -p "$DEST"
cd "$DEST"
echo "== Copia de código y configuración (sin datos, sin entorno)"
tar -C "$PROY" -cf - sipsa sql config herramientas pruebas requirements.txt requirements.lock sipsa.sh | tar -xf -
echo "== Entorno nuevo: $($PYBASE --version)"
"$PYBASE" -m venv .venv
.venv/bin/python -m pip install --quiet --no-cache-dir -r requirements.lock
.venv/bin/python -m pip freeze > evidencia_pip_freeze.txt
echo "== Extracción de fuentes congeladas"
mkdir -p datos/fuentes_a datos/fuentes_b
unzip -q "$Z1" -d datos/fuentes_a
unzip -q "$Z2" -d datos/fuentes_b
(cd datos/fuentes_a && shasum -a 256 -c MANIFIESTO_ENTREGA.sha256 >/dev/null)
(cd datos/fuentes_b && shasum -a 256 -c MANIFIESTO_ENTREGA.sha256 >/dev/null)
mkdir -p datos/raw
cp -R datos/fuentes_a/raw/. datos/raw/
cp -R datos/fuentes_b/raw/. datos/raw/
rm -rf datos/fuentes_a datos/fuentes_b
echo "== Pruebas unitarias"
.venv/bin/python -m unittest pruebas.test_unitarias
echo "== Construcción completa sin caché"
SIPSA_PYTHON=.venv/bin/python bash sipsa.sh construir --sin-cache
.venv/bin/python -m sipsa verificar > verificacion.json
.venv/bin/python - "$PROY" <<'EOF'
import json, sys
from pathlib import Path
proy = Path(sys.argv[1])
limpio = json.loads(Path("datos/APROBADO.json").read_text())
original = json.loads((proy / "datos/APROBADO.json").read_text())
res = {"lote_limpio": limpio["lote_id"], "lote_proyecto": original["lote_id"],
       "huella_limpia": limpio["huella_contenido"], "huella_proyecto": original["huella_contenido"],
       "misma_huella_de_contenido": limpio["huella_contenido"] == original["huella_contenido"]}
a = json.loads((Path("datos") / limpio["ruta"] / "MANIFIESTO.json").read_text())["archivos"]
b = json.loads((proy / "datos" / original["ruta"] / "MANIFIESTO.json").read_text())["archivos"]
res["archivos_distintos"] = sorted(k for k in set(a) | set(b) if a.get(k, {}).get("sha256") != b.get(k, {}).get("sha256"))
Path("comparacion_con_proyecto.json").write_text(json.dumps(res, ensure_ascii=False, indent=2) + "\n")
print(json.dumps(res, ensure_ascii=False, indent=2))
sys.exit(0 if res["misma_huella_de_contenido"] else 1)
EOF
