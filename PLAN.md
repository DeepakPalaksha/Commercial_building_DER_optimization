# Elexity Building Energy Analysis â€” PLAN.md
## C&I Building DER Optimization for a SoCal Secondary School

---

## Goal

Build a production-grade commercial building energy analysis tool for a
technical interview exercise at Elexity (elexity.io). Given a secondary
school's 15-minute interval meter data in Southern California (SCE
territory, CAISO market), the system identifies electricity cost drivers,
recommends DER investments (solar, battery, HVAC load control, grid
services), quantifies savings and payback, and presents results through
a LangGraph agent pipeline and an interactive Streamlit dashboard.

This implements the full Elexity "value stack" methodology and mirrors
the published JSerra Catholic High School case study numbers.

---

## What Is Being Built

| Module | Files | Purpose | Runs on |
|---|---|---|---|
| Data scripts | `scripts/download_data.py` | Download all 5 data sources | CLI, once |
| Tariff + Bill | `analysis/tariff.py` | Parse SCE TOU-GS-3 rates | CLI / agent |
| Bill calc | `analysis/bill_calculator.py` | Reconstruct monthly bill | CLI / agent |
| Cost driver | `analysis/cost_driver.py` | Decompose charges, plots | CLI / agent |
| Control strategy | `analysis/control_strategy.py` | Seasonal dispatch | agent |
| Savings calc | `analysis/savings_calculator.py` | Waterfall, payback | agent |
| Thermal model | `models/thermal_model.py` | RC calibration, pre-cool sim | agent |
| Battery model | `models/battery_model.py` | SoC state machine | optimizer |
| Solar model | `models/solar_model.py` | PVWatts profile + scaling | optimizer |
| MILP optimizer | `models/optimizer.py` | cvxpy dispatch optimizer | agent |
| Agents (x5) | `agents/` | LangGraph specialist agents | orchestrator |
| Orchestrator | `agents/orchestrator.py` | LangGraph StateGraph | CLI |
| Dashboard | `streamlit_app/app.py` | Interactive savings simulator | Streamlit |
| Notebook | `notebooks/analysis.ipynb` | 90-min exercise deliverable | Jupyter |
| Docker | `Dockerfile` | Container for full stack | Docker |

---

## Market / Geography Consistency â€” Critical

Everything must be geographically consistent:

- **Building location:** Southern California (Mission Viejo / Orange County)
- **Utility:** Southern California Edison (SCE)
- **Tariff:** SCE TOU-GS-3 (Time-of-Use General Service, demand charge)
- **Wholesale market:** CAISO (California ISO)
- **Grid services:** DSGS (Demand Side Grid Support) â€” CA-specific DR program
- **Weather:** Los Angeles TMY3 (dry, hot summers, mild winters)

Do NOT mix Oregon tariffs with California buildings.
Do NOT use PG&E rates for SCE territory.

---

## Data Flow

```
[NREL ComStock S3]  -->  meter/school_ca_15min.parquet (35,040 rows, 15-min)
[EnergyPlus EPW]    -->  weather/USA_CA_Los.Angeles.TMY3.epw
[CAISO OASIS API]   -->  prices/caiso_dam_lmp_2023.csv ($/MWh, SP15 zone)
[SCE tariff JSON]   -->  tariff/sce_tou_gs3.json (hand-encoded)
[NREL PVWatts API]  -->  solar/pvwatts_100kw_socal.csv (hourly AC kWh)
                                      |
                                      v
                              [Data Agent]
                         load, validate, align timestamps
                                      |
                    +-----------------+-----------------+
                    v                 v                 v
             [Tariff Agent]   [Thermal Agent]   [Optimizer Agent]
             baseline bill    RC fit + pre-cool  MILP per scenario
             rate schedule    schedule            per month
                    +                 +                 +
                    v                 v                 v
                              [Report Agent]
                    waterfall chart + charts + Claude narrative
                    writes outputs/{timestamp}/savings_summary.json
```

---

## Data Sources

All data is downloaded by [download_data.py](scripts/download_data.py) â€”
run once before analysis.

| Data | Source | File |
|---|---|---|
| Building meter (15-min) | NREL ComStock S3 | `data/meter/school_ca_15min.parquet` |
| Weather (hourly) | EnergyPlus EPW | `data/weather/USA_CA_Los.Angeles.TMY3.epw` |
| Electricity prices | CAISO OASIS API | `data/prices/caiso_dam_lmp_2023.csv` |
| Solar generation | NREL PVWatts API | `data/solar/pvwatts_100kw_socal.csv` |
| SCE tariff | Hand-encoded | `data/tariff/sce_tou_gs3.json` |

