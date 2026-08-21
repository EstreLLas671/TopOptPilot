from __future__ import annotations

import pandas as pd

from topoptpilot.benchmarks import BenchmarkRunner


def render_benchmarks(st, service) -> None:
    st.markdown("### Baseline Dashboard")
    st.caption("Equal-budget deterministic comparison: Random / Grid / TPE / Rule / Pi")
    if st.button("Run compact benchmark", type="primary"):
        runner = BenchmarkRunner()
        with st.spinner("Running real coarse 2D FEM baselines…"):
            st.session_state.baseline_results = [runner.run(method, budget=5, max_iter=20)
                                                 for method in runner.METHODS if method != "Pi"]
    if st.button("Run live Pi baseline"):
        runner = BenchmarkRunner()
        with st.spinner("Pi is planning; FEM runs asynchronously…"):
            st.session_state.pi_baseline = runner.run_pi_campaign(service, budget=5, timeout=180)
        st.session_state.baseline_results = [*st.session_state.get("baseline_results", []),
                                             st.session_state.pi_baseline]
    values = st.session_state.get("baseline_results", [])
    if values:
        rows = [{"method": item["method"],
                 "compliance": item["metrics"].get("best_compliance"),
                 "gray_ratio": item["metrics"].get("best_gray_ratio"),
                 "experiments_to_feasible": item["metrics"].get("experiments_to_feasible"),
                 "total_fem_cost": item["metrics"].get("total_fem_cost"),
                 "budget": item["budget"]} for item in values]
        frame = pd.DataFrame(rows).set_index("method")
        st.dataframe(frame, use_container_width=True)
        st.bar_chart(frame[["compliance"]])
    with st.expander("Ablation definitions"):
        st.json(BenchmarkRunner().ablations())
