"""
Cost driver decomposition for a commercial building.

Produces:
  - Bill component % shares (energy / demand / fixed)
  - Load heatmap: average kW by hour-of-day x month
  - Load vs outdoor temperature scatter with linear trendline
  - Monthly peak demand trend

See PLAN.md — Engineering Tradeoffs section.
"""

import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from pathlib import Path

from analysis.bill_calculator import calculate_annual_bill, _load_meter

matplotlib.use("Agg")  # non-interactive backend safe for scripts + Docker

OUTPUT_DIR = Path("outputs/cost_driver")

# Month abbreviations used in plots
MONTH_LABELS = [
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
]


# ── Bill decomposition ────────────────────────────────────────────────────

def decompose_bill(annual_df: pd.DataFrame) -> dict:
    """
    Return % share of each bill component.

    Args:
        annual_df: output of calculate_annual_bill()

    Returns:
        dict with keys 'energy', 'demand', 'fixed' (values sum to 100.0)
    """
    totals = {
        "energy": annual_df["energy_charge"].sum(),
        "demand": annual_df["demand_charge"].sum(),
        "fixed": annual_df["fixed_charge"].sum(),
    }
    grand = sum(totals.values())
    return {k: round(v / grand * 100, 1) for k, v in totals.items()}


# ── Load heatmap ──────────────────────────────────────────────────────────

def plot_load_heatmap(df: pd.DataFrame, output_path: Path) -> None:
    """
    Plot average demand (kW) as a heatmap: hour-of-day (y) x month (x).

    Shows when peak demand occurs across the year. Useful for identifying
    which TOU periods drive the demand charge.
    """
    df = df.copy()
    df["hour"] = df["timestamp"].dt.hour
    df["month"] = df["timestamp"].dt.month

    pivot = df.pivot_table(
        values="demand_kw", index="hour", columns="month", aggfunc="mean"
    )

    fig, ax = plt.subplots(figsize=(12, 6))
    im = ax.imshow(
        pivot.values,
        aspect="auto",
        origin="lower",
        cmap="YlOrRd",
        interpolation="nearest",
    )
    ax.set_xlabel("Month")
    ax.set_ylabel("Hour of Day")
    ax.set_title("Average Building Demand (kW) — Hour x Month")
    ax.set_xticks(range(12))
    ax.set_xticklabels(MONTH_LABELS, fontsize=9)
    ax.set_yticks(range(0, 24, 3))
    ax.set_yticklabels([f"{h:02d}:00" for h in range(0, 24, 3)], fontsize=9)
    plt.colorbar(im, ax=ax, label="Average kW")
    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=150)
    plt.close(fig)
    print(f"  Saved: {output_path}")


# ── Load vs temperature scatter ───────────────────────────────────────────

def plot_load_vs_temperature(df: pd.DataFrame, output_path: Path) -> None:
    """
    Scatter of HVAC demand vs outdoor temperature with linear trendline.

    Requires columns: 'T_outdoor_f' and 'out.electricity.hvac.demand_kw'.
    This is the visual basis for calibrating the RC thermal model.
    """
    has_hvac = "out.electricity.hvac.demand_kw" in df.columns
    has_temp = "T_outdoor_f" in df.columns

    if not (has_hvac and has_temp):
        print("  Skipping temp scatter: HVAC or temperature column missing.")
        return

    # Only cooling-season, warm hours to show the linear relationship
    sub = df[df["T_outdoor_f"] > 60].copy()
    x = sub["T_outdoor_f"].values
    y = sub["out.electricity.hvac.demand_kw"].values

    # Linear trendline
    coeffs = np.polyfit(x, y, 1)
    x_range = np.linspace(x.min(), x.max(), 200)
    y_fit = np.polyval(coeffs, x_range)
    r2 = float(np.corrcoef(x, y)[0, 1] ** 2)

    fig, ax = plt.subplots(figsize=(8, 5))
    ax.scatter(x, y, alpha=0.05, s=2, color="steelblue", label="15-min data")
    ax.plot(
        x_range,
        y_fit,
        "r-",
        linewidth=2,
        label=f"Linear fit: {coeffs[0]:.2f} kW/°F  (R²={r2:.2f})",
    )
    ax.set_xlabel("Outdoor Temperature (°F)")
    ax.set_ylabel("HVAC Load (kW)")
    ax.set_title("HVAC Load vs Outdoor Temperature — RC Model Basis")
    ax.legend(fontsize=9)
    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=150)
    plt.close(fig)
    print(f"  Saved: {output_path}")