Both real and synthetic fallback data are supported. If S3 or API access
fails, `download_data.py` generates physics-based synthetic data that
matches NREL/CAISO published statistics.

---

## Package Management â€” uv Only

Use `uv` exclusively. No pip, no poetry, no conda.

| File | Purpose |
|---|---|
| `pyproject.toml` | Dependency declarations (human-managed) |
| `uv.lock` | Reproducible lockfile â€” commit to git, never gitignore |

```bash
uv run python scripts/download_data.py
uv run python analysis/bill_calculator.py
uv run streamlit run streamlit_app/app.py
```

Docker pattern:
```dockerfile
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
```

`uv sync --frozen` reads the lockfile exactly â€” no version drift between
local dev and the Docker container.

---

## Core Models

### Thermal Model (RC)

The building is a first-order RC circuit â€” standard in building energy
literature and what Elexity uses.

```
dT_indoor/dt = (T_outdoor - T_indoor) / (R * C) - Q_hvac / C

R = thermal resistance (Â°FÂ·h/kWh) â€” insulation quality
C = thermal capacitance (kWh/Â°F) â€” thermal mass
```

R and C are **calibrated from data** via `curve_fit` on the HVAC load
vs outdoor temperature scatter. Never hardcode R or C.
RÂ² requirement: >= 0.70, otherwise flag as non-HVAC-dominated.

### Battery Model

125 kW / 250 kWh (2-hour) system matching Elexity's CPS partnership.
Round-trip efficiency: 92%. SoC bounds: 10%â€“95%.
See `models/battery_model.py`.

### Solar Model

Load NREL PVWatts hourly CSV (100 kW system, Mission Viejo, CA).
Scale linearly for user-selected system size.
See `models/solar_model.py`.

### MILP Optimizer (cvxpy)

Minimizes monthly electricity bill subject to:
- Battery SoC dynamics and power limits
- Thermal comfort constraints (70â€“76 Â°F)
- Power balance (grid + solar + discharge = load + charge)
- Peak demand tracking variable (for demand charge)

Solver: `cp.GLPK_MI` (free, no license required).
See `models/optimizer.py` and CONTEXT.md Â§ MILP Optimizer.

---

## Seasonal Control Strategies

| Season | Months | Primary lever | Battery mode |
|---|---|---|---|
| Summer | Junâ€“Sep | HVAC pre-cool (10amâ€“2pm) | Demand charge management |
| Shoulder | Aprâ€“May, Octâ€“Nov | Moderate HVAC | TOU arbitrage |
| Winter | Janâ€“Mar, Dec | No HVAC cooling | Grid services + TOU arbitrage |

Summer: pre-cool to 70 Â°F before on-peak (2pmâ€“8pm), battery discharges
during on-peak to cut the demand charge peak.

Winter: enroll in DSGS for demand-response revenue; no pre-cooling needed.

---

## Bill Calculator â€” SCE TOU-GS-3

This is the most critical function. It must be exact.

**Rate periods (Summer: Junâ€“Sep):**

| Period | Hours | Type | Rate ($/kWh) |
|---|---|---|---|
| On-peak | 14:00â€“20:00 weekdays | Energy | $0.28317 |
| Mid-peak | 10:00â€“14:00 + 20:00â€“21:00 weekdays | Energy | $0.15498 |
| Off-peak | All other hours | Energy | $0.09871 |

**Rate periods (Winter: Octâ€“May):**

| Period | Hours | Rate ($/kWh) |
|---|---|---|
| Mid-peak | 10:00â€“21:00 weekdays | $0.13245 |
| Off-peak | All other hours | $0.09871 |

**Demand charges:**
- Summer on-peak: $19.10/kW (highest 15-min kW during on-peak hours)
- All-time: $8.85/kW (highest 15-min kW in any hour of the month)

**Fixed charge:** $302.72/month customer charge.

Demand charge is based on the **highest single 15-minute average kW**
in the billing period, not an hourly average.

---

## Agent Architecture (LangGraph)

Five specialist agents orchestrated by a LangGraph StateGraph.

```
User Input (data path, tariff, scenario params)
                  |
          [Orchestrator Agent]
          agents/orchestrator.py
         /    |       |      |    \
        v     v       v      v     v
      Data  Tariff Thermal  MILP  Report
     Agent  Agent   Agent  Agent  Agent
```

| Agent | File | Responsibility |
|---|---|---|
| Data | `agents/data_agent.py` | Load, validate, align all 5 sources |
| Tariff | `agents/tariff_agent.py` | Baseline bill + rate schedule array |
| Thermal | `agents/thermal_agent.py` | RC fit, RÂ² check, pre-cool schedule |
| Optimizer | `agents/optimizer_agent.py` | MILP for 5 scenarios x 12 months |
| Report | `agents/report_agent.py` | Charts, narrative (Claude), JSON output |

