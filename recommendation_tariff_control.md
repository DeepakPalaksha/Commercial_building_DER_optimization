# California Commercial Building — Power Market, Billing & Optimization Guide

> **Purpose:** Complete reference for understanding the California electricity
> market, how SCE TOU-GS-3 bills are calculated, and the full priority-ranked
> optimization strategy for a C&I commercial building (secondary school,
> Southern California).
>
> **Building:** Secondary school, Mission Viejo CA (SCE territory, CAISO market)
> **Tariff:** SCE TOU-GS-3
> **Market:** CAISO (California ISO)

---

## Part 1 — The California Electricity Market Structure

### 1.1 Who Does What — Regulatory Bodies

```
FEDERAL LEVEL
    ↓
FERC (Federal Energy Regulatory Commission)
    ├─ Regulates: Interstate commerce, wholesale markets, transmission
    ├─ Role: Approves CAISO tariffs, regulates transmission rates
    └─ Relevant to you: Sets rules for wholesale market participation

STATE LEVEL
    ├─ CPUC (California Public Utilities Commission)
    │   ├─ Regulates: Retail electricity rates, utility operations
    │   ├─ Role: Approves SCE's TOU-GS-3 tariff rates (the 7 values)
    │   └─ Relevant to you: Sets $0.2832, $19.10, $302.72 etc.
    │
    └─ CEC (California Energy Commission)
        ├─ Regulates: Energy planning, building efficiency standards
        ├─ Role: Title 24 building codes, solar/storage mandates
        └─ Relevant to you: Requires solar + BESS on new commercial buildings

MARKET OPERATOR
    ↓
CAISO (California Independent System Operator)
    ├─ Operates: Wholesale electricity market, grid stability
    ├─ Role: Runs day-ahead and real-time auctions, manages DSGS program
    └─ Relevant to you: Sets LMP prices, operates grid services revenue

DISTRIBUTION UTILITY (Retail)
    ↓
SCE (Southern California Edison)
    ├─ Owns: Local distribution network (poles, wires, transformers)
    ├─ Role: Buys wholesale power from CAISO, sells retail to buildings
    └─ Relevant to you: Sends the monthly bill, applies TOU-GS-3 rates
```

### 1.2 Key Acronyms

| Acronym | Full Name | What It Is |
|---------|-----------|-----------|
| **FERC** | Federal Energy Regulatory Commission | Federal wholesale market regulator |
| **CPUC** | California Public Utilities Commission | State retail rate regulator |
| **CEC** | California Energy Commission | State energy planning + building codes |
| **CAISO** | California Independent System Operator | Wholesale market operator |
| **SCE** | Southern California Edison | Your retail utility — sends the bill |
| **TOU** | Time-of-Use | Tariff with different rates by time of day |
| **TOU-GS-3** | Time-of-Use General Service (Large) | The specific tariff for this building |
| **LMP** | Locational Marginal Price | Wholesale electricity price ($/MWh) |
| **DSGS** | Demand Side Grid Support | CAISO grid services program — pays for load reduction |
| **DR** | Demand Response | General term for reducing load when grid requests |
| **NEM** | Net Energy Metering | Credit for excess solar exported to grid |
| **BTM** | Behind-the-Meter | Equipment on customer side of meter |
| **BESS** | Battery Energy Storage System | Battery storage |
| **DER** | Distributed Energy Resource | Solar, battery, EV, flexible loads |
| **ITC** | Investment Tax Credit | 30% federal tax credit on solar + storage capex |

### 1.3 Two Completely Separate Price Signals

This is the most important concept. There are TWO price signals and they
must never be confused:

**Price Signal 1 — SCE TOU-GS-3 Tariff (FIXED)**
```
→ Set by CPUC regulatory approval
→ Changes: once per year (or multi-year regulatory cycle)
→ Known: 12 months in advance
→ Used for: calculating the building's monthly electricity BILL
→ Example: $0.2832/kWh on-peak, $19.10/kW on-peak demand
→ These values do NOT change day to day
```

**Price Signal 2 — CAISO Day-Ahead LMP (VARIABLE)**
```
→ Set by wholesale market supply/demand bidding
→ Changes: every hour, every day
→ Known: 24 hours in advance (published 10am for next day)
→ Used for: battery optimization + DSGS grid services REVENUE
→ Example: $35/MWh at 3am, $150/MWh at 7pm on a hot day
→ These values change every single day
```

The building **always pays SCE the TOU tariff** — that bill is non-negotiable.
Separately, the battery **can earn revenue from CAISO markets** via DSGS.