# ── Monthly bill stacked bar ──────────────────────────────────────────────

def plot_monthly_bill_breakdown(
    annual_df: pd.DataFrame, output_path: Path
) -> None:
    """
    Stacked bar chart of monthly bill split into energy / demand / fixed.
    """
    months = annual_df["month"].values
    energy = annual_df["energy_charge"].values
    demand = annual_df["demand_charge"].values
    fixed = annual_df["fixed_charge"].values

    fig, ax = plt.subplots(figsize=(12, 5))
    ax.bar(months, energy, label="Energy", color="#4C72B0")
    ax.bar(months, demand, bottom=energy, label="Demand", color="#DD8452")
    ax.bar(
        months,
        fixed,
        bottom=energy + demand,
        label="Fixed",
        color="#55A868",
    )
    ax.set_xlabel("Month")
    ax.set_ylabel("Bill ($)")
    ax.set_title("Monthly Bill Breakdown — SCE TOU-GS-3")
    ax.set_xticks(months)
    ax.set_xticklabels(MONTH_LABELS, fontsize=9)
    ax.yaxis.set_major_formatter(
        matplotlib.ticker.FuncFormatter(lambda v, _: f"${v:,.0f}")
    )
    ax.legend()
    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=150)
    plt.close(fig)
    print(f"  Saved: {output_path}")


# ── Peak demand trend ─────────────────────────────────────────────────────

def plot_peak_demand_trend(
    annual_df: pd.DataFrame, output_path: Path
) -> None:
    """
    Monthly peak demand bar chart. Highlights summer vs winter contrast.
    """
    months = annual_df["month"].values
    peaks = annual_df["peak_demand_kw"].values
    colors = [
        "#DD4444" if m in (6, 7, 8, 9) else "#4488CC" for m in months
    ]

    fig, ax = plt.subplots(figsize=(10, 4))
    ax.bar(months, peaks, color=colors)
    ax.axhline(peaks.max(), linestyle="--", color="red", alpha=0.5,
                label=f"Annual peak: {peaks.max():.0f} kW")
    ax.axhline(peaks.mean(), linestyle="--", color="gray", alpha=0.5,
                label=f"Monthly avg peak: {peaks.mean():.0f} kW")
    ax.set_xlabel("Month")
    ax.set_ylabel("Peak Demand (kW)")
    ax.set_title("Monthly Peak Demand — Demand Charge Driver")
    ax.set_xticks(months)
    ax.set_xticklabels(MONTH_LABELS, fontsize=9)
    ax.legend(fontsize=9)
    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=150)
    plt.close(fig)
    print(f"  Saved: {output_path}")


# ── Summary printer ───────────────────────────────────────────────────────

def print_summary(annual_df: pd.DataFrame, shares: dict) -> None:
    """Print a concise cost driver summary to stdout."""
    annual_total = annual_df["total"].sum()
    peak_month = annual_df.loc[
        annual_df["peak_demand_kw"].idxmax(), "month"
    ]
    print()
    print("=" * 56)
    print("  Cost Driver Summary — SCE TOU-GS-3")
    print("=" * 56)
    print(f"  Annual bill:        ${annual_total:>10,.0f}")
    print(f"  Energy charge:      {shares['energy']:>5.1f}%")
    print(f"  Demand charge:      {shares['demand']:>5.1f}%")
    print(f"  Fixed charge:       {shares['fixed']:>5.1f}%")
    print()
    print(f"  Peak demand month:  {MONTH_LABELS[peak_month - 1]}")
    print(
        f"  Annual peak:        "
        f"{annual_df['peak_demand_kw'].max():.1f} kW"
    )
    print(
        f"  July peak:          "
        f"{annual_df.loc[annual_df['month']==7, 'peak_demand_kw'].values[0]:.1f} kW"
        f"  (school closed)"
    )
    print("=" * 56)


# ── Entry point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print("Loading meter data...")
    df = _load_meter()

    print("Calculating annual bill...")
    annual = calculate_annual_bill(df)
    shares = decompose_bill(annual)
    print_summary(annual, shares)

    print("\nGenerating plots...")
    plot_load_heatmap(df, OUTPUT_DIR / "load_heatmap.png")
    plot_load_vs_temperature(df, OUTPUT_DIR / "load_vs_temp.png")
    plot_monthly_bill_breakdown(annual, OUTPUT_DIR / "monthly_bill.png")
    plot_peak_demand_trend(annual, OUTPUT_DIR / "peak_demand_trend.png")

    print(f"\nAll outputs written to {OUTPUT_DIR}/")