Orchestrator uses LangGraph `StateGraph` with typed state dict passed
between agents. Error handling: missing data (<2 hr gap â†’ interpolate,
>2 hr â†’ flag); infeasible MILP â†’ relax comfort bounds and retry.

---

## Streamlit Dashboard

**File:** `streamlit_app/app.py`

Three panels:

**Panel 1 â€” Building Overview (static)**
- Monthly load profile heatmap (hour of day x month)
- HVAC load vs outdoor temperature scatter + RC fit overlay
- Monthly bill breakdown stacked bar (energy / demand / fixed)
- Key stats: peak kW, annual kWh, annual bill $

**Panel 2 â€” Scenario Simulator (interactive)**
Sliders: solar size (0â€“500 kW), battery (0â€“500 kW / 0â€“1000 kWh),
comfort band (Â±1â€“6 Â°F), DSGS enrollment toggle.
On change: re-run optimizer, update waterfall chart, savings chart,
payback table.

**Panel 3 â€” Engineering Tradeoffs (static analysis)**
- Pre-cool depth vs free load-shed window
- Battery size vs demand charge savings (diminishing returns)
- Grid services revenue vs demand charge savings conflict
- Seasonal dispatch comparison

---

## Output Format

Every run writes `outputs/{run_timestamp}/savings_summary.json`:

```json
{
  "run_id": "2024-01-15T10:32:00",
  "building": {
    "type": "SecondarySchool",
    "location": "Mission Viejo, CA",
    "peak_demand_kw": 187.3,
    "annual_kwh": 1842000
  },
  "tariff": "SCE TOU-GS-3",
  "baseline_annual_bill": 185420,
  "scenarios": {
    "solar_only":        { "annual_savings": 42220, "capex": 280000 },
    "solar_plus_hvac":   { "annual_savings": 64620, "capex": 285000 },
    "solar_hvac_battery":{ "annual_savings": 92020, "capex": 435000 },
    "full_stack":        { "annual_savings": 111220, "capex": 435000,
                           "grid_services_revenue": 19200 }
  },
  "engineering_tradeoffs": {
    "optimal_precool_temp_summer_f": 70,
    "free_loadshed_window_hours": 2.5,
    "thermal_model_r2": 0.84
  }
}
```

---

## Engineering Tradeoffs to Highlight

These four tradeoffs demonstrate domain depth. Each must appear in the
notebook and dashboard.

**Tradeoff 1 â€” Pre-cooling depth vs morning energy cost**
Deeper pre-cool = longer free afternoon load-shed window.
But morning energy is not free â€” it is mid-peak rate in summer.
Optimum: minimize `(morning energy cost) - (afternoon demand charge avoided)`.
Typical result: 70 Â°F pre-cool, 2.5 hr free window.

**Tradeoff 2 â€” Battery sizing: power vs energy**
Demand charge management needs high kW (short burst).
TOU arbitrage needs high kWh (sustained discharge).
DSGS requires SoC headroom â€” can't fully commit to either.
Show: demand charge savings vs battery size (flat after ~125 kW here).
Show: HVAC load control reduces required battery size by ~33%.

**Tradeoff 3 â€” Grid services vs demand charge conflict**
DSGS events coincide with afternoon on-peak (that is when the grid needs
load relief). Battery dispatched for DSGS may not be available for peak
shaving. Resolution: hold minimum SoC reserve for demand charge during
DSGS events. Show this with a specific day example.

**Tradeoff 4 â€” Seasonal strategy differences**
Summer: HVAC pre-cool is the dominant lever; battery amplifies it.
Winter: no HVAC cooling; battery does TOU arbitrage + grid services only.
Shoulder: moderate everything; demand charge reduction is primary goal.
Show: month-by-month savings by intervention type (stacked bar).

---

## Sanity-Check Numbers

From Elexity's published JSerra Catholic High School case study.
If analysis diverges significantly, check tariff rates and peak demand.

| Item | Expected value |
|---|---|
| Building peak demand | 150â€“200 kW (hot day) |
| HVAC fraction (summer) | 60â€“70% of total load |
| Battery savings (125kW/250kWh) | ~$27,000/year |
| HVAC load control additional savings | ~$17,000/year |
| Grid services (DSGS) revenue | ~$8,000/year |
| Total annual value | ~$52,000/year |
| System payback | ~3.5 years |

---

## Implementation Order

Phases 0â€“9 map to TASKS.md. Phases 10â€“12 are the Phase 2 roadmap.