```
Complete Financial Picture:

MONTHLY BILL    = SCE energy charges + SCE demand charges + fixed
                  (calculated using fixed TOU-GS-3 rates)

MONTHLY REVENUE = CAISO DSGS grid services earnings
                  (calculated using variable LMP prices)

MONTHLY NET     = Bill - Revenue
```

### 1.4 California vs Europe — Critical Difference

| Aspect | Europe (e.g., Germany) | California (SCE TOU-GS-3) |
|--------|----------------------|--------------------------|
| Energy pricing | Variable spot price every 15 min | Fixed TOU rate by time window |
| Demand charge | Small or €0 (negligible) | Large — up to 47% of total bill |
| Optimization focus | Energy arbitrage (buy cheap, sell dear) | Demand peak shaving (never spike) |
| Battery primary value | TOU price spread arbitrage | Demand charge management |
| HVAC load control value | Low (demand charge small) | Very high ($19.10/kW saved) |
| Price known how far ahead | Day-ahead (variable) | Full year (fixed schedule) |

**Consequence:** In California, knowing the tariff 12 months ahead means you
can pre-plan HVAC schedules precisely. In Europe, you react to daily spot prices.
California rewards infrastructure investment and smart control. Europe rewards
real-time market participation.

---

## Part 2 — How SCE TOU-GS-3 Bills Are Calculated

### 2.1 The Seven Fixed Tariff Values

SCE publishes these once per year (or regulatory cycle). They are constant
for the entire year:

```
ENERGY RATES ($/kWh — charged per unit of electricity consumed):
  1. Off-peak rate:   $0.0987/kWh  (most hours)
  2. Mid-peak rate:   $0.1550/kWh  (transition hours, weekdays)
  3. On-peak rate:    $0.2832/kWh  (most expensive, weekday afternoons)

DEMAND RATES ($/kW — charged on single highest 15-min reading):
  4. On-peak demand rate:   $19.10/kW
  5. Mid-peak demand rate:  $5.80/kW
  6. All-time demand rate:  $8.85/kW

FIXED CHARGE (flat monthly fee, regardless of consumption):
  7. Customer charge:  $302.72/month
```

### 2.2 Time Windows — When Each Rate Applies

**Summer (June–September):**
```
WEEKDAYS:
  00:00 – 10:00  → Off-peak    ($0.0987/kWh energy, $8.85/kW all-time demand only)
  10:00 – 14:00  → Mid-peak   ($0.1550/kWh energy, $5.80/kW mid-peak demand)
  14:00 – 20:00  → ON-PEAK    ($0.2832/kWh energy, $19.10/kW on-peak demand) ← MOST EXPENSIVE
  20:00 – 21:00  → Mid-peak   ($0.1550/kWh energy, $5.80/kW mid-peak demand)
  21:00 – 00:00  → Off-peak   ($0.0987/kWh energy, $8.85/kW all-time demand only)

WEEKENDS + HOLIDAYS:
  All hours      → Off-peak   ($0.0987/kWh energy, $8.85/kW all-time demand only)
```

**Winter (October–May):**
```
WEEKDAYS:
  00:00 – 10:00  → Off-peak   ($0.0987/kWh)
  10:00 – 21:00  → Mid-peak   ($0.1325/kWh, $5.80/kW mid-peak demand)
  21:00 – 00:00  → Off-peak   ($0.0987/kWh)

WEEKENDS + HOLIDAYS:
  All hours      → Off-peak   ($0.0987/kWh)
```

> **Note on SCE rate evolution:** SCE has been shifting the on-peak window
> later in the day (from 12:00–18:00 → 14:00–20:00 → potentially 16:00–21:00
> in future rate cases). This shift makes solar LESS effective at demand charge
> management (solar is declining by 4pm). Always verify which rate version
> applies to the exercise data.

### 2.3 The 15-Minute Interval — How Energy is Measured

Meters record average power (kW) over every 15-minute window.
Energy consumed = kW × time:

```
Energy in one 15-min interval = demand_kW × (15/60) = demand_kW × 0.25 hours

Example:
  15:00–15:15 interval reads 120 kW
  Energy = 120 × 0.25 = 30 kWh
  Cost   = 30 × $0.2832 = $8.50  (on-peak rate)

Monthly total = sum of all 96 intervals/day × 30 days = 2,880 intervals
This is a Riemann sum of the continuous power curve.
```

### 2.4 The Four Demand Charges — How They Work

