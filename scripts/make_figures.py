"""README figures, drawn only from files in results/ (light and dark variants for GitHub's <picture>).

Writes results/figures/{fleet_reliability,survival_by_manufacturer,early_warning}_{light,dark}.png.
Palette and mark specs follow the project's data-viz guidance (validated categorical slots, thin marks,
recessive grid, text in ink colors, direct labels where contrast is low).
Usage: uv run python scripts/make_figures.py
"""
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results/figures"
OUT.mkdir(parents=True, exist_ok=True)

THEMES = {
    "light": dict(surface="#fcfcfb", ink="#0b0b0b", ink2="#52514e", muted="#898781", grid="#e1e0d9", axis="#c3c2b7",
                  series=["#2a78d6", "#eb6834", "#1baf7a", "#eda100"]),
    "dark": dict(surface="#1a1a19", ink="#f0efec", ink2="#c3c2b7", muted="#898781", grid="#2c2c2a", axis="#383835",
                 series=["#3987e5", "#d95926", "#199e70", "#c98500"]),
}
MFR_ORDER = ["Seagate", "HGST", "Toshiba", "WDC"]  # fixed slot order: color follows the manufacturer
PRETTY = {"HGST": "HGST", "Seagate": "Seagate", "Toshiba": "Toshiba", "WDC": "WDC"}


def style(ax, t, grid_axis="x"):
    ax.set_facecolor(t["surface"])
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(t["axis"])
    ax.tick_params(colors=t["muted"], labelsize=9, length=0)
    ax.grid(axis=grid_axis, color=t["grid"], linewidth=0.8)
    ax.set_axisbelow(True)


def title(fig, t, text, sub):
    fig.text(0.012, 0.985, text, ha="left", va="top", fontsize=13, fontweight="bold", color=t["ink"])
    fig.text(0.012, 0.945, sub, ha="left", va="top", fontsize=9.5, color=t["ink2"])


def label_model(model, mfr):
    return model if model.split(" ")[0] in ("HGST", "TOSHIBA", "WDC") else f"Seagate {model}"


def fig_fleet(t, mode):
    d = pd.read_csv(ROOT / "results/phase4/bayes_estimates.csv")
    d = d[d["drive_days"] >= 1_000_000].sort_values("afr_observed_mix_median")
    fig, ax = plt.subplots(figsize=(10, 9.2), dpi=150)
    fig.patch.set_facecolor(t["surface"])
    c = t["series"][0]
    y = np.arange(len(d))
    ax.hlines(y, d["afr_observed_mix_lo"], d["afr_observed_mix_hi"], color=c, linewidth=2, alpha=0.55)
    ax.scatter(d["afr_observed_mix_median"], y, s=42, color=c, edgecolor=t["surface"], linewidth=1.5, zorder=3)
    for yi, (_, r) in zip(y, d.iterrows()):
        ax.text(r["afr_observed_mix_hi"] + 0.12, yi, f"{r['afr_observed_mix_median']:.2f}%", va="center",
                fontsize=8.5, color=t["ink2"])
    ax.set_yticks(y, [label_model(m, f) for m, f in zip(d["model"], d["manufacturer"])], fontsize=9, color=t["ink"])
    ax.tick_params(axis="y", colors=t["ink"])
    ax2 = ax.secondary_yaxis("right")
    ax2.set_yticks(y, [f"{v/1e6:.1f}M" for v in d["drive_days"]], fontsize=8.5)
    ax2.tick_params(colors=t["muted"], length=0)
    ax2.spines["right"].set_visible(False)
    ax.set_xlim(0, d["afr_observed_mix_hi"].max() + 1.0)
    ax.set_xlabel("Annualized failure rate (%): posterior median and 90% credible interval", color=t["ink2"], fontsize=9.5)
    style(ax, t)
    ax.tick_params(axis="y", labelcolor=t["ink"])
    fig.text(0.985, 0.905, "drive-days", ha="right", fontsize=8.5, color=t["muted"])
    title(fig, t, "Failure rate by drive model",
          "26 models with ≥ 1M drive-days, Jul 2023 – Jun 2026. Hierarchical Bayesian estimate (results/phase4/bayes_estimates.csv)")
    fig.subplots_adjust(left=0.26, right=0.9, top=0.89, bottom=0.07)
    fig.savefig(OUT / f"fleet_reliability_{mode}.png", facecolor=t["surface"])
    plt.close(fig)


def fig_survival(t, mode):
    k = pd.read_csv(ROOT / "results/phase4/km_by_manufacturer.csv")
    fig, ax = plt.subplots(figsize=(10, 5.6), dpi=150)
    fig.patch.set_facecolor(t["surface"])
    for i, m in enumerate(MFR_ORDER):
        g = k[k["manufacturer"] == m].sort_values("age")
        c = t["series"][i]
        ax.fill_between(g["age"], g["ci_lower"], g["ci_upper"], color=c, alpha=0.15, linewidth=0, step="post")
        ax.step(g["age"], g["survival"], where="post", color=c, linewidth=2, label=PRETTY[m])
        end = g.iloc[-1]
        ax.text(end["age"] + 0.12, end["survival"], f"{PRETTY[m]} {end['survival']:.2f}", va="center",
                fontsize=9, color=t["ink"])
        ax.plot([end["age"]], [end["survival"]], marker="o", markersize=6, color=c,
                markeredgecolor=t["surface"], markeredgewidth=1.5)
    ax.set_ylim(0.8, 1.0)
    ax.set_xlim(0, k["age"].max() + 1.6)
    ax.set_xlabel("Drive age (years of power-on time)", color=t["ink2"], fontsize=9.5)
    ax.set_ylabel("Share of drives still running", color=t["ink2"], fontsize=9.5)
    style(ax, t, grid_axis="y")
    leg = ax.legend(loc="lower left", frameon=False, fontsize=9)
    for txt in leg.get_texts():
        txt.set_color(t["ink"])
    title(fig, t, "Survival by drive age",
          "Kaplan-Meier with right-censoring and delayed entry, conditional on reaching the first age with ≥ 100 drives at risk\n"
          "(results/phase4/km_by_manufacturer.csv)")
    fig.subplots_adjust(left=0.08, right=0.98, top=0.82, bottom=0.11)
    fig.savefig(OUT / f"survival_by_manufacturer_{mode}.png", facecolor=t["surface"])
    plt.close(fig)


