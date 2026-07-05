"""Quick verification that all data files are on 2023 timestamps."""
import pandas as pd

# CAISO prices
df = pd.read_csv("data/prices/caiso_dam_lmp_2023.csv")
lmp = df[df["LMP_TYPE"] == "LMP"].copy()
ts = pd.to_datetime(lmp["INTERVALSTARTTIME_GMT"], utc=True)
summer = ts.dt.month.isin([6, 7, 8, 9]) & (ts.dt.hour >= 14) & (ts.dt.hour < 21)
print("=== CAISO Prices ===")
print(f"  Total rows:          {len(df)}")
print(f"  LMP-only rows:       {len(lmp)}")
print(f"  Months covered:      {sorted(ts.dt.month.unique().tolist())}")
print(f"  Annual avg LMP:      {lmp['MW'].mean():.1f} USD/MWh")
print(f"  Summer on-peak avg:  {lmp['MW'][summer].mean():.1f} USD/MWh")
print(f"  Min / Max LMP:       {lmp['MW'].min():.1f} / {lmp['MW'].max():.1f}")

# Meter
meter = pd.read_parquet("data/meter/school_ca_15min.parquet")
meter_ts = pd.to_datetime(meter["timestamp"])
print("\n=== Meter Data ===")
print(f"  Rows:                {len(meter)}")
print(f"  Year(s):             {sorted(meter_ts.dt.year.unique().tolist())}")
print(f"  Peak demand:         {meter['demand_kw'].max():.1f} kW")

# Solar
solar = pd.read_csv("data/solar/pvwatts_100kw_socal.csv")
solar_ts = pd.to_datetime(solar["timestamp"])
print("\n=== Solar Data ===")
print(f"  Rows:                {len(solar)}")
print(f"  Year(s):             {sorted(solar_ts.dt.year.unique().tolist())}")
print(f"  Annual generation:   {solar['ac_output_kw'].sum():.0f} kWh")

# Alignment check
meter_year = meter_ts.dt.year.unique()[0]
solar_year = solar_ts.dt.year.unique()[0]
price_year = ts.dt.year.unique()
print(f"\n=== Alignment ===")
print(f"  Meter year:          {meter_year}")
print(f"  Solar year:          {solar_year}")
print(f"  Price years:         {sorted(price_year.tolist())}")
all_2023 = (meter_year == 2023) and (solar_year == 2023)
print(f"  All data on 2023:    {all_2023}")