Each demand charge looks at a DIFFERENT time window and finds the single
highest 15-minute reading in that window during the billing month.
They are measured INDEPENDENTLY.

```
DEMAND CHARGE 1 — On-Peak Demand
  Window:   14:00–20:00, weekdays only, entire month
  Reading:  single highest 15-min kW in that window
  Rate:     × $19.10/kW
  Example:  210.5 kW × $19.10 = $4,021 for June

DEMAND CHARGE 2 — Mid-Peak Demand
  Window:   10:00–14:00 and 20:00–21:00, weekdays only, entire month
  Reading:  single highest 15-min kW in that window
  Rate:     × $5.80/kW
  Example:  180 kW × $5.80 = $1,044 for June

DEMAND CHARGE 3 — All-Time Demand (Facilities-Related)
  Window:   every 15-min interval in entire month (any hour, any day)
  Reading:  single highest 15-min kW anywhere in the month
  Rate:     × $8.85/kW
  Example:  210.9 kW × $8.85 = $1,867 for June

DEMAND CHARGE 4 — Mid-Peak 2 (winter months)
  Window:   10:00–21:00, weekdays, winter months only
  Reading:  single highest 15-min kW in that window
  Rate:     × $5.80/kW
```

### 2.5 Complete June Bill Example

**Building profile:** 85,000 sqft secondary school, Southern California
- Peak demand: 210.9 kW (occurs weekday 14:30, HVAC + occupancy)
- Monthly energy: 68,400 kWh
- On-peak energy: 8,000 kWh
- Mid-peak energy: 6,000 kWh
- Off-peak energy: 54,400 kWh

```
ENERGY CHARGES:
  On-peak:   8,000 kWh × $0.2832  =  $2,266
  Mid-peak:  6,000 kWh × $0.1550  =  $  930
  Off-peak: 54,400 kWh × $0.0987  =  $5,370
  Energy subtotal:                    $8,566

DEMAND CHARGES:
  On-peak demand:  210.5 kW × $19.10 =  $4,021
  Mid-peak demand: 180.0 kW × $5.80  =  $1,044
  All-time demand: 210.9 kW × $8.85  =  $1,867
  Demand subtotal:                       $6,932

FIXED CHARGE:
  Customer charge:                       $  303

JUNE TOTAL:                             $15,801

Demand charges = 44% of total bill
```

### 2.6 The All-Time Demand Charge Trap (Critical Warning)

The all-time demand charge applies to the highest 15-min reading at ANY time,
including midnight, weekends, holidays.

**The battery charging trap:**
```
Scenario: Winter night, building draws 18 kW, battery charges at 125 kW
  Grid sees: 18 + 125 = 143 kW ← NEW ALL-TIME MONTHLY PEAK

Demand charge with this mistake:
  143 kW × $8.85 = $1,266/month

Demand charge without this mistake:
  18 kW × $8.85  = $159/month

Monthly penalty: $1,107 → erases all battery savings
```

**Rule:** Never charge battery faster than: `target_demand - current_building_load`

### 2.7 Annual Bill Summary (Baseline, No Optimization)

```
Month   Peak (kW)  Bill       Notes
─────────────────────────────────────────────────────
Jan       55.4     $5,200    Winter — mild, low HVAC
Feb       86.0     $6,800    Still winter
Mar      137.3     $9,400    Spring — HVAC starting
Apr      175.7    $11,200    Shoulder — moderate HVAC
May      210.1    $14,800    Pre-summer — near peak
Jun      210.9    $15,801    Highest bill (school in session + HVAC peak)
Jul       53.3     $4,100    School CLOSED (summer break) — anomaly
Aug      196.8    $14,200    School reopens + hottest temperatures
Sep      140.3    $10,100    Back-to-school, cooling off
Oct      102.8     $7,900    Shoulder
Nov       59.8     $5,400    Cooling off
Dec       53.3     $5,100    Winter, minimal HVAC
─────────────────────────────────────────────────────
ANNUAL             $110,001
```

> **July anomaly explained:** School closes for summer break. Occupancy drops
> to zero → baseline load drops from 52 kW to 18 kW → HVAC drops ~80%.
> Peak of 53.3 kW is correct. The months that matter for optimization are
> June, August, September — not July.

---

## Part 3 — Optimization Priority Recommendations

> **Philosophy:** Always do free things first. Never spend capital until you have
> exhausted control strategies. Size capital investments to the RESIDUAL problem
> after controls are applied — this minimizes capex.

### Priority Pyramid Overview

