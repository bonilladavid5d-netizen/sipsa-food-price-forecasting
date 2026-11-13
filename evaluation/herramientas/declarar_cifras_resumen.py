"""Declara las cifras que cita RESUMEN_RESULTADOS.md, recalculadas desde predicciones.csv (recalcular.cifras_clave).
Escribe resultados/cifras_resumen.json con valores redondeados a 2 decimales y su forma escrita en el resumen.
El validador recalcula de nuevo y exige: (a) igualdad con estos valores; (b) que cada forma escrita aparezca en
RESUMEN_RESULTADOS.md. Uso único tras redactar el resumen; no forma parte de la ejecución ni de los controles."""
import json, sys
from pathlib import Path
RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
from evaluacion.recalcular import recalcular
r = recalcular()
c = {k: round(v, 2) for k, v in r["cifras_recalculadas"].items()}
es = lambda x, d=2: f"{x:.{d}f}".replace(".", ",")
escritas = {
    "reduccion_mase_rf_precio_vs_ingenuo_pct_conjunta": f"{es(c['reduccion_mase_rf_precio_vs_ingenuo_pct_conjunta'])} %",
    "reduccion_mase_rf_precio_vs_ingenuo_pct_2024": f"{es(c['reduccion_mase_rf_precio_vs_ingenuo_pct_2024'])} %",
    "reduccion_mase_rf_precio_vs_ingenuo_pct_2025": f"{es(c['reduccion_mase_rf_precio_vs_ingenuo_pct_2025'])} %",
    "mediana_mae_rf_precio_cop_kg": es(c["mediana_mae_rf_precio_cop_kg"]),
    "mediana_mae_ingenuo_cop_kg": es(c["mediana_mae_ingenuo_cop_kg"]),
    "cambio_mediana_mae_rf_precio_vs_ingenuo_pct": f"+{es(c['cambio_mediana_mae_rf_precio_vs_ingenuo_pct'])} %",
    "error_pct_firmado_medio_rf_precio": f"+{es(c['error_pct_firmado_medio_rf_precio'])} %",
    "series_rf_precio_error_firmado_positivo_cop_kg": f"{int(c['series_rf_precio_error_firmado_positivo_cop_kg'])} de 30",
    "cambio_mase_con_abast_rf_pct": f"+{es(c['cambio_mase_con_abast_rf_pct'])} %",
    "cambio_mase_con_abast_ridge_pct": f"+{es(c['cambio_mase_con_abast_ridge_pct'])} %",
}
out = {"fuente": "recalculado desde resultados/predicciones.csv con evaluacion/recalcular.cifras_clave (retro_r1)",
       "redondeo": 2, "cifras": c, "escritas_en_resumen": escritas}
(RAIZ / "resultados/cifras_resumen.json").write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n")
print(json.dumps(escritas, ensure_ascii=False, indent=1))
