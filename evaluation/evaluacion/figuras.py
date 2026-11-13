"""Tres figuras con el diseño fijado en el protocolo (sección 10). Solo leen tablas exportadas."""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

RAIZ = Path(__file__).resolve().parents[1]
RES = RAIZ / "resultados"
FIG = RES / "figuras"
# Paleta de referencia validada (dataviz/references/palette.md), modo claro.
AZUL, NARANJA, AQUA = "#2a78d6", "#eb6834", "#1baf7a"
TINTA, TINTA2, GRIS, SUPERFICIE = "#0b0b0b", "#52514e", "#a9a8a2", "#fcfcfb"
ETIQ = {"ingenuo": "Último precio", "estacional": "Mismo mes año anterior", "ridge_precio": "Ridge (precios)",
        "ridge_abast": "Ridge (+ abastecimiento)", "rf_precio": "Random Forest (precios)", "rf_abast": "Random Forest (+ abastecimiento)"}
FUENTE = "Fuente de los datos: DANE, SIPSA. Evaluación retrospectiva; escenarios de disponibilidad supuestos."


def _estilo(ax):
    ax.set_facecolor(SUPERFICIE)
    for s in ["top", "right"]:
        ax.spines[s].set_visible(False)
    for s in ["left", "bottom"]:
        ax.spines[s].set_color(GRIS)
    ax.tick_params(colors=TINTA2, labelsize=9)
    ax.grid(axis="x", color="#e6e5e0", linewidth=0.8)
    ax.set_axisbelow(True)