```
                     TIER 1 — Free (Do First)
              ┌──────────────────────────────────────┐
              │  HVAC Pre-cooling                    │  $5k–$17k/yr
              │  Load Scheduling + Staggering        │  $2k–$8k/yr
              │  Lighting + Plug Load Scheduling     │  $1k–$3k/yr
              │  Subtotal:                           │  $8k–$28k/yr
              └──────────────────────────────────────┘
                     TIER 2 — Solar ($280k capex)
              ┌──────────────────────────────────────┐
              │  Rooftop Solar PV (100–300 kW)       │  $19k–$30k/yr
              │  + Powers pre-cooling for free       │
              │  + Reduces mid-peak energy cost      │
              └──────────────────────────────────────┘
                     TIER 3 — Battery ($155k additional)
              ┌──────────────────────────────────────┐
              │  Battery (125kW / 250kWh)            │  $8k–$27k/yr
              │  → Demand shaving (1st priority)     │
              │  → TOU arbitrage (2nd priority)      │
              └──────────────────────────────────────┘
                     TIER 4 — Grid Services (Revenue)
              ┌──────────────────────────────────────┐
              │  DSGS demand response enrollment     │  $4k–$14k/yr
              │  Day-ahead price optimization        │  +15–25% battery value
              └──────────────────────────────────────┘
                     TIER 5 — Secondary Value Streams
              ┌──────────────────────────────────────┐
              │  NEM 3.0 solar export credits        │  Small (avoid oversizing)
              │  VPP enrollment                      │  $2k–$5k/yr
              │  EV charging optimization            │  $1k–$3k/yr
              └──────────────────────────────────────┘

TOTAL ANNUAL VALUE STACK:  $39k–$99k/yr
TOTAL CAPEX:               $435k (solar + battery)
BLENDED PAYBACK:           4.4–11yr depending on dispatch quality
```

---

### TIER 1 — Control Strategies (Zero Capital — Always Do First)

#### 1A. HVAC Pre-Cooling (Highest Value Control Strategy)

```
What it does:
  Cool building to 70°F before 14:00 using off-peak/mid-peak energy
  Raise setpoint to 76°F during on-peak (14:00–20:00)
  Building thermal mass maintains comfort during free "coasting" window

Why it works:
  On-peak demand charge = $19.10/kW (most expensive thing on bill)
  Every kW of HVAC load shifted out of 14:00–20:00 saves $19.10/month
  × 4 summer months = $76.40/kW/year in demand charge savings

How long the free window lasts (RC thermal model):
  Free coasting time = R × C × ln((T_outdoor - T_precool) / (T_outdoor - T_comfort_max))

  Where:
    R = thermal resistance (°F·hr/kWh) — building insulation quality
    C = thermal capacitance (kWh/°F) — building thermal mass
    τ = R × C = time constant

  Example:
    T_outdoor    = 92°F (hot summer afternoon)
    T_precool    = 70°F (pre-cooled temperature)
    T_comfort    = 76°F (upper comfort limit)
    τ = 2hr (poorly insulated building):   free window = 0.64hr (38 min)
    τ = 4hr (moderately insulated):        free window = 1.28hr (77 min)
    τ = 6hr (well insulated/heavy mass):   free window = 1.90hr (114 min)

Key tradeoff:
  Deeper pre-cool (lower T_precool) → longer free window
  BUT morning energy is not free (mid-peak at $0.1550/kWh)
  Optimal T_precool minimizes: (morning energy cost) - (afternoon demand saved)
  Typical optimum: 70°F pre-cool, 2–3hr free window (if τ > 4hr)

Annual savings:
  $5,000–$17,000/yr depending on τ (thermal time constant)
  Higher for concrete/brick buildings (τ = 6–8hr, heavy thermal mass)
  Lower for lightweight construction (τ = 1–2hr, minimal benefit)

Capex: $0 — software/controls change only
Risk:  Occupant comfort complaints if τ is too short
```

#### 1B. Load Scheduling and Peak Staggering

```
What it does:
  Spread equipment startup times to prevent coincident demand spikes
  e.g., stagger HVAC unit startups by 5 minutes each at 8am
  Schedule non-critical loads (EV charging, water heaters) in off-peak

Why it works:
  Demand charge is set by the single highest 15-min interval
  If 5 HVAC units start simultaneously at 08:00: 5 × 30kW = 150kW spike
  If staggered by 5 min each: max simultaneous = 2 units = 60kW spike
  Demand charge reduction: 90kW × $8.85 = $797/month = $9,560/yr

Annual savings: $2,000–$8,000/yr
Capex: $0 — scheduling changes only
```

