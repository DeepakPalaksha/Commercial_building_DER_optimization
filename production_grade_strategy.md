# Production-Grade C&I Building Energy Optimization System

> **Status:** Design document — brainstormed July 6, 2026
> **Scope:** Day-ahead market only (real-time = Phase 3)
> **Building:** Southern California secondary school
> **Market:** SCE TOU-GS-3 tariff + CAISO DSGS

---

## System Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                    FORECASTING LAYER (10am daily)               │
│  Load Forecast │ Solar Forecast │ DA Price (CAISO published)    │
└────────────────────────┬────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────────────────┐
│                    OPTIMIZATION LAYER                           │
│              MILP (Day-Ahead, 96 × 15-min intervals)           │
│    Objective: minimize bill − DSGS revenue                      │
└────────────────────────┬────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────────────────┐
│                    DISPATCH LAYER                               │
│  Battery │ HVAC Pre-Cool │ EV Charging │ Flexible Loads         │
└────────────────────────┬────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────────────────┐
│                    MONITORING LAYER                             │
│  Real-time dashboard │ Alerts │ Bill verification │ KPIs        │
└─────────────────────────────────────────────────────────────────┘
```

---

## Phase Roadmap

```
PHASE 1 — Exercise Deliverable (NOW)
  ✓ Deterministic full-month optimization
  ✓ Known actual meter data (perfect foresight)
  ✓ MILP optimizer (cvxpy)
  ✓ SCE TOU-GS-3 bill calculator
  ✓ Streamlit dashboard
  ✓ Savings waterfall chart
  → Upper bound on achievable savings

PHASE 2 — Production Deployment (3-6 months)
  → Load forecasting (LSTM, ±15% MAPE)
  → Solar forecasting (weather-based, ±10% MAPE)
  → DA price: use actual CAISO published prices
  → Rolling 24h optimization (run daily at 10am)
  → Real-time meter data ingestion
  → Battery BMS telemetry
  → DSGS auto-enrollment

PHASE 3 — Advanced Features (6-12 months)
  → RL for real-time adaptive control
  → Stochastic MILP (handle forecast uncertainty)
  → Multi-site portfolio optimization
  → EV fleet V2G integration
  → Real-time market participation
  → Battery degradation modeling
```

---

## Forecasting Architecture

### Three Pillars — Why Each is Needed

```
LOAD is NOT a single forecast — it has independent sub-components:

Total_Load = HVAC_Load + Lighting + Plug_Loads + Water_Heating + EV_Charging

HVAC_Load:      driven by outdoor temperature → weather-dependent
Lighting:       driven by occupancy schedule → deterministic (school calendar)
Plug_Loads:     driven by occupancy → semi-deterministic
Water_Heating:  driven by occupancy + usage → semi-deterministic
EV_Charging:    controllable variable → optimization decision

Solar:          driven by cloud cover + sun angle → weather-dependent
DA Price:       use actual CAISO published prices (not forecast)
```

### Pillar 1 — Load Forecasting

```
Target:   Total building demand, 15-min intervals, 24h ahead
Accuracy: ±15% MAPE

HVAC Sub-Model (most important):
  Physics:   Q_hvac = UA × (T_outdoor - T_setpoint) / COP
  Empirical: Linear regression on hourly T_outdoor (fast, good R²)
  ML:        LSTM on (past 7d load, T_outdoor forecast, occupancy)

Lighting Sub-Model:
  Input: Occupancy schedule (known, school calendar)
  Output: 52 kW (occupied) or 8 kW (unoccupied)
  Method: Rule-based (deterministic)

Combined:
  load_forecast[t] = hvac_model(T_outdoor_forecast[t], occupancy[t])
                   + lighting_model(occupancy[t])
                   + plug_load_model(occupancy[t])
                   + water_heating_model(occupancy[t])

Libraries: scikit-learn (regression), PyTorch (LSTM)
Training data: 6+ months of 15-min meter data
Update: Retrain monthly with latest data
```

### Pillar 2 — Solar Forecasting

```
Target:   PV generation, 15-min intervals, 24h ahead
Accuracy: ±10% MAPE

Method 1 (Simple, Phase 2):
  Clear-sky model (PVLib) × cloud_cover_factor
  cloud_cover_factor from weather API (OpenWeatherMap, Tomorrow.io)
  
Method 2 (Better, Phase 3):
  Historical pattern matching + weather regression
  Input: past 30d solar at same hour, cloud cover, humidity
  Output: expected generation ± confidence interval