1. Phase 0 â€” Prerequisites (env, dirs, gitignore) [DONE]
2. Phase 1 â€” Data acquisition [DONE]
3. Phase 2 â€” Tariff parser + bill calculator [DONE]
4. Phase 3 â€” Cost driver analysis
5. Phase 4 â€” Core models (thermal, battery, solar, MILP)
6. Phase 5 â€” Control strategies + savings calculator
7. Phase 6 â€” LangGraph agents (5 specialists + orchestrator)
8. Phase 7 â€” Streamlit dashboard
9. Phase 8 â€” Notebook deliverable
10. Phase 9 â€” FastAPI service + Docker (Swagger UI testable)
11. Phase 10 â€” DA price forecast module (replaces perfect foresight)
12. Phase 11 â€” Rolling MPC controller (intraday re-optimization)
13. Phase 12 â€” CAISO ancillary services value stack

---

## FastAPI Service + Docker (Phase 9)

The analysis pipeline is wrapped in a FastAPI service so that every
core function is callable via HTTP and testable via Swagger UI at
`http://localhost:8000/docs`. The same container also runs the
Streamlit dashboard.

---

### Why FastAPI over a plain CLI

| Concern | CLI only | FastAPI |
|---|---|---|
| Integration testing | ad-hoc prints | Swagger UI + pytest client |
| Remote invocation | SSH / subprocess | REST POST, curl-friendly |
| Agent orchestration | subprocess call | internal import or HTTP |
| CI smoke test | shell script | `pytest -k api` in-container |
| Demo to stakeholders | terminal only | browser-accessible endpoints |

---

### API Design

**Base URL:** `http://localhost:8000`
**Docs:** `/docs` (Swagger UI), `/redoc` (ReDoc)

All endpoints accept JSON and return JSON. Heavy computation (MILP,
full-year optimizer) runs synchronously; typical latency < 2 s for a
single month on the synthetic dataset.

#### Endpoints

```
GET  /health
     Returns: {"status": "ok", "data_loaded": bool}

POST /bill/monthly
     Body:   {"month": 1-12}
     Returns: monthly bill dict (energy_charge, demand_charge, ...)

POST /bill/annual
     Body:   {}
     Returns: list of 12 monthly bill dicts + annual summary

POST /cost-driver
     Body:   {}
     Returns: bill decomposition % shares + heatmap data

POST /optimize
     Body: {
       "month": int,
       "solar_kw": float,       # installed PV size
       "battery_power_kw": float,
       "battery_energy_kwh": float,
       "enable_precool": bool,
       "enable_dsgs": bool
     }
     Returns: dispatch schedule + savings vs baseline for that month

POST /savings/annual
     Body: same as /optimize but runs all 12 months
     Returns: scenario waterfall + NPV + payback years

GET  /tariff
     Returns: full SCE TOU-GS-3 rate schedule from tariff JSON
```

#### Error contract

All errors return `{"detail": "<message>"}` with the appropriate HTTP
status code (400 for bad input, 422 for validation, 500 for solver
failure). Infeasible MILP returns 200 with
`{"status": "infeasible", "reason": "..."}` so callers can distinguish
solver issues from HTTP failures.

---

### Module â€” `api/main.py`

```
api/
  __init__.py
  main.py       â† FastAPI app, lifespan loader, all routes
  schemas.py    â† Pydantic request/response models
  deps.py       â† dependency-injection for shared DataLoader state
```

**Lifespan pattern** â€” data and tariff are loaded once at startup into
module-level state (`app.state.df`, `app.state.tariff`), not re-read
on every request:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.df = _load_meter()      # loads parquet once
    app.state.tariff = load_tariff()  # loads JSON once
    yield
    # cleanup if needed
```

**No async I/O in route handlers** â€” all computation is CPU-bound
(pandas, cvxpy). Use plain `def` routes so FastAPI runs them in a
thread-pool executor automatically, keeping the event loop free.

---

### Pydantic schemas (`api/schemas.py`)

```python
class OptimizeRequest(BaseModel):
    month: int = Field(..., ge=1, le=12)
    solar_kw: float = Field(100.0, ge=0, le=1000)
    battery_power_kw: float = Field(125.0, ge=0, le=500)
    battery_energy_kwh: float = Field(250.0, ge=0, le=2000)
    enable_precool: bool = True
    enable_dsgs: bool = True

class MonthlyBillResponse(BaseModel):
    month: int
    energy_charge: float
    demand_charge: float
    fixed_charge: float
    total: float
    peak_demand_kw: float
    total_kwh: float