#### 1C. Lighting and Plug Load Scheduling

```
What it does:
  Dim or switch off non-essential lighting during on-peak hours
  Schedule dishwashers, water heaters, pool pumps to off-peak

Annual savings: $1,000–$3,000/yr
Capex: $0–$2,000 (smart plugs, programmable timers)
```

---

### TIER 2 — Solar PV (First Capital Investment)

#### 2A. Rooftop Solar PV (100–300 kW)

```
What it does:
  Generates electricity during daylight (peak ~11:00–15:00)
  Directly offsets on-peak and mid-peak grid consumption
  Partially reduces on-peak demand (declining by 14:00–20:00 window)

Critical note on SCE rate shift:
  OLD on-peak: 12:00–18:00 → solar perfectly aligned, high demand value
  NEW on-peak: 14:00–20:00 → solar declining by 14:00, partial alignment
  FUTURE:      16:00–21:00 → solar minimal overlap, demand value very low

  This means solar is increasingly LESS effective at demand charge management.
  Solar remains valuable for energy cost reduction.
  Battery becomes MORE important for demand charges under new rates.

Value breakdown (100kW system):
  Annual generation:    130,000–165,000 kWh  (1,300–1,650 kWh/kW)
  Energy savings:       $16,000–$20,000/yr   (at blended $0.12–$0.13/kWh)
  Demand savings:       $5,000–$10,000/yr    (partial overlap with on-peak)
  Total annual value:   $21,000–$30,000/yr

Capex:     $280,000  ($2.80/W installed, 100kW system)
With ITC:  $196,000  (30% Investment Tax Credit)
Payback:   11–12yr without ITC, 7–8yr with ITC
IRR:       5.5% without ITC, 9–10% with ITC

NEM 3.0 warning:
  Since April 2023, excess solar exported to grid earns only ~$0.08/kWh
  (wholesale rate), not the retail $0.28/kWh under old NEM 2.0.
  DO NOT oversize solar. Charge battery with excess before exporting.
```

#### 2B. Solar + HVAC Pre-Cooling (Combined Strategy)

```
Why this combination is more valuable than each alone:

  Without solar: pre-cooling costs $0.1550/kWh (mid-peak energy rate)
  With solar:    pre-cooling powered by solar = ~$0/kWh (free energy)

  Solar generates maximum power exactly when pre-cooling runs (10:00–14:00)
  → Solar covers the energy cost of pre-cooling
  → Pre-cooling reduces the demand charge during on-peak
  → Double benefit from single solar investment

Seasonal strategy:
  Summer: Solar → pre-cool aggressively 10:00–14:00
           Building coasts on thermal mass 14:00–16:00
           Battery handles remaining on-peak spike 14:00–20:00

  Winter: Solar → charge battery (demand charges are smaller in winter)
           Battery does TOU arbitrage (charge mid-peak with solar,
           discharge when solar unavailable)

Annual savings (combined):  $25,000–$35,000/yr
vs Solar alone:              $21,000–$30,000/yr
Pre-cooling adds:            ~$5,000/yr at no additional capex
```

---

### TIER 3 — Battery Storage (Second Capital Investment)

#### 3A. Battery for On-Peak Demand Shaving (Primary Use)

```
What it does:
  Charges during off-peak (00:00–10:00) at $0.0987/kWh
  Discharges during on-peak (14:00–20:00) to reduce grid import
  Caps building grid demand at target level (e.g., 85 kW after solar + control)

Battery sizing reality check:
  On-peak window:      6 hours (14:00–20:00)
  Battery (125kW/250kWh): lasts only 1.7 hours at full power (250 ÷ 125)
  → Cannot cover full on-peak window alone
  → BUT: solar + HVAC control handle first 2–3 hours of on-peak
  → Battery only needs to cover the remaining HVAC spike (1–2 hours)
  → 250kWh is sufficient when combined with Tier 1 + Tier 2

All-time demand constraint (CRITICAL):
  Max charge power = max(0, target_demand - current_building_load)
  Never charge faster than the headroom below your demand target
  This prevents battery charging from creating new all-time peak

Annual savings:
  Rule-based dispatch:  $423/yr  (conservative floor — from analysis)
  MILP optimal:         $8,000–$27,000/yr  (upper bound)
  Gap is due to: (1) battery cannot cover full 6hr on-peak window
                 (2) rule-based is myopic, MILP sees whole month
                 (3) July school closure not handled by rules

Capex:   $155,000  (battery only, solar already installed)
Payback: Depends critically on dispatch quality
```

