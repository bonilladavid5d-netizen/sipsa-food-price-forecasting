#!/usr/bin/env bash
# Orden documentada de reproducción de la evaluación predictiva SIPSA (David Bonilla).
# Requisitos: Python 3.13, el proyecto de ingeniería con su lote aprobado (lote-20261111T192146Z-0dba2228adae)
# y acceso a pip para instalar requirements.lock.
#   SIPSA_PROYECTO_INGENIERIA=/ruta/a/engineering  (en la copia pública, por defecto ../engineering)
set -euo pipefail
cd "$(dirname "$0")"
if [ -z "${SIPSA_PROYECTO_INGENIERIA:-}" ] && [ -d ../engineering ]; then export SIPSA_PROYECTO_INGENIERIA="$(cd ../engineering && pwd)"; fi
PY="${SIPSA_PYTHON:-.venv/bin/python}"
if [ ! -x "$PY" ]; then python3 -m venv .venv && .venv/bin/python -m pip install -q -r requirements.lock; PY=.venv/bin/python; fi
# 1. Si no existe registro de congelamiento, congelar (en una reproducción se copia el registro original).
[ -f resultados/registro_protocolo.json ] || "$PY" -m evaluacion congelar
# 2. Selección (2023-01..10), congelamiento de parámetros y evaluación 2024-2025 en tres escenarios.
"$PY" -m evaluacion ejecutar
# 3. Pruebas de fuga (sintéticas y copia derivada del lote).
"$PY" -m unittest pruebas.test_fugas
# 4. Recalcular métricas desde predicciones.csv. `recalcular` retira cualquier aprobación anterior; por eso va antes
#    de `controles`, el único comando que emite VALIDACION_VIGENTE.json (solo si todo pasa).
"$PY" -m evaluacion recalcular
"$PY" -m evaluacion controles
# 5. Figuras.
"$PY" -m evaluacion figuras
