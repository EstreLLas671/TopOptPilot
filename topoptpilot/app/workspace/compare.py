from __future__ import annotations

from topoptpilot.app.components.topology_view import render_topology


def render_compare(st, experiments: list[dict]) -> None:
    if len(experiments) != 2:
        st.info("Use `/compare E01 E02` to select two experiments.")
        return
    left, right = st.columns(2)
    for column, experiment in zip((left, right), experiments):
        with column:
            st.markdown(f"### {experiment['id']}")
            render_topology(st, experiment)
            result = experiment.get("result") or {}
            st.json({"parameters": experiment["parameters"],
                     "objective": result.get("objective", {}),
                     "quality": result.get("quality", {})})
    lq, rq = ((item.get("result") or {}).get("quality", {}) for item in experiments)
    lg, rg = lq.get("gray_ratio"), rq.get("gray_ratio")
    if isinstance(lg, (float, int)) and isinstance(rg, (float, int)) and lg:
        delta = (rg - lg) / lg
        st.info(f"ANALYSIS — Gray ratio changed by {delta:+.1%}. "
                f"Connectivity changed from {lq.get('connected_components', '—')} to "
                f"{rq.get('connected_components', '—')} components.")