```

---

### Docker Architecture

Two services in `docker-compose.yml`:

```
â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
â”‚  Docker Compose                                          â”‚
â”‚                                                          â”‚
â”‚  api   (port 8000)  â† FastAPI + uvicorn                  â”‚
â”‚  dash  (port 8501)  â† Streamlit app                      â”‚
â”‚                                                          â”‚
â”‚  Shared volume: ./data â†’ /app/data (read-only)           â”‚
â”‚  Shared volume: ./outputs â†’ /app/outputs (read-write)    â”‚
â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜
```

**`Dockerfile`** â€” multi-stage, single image used by both services:

```dockerfile
FROM python:3.12-slim AS base
WORKDIR /app

# Install uv
RUN pip install uv --no-cache-dir

# Copy dependency files first for layer caching
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# Copy source
COPY . .

# Default: FastAPI on 8000
CMD ["uv", "run", "uvicorn", "api.main:app",
     "--host", "0.0.0.0", "--port", "8000"]
```

**`docker-compose.yml`** â€” override CMD for Streamlit:

```yaml
services:
  api:
    build: .
    ports: ["8000:8000"]
    volumes:
      - ./data:/app/data:ro
      - ./outputs:/app/outputs
    env_file: .env

  dash:
    build: .
    command: >
      uv run streamlit run streamlit_app/app.py
      --server.port 8501 --server.address 0.0.0.0
    ports: ["8501:8501"]
    volumes:
      - ./data:/app/data:ro
    env_file: .env
```

---

### Swagger UI Test Workflow

After `docker compose up`:

1. Open `http://localhost:8000/docs` in browser.
2. **`GET /health`** â€” confirms data loaded.
3. **`POST /bill/monthly`** with `{"month": 7}` â€” spot-check July bill.
4. **`POST /optimize`** with month 7, solar 100, battery 125/250 â€”
   verify savings > 0 for a summer month.
5. **`POST /savings/annual`** â€” full-year run; confirm NPV > 0 with
   default DER assumptions.
6. **`GET /tariff`** â€” confirms tariff JSON is served correctly.

All of the above can also run as automated pytest tests using
`httpx.AsyncClient(app=app)` without Docker (see Phase 9 Task 9.4).

---

### `pyproject.toml` additions for Phase 9

```toml
# Add to [project] dependencies:
"fastapi>=0.111",
"uvicorn[standard]>=0.29",
"httpx>=0.27",   # for pytest API client
```

Add via: `uv add fastapi "uvicorn[standard]" httpx`

---

## Key Design Decisions

- **uv only** â€” no pip, no poetry, no conda. `uv.lock` is committed.
- **Geographic consistency** â€” SCE tariff, CAISO prices, LA weather,
  DSGS grid services. Never mix utility territories.
- **MILP not heuristic** â€” cvxpy with GLPK_MI resolves competing
  objectives (demand charge vs TOU vs grid services) optimally.
- **Calibrated R and C** â€” RC parameters come from curve_fit on data.
  Never hardcode. RÂ² < 0.70 means the building is not HVAC-dominated.
- **All units explicit** â€” power in kW, energy in kWh, temperature in Â°F,
  money in USD. No silent unit conversions.
- **Data fallback** â€” synthetic data generation for when S3/API access
  fails, matching published NREL/CAISO statistics.
- **Tariff JSON is authoritative** â€” `data/tariff/sce_tou_gs3.json` is
  the single source of truth for all rate lookups.
- **DSGS rate** â€” $2.00/kWh for demand response events (from tariff JSON
  notes field).
- **Never commit** `.env`, `data/`, `outputs/` â€” only tariff JSON stays
  in git.

---

## Version 2 Roadmap â€” Market Design Improvements

This section documents known model limitations and the improvement plan
derived from literature review (July 2026). Sources: CAISO Tariff
Section 8 (Nov 2025), CAISO 2024 Battery Storage Special Report,
LBNL "Navigating Modeling Frontiers for ESRs" (2024), Springer
"Optimal operation of storage in intraday markets" (2026), arXiv
"Battery Bidding under Price Uncertainty" (June 2026).

---

### Market Layer Architecture â€” DA vs Real-Time

The current Phase 0â€“9 model uses historical 2023 CAISO LMPs as if they
were known with certainty across the full year. This is ex-post perfect
foresight and overestimates TOU arbitrage revenue.

The correct two-layer market architecture:

```
Layer 1: Day-Ahead (IFM)
  CAISO clears at ~1pm D-1 and publishes LMPs for all 24 hours.
  Prices ARE known at bid time. DA MILP is valid here.
  Run: 24hr MILP using IFM-cleared prices -> submit bids.

Layer 2: Real-Time (FMM + RTD)
  FMM: 75-min look-ahead, 15-min intervals, 1st interval binding.
  RTD: 65-min look-ahead, 5-min intervals, 1st interval binding.
  Prices are UNKNOWN at decision time. Requires MPC or stochastic opt.
  Run: re-solve 24hr MILP every 15 min with updated SoC + forecast.
```

