from __future__ import annotations

from topoptpilot.app.components.decision_card import render_decision_card
from topoptpilot.app.components.experiment_card import render_experiment_card


def render_research_stream(st, service, research: dict) -> None:
    experiments = {item["id"]: item for item in research["experiments"]}
    pending = {item.get("experiment_id"): item for item in research["decisions"]
               if item["status"] == "PENDING"}
    rendered_experiments: set[str] = set()
    for event in research["events"]:
        experiment_id = event.get("experiment_id")
        if event["kind"] == "EXPERIMENT" and experiment_id in experiments:
            if experiment_id not in rendered_experiments:
                with st.container(border=True):
                    render_experiment_card(st, service, experiments[experiment_id])
                    if experiment_id in pending:
                        st.divider()
                        render_decision_card(st, service, pending[experiment_id])
                rendered_experiments.add(experiment_id)
            continue
        with st.container(border=True):
            css_kind = event["kind"].lower().replace(" ", "-")
            st.markdown(f"<div class='event-label {css_kind}'>{event['kind']}</div>",
                        unsafe_allow_html=True)
            st.markdown(f"**{event['title']}**")
            st.markdown(event["body"])
    session = service.store.get_agent_session(research["id"]) or {}
    if session.get("status") == "STREAMING":
        with st.container(border=True):
            st.markdown("<div class='event-label agent-message'>PI RESEARCH AGENT · STREAMING</div>",
                        unsafe_allow_html=True)
            st.markdown(session.get("stream_text") or "正在读取科研状态…")