#### 3B. Battery for TOU Energy Arbitrage (Secondary Use)

```
What it does:
  Charges at off-peak ($0.0987/kWh), discharges at on-peak ($0.2832/kWh)
  Spread: $0.1845/kWh per round-trip cycle
  Theoretical max: 250kWh × $0.1845 × 250 cycles = $11,540/yr

Reality:
  Demand shaving is ALWAYS higher priority than arbitrage
  Battery SoC committed to demand shaving first
  Only residual capacity used for arbitrage
  Practical arbitrage savings: $3,000–$8,000/yr

Dispatch hierarchy for battery:
  1st. Demand charge management (on-peak demand shaving)
  2nd. All-time demand protection (never charge past target)
  3rd. TOU energy arbitrage (charge cheap, discharge expensive)
  4th. Grid services / DSGS (if SoC headroom available)
```

#### 3C. Seasonal Battery Strategy

```
SUMMER (Jun–Sep):
  Priority: On-peak demand shaving
  Charge:   21:00–10:00 (off-peak, staying below demand target)
  Discharge: 14:00–20:00 (on-peak, maximum discharge)
  HVAC:     Pre-cool 10:00–14:00, coast 14:00–16:00, minimal 16:00–20:00
  Solar:    Powers pre-cooling 10:00–14:00, supplements on-peak 14:00–16:00

SHOULDER (Apr–May, Oct–Nov):
  Priority: Mid-peak demand + TOU arbitrage
  Charge:   22:00–08:00 (off-peak overnight)
  Discharge: 14:00–21:00 (mid/on-peak)
  HVAC:     Moderate pre-cooling, less critical than summer

WINTER (Jan–Mar, Dec):
  Priority: TOU arbitrage + grid services
  Charge:   22:00–08:00 (off-peak overnight)
  Discharge: 10:00–21:00 (mid-peak, smaller demand charges)
  Note:     Enroll in DSGS program for winter grid services revenue
```

---

### TIER 4 — Day-Ahead Market and Grid Services

#### 4A. DSGS (Demand Side Grid Support) — California Program

```
What it is:
  CAISO program that pays buildings to reduce load during grid stress events
  Typically 4–8 events per summer, triggered by heat waves / high demand

How it works:
  CAISO declares a DSGS event (typically 1–4 hours notice)
  Building + battery reduce load by maximum possible amount
  CAISO pays $2.00/kWh for every kWh of reduction delivered

Revenue calculation:
  Conservative: 4 events × 4hr × 125kW = 2,000 kWh × $2.00 = $4,000/yr
  Moderate:     6 events × 5hr × 175kW = 5,250 kWh × $2.00 = $10,500/yr
  Optimistic:   8 events × 5hr × 175kW = 7,000 kWh × $2.00 = $14,000/yr
  Model uses:   $8,000/yr (median estimate)

Key conflict with demand shaving:
  DSGS events happen during summer afternoon peak — exactly when battery
  is needed for demand charge management
  
  Resolution: Reserve minimum SoC for demand charges
    30% SoC reserved for demand shaving at all times
    70% SoC available for DSGS dispatch during events
    
  If DSGS and peak demand conflict:
    Demand shaving saves $19.10/kW × peak reduction = certain, calculable
    DSGS pays $2.00/kWh = depends on event frequency (uncertain)
    In most months, demand shaving wins. During declared events, DSGS wins.

Capex: Minimal (enrollment fee + telemetry hardware ~$5,000 one-time)
Annual revenue: $4,000–$14,000/yr
```

#### 4B. Day-Ahead Price Signal for Battery Optimization

```
What it is:
  CAISO publishes next-day hourly prices by 10am each morning
  Use these to optimize WHEN to charge battery (cheapest hours)

How it interacts with fixed TOU tariff:
  TOU tariff:   fixed — tells you WHEN building bill is highest (known all year)
  DA LMP price: variable — tells you WHEN grid energy is cheapest to buy

  Optimal charge time = hours when BOTH tariff is cheap AND DA price is low
  Optimal discharge = hours when TOU on-peak AND DA price both high

  In practice:
    DA prices are cheapest 01:00–06:00 (often $20–$30/MWh)
    DA prices are highest 17:00–21:00 (often $60–$150/MWh)
    This aligns well with TOU off-peak/on-peak windows

Implementation:
  10am: fetch CAISO DA prices for next day via OASIS API
  Run optimization: solve for optimal charge/discharge schedule
  10pm: execute schedule; battery follows plan

Savings uplift vs fixed rule-based schedule:
  +15–25% additional battery revenue
  Especially valuable during spring (duck curve — negative DA prices midday)
  During negative DA prices: charge battery for free (or get paid to charge)

Spring duck curve opportunity:
  California has high solar generation in spring, causing midday prices
  to go negative (March–May, 10:00–14:00)
  Battery can charge during negative prices = gets paid to charge
  Then discharge during 17:00–21:00 peak prices
  This TOU arbitrage is ADDITIONAL to demand charge management
```