Tasks 10 (price forecast) and Task 11 (MPC controller) implement this.

---

### CAISO Ancillary Services â€” Stacking Rules

CAISO **co-optimizes energy and all ancillary services simultaneously**
in the IFM (DA) and RTM (RT). The same MW of battery capacity can be
simultaneously bid into:

- Energy arbitrage (charge/discharge)
- Regulation Up (AGC 4-second response)
- Regulation Down
- Spinning Reserve (10-min synchronised)
- Non-Spinning Reserve (10-min non-synchronised)

Physical gate: **ASSOC (Ancillary Services State-of-Charge)** â€” battery
must hold stored energy sufficient for all AS awards for >= 30 minutes.

This is unlike European markets (EPEX/OMIE + FCR/aFRR), where energy
and frequency regulation are separate sequential auctions and the same
MW cannot be committed to both in the same delivery window.

ERCOT added real-time AS co-optimization (RTC+B) in December 2025,
aligning with CAISO's co-optimization framework.

**DSGS stacking restriction:** DSGS is a CEC state program, not a CAISO
market product. DSGS 5th Edition (2026) prohibits dual compensation â€”
a load reduction cannot receive both DSGS payment and CAISO AS/energy
revenue in the same interval. Model DSGS and CAISO AS as mutually
exclusive for any given dispatch window.

**Revenue missing from current model:**
Batteries provided ~84% of CAISO regulation in 2024. A 125kW/250kWh
battery can earn $15,000â€“$25,000/year from Regulation Up + Down alone.
This is absent from the current value stack. Task 12 adds it.

---

### Current Model Simplifications â€” Prioritised

High impact (Phase 2):

| Simplification | Current | Target |
|---|---|---|
| Price certainty | Perfect foresight (ex-post) | DA forecast + RT MPC |
| Horizon | Monthly MILP | 24hr rolling, carryover SoC |
| AS revenue | DSGS only ($8k flat) | Reg Up/Down + Spin + DSGS |
| DSGS revenue | $8k/yr flat | Probabilistic event model |

Medium impact (Version 2 or Version 3):

| Simplification | Current | Target |
|---|---|---|
| RC model | 1st-order, temperature only | 2-zone, humidity + ventilation |
| HVAC control | Continuous variable p_hvac | VFD modulation constraints |
| Solar profile | Deterministic PVWatts | 3-scenario stochastic fan |

Lower impact (Phase 3):

| Simplification | Current | Target |
|---|---|---|
| Battery degradation | Constant 92% RT efficiency | Rainflow cycle counting |
| Scale | Single building | VPP aggregation |
| RT dispatch | Not modelled | RL policy (offline trained) |

---

### Version 2 New Modules

Three new files added in Tasks 10â€“12 (see TASKS.md):

**`models/price_forecast.py`** (Task 10)
Simple DA price shape model: seasonal median LMP by hour-of-week, plus
a weather adjustment term (temperature drives afternoon spike in CAISO).
Replaces the perfect-foresight assumption for prospective analysis.

**`models/mpc_controller.py`** (Task 11)
Rolling MPC loop that wraps the existing `models/optimizer.py` MILP:
- Re-solve every 15 minutes using updated SoC as initial condition
- Use `price_forecast.py` output as price signal for next 24 hours
- Implements the DA layer (known prices) + RT layer (forecast prices)

**`analysis/ancillary_services.py`** (Task 12)
CAISO Regulation Up/Down and Spinning Reserve revenue estimate:
- Load historical CAISO AS prices (downloadable from CAISO OASIS)
- Estimate max AS capacity the battery can offer given SoC constraints
- Add AS revenue to the value stack waterfall in savings_calculator.py
- Enforce DSGS/AS mutual exclusivity for each dispatch interval

---

## Version 3 Roadmap â€” Advanced Modelling

Phase 3 items are lower-urgency improvements for after the full Phase 2
pipeline is validated. They address physical realism and scale.

---

### V3-A â€” Battery Degradation Model

**Problem:** The current battery model uses a fixed 92% round-trip
efficiency and never ages the battery. Real lithium-ion cells degrade
with cycle depth, temperature, and calendar time. The optimal DoD
(depth of discharge) shifts over the asset's lifetime as capacity fades.

**Approach â€” Rainflow cycle counting + linear capacity fade:**

