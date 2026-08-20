"""Codex-like local research workspace. Start with: streamlit run app.py"""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from topoptpilot.app.components.status_bar import render_status_bar
from topoptpilot.app.workspace.command_bar import render_command_bar
from topoptpilot.app.workspace.compare import render_compare
from topoptpilot.app.workspace.explorer import render_explorer
from topoptpilot.app.workspace.inspector import render_inspector
from topoptpilot.app.workspace.research_stream import render_research_stream
from topoptpilot.app.workspace.timeline import render_timeline
from topoptpilot.app.workspace.benchmarks import render_benchmarks
from topoptpilot.service import ResearchService


st.set_page_config(page_title="TopOptPilot Workspace", page_icon="◈", layout="wide",
                   initial_sidebar_state="collapsed")


@st.cache_resource
def get_service() -> ResearchService:
    return ResearchService()


def initialize_ui(service: ResearchService) -> None:
    research = service.bootstrap_demo()
    defaults = {
        "selected_research": research["id"], "selected_experiment": None,
        "selected_object": ("research", research["id"]), "workspace_view": "CHAT",
        "current_round": 1, "execution_status": "READY", "approval_pending": None,
        "selected_compare_runs": [], "chat_history": [], "ui_mode": "COPILOT",
        "editing_experiment": None,
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


def render_editor(service: ResearchService, experiment: dict | None) -> None:
    if not experiment:
        return
    with st.expander(f"Edit {experiment['id']}", expanded=True):
        with st.form(f"editor-{experiment['id']}"):
            parameters = experiment["parameters"]
            beta = st.number_input("beta", min_value=1.0, value=float(parameters.get("beta", 1)))
            rmin = st.number_input("rmin", min_value=0.5, value=float(parameters.get("rmin", 1.5)))
            penal = st.number_input("penal", min_value=1.0, value=float(parameters.get("penal", 3)))
            if st.form_submit_button("Save human override"):
                parameters.update(beta=beta, rmin=rmin, penal=penal)
                service.store.update_experiment(experiment["id"], parameters=parameters)
                service.store.append_event(experiment["research_id"], "HUMAN OVERRIDE", "PARAMETERS EDITED",
                                           f"User set beta={beta}, rmin={rmin}, penal={penal}.", experiment["id"])
                st.session_state.editing_experiment = None
                st.rerun()


def main() -> None:
    service = get_service()
    initialize_ui(service)
    style_path = Path(__file__).with_name("theme") / "style.css"
    st.markdown(f"<style>{style_path.read_text(encoding='utf-8')}</style>", unsafe_allow_html=True)
    research = service.get_research(st.session_state.selected_research)
    render_status_bar(st, research, service.health())
    explorer_col, main_col, inspector_col = st.columns([0.22, 0.56, 0.22], gap="medium")
    with explorer_col:
        render_explorer(st, service, research)
    with main_col:
        view = st.radio("Workspace view", ["CHAT", "TIMELINE", "COMPARE", "BENCHMARKS"], horizontal=True,
                        key="workspace_view", label_visibility="collapsed")
        if view == "TIMELINE":
            render_timeline(st, research)
        elif view == "COMPARE":
            selected = st.session_state.selected_compare_runs
            render_compare(st, service.compare(research["id"], selected) if len(selected) == 2 else [])
        elif view == "BENCHMARKS":
            render_benchmarks(st, service)
        else:
            render_research_stream(st, service, research)
        editing = st.session_state.get("editing_experiment")
        render_editor(service, next((e for e in research["experiments"] if e["id"] == editing), None))
    with inspector_col:
        render_inspector(st, research, st.session_state.selected_object)
    render_command_bar(st, service, research["id"])
    agent_session = service.store.get_agent_session(research["id"]) or {}
    if (any(e["status"] in {"WAITING", "RUNNING"} and e["run_id"] for e in research["experiments"])
            or agent_session.get("status") == "STREAMING"):
        import time
        time.sleep(1)
        st.rerun()


if __name__ == "__main__":
    main()
