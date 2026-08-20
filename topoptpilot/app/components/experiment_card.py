from __future__ import annotations

from topoptpilot.app.components.topology_view import render_convergence, render_topology


def render_experiment_card(st, service, experiment: dict) -> None:
    status = experiment["status"]
    symbol = {"WAITING": "○", "RUNNING": "▶", "SUCCESS": "✓",
              "FAILED": "✗", "CANCELLED": "⚠"}.get(status, "○")
    st.markdown(f"<div class='event-label experiment'>{symbol} EXPERIMENT {experiment['id']} · {status}</div>",
                unsafe_allow_html=True)
    st.markdown(f"**{experiment['fidelity']}** — {experiment['purpose']}")
    if status in {"RUNNING", "WAITING"}:
        st.progress(float(experiment.get("progress", 0)),
                    text=f"Iteration {experiment.get('current_iteration', 0)}")
    result = experiment.get("result") or {}
    if result:
        objective, quality = result.get("objective", {}), result.get("quality", {})
        cols = st.columns(4)
        cols[0].metric("Compliance", _display(objective.get("compliance")))
        cols[1].metric("Gray", _percent(quality.get("gray_ratio")))
        cols[2].metric("Components", _display(quality.get("connected_components")))
        cols[3].metric("Runtime", f"{result.get('solver', {}).get('solve_time_seconds', 0):.1f}s")
        topology, convergence, metrics = st.tabs(["Topology", "Convergence", "Metrics"])
        with topology:
            render_topology(st, experiment)
        with convergence:
            render_convergence(st, experiment)
        with metrics:
            st.json({"objective": objective, "constraints": result.get("constraints", {}),
                     "quality": quality, "solver": result.get("solver", {})})
    if experiment.get("error"):
        st.error(experiment["error"])


def _display(value):
    if value is None:
        return "—"
    return f"{value:.3f}" if isinstance(value, float) else str(value)


def _percent(value):
    return f"{value:.1%}" if isinstance(value, (float, int)) else "—"