```
Degradation model (simplified):
  - Count charge/discharge half-cycles using Rainflow algorithm.
  - Each cycle at depth d removes capacity: delta_cap = k * d^alpha
    (typical: alpha ~ 1.8 for NMC chemistry)
  - Throughput degradation: ~0.03% capacity loss per full equivalent
    cycle (FEC) for modern LFP cells.
  - Calendar ageing: ~2â€“4% capacity loss per year at 25Â°C.

Operational impact:
  - Deeper cycles (10%â€“95% SoC) maximise daily revenue but accelerate
    degradation. Optimal SoC window narrows to ~20%â€“80% over 10yr.
  - Battery replacement cost (~$200/kWh for LFP, 2025 prices) enters
    the NPV calculation as a capital event at year ~12â€“15.
```

**New module:** `models/battery_degradation.py`
- `RainflowCounter` class: accumulates half-cycles from SoC time series.
- `CapacityFadeModel`: maps cycle history to remaining capacity (kWh).
- `compute_degradation_cost(dispatch_log)`: returns $/year degradation
  cost as a negative revenue stream in the value stack.
- Integration: `models/battery_model.py` calls the counter on each
  charge/discharge event; `analysis/savings_calculator.py` deducts
  degradation cost from NPV.

**Reference:** CAISO 2024 Battery Report Â§4 (SoC modeling); NREL
"Battery Storage Technology Assessment" (2023); IEC 62660 cycle life
standard for Li-ion traction batteries.

**Done signal:** NPV calculation in savings_calculator shows ~$8,000â€“
$15,000/year degradation cost for a 125kW/250kWh battery cycling daily
at 80% DoD, narrowing the optimal DoD to ~60% for a 10-yr asset life.

---

### V3-B â€” Two-Zone RC Thermal Model

**Problem:** The Phase 1 RC model is single-zone, temperature-only.
It captures the bulk HVAC load response but misses:
- Thermal stratification (roof vs floor zones heat at different rates)
- Latent (humidity) loads, which dominate in SoCal coastal buildings
- Ventilation loads (outdoor air economiser cycles)

**Approach â€” Two-zone RC with latent load term:**

```
Zone 1 (envelope): T_env, R_env, C_env
Zone 2 (air mass): T_air, R_air, C_air

dT_air/dt = (T_env - T_air)/(R_air * C_air)
            - Q_hvac_sensible / C_air
            - Q_latent / C_air   (latent term: moisture removal)

dT_env/dt = (T_outdoor - T_env)/(R_env * C_env)
            + (T_air - T_env)/(R_air * C_env)

Q_latent = f(humidity_outdoor - humidity_setpoint)  [kW_thermal]
Q_hvac_total = Q_hvac_sensible + Q_latent / COP_latent
```

**Calibration:** Fit R_env, C_env, R_air, C_air from the HVAC load time
series using multi-parameter curve_fit on both temperature and (if
available) humidity from the EPW weather file. pvlib parses the EPW
`relative_humidity` column alongside `temp_air`.

**New module:** `models/thermal_model_2zone.py`
- `fit_2zone_rc(df, weather_df)`: fits 4 parameters instead of 1.
- `simulate_precooling_2zone(...)`: two coupled ODEs, same interface as
  the existing `simulate_precooling` for drop-in replacement.
- Expected improvement: RÂ² from ~0.75 to ~0.90 for SoCal buildings
  where latent loads are 20â€“30% of total HVAC.

**Reference:** Aste et al. (2013) "RC Thermal Network Models for
Building Simulation"; EnergyPlus Engineering Reference Â§4.

---

### V3-C â€” Stochastic Solar with Forecast Uncertainty

**Problem:** PVWatts gives a deterministic typical-year profile.
Cloud cover introduces Â±20â€“30% hour-ahead forecast error in SoCal.
On a cloudy afternoon, expected solar offset does not materialise â€” the
battery may have insufficient SoC to cover the demand charge peak because
the dispatch plan assumed solar would reduce grid draw.

**Approach â€” 3-scenario fan:**

```
Scenarios (probability weighted):
  Clear (p=0.65):    solar = PVWatts nominal output
  Partly cloudy (p=0.25): solar = PVWatts * cloud_factor ~ 0.55
  Overcast (p=0.10): solar = PVWatts * cloud_factor ~ 0.15

Cloud factor sampled from Beta(8, 2) for clear days (LA climatology).
```

**Integration:** The MILP in `models/optimizer.py` is extended to a
2-stage stochastic program:
- Stage 1: dispatch decisions made before solar realises (charge schedule)
- Stage 2: recourse decisions after solar realises (grid draw adjustment)
- Objective: minimise expected bill across all 3 scenarios

