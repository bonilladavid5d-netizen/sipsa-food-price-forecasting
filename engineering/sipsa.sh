#!/usr/bin/env bash
# Punto de entrada único de la receta. Ejemplos:
#   bash sipsa.sh construir            # verifica fuentes, normaliza (con caché), construye, valida y publica
#   bash sipsa.sh construir --sin-cache
#   bash sipsa.sh estado | verificar | fuentes | revertir <lote_id>
#   bash sipsa.sh consultar --escenario retro_r1 --origen 2023-07
set -euo pipefail
cd "$(dirname "$0")"
SIPSA_PYTHON="${SIPSA_PYTHON:-.venv/bin/python}"
# Copia pública: las referencias de regresión con series del DANE no se distribuyen; se reconstruyen localmente.
if [ "${1:-}" = "construir" ]; then
  for r in referencia_panel_viabilidad.csv referencia_candidatos_viabilidad.csv referencia_conciliacion_viabilidad.csv; do
    if [ ! -f "config/$r" ]; then
      echo "NO EJECUTADO: falta config/$r (no se distribuye; contiene series del DANE)." >&2
      echo "Ejecute primero: $SIPSA_PYTHON herramientas/reconstruir_referencias.py" >&2
      exit 3
    fi
  done
fi
exec "$SIPSA_PYTHON" -m sipsa "$@"