Key Use Case:
  IF tomorrow_solar_forecast > X kWh:
    Do NOT charge battery overnight (solar will top it up)
    Leave SoC headroom for solar charging 10:00-14:00
  ELSE (cloudy forecast):
    Charge battery fully overnight from grid (off-peak rate)

Libraries: pvlib (clear-sky), requests (weather API)
```

### Pillar 3 — DA Price (CAISO OASIS)

```
Target:   Hourly LMP, SP15 zone, published day-ahead
Source:   CAISO OASIS API (free, no account needed)
Method:   Fetch actual published prices (NOT forecast)
Timing:   CAISO publishes by 10am for next day

API Call:
  GET oasis.caiso.com/oasisapi/SingleZip
  params: queryname=PRC_LMP, market_run_id=DAM, node=TH_SP15_GEN-APND
  Fetch at 10am daily → parse CSV → use in MILP

Price Forecasting (for monthly/annual planning only):
  Method: Historical average by hour × season × day_type
  Input: 12+ months of CAISO LMP history
  Output: Expected DA price ± uncertainty band
  Use: Long-term investment analysis, not day-ahead dispatch
```

---

## Optimal Control Strategy (Day-Ahead, Summer Weekday)

### Phase-by-Phase Dispatch

```
10:00am (Day Before) — PLANNING
  1. Fetch CAISO DA prices for tomorrow
  2. Run load forecast for tomorrow
  3. Run solar forecast for tomorrow
  4. Solve MILP for tomorrow's 96 intervals
  5. Output: dispatch schedule (battery, HVAC, EV charging)

21:00 – 10:00 (OFF-PEAK, Night)
  Battery charge:
    Target SoC = 95% - (expected_solar_charge / capacity)
    Only charge what solar won't provide tomorrow
    charge_power ≤ demand_ceiling - building_load (all-time demand protection)
  EV charging:
    Schedule all EV charging in this window
    Never charge EVs during on-peak (14:00–20:00)
  HVAC: Minimal (building unoccupied, standby only)
  Grid rate: $0.0987/kWh ← cheapest

10:00 – 12:00 (MID-PEAK, Solar Rising)
  Solar: Generating, feeding building load
  Battery: Charge incrementally from solar excess ONLY
    battery_charge = max(0, solar[t] - building_load[t])
    Never charge from grid at mid-peak rates ($0.1550)
  HVAC: Normal operation

12:00 – 14:00 (MID-PEAK, Pre-Cooling Window)
  HVAC: Aggressive pre-cooling
    Target indoor temperature: 17–18°C
    Energy source: Solar (free) supplemented by grid (mid-peak $0.1550)
    Cost justification: $0.1550 now vs $0.2832 on-peak = save $0.1282/kWh
    PLUS demand charge: every kW shifted saves $19.10/month
  Solar: Peak generation, charge battery with excess
  Battery: Top up from solar excess if SoC not at target

14:00 – 16:00 (ON-PEAK, Coasting Phase)
  HVAC: OFF (building coasting on pre-cooled thermal mass)
    Indoor temp drifts: 17–18°C → 21–22°C (comfort maintained)
    Free load shed window determined by RC time constant τ
    τ = R × C; free window = τ × ln((T_out - T_precool) / (T_out - T_comfort))
  Solar: Declining but still generating (50–80 kW)
  Battery: Begin partial discharge (50–75 kW, save full power for peak spike)
  Grid: Minimum import (solar + partial battery cover load)
  DSGS check: IF event declared AND DA price > $2.00/kWh → discharge to grid

15:00 – 17:00 (ON-PEAK, Maximum Demand Spike)
  HVAC: Restarts as building hits comfort upper limit (24–25°C)
    Building load spikes: 200+ kW
  Battery: FULL DISCHARGE (125 kW)
    Grid import capped: 210 - 125 = 85 kW
    Demand charge reading: 85 kW × $19.10 = $1,624 vs 210 × $19.10 = $4,011
    Monthly saving: $2,387
  DSGS Decision:
    IF (DSGS event + DA price > $2.00/kWh):
      Discharge to grid → revenue $125 kW × hrs × $2.00
      Accept higher demand charge (trade-off)
    ELSE:
      Discharge to building → demand charge management (certain savings)

17:00 – 20:00 (ON-PEAK, Late)
  Battery: Partial discharge (SoC depleting)
    17:00: ~100 kW discharge
    18:00: ~75 kW discharge
    19:00: ~50 kW discharge
    20:00: 10% SoC → STOP
  Solar: Minimal (<20 kW, zero by 19:30)
  Grid: Carries remaining load

