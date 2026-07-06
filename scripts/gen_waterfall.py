"""Generate updated waterfall chart reflecting MILP battery savings."""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pathlib

labels = [
    "Baseline\nbill",
    "Solar\n(100 kW)",
    "+ HVAC\npre-cool",
    "+ Battery\n(125kW/250kWh)",
    "+ DSGS\ngrid services",
]
values = [0, 23_522, 1_896, 12_034, 8_000]
colors = ["#2196F3"] * len(values)

fig, ax = plt.subplots(figsize=(10, 6))
bars = ax.bar(
    labels, values, color=colors, width=0.6,
    edgecolor="white", linewidth=1.5,
)
for bar, val in zip(bars, values):
    if val > 0:
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 200,
            f"${val:,.0f}",
            ha="center", va="bottom",
            fontweight="bold", fontsize=11,
        )

ax.set_ylabel("Annual Savings / Revenue ($)", fontsize=12)
ax.set_title(
    "DER Value Stack — Incremental Annual Savings\n"
    "(MILP 3-Demand Optimizer: battery $12,034/yr vs $423 rule-based)",
    fontsize=12, fontweight="bold",
)
ax.set_ylim(0, max(values) * 1.18)
ax.yaxis.set_major_formatter(
    plt.FuncFormatter(lambda x, _: f"${x:,.0f}")
)
ax.grid(axis="y", alpha=0.3)
ax.spines["top"].set_visible(False)
ax.spines["right"].set_visible(False)
fig.tight_layout()

out = pathlib.Path("outputs")
out.mkdir(exist_ok=True)
fig.savefig(out / "waterfall_milp.png", dpi=130, bbox_inches="tight")
print("Saved: outputs/waterfall_milp.png")
