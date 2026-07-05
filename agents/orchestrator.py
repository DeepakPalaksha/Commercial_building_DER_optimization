"""
LangGraph orchestrator: chains all specialist agents into a single
StateGraph pipeline.

Pipeline:
  data --> tariff --> thermal --> optimizer --> report --> END

Usage:
  uv run python agents/orchestrator.py
  uv run python agents/orchestrator.py --input data/meter/school_ca_15min.parquet

See PLAN.md -- Agent Architecture section.
"""
from __future__ import annotations

import argparse
from langgraph.graph import StateGraph, END

from agents.data_agent import run_data_agent
from agents.tariff_agent import run_tariff_agent
from agents.thermal_agent import run_thermal_agent
from agents.optimizer_agent import run_optimizer_agent
from agents.report_agent import run_report_agent


def build_graph() -> "CompiledGraph":  # type: ignore[name-defined]
    """Construct and compile the LangGraph StateGraph."""
    graph = StateGraph(dict)

    graph.add_node("data", run_data_agent)
    graph.add_node("tariff", run_tariff_agent)
    graph.add_node("thermal", run_thermal_agent)
    graph.add_node("optimizer", run_optimizer_agent)
    graph.add_node("report", run_report_agent)

    graph.set_entry_point("data")
    graph.add_edge("data", "tariff")
    graph.add_edge("tariff", "thermal")
    graph.add_edge("thermal", "optimizer")
    graph.add_edge("optimizer", "report")
    graph.add_edge("report", END)

    return graph.compile()


def run_pipeline(meter_path: str | None = None) -> dict:
    """
    Execute the full analysis pipeline.

    Args:
        meter_path: optional override path to a meter parquet file.
                    If None, the default data/meter/ path is used.

    Returns:
        Final state dict with all agent outputs.
    """
    initial_state: dict = {}
    if meter_path:
        initial_state["meter_path"] = meter_path

    app = build_graph()
    final_state = app.invoke(initial_state)
    return final_state


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Elexity Building Energy Analysis Pipeline"
    )
    parser.add_argument(
        "--input",
        default=None,
        help="Path to meter parquet file (default: data/meter/school_ca_15min.parquet)",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("  Elexity Building Energy Analysis Pipeline")
    print("  Southern California Secondary School | SCE TOU-GS-3")
    print("=" * 60)
    print()

    result = run_pipeline(meter_path=args.input)

    print("\n" + "=" * 60)
    print(f"  Pipeline complete.")
    print(f"  Output: {result.get('output_dir', 'N/A')}")
    print("=" * 60)
