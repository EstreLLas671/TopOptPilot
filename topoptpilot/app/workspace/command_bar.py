from __future__ import annotations


def render_command_bar(st, service, research_id: str) -> None:
    text = st.chat_input("Ask TopOptPilot or enter command…")
    if not text:
        return
    result = service.execute_command(research_id, text, st.session_state.get("selected_experiment"))
    st.session_state.last_command = result.model_dump()
    if result.action == "compare":
        st.session_state.selected_compare_runs = result.data["experiments"]
        st.session_state.workspace_view = "COMPARE"
    elif result.action == "edit":
        st.session_state.workspace_view = "CHAT"
    elif result.action == "select":
        st.session_state.selected_experiment = result.data["experiment_id"]
    if not result.ok:
        st.toast(result.message, icon="⚠️")
    else:
        st.toast(result.message, icon="✓")
    st.rerun()