def figuras():
    FIG.mkdir(parents=True, exist_ok=True)
    cong = json.loads((RES / "seleccion/parametros_congelados.json").read_text())
    fam = cong["familia_principal"]
    ms = pd.read_csv(RES / "metricas_por_serie.csv")
    ap = pd.read_csv(RES / "aporte_abastecimiento.csv")

    # 1. Precisión: MASE por modelo (retro_r1), punto por serie + media.
    d = ms[(ms.escenario == "retro_r1") & ms.modelo.isin(ETIQ)]
    orden = d.groupby("modelo").mase.mean().sort_values(ascending=False).index.tolist()
    fig, ax = plt.subplots(figsize=(8, 4.2), dpi=150)
    fig.patch.set_facecolor(SUPERFICIE)
    _estilo(ax)
    rng = np.random.default_rng(0)
    for i, mod in enumerate(orden):
        v = d[d.modelo == mod].mase.to_numpy()
        ax.scatter(v, i + rng.uniform(-0.15, 0.15, len(v)), s=14, color=GRIS, alpha=0.8, linewidths=0, zorder=2)
        ax.scatter([v.mean()], [i], s=90, marker="D", color=AZUL if mod == cong["referente"] else TINTA, zorder=3,
                   edgecolors=SUPERFICIE, linewidths=1.5)
        ax.text(d.mase.max() * 1.0 + 0.08, i, f"media {v.mean():.3f}", ha="left", va="center", fontsize=8.5, color=TINTA)
    ax.set_yticks(range(len(orden)), [ETIQ[m] + (" — referente" if m == cong["referente"] else "") for m in orden])
    ax.set_xlabel("MASE estacional (m = 12); menor es mejor", color=TINTA2, fontsize=9)
    ax.set_xlim(right=d.mase.max() + 0.75)
    ax.set_title("Precisión 2024–2025 (retro_r1)\nMASE por serie (gris) y media de 30 series (rombo)",
                 loc="left", fontsize=10.5, color=TINTA)
    fig.text(0.01, 0.01, FUENTE, fontsize=7, color=TINTA2)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(FIG / "fig1_precision_por_modelo.png", facecolor=SUPERFICIE)
    plt.close(fig)

    # 2. Aporte del volumen por serie (familia principal), con controlada.
    a = ap[(ap.escenario == "retro_r1") & (ap.familia == fam) & (ap.anio == "todos")]
    p = a[a.tipo == "parametros_propios"].set_index(["product", "market"]).delta_mase
    c = a[a.tipo == "parametros_comunes_controlada"].set_index(["product", "market"]).delta_mase
    p = p.sort_values()
    c = c.reindex(p.index)
    abrev = {"Bogotá, D.C., Corabastos": "Corabastos", "Medellín, Central Mayorista de Antioquia": "CMA", "Bucaramanga, Centroabastos": "Centroabastos"}
    etiquetas = [f"{pr} · {abrev.get(mk, mk)}" for pr, mk in p.index]
    fig, ax = plt.subplots(figsize=(8, 8.5), dpi=150)
    fig.patch.set_facecolor(SUPERFICIE)
    _estilo(ax)
    y = np.arange(len(p))
    ax.axvline(0, color=TINTA2, linewidth=1)
    ax.hlines(y, np.minimum(p, c), np.maximum(p, c), color="#e0dfda", linewidth=2, zorder=1)
    iguales = bool(np.allclose(p.to_numpy(), c.to_numpy()))
    ax.scatter(c, y, s=70, facecolors="none", edgecolors=NARANJA, marker="s", linewidths=1.5, zorder=3,
               label="Controlada (mismos parámetros que sin volumen)")
    ax.scatter(p, y, s=28, color=AZUL, zorder=4, label="Parámetros propios", edgecolors=SUPERFICIE, linewidths=0.8)
    if iguales:
        ax.text(0.99, 0.08, "Los parámetros seleccionados con y sin volumen\ncoincidieron: ambas comparaciones son idénticas.",
                transform=ax.transAxes, ha="right", va="bottom", fontsize=8, color=TINTA2)
    ax.set_yticks(y, etiquetas, fontsize=8)
    nom = "Ridge" if fam == "ridge" else "Random Forest"
    ax.set_xlabel("Δ MASE = con abastecimiento − sin abastecimiento  (negativo = el volumen ayuda)", color=TINTA2, fontsize=9)
    ax.set_title(f"Aporte del abastecimiento por serie\n{nom} (familia principal), retro_r1, objetivos 2024–2025",
                 loc="left", fontsize=10.5, color=TINTA)
    ax.legend(loc="lower right", fontsize=8, frameon=False)
    fig.text(0.01, 0.005, FUENTE, fontsize=7, color=TINTA2)
    fig.tight_layout(rect=(0, 0.02, 1, 1))
    fig.savefig(FIG / "fig2_aporte_abastecimiento_por_serie.png", facecolor=SUPERFICIE)
    plt.close(fig)

    # 3. Estabilidad: Δ MASE medio por año y escenario, ambas familias.
    b = ap[ap.tipo == "parametros_propios"].groupby(["familia", "escenario", "anio"]).delta_mase.mean().reset_index()
    escs = ["retro_r1", "retro_p1_a2", "retro_r2"]
    anios = ["2024", "2025", "todos"]
    colores = dict(zip(escs, [AZUL, NARANJA, AQUA]))
    fig, axs = plt.subplots(1, 2, figsize=(9, 3.8), dpi=150, sharey=True)
    fig.patch.set_facecolor(SUPERFICIE)
    for ax, f in zip(axs, ["ridge", "rf"]):
        _estilo(ax)
        ax.grid(axis="y", color="#e6e5e0", linewidth=0.8)
        ax.grid(axis="x", visible=False)
        ax.axhline(0, color=TINTA2, linewidth=1)
        w = 0.26
        for j, e in enumerate(escs):
            vals = [b[(b.familia == f) & (b.escenario == e) & (b.anio == an)].delta_mase.iloc[0] for an in anios]
            ax.bar(np.arange(3) + (j - 1) * w, vals, width=w - 0.03, color=colores[e], label=e)
        ax.set_xticks(range(3), ["2024", "2025", "2024–2025"])
        ax.set_title(("Ridge" if f == "ridge" else "Random Forest") + (" (principal)" if f == fam else ""),
                     loc="left", fontsize=10, color=TINTA)
    axs[0].set_ylabel("Δ MASE medio (con − sin volumen)", color=TINTA2, fontsize=9)
    axs[1].legend(fontsize=8, frameon=False, title="Escenario", title_fontsize=8)
    fig.suptitle("Estabilidad del aporte del abastecimiento (negativo = mejora)", x=0.01, ha="left", fontsize=10.5, color=TINTA)
    fig.text(0.01, 0.01, FUENTE, fontsize=7, color=TINTA2)
    fig.tight_layout(rect=(0, 0.04, 1, 0.95))
    fig.savefig(FIG / "fig3_estabilidad_aporte.png", facecolor=SUPERFICIE)
    plt.close(fig)
    print("figuras en", FIG)