#### 4C. Real-Time Market (Advanced — Version 2)

```
What it is:
  CAISO publishes 5-minute real-time prices
  Battery responds to unexpected price spikes or drops

Value:
  DA optimization captures 80–90% of available market value
  Real-time adds 10–20% on top
  Adds operational complexity

Recommendation:
  Implement DA optimization first (Tier 4B)
  Add real-time response in Version 2 roadmap
```

---

### TIER 5 — Secondary Value Streams

#### 5A. NEM 3.0 Solar Export Credits

```
Critical change (April 2023):
  OLD NEM 2.0: export credit = retail rate (~$0.28/kWh) — very valuable
  NEW NEM 3.0: export credit = wholesale rate (~$0.08/kWh) — much lower

  This fundamentally changes solar sizing strategy:
  → DO NOT oversize solar for export
  → Size solar to match on-site consumption
  → Charge battery with excess solar BEFORE exporting
  → Export only what battery cannot absorb

If solar produces more than building + battery can absorb:
  Old NEM 2.0: great, export it for $0.28/kWh credit
  New NEM 3.0: curtail or accept $0.08/kWh — not worth oversizing for

Solar sizing rule of thumb:
  Target: annual generation ≈ 80–90% of annual building consumption
  For 385,000 kWh/yr building: 100kW system generates ~130,000 kWh (34%)
  To reach 80%: need ~250kW system
  But check: can battery absorb all excess? If not, curtailment reduces ROI
```

#### 5B. VPP (Virtual Power Plant) Enrollment

```
What it is:
  Aggregate building with other buildings/batteries into a VPP
  Utility or aggregator manages combined dispatch
  Building gets paid for availability (capacity payment) + dispatch

Revenue for single building: $2,000–$5,000/yr
Note: May conflict with DSGS enrollment — cannot double-enroll capacity
```

#### 5C. EV Charging Optimization

```
If school has EV chargers (staff parking, school bus fleet):
  Rule 1: Never charge EVs during 14:00–20:00 weekday on-peak
  Rule 2: Charge EVs during off-peak (22:00–07:00) or from solar (10:00–14:00)
  Rule 3: If solar excess available, use for EV charging before battery

With V2G (Vehicle-to-Grid) — future technology:
  EV batteries discharge during on-peak, earn TOU arbitrage revenue
  Currently only available with specific charger + vehicle combinations
```

---

## Part 4 — Complete Optimization Model

### 4.1 MILP Objective Function

```python
# Minimize monthly electricity bill across all 4 demand charge components
# Priority weights ensure demand shaving > energy arbitrage

minimize = (
    # Priority 1: On-peak demand charge (highest $/kW, summer only)
    w1 * peak_on_peak_kw * tariff['on_peak_demand_rate']

    # Priority 2: Mid-peak demand charge
  + w2 * peak_mid_peak_kw * tariff['mid_peak_demand_rate']

    # Priority 3: All-time demand charge (applies all months)
  + w3 * peak_all_time_kw * tariff['all_time_demand_rate']

    # Priority 4: Energy cost (TOU rates × consumption)
  + w4 * sum(energy_rate[t] * grid_import[t] * dt for t in T)

    # Priority 5: DSGS revenue (subtract — it's income)
  - w5 * sum(dsgs_price[t] * dsgs_dispatch[t] * dt for t in T)
)

# Weights: w1 >> w2 > w3 >> w4 > w5
# e.g., w1=1000, w2=100, w3=50, w4=1, w5=0.5
```

### 4.2 Key Constraints

