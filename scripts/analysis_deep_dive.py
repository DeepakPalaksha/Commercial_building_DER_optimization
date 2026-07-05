"""Extract detailed building and savings stats for deep-dive analysis."""
import pandas as pd
import numpy as np
from analysis.bill_calculator import calculate_annual_bill
from models.solar_model import load_solar_profile
from analysis.tariff import load_tariff

df = pd.read_parquet("data/meter/school_ca_15min.parquet")
df["timestamp"] = pd.to_datetime(df["timestamp"])
ts = df["timestamp"]

print("=== METER DATA ===")
print(f"  Rows: {len(df):,}  Year: {ts.dt.year.unique().tolist()}")
print(f"  Peak demand:       {df.demand_kw.max():.1f} kW")
print(f"  Mean demand:       {df.demand_kw.mean():.1f} kW")
annual_kwh = df.demand_kw.sum() * 0.25
print(f"  Annual energy:     {annual_kwh:,.0f} kWh  ({annual_kwh/1000:.0f} MWh)")
monthly_peak = df.groupby(ts.dt.month)["demand_kw"].max()
print("  Monthly peaks:")
for m, pk in monthly_peak.items():
    print(f"    Month {m:02d}: {pk:.1f} kW")

print("\n=== TARIFF STRUCTURE ===")
t = load_tariff()
d = t["demand_charges"]
print("  Summer demand charges (Jun-Sep):")
print(f"    On-peak  (14-20h, wkday): ${d['summer']['on_peak_kw']:.2f}/kW")
print(f"    Mid-peak (10-14+20-21h):  ${d['summer']['mid_peak_kw']:.2f}/kW")
print(f"    All-time:                 ${d['summer']['all_time_kw']:.2f}/kW")
print("  Winter demand charges (all other months):")
print(f"    Mid-peak (10-21h, wkday): ${d['winter']['mid_peak_kw']:.2f}/kW")
print(f"    All-time:                 ${d['winter']['all_time_kw']:.2f}/kW")
e = t["energy_charges_per_kwh"]
print("  Energy rates (summer):")
print(f"    On-peak:   ${e['summer']['on_peak']['rate']:.5f}/kWh")
print(f"    Mid-peak:  ${e['summer']['mid_peak']['rate']:.5f}/kWh")
print(f"    Off-peak:  ${e['summer']['off_peak']['rate']:.5f}/kWh")

# Demand charge analysis
on_peak_mask = (
    ts.dt.month.isin([6, 7, 8, 9])
    & (ts.dt.dayofweek < 5)
    & (ts.dt.hour >= 14)
    & (ts.dt.hour < 20)
)
print("\n=== DEMAND CHARGE DETAIL (worst month) ===")
for m in [6, 7, 8, 9]:
    mask_m = ts.dt.month == m
    op_m = mask_m & on_peak_mask
    pk_all = df.loc[mask_m, "demand_kw"].max()
    pk_op = df.loc[op_m, "demand_kw"].max() if op_m.sum() > 0 else 0
    dc_op = pk_op * 19.10
    dc_mp = pk_op * 5.80   # simplification
    dc_at = pk_all * 8.85
    total_dc = dc_op + dc_mp + dc_at
    print(f"  Month {m}: on-peak peak={pk_op:.1f}kW, all-time={pk_all:.1f}kW, "
          f"demand charges ~${total_dc:.0f}")

print("\n=== SOLAR OFFSET ===")
sol = load_solar_profile(100.0)
merged = df.merge(sol[["timestamp", "solar_kw"]], on="timestamp", how="left")
merged["solar_kw"] = merged["solar_kw"].fillna(0.0)
merged["net_kw"] = (merged["demand_kw"] - merged["solar_kw"]).clip(lower=0)
solar_kwh = sol["solar_kw"].sum() * 0.25
print(f"  Solar annual:     {solar_kwh:,.0f} kWh  ({solar_kwh/1000:.0f} MWh)")
print(f"  Building load:    {annual_kwh:,.0f} kWh")
print(f"  Solar fraction:   {solar_kwh/annual_kwh*100:.0f}%")
print(f"  Net load peak:    {merged.net_kw.max():.1f} kW (was {df.demand_kw.max():.1f} kW)")

# Solar during on-peak hours
op_solar = merged.loc[on_peak_mask, "solar_kw"].mean()
print(f"  Avg solar during on-peak: {op_solar:.1f} kW  "
      f"({op_solar/df.loc[on_peak_mask,'demand_kw'].mean()*100:.0f}% of on-peak load)")

print("\n=== BATTERY ECONOMICS ===")
# 125kW/250kWh battery dispatch potential
# Summer: discharge 6 hours on-peak per day, 4 months
summer_days = 4 * 30   # Jun-Sep, ~30 days
# Battery can deliver 125kW for 250*0.85/125 = 1.7 hours continuous
usable_kwh = 250 * (0.95 - 0.10)
hours_at_peak = usable_kwh / 125
print(f"  Usable capacity: {usable_kwh:.0f} kWh  (90-95% SoC window x 250kWh)")
print(f"  Full discharge time at 125kW: {hours_at_peak:.1f} hr  "
      f"(6hr on-peak window needs {6*125:.0f} kWh)")
print(f"  Battery only covers {usable_kwh/(6*125)*100:.0f}% of full on-peak window")
print(f"  Demand reduction if flattened: "
      f"up to {125:.0f} kW (from avg on-peak {df.loc[on_peak_mask,'demand_kw'].mean():.0f} kW)")

# Annual energy arbitrage potential
off_peak_rate = e["summer"]["off_peak"]["rate"]
on_peak_rate = e["summer"]["on_peak"]["rate"]
spread = on_peak_rate - off_peak_rate
summer_cycles = summer_days  # 1 cycle/day in summer
shoulder_cycles = 2 * 30    # spring+fall, 1 cycle/day
annual_kwh_dispatched = (summer_cycles + shoulder_cycles) * usable_kwh * 0.92
arbitrage_value = annual_kwh_dispatched * spread
print(f"  Energy spread on-peak vs off-peak: ${spread:.4f}/kWh")
print(f"  Annual kwh dispatched: {annual_kwh_dispatched:,.0f} kWh")
print(f"  Annual arbitrage value (energy only): ${arbitrage_value:,.0f}")
print(f"  Demand charge reduction potential: "
      f"${125*19.10*4:.0f}/yr (if peak shaved 125kW x 4 summer months)")
