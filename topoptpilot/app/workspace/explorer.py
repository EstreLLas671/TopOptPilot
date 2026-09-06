from __future__ import annotations


def render_explorer(st, service, research: dict) -> None:
    st.markdown("<div class='panel-heading'>RESEARCH EXPLORER</div>", unsafe_allow_html=True)
    with st.expander("＋ New research", expanded=False):
        with st.form("new-research"):
            name = st.text_input("Name", value="MBB Beam Study")
            goal = st.text_area("Goal", value="Minimize compliance while satisfying constraints.")
            budget = st.number_input("Total FEM budget", 1, 100, 12)
            mode = st.selectbox("Mode", ["COPILOT", "AUTONOMOUS"])
            if st.form_submit_button("Create"):
                created = service.create_research({"name": name, "goal": goal,
                                                   "budget_total": budget, "mode": mode})
                st.session_state.selected_research = created["id"]
                st.session_state.selected_object = ("research", created["id"])
                st.rerun()
    if st.button(f"▾  {research['id']}", key="select-research", use_container_width=True):
        st.session_state.selected_object = ("research", research["id"])
    with st.expander("Goal & Constraints", expanded=False):
        st.caption(research["goal"])
        for key, value in research["constraints"].items():
            st.markdown(f"`{key}`  {value}")
    session = service.store.get_agent_session(research["id"])
    context = float((session or {}).get("context_usage", 0) or 0)
    st.caption(f"Pi · {(session or {}).get('status', 'OFFLINE')} · "
               f"{service.health()['agent_model']} · context {context:.1%}")
    if research["status"] not in {"STOPPED"} and st.button("▶ Start autonomous Pi", use_container_width=True):
        service.start_autonomous_research(research["id"])
        st.rerun()
    st.markdown("<div class='tree-section'>EXPERIMENTS</div>", unsafe_allow_html=True)
    for experiment in research["experiments"]:
        symbol = {"WAITING": "○", "RUNNING": "▶", "SUCCESS": "✓",
                  "FAILED": "✗", "CANCELLED": "⚠"}.get(experiment["status"], "○")
        label = f"{symbol}  {experiment['id']}  ·  {experiment['fidelity'].split('—')[0].strip()}"
        if st.button(label, key=f"explorer-{experiment['id']}", use_container_width=True):
            st.session_state.selected_experiment = experiment["id"]
            st.session_state.selected_object = ("experiment", experiment["id"])
    st.markdown("<div class='tree-section'>EVIDENCE</div>", unsafe_allow_html=True)
    pareto = service.tools.research_get_pareto(research["id"])
    st.caption(f"⌁ Trends\n\n⚠ Failures\n\n◇ Pareto Front ({len(pareto)})")
    st.markdown("<div class='tree-section'>DECISIONS</div>", unsafe_allow_html=True)
    for decision in research["decisions"][-5:]:
        st.caption(f"{decision['id']} · {decision['status']}")
    st.markdown("<div class='tree-section'>FILES</div>", unsafe_allow_html=True)
    st.caption("research.db\n\nprogress/\n\nreports/report.md")