```python
constraints = [
    # Power balance: every 15-min interval
    grid_import[t] == building_load[t] - solar[t] - battery_discharge[t] + battery_charge[t],

    # Battery SoC dynamics
    soc[t+1] == soc[t] + (battery_charge[t] * η_charge - battery_discharge[t] / η_discharge) * dt,
    soc >= 0.10 * battery_capacity,  # Never below 10%
    soc <= 0.95 * battery_capacity,  # Never above 95%

    # Battery power limits
    battery_charge[t] <= battery_power_kw,
    battery_discharge[t] <= battery_power_kw,

    # CRITICAL: All-time demand charge protection
    # Never charge faster than headroom below demand target
    battery_charge[t] <= max(0, demand_target - building_load[t]),

    # Thermal model constraints (if HVAC controllable)
    T_indoor[t+1] == T_indoor[t] + ((T_outdoor[t] - T_indoor[t]) / (R * C) - hvac_kw[t] / C) * dt,
    T_indoor[t] >= 70,  # Comfort minimum
    T_indoor[t] <= 76,  # Comfort maximum

    # DSGS SoC reserve
    soc[t] >= 0.30 * battery_capacity  # Reserve 30% for demand shaving during DSGS events
]
```

### 4.3 Expected Annual Results

| Scenario | Annual Savings | CapEx | Payback | Notes |
|----------|---------------|-------|---------|-------|
| Tier 1 only (controls) | $8k–$28k/yr | $0 | Immediate | Always do first |
| + Solar (Tier 2) | $29k–$58k/yr | $280k ($196k with ITC) | 5–10yr | ITC critical |
| + Battery (Tier 3) | $37k–$85k/yr | $435k ($351k with ITC) | 4–12yr | Dispatch quality matters |
| + DSGS (Tier 4) | $41k–$99k/yr | $440k | 4–11yr | Revenue uncertain ±50% |

### 4.4 Sanity Check — vs Elexity White Paper (JSerra School)

| Metric | This Model | JSerra (Elexity) | Match? |
|--------|-----------|-----------------|--------|
| Battery savings | $8k–$27k/yr | $27k/yr | ✓ |
| HVAC control savings | $5k–$17k/yr | $17k/yr | ✓ |
| Grid services revenue | $4k–$14k/yr | $8k/yr | ✓ |
| Total value stack | $17k–$58k/yr | $52k/yr | ✓ |
| System payback | 3.5–7yr | 3.5yr | ✓ (ITC + optimal dispatch) |

---

## Part 5 — Questions Likely to Come Up

**Q: "Why is demand charge management the top priority over energy arbitrage?"**
> Demand shaving saves $19.10/kW/month. Energy arbitrage saves $0.1845/kWh.
> To save $19.10 via arbitrage you need to arbitrage 103 kWh. One 15-min peak
> reduction saves the equivalent of 103 kWh of arbitrage. Demand shaving is
> structurally superior.

**Q: "Why does battery dispatch only save $423/yr in your rule-based model?"**
> Rule-based dispatch is conservative by design. It doesn't know the monthly
> peak will occur at a specific interval and discharges suboptimally. MILP
> solves the full month globally and achieves $8k–$27k/yr. The $423 is a
> floor, not a ceiling. See Section 5.2 of the deep-dive document.

**Q: "How does CAISO day-ahead price relate to SCE TOU tariff?"**
> They are completely separate. SCE TOU = what you pay SCE (fixed schedule).
> CAISO DA = wholesale market price that varies daily. Battery charges from
> grid at SCE rates but earns DSGS revenue at CAISO rates. Both apply
> simultaneously to different cash flows.

**Q: "Why is solar NPV negative at 8% but payback is under 12 years?"**
> Simple payback ignores time value of money. At 8% discount rate, a dollar
> saved in year 11 is worth $0.43 today — NPV captures this correctly.
> At 4–5% (school bond financing rate), NPV is strongly positive.

**Q: "Can battery do DSGS and demand charge management simultaneously?"**
> Yes, but with SoC reservation. Reserve 30% SoC for demand shaving at all
> times. Use the remaining 70% for DSGS dispatch during events. If DSGS event
> occurs on a day with high building demand, demand shaving takes priority.

**Q: "What happens if SCE shifts on-peak to 4pm–9pm (future rates)?"**
> Solar becomes nearly irrelevant for demand charge management (solar output
> is minimal by 4pm). Battery becomes the primary demand charge tool. HVAC
> pre-cooling window extends (more time to pre-cool before 4pm). The analysis
> should be re-run with the new rate window.

---

*Sources: SCE TOU-GS-3 tariff schedule, CAISO OASIS market data,
Elexity white paper (JSerra Catholic High School case study),
CPUC NEM 3.0 decision D.22-12-056, CEC Title 24 2025 standards,
LBNL Electricity Markets & Policy Group research, NREL ComStock dataset.*

*Last updated: 2026-07-06*