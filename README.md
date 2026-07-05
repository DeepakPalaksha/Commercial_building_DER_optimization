# Elexity Building Energy Analysis

C&I building energy cost analysis tool â€” Southern California Secondary School
(SCE TOU-GS-3 tariff, CAISO market, DSGS grid services).

Read `CONTEXT.md` before touching any code. It has everything.

---

## Quickstart

### Step 1 â€” Install uv

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.bashrc  # or restart terminal
```

### Step 2 â€” Clone and set up

```bash
cd elexity-analysis
uv python pin 3.11
uv sync
```

### Step 3 â€” Set up environment variables

```bash
cp .env.example .env
# Edit .env and add:
# NREL_API_KEY=your_key_from_developer.nrel.gov  (free registration)
# ANTHROPIC_API_KEY=your_key  (for report agent narrative generation)
```

### Step 4 â€” Download data (do this once)

```bash
uv run python scripts/download_data.py
```

This downloads:
- NREL ComStock building meter data (secondary school, SoCal, 2023)
- CAISO day-ahead LMP prices (2023, SP15 zone)
- Los Angeles TMY3 weather file
- NREL PVWatts solar generation profile (100kW, Mission Viejo CA)

SCE tariff JSON is already included in `data/tariff/sce_tou_gs3.json`.

### Step 5 â€” Run the analysis

```bash
# Full pipeline via agents
uv run python agents/orchestrator.py --input data/meter/school_ca_15min.parquet

# Or run individual steps
uv run python analysis/bill_calculator.py
uv run python analysis/cost_driver.py
uv run python analysis/savings_calculator.py
```

### Step 6 â€” Launch the dashboard

```bash
uv run streamlit run streamlit_app/app.py
# Opens at http://localhost:8501
```

### Step 7 â€” Run with Docker

```bash
docker build -t elexity-analysis .
docker run -p 8501:8501 -v $(pwd)/data:/app/data elexity-analysis
```

---

## Data Sources

| Data | Source | How to get it |
|---|---|---|
| Building meter data | NREL ComStock (public S3) | `scripts/download_data.py` |
| Weather | EnergyPlus EPW (NOAA/DOE) | `scripts/download_data.py` |
| Electricity prices | CAISO OASIS (free API) | `scripts/download_data.py` |
| Solar generation | NREL PVWatts (free API) | `scripts/download_data.py` |
| SCE tariff | Hand-encoded from SCE website | Already in `data/tariff/` |

---

## Project Structure

See `CONTEXT.md` for full details. Quick reference:

```
models/          RC thermal model, battery model, solar model, MILP optimizer
analysis/        Bill calculator, cost driver, savings calculator
agents/          LangGraph orchestrator + 5 specialist agents
streamlit_app/   Interactive dashboard
notebooks/       90-minute exercise deliverable
outputs/         Run results (gitignored)
data/            All data files (gitignored except tariff JSON)
```

---

## Key Numbers (Sanity Check)

From Elexity's published JSerra Catholic High School case study:
- Building peak demand: 150â€“200 kW
- Battery savings: ~$27k/year (125kW, 2hr battery)
- HVAC load control: +$17k/year additional
- Grid services: +$8k/year revenue
- Total payback: ~3.5 years

If your numbers are far from these, check the tariff rates and peak demand values.