def fig_early_warning(t, mode):
    tr = pd.read_csv(ROOT / "results/phase5/tradeoff_30d.csv")
    lead = pd.read_csv(ROOT / "tableau/extract_ew_lead_times.csv")
    fig, (a, b) = plt.subplots(1, 2, figsize=(11, 4.9), dpi=150, gridspec_kw={"width_ratios": [1.35, 1]})
    fig.patch.set_facecolor(t["surface"])
    lg = tr[tr["model"] == "lightgbm"].sort_values("budget_per_1000")
    rule = tr[tr["model"] == "simple_rule"].iloc[0]
    c1, c2 = t["series"][0], t["series"][1]
    a.plot(lg["false_alarms_per_1000"], lg["recall"], color=c1, linewidth=2, marker="o", markersize=5,
           markeredgecolor=t["surface"], markeredgewidth=1.2, label="LightGBM (each point = an alert budget)")
    a.plot([rule["false_alarms_per_1000"]], [rule["recall"]], marker="D", markersize=8, color=c2, linestyle="none",
           markeredgecolor=t["surface"], markeredgewidth=1.2, label="Simple rule: any critical SMART value > 0")
    five = lg[lg["budget_per_1000"] == 5.0].iloc[0]
    a.annotate(f"5 alerts / 1,000 drive-days\n{five['recall']:.0%} of failure-days caught",
               (five["false_alarms_per_1000"], five["recall"]), xytext=(0.6, 0.62), textcoords="data",
               fontsize=8.5, color=t["ink"], arrowprops=dict(arrowstyle="-", color=t["muted"], linewidth=0.8))
    a.annotate(f"Rule: {rule['recall']:.0%} caught,\n{rule['false_alarms_per_1000']:.0f} false alarms / 1,000",
               (rule["false_alarms_per_1000"], rule["recall"]), xytext=(18, 0.25), textcoords="data",
               fontsize=8.5, color=t["ink"], arrowprops=dict(arrowstyle="-", color=t["muted"], linewidth=0.8))
    a.set_xscale("log")
    a.xaxis.set_major_locator(matplotlib.ticker.FixedLocator([0.2, 0.5, 1, 2, 5, 10, 20, 50, 100]))
    a.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:g}"))
    a.xaxis.set_minor_locator(matplotlib.ticker.NullLocator())
    a.set_xlabel("False alarms per 1,000 drive-days (log scale)", color=t["ink2"], fontsize=9.5)
    a.set_ylabel("Share of failure-days alerted (≤ 30 days before failure)", color=t["ink2"], fontsize=9)
    a.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0, decimals=0))
    a.set_ylim(0, 0.8)
    style(a, t, grid_axis="y")
    leg = a.legend(loc="upper left", frameon=False, fontsize=8.5)
    for txt in leg.get_texts():
        txt.set_color(t["ink"])

    order = ["30+ days", "7-29 days", "0-6 days", "not alerted"]
    cnt = lead["lead_bucket"].value_counts().reindex(order)
    x = np.arange(len(order))
    b.bar(x, cnt.values, width=0.62, color=t["series"][0], edgecolor=t["surface"], linewidth=2)
    for xi, v in zip(x, cnt.values):
        b.text(xi, v + 12, f"{v:,}\n{v / cnt.sum():.0%}", ha="center", va="bottom", fontsize=8.5, color=t["ink2"])
    b.set_xticks(x, order, fontsize=9)
    b.set_ylim(0, cnt.max() * 1.25)
    b.set_ylabel("Failed drives in test year", color=t["ink2"], fontsize=9.5)
    b.set_xlabel("Warning before failure (model at 5 alerts / 1,000 drive-days)", color=t["ink2"], fontsize=9)
    style(b, t, grid_axis="y")
    b.tick_params(axis="x", labelcolor=t["ink"])
    title(fig, t, "Early warning from SMART telemetry",
          f"Test year Jul 2025 – Jun 2026, {cnt.sum():,} failed test drives, natural distribution "
          "(results/phase5/tradeoff_30d.csv; lead times from the 5 / 1,000 alert)")
    fig.subplots_adjust(left=0.07, right=0.99, top=0.84, bottom=0.14, wspace=0.28)
    fig.savefig(OUT / f"early_warning_{mode}.png", facecolor=t["surface"])
    plt.close(fig)


plt.rcParams["font.family"] = "DejaVu Sans"
for mode, t in THEMES.items():
    fig_fleet(t, mode)
    fig_survival(t, mode)
    fig_early_warning(t, mode)
print(sorted(p.name for p in OUT.glob("*.png")))