**New module:** `models/solar_model_stochastic.py`
- `generate_solar_scenarios(base_profile, n_scenarios=3)`: returns
  scenario matrix (T x n_scenarios) with probability weights.
- `optimize_dispatch_stochastic(...)`: extends `optimizer.py` with
  scenario-indexed variables for Stage 2 recourse.

**Reference:** Morales et al. (2013) "Integrating Renewables in
Electricity Markets"; arXiv 2606.14050 (June 2026) scenario approach.

---

### V3-D â€” Reinforcement Learning Intraday Dispatch

**Problem:** Rolling MPC (Task 11) re-solves the MILP every 15 min,
which requires a price forecast. RL avoids the forecast entirely by
learning a dispatch policy from historical data.

**Approach:**

```
State space:
  s_t = (SoC_t, hour_of_day, month, T_outdoor_t, solar_fraction_t,
         demand_peak_so_far_t)  â†’ 6 features

Action space:
  a_t = p_charge_t or p_discharge_t in [0, battery_power_kw]
  Discretised: [-125, -100, -75, -50, -25, 0, 25, 50, 75, 100, 125] kW

Reward:
  r_t = -(energy_cost_t + demand_charge_contribution_t)
        + grid_services_revenue_t

Algorithm: Proximal Policy Optimisation (PPO) or SAC (Soft Actor-
Critic). SAC is preferred for continuous action space.
Training: 1 year of 2023 data (35,040 steps). Evaluate on hold-out
year. Benchmark against MPC policy from Task 11.
```

**New module:** `models/rl_dispatch.py`
- `BatteryEnv`: OpenAI Gym-compatible environment wrapping
  `models/battery_model.py` and the tariff rate lookup.
- `train_policy(env, n_episodes=500)`: trains SAC with stable-baselines3.
- `evaluate_policy(policy, env)`: returns annual bill and gap vs MPC.
- Expected: RL within 5â€“10% of MPC on in-distribution data; better on
  price spike days where MPC forecast fails.

**New dependency:** `stable-baselines3>=2.0`, `gymnasium>=0.29`.
Add via `uv add stable-baselines3 gymnasium`.

**Reference:** arXiv "Battery Bidding under Price Uncertainty" (June 2026,
RL section); Cao et al. (2020) "Reinforcement Learning and its Application
to Energy Storage Bidding".

---

### V3-E â€” VPP Aggregation

**Problem:** CAISO AS markets have minimum participation thresholds.
A single 125kW battery falls below the 1MW minimum for direct CAISO
market participation. Elexity's real product aggregates many C&I
buildings into a Virtual Power Plant (VPP).

**Architecture:**

```
VPP Aggregator
  Building 1 (school):     125kW / 250kWh battery
  Building 2 (office):     100kW / 200kWh battery
  Building 3 (warehouse):   75kW / 150kWh battery
  â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
  Aggregate:               300kW / 600kWh  â†’  CAISO AS eligible

Dispatch hierarchy:
  Orchestrator sends aggregate MW signal â†’ each building's MPC
  controller translates to local p_charge / p_discharge.
  Inter-building SoC balancing: charge low-SoC buildings first.
```

**DSGS Option 3 relevance:** The DSGS 5th Edition (2026) explicitly
targets storage VPP aggregations. Minimum 500kW nominal power rating
for VPP providers (updated from 100kW in prior edition). The three-
building aggregate above qualifies.

**New module:** `agents/vpp_orchestrator.py`
- `VPPOrchestrator`: holds list of `BatteryModel` instances.
- `dispatch_aggregate(target_kw)`: allocates MW across buildings
  pro-rata by available SoC headroom.
- `compute_aggregate_as_capacity()`: returns total MW available for
  CAISO Reg Up/Down, respecting per-building ASSOC constraints.

**Reference:** DSGS 5th Edition Program Guidelines (CEC, 2026) Â§5.A;
CAISO "Aggregated Distributed Energy Resources" tariff provisions.

---

### Version 3 Implementation Order

Suggested order based on dependencies and expected value:

1. V3-B (Two-zone RC) â€” improves thermal model accuracy, feeds back
   into Task 11 MPC's pre-cool schedule.
2. V3-C (Stochastic solar) â€” extends the existing MILP; moderate
   effort; improves demand charge risk quantification.
3. V3-A (Battery degradation) â€” adds cost term to NPV; changes
   optimal DoD recommendation.
4. V3-D (RL dispatch) â€” benchmarks against MPC; highest research
   novelty; requires new dependency (stable-baselines3).
5. V3-E (VPP aggregation) â€” changes the business model; implement
   only after single-building pipeline is fully validated.

