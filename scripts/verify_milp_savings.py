"""Quick verification: compare rule-based vs MILP battery savings."""
import pandas as pd
from pathlib import Path
from analysis.savings_calculator import (
    run_baseline,
    run_solar_only,
    run_solar_hvac,
    run_solar_hvac_battery,
    DSGS_ANNUAL_REVENUE,
    CAPEX,
    calculate_payback,
)

ROOT = Path(__file__).parent.parent

print("Loading meter data...")
df = pd.read_parquet(ROOT / "data" / "meter" / "school_ca_15min.parquet")
df["timestamp"] = pd.to_datetime(df["timestamp"])

print("Baseline...")
baseline_total = float(run_baseline(df)["total"].sum())
print(f"  ${baseline_total:,.0f}")

print("Solar only...")
solar_total = float(run_solar_only(df)["total"].sum())
print(f"  ${solar_total:,.0f}")

print("Solar + HVAC...")
sh_total = float(run_solar_hvac(df)["total"].sum())
print(f"  ${sh_total:,.0f}")

print("Solar + HVAC + Battery (rule-based)...")
shb_rule = run_solar_hvac_battery(df, use_milp=False)
shb_rule_total = float(shb_rule["total"].sum())
print(f"  ${shb_rule_total:,.0f}")

print("Solar + HVAC + Battery (MILP, 12 months) -- may take ~3 min...")
shb_milp = run_solar_hvac_battery(df, use_milp=True)
shb_milp_total = float(shb_milp["total"].sum())
print(f"  ${shb_milp_total:,.0f}")

print()
print("=" * 58)
print("  DER Savings: Rule-based vs MILP Comparison")
print("=" * 58)
print(f"  {'Scenario':<32} {'Annual Bill':>12}")
print("  " + "-" * 46)
print(f"  {'Baseline':32} ${baseline_total:>10,.0f}")
print(f"  {'+ Solar (100 kW)':32} ${solar_total:>10,.0f}"
      f"  saves ${baseline_total - solar_total:,.0f}")
print(f"  {'+ HVAC pre-cool':32} ${sh_total:>10,.0f}"
      f"  saves ${baseline_total - sh_total:,.0f}")
print(f"  {'+ Battery (rule-based)':32} ${shb_rule_total:>10,.0f}"
      f"  bat = ${sh_total - shb_rule_total:,.0f}/yr")
print(f"  {'+ Battery (MILP)':32} ${shb_milp_total:>10,.0f}"
      f"  bat = ${sh_total - shb_milp_total:,.0f}/yr")
print()

full_stack_milp = shb_milp_total - DSGS_ANNUAL_REVENUE
full_savings = baseline_total - full_stack_milp
pb = calculate_payback(
    baseline_total - shb_milp_total + DSGS_ANNUAL_REVENUE,
    CAPEX["full_stack"],
)
print(f"  Full stack (MILP + DSGS):  saves ${full_savings:,.0f}/yr")
print(f"  Simple payback: {pb['simple_payback_years']:.1f} yr")
print(f"  NPV (20yr @ 8%): ${pb['npv']:,.0f}")
print()
bat_rule = sh_total - shb_rule_total
bat_milp = sh_total - shb_milp_total
if bat_rule > 0:
    print(f"  MILP battery is {bat_milp / bat_rule:.1f}x better than rule-based")
