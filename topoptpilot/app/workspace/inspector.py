from __future__ import annotations


def render_inspector(st, research: dict, selected: tuple[str, str]) -> None:
    st.markdown("<div class='panel-heading'>INSPECTOR</div>", unsafe_allow_html=True)
    kind, object_id = selected
    if kind == "experiment":
        experiment = next((item for item in research["experiments"] if item["id"] == object_id), None)
        if experiment:
            _experiment(st, experiment)
            return
    if kind == "decision":
        decision = next((item for item in research["decisions"] if item["id"] == object_id), None)
        if decision:
            _decision(st, decision)
            return
    _research(st, research)


def _research(st, research: dict) -> None:
    st.markdown(f"### {research['id']}")
    st.caption(research["name"])
    st.markdown("**Goal**")
    st.write(research["goal"])
    st.markdown("**Constraints**")
    st.json(research["constraints"])
    st.metric("Budget", f"{research['budget_used']} / {research['budget_total']}")
    best = research.get("best_experiment")
    st.metric("Current Best", best["id"] if best else "—")
    st.markdown(f"**Termination**  \n{research['status']}")
    if research["locks"]:
        st.markdown("**Locked parameters**")
        st.json(research["locks"])


def _experiment(st, experiment: dict) -> None:
    st.markdown(f"### {experiment['id']}")
    st.caption(experiment["status"])
    st.markdown(f"**Fidelity**  \n{experiment['fidelity']}")
    st.markdown(f"**Mesh**  \n{experiment['mesh_level']}")
    st.markdown("**Parameters**")
    for key, value in experiment["parameters"].items():
        st.markdown(f"<div class='kv'><span>{key}</span><strong>{value}</strong></div>",
                    unsafe_allow_html=True)
    result = experiment.get("result") or {}
    if result:
        st.divider()
        st.markdown("**Results**")
        values = {**result.get("objective", {}), **result.get("quality", {}),
                  "runtime_s": result.get("solver", {}).get("solve_time_seconds")}
        for key, value in values.items():
            st.markdown(f"<div class='kv'><span>{key}</span><strong>{_short(value)}</strong></div>",
                        unsafe_allow_html=True)
    st.divider()
    st.markdown(f"**Safety**  \n{experiment['safety']}")
    st.markdown(f"**Initialization**  \nWarm Start: {experiment.get('warm_start') or 'None'}")


def _decision(st, decision: dict) -> None:
    st.markdown(f"### {decision['id']}")
    st.markdown(f"**Intent**  \n{decision['intent']}")
    st.markdown(f"**Evidence**  \n{decision['reason']}")
    st.markdown(f"**Policy Result**  \nRisk: {decision['risk']}")
    st.markdown(f"**Human Approval**  \n{decision['status']}")


def _short(value):
    return f"{value:.4g}" if isinstance(value, float) else value