20:00 – 21:00 (MID-PEAK End)
  Battery: Rest at SoC minimum
  HVAC: Normal, temperature stabilizing
  Grid rate: $0.1550/kWh — don't charge battery yet

21:00 → Back to Night Phase
```

---

## EV Charging Integration

```python
# EV optimization constraints (add to MILP)

# Rule 1: Never charge EVs during on-peak
ev_charge_power[t] = 0  for t in on_peak_hours  # 14:00-20:00

# Rule 2: Must meet daily energy requirement by departure
sum(ev_charge_power[t] * dt for t in charge_window) >= ev_daily_kwh

# Rule 3: All-time demand protection
ev_charge_power[t] + building_load[t] + battery_charge[t] <= demand_ceiling

# Rule 4: Solar priority charging (daytime)
if solar_excess[t] > 0:
    ev_charge_power[t] = min(ev_charger_capacity, solar_excess[t])

# Annual savings per charging station: $1,000–$3,000/yr
# Key: shift EV load entirely to off-peak (21:00–07:00)
```

---

## MILP vs RL — Final Decision

```
Day-Ahead Planning: MILP (definitive choice)

Reasons:
  ✓ Provably globally optimal (for given forecasts)
  ✓ Fast: 96 intervals × multiple variables = <1 second solve
  ✓ Interpretable: can explain EVERY dispatch decision
  ✓ Handles all constraints exactly (SoC, demand ceiling, comfort)
  ✓ No training data needed (works from day 1)

RL is NOT better for day-ahead when forecasts are available:
  ✗ RL needs 6-12 months of training data (cold start problem)
  ✗ RL may not beat MILP even after training (MILP is already optimal)
  ✗ RL is a black box (hard to explain to Mike / customer)
  ✗ RL optimal for stochastic control, not deterministic optimization

When RL adds value (Phase 3):
  → Real-time intra-day adaptation (handle forecast errors)
  → Learn building-specific patterns over months of operation
  → Multi-objective balance (cost + comfort + battery life)
  → Portfolio-level optimization across multiple buildings

Implementation:
  Phase 1 + 2: MILP only (cvxpy + GLPK_MI solver)
  Phase 3: MILP for planning + RL for real-time override
```

---

## What a Complete Production System Needs

### Data Infrastructure

```
INBOUND DATA (real-time):
  → Building meter (15-min demand): MQTT or Modbus TCP → InfluxDB/ClickHouse
  → Solar inverter output (15-min): SunSpec Modbus → database
  → Battery BMS (SoC, temperature, health, 1-min): RS-485 / CAN → database
  → Outdoor weather (hourly): OpenWeatherMap API or on-site sensor
  → CAISO DA prices (daily at 10am): CAISO OASIS API → database
  → Occupancy (binary, 15-min): BMS or calendar integration

OUTBOUND COMMANDS (dispatch):
  → Battery charge/discharge setpoint: RS-485 or Modbus to BMS
  → HVAC setpoint adjustment: BACnet or Modbus to building controller
  → EV charger power limit: OCPP to charger management system
  → DSGS dispatch signal: CAISO telemetry interface
```

### Monitoring and Alerting

```
REAL-TIME DASHBOARD:
  → Actual vs forecasted load (15-min rolling chart)
  → Battery SoC trajectory (actual vs planned)
  → Solar generation (actual vs forecast)
  → Instantaneous grid import (kW)
  → Running demand charge this month ($ and kW peak so far)
  → Savings to date this month ($ vs baseline)
  → DSGS event status (active / standby / idle)

ALERTS:
  → Battery SoC deviates >10% from plan → potential fault
  → Demand charge about to set new monthly peak → emergency dispatch
  → DSGS event declared → auto-dispatch and notify
  → Solar generation >20% below forecast → check inverter
  → Forecast vs actual load diverging >15% → model retraining needed

MONTHLY REPORTING:
  → Actual SCE bill vs model prediction (variance analysis)
  → Attribution: solar savings / HVAC savings / battery savings / DSGS
  → Payback tracking (actual vs projected)
  → Battery health: SoC cycles, degradation trend
```

### Battery Degradation Modeling

```
LFP Battery (Lithium Iron Phosphate):
  Cycle life: 3,000–6,000 cycles (vs NMC 1,000–2,000)
  Degradation: ~2-3% capacity loss per year at 1 cycle/day
  
At 0.5 cycles/day: 182 cycles/year
  Year 5:  250 kWh × (1 - 0.025×5) = 219 kWh (87.5%)
  Year 10: 250 kWh × (1 - 0.025×10) = 187 kWh (75%)
  Year 15: 250 kWh × (1 - 0.025×15) = 156 kWh (62.5%)

Impact on savings projections:
  Year 1:  125 kW / 212 kWh usable → 1.7hr duration
  Year 10: 125 kW / 159 kWh usable → 1.27hr duration
  Savings degrade proportionally to usable capacity

Include in financial model: degradation-adjusted savings per year
```

### Grid Services Automation

```
DSGS Enrollment:
  1. Register with SCE (Demand Response portal)
  2. Register with CAISO (via aggregator or direct)
  3. Install CAISO-certified telemetry hardware ($5,000 one-time)
  4. Demonstrate dispatch capability (commissioning test)

DSGS Event Response:
  1. CAISO sends event signal (1-4 hours notice typically)
  2. System receives signal automatically (API webhook)
  3. Override current dispatch schedule
  4. Discharge battery + activate HVAC load shed
  5. Report delivered kWh back to CAISO
  6. CAISO verifies and processes payment (monthly)

Performance Requirements:
  Response time: within 10 minutes of event call
  Accuracy: ±10% of committed reduction
  Availability: must respond to >80% of declared events to maintain enrollment
```

### Security and Compliance

```
Cybersecurity:
  → TLS encryption for all API communications
  → Authentication for battery BMS (no open Modbus ports)
  → Role-based access (operator vs viewer vs admin)
  → Audit log of all dispatch commands

Compliance:
  → NERC CIP: applies if grid-connected resource >1 MW (not applicable here)
  → UL 9540: battery safety standard (required for interconnection)
  → IEEE 1547: inverter interconnection standard
  → SCE Rule 21: California interconnection rule for BTM storage
```

---

## Solar Export Strategy (NEM 3.0)

```
NEM 3.0 export rate: $0.079/kWh (fixed quarterly)
vs tariff savings:    $0.2832/kWh (on-peak)
vs DSGS revenue:      $2.00/kWh (event-triggered)

Decision tree for excess solar:
  IF solar[t] > building_load[t]:
    excess = solar[t] - building_load[t]
    
    IF battery_soc[t] < battery_soc_max:
      → Charge battery with excess (save for later)
      Priority: Use solar to avoid overnight grid charging
      
    ELIF DSGS event active:
      → Export to grid via DSGS (earn $2.00/kWh)
      This is the only time export is valuable
      
    ELSE:
      → Export via NEM 3.0 ($0.079/kWh)
      Accept poor rate — cannot avoid if battery is full

Solar sizing rule under NEM 3.0:
  Size system to match: annual load ≈ annual generation
  Do NOT oversize for export (export value is negligible)
  For 385 MWh/yr building: ~250 kW system optimal
  BUT check: battery can only absorb so much excess
  Better: 100–150 kW system, maximize self-consumption
```

---

## Financial Summary (Full Production System)

```
ANNUAL VALUE STACK (steady-state, optimal dispatch):

Tier 1 — Control (free):
  HVAC pre-cooling:          $5,000–$17,000/yr
  Load scheduling:           $2,000–$8,000/yr
  Subtotal:                  $7,000–$25,000/yr

Tier 2 — Solar ($280k, 7yr payback with ITC):
  Energy savings:            $16,000–$20,000/yr
  Demand charge reduction:   $5,000–$10,000/yr
  Free pre-cooling energy:   $2,000–$5,000/yr
  Subtotal:                  $23,000–$35,000/yr

Tier 3 — Battery ($155k additional):
  Demand charge management:  $8,000–$27,000/yr (MILP dispatch)
  TOU arbitrage:             $3,000–$8,000/yr
  Subtotal:                  $11,000–$35,000/yr

Tier 4 — Grid Services (minimal additional capex):
  DSGS revenue:              $4,000–$14,000/yr
  DA price optimization:     +15–25% battery value
  Subtotal:                  $4,000–$14,000/yr

Tier 5 — EV + Other:
  EV charging optimization:  $1,000–$3,000/yr

TOTAL ANNUAL BENEFIT:        $46,000–$112,000/yr
TOTAL CAPEX:                 $435,000 ($305,000 after 30% ITC)
BLENDED PAYBACK:             2.7–6.6yr (with ITC)
```

---

*Document created: 2026-07-06*
*Status: Living document — update as system evolves*
*Next update: After Phase 2 deployment*