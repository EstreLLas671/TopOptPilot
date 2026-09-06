from __future__ import annotations


def render_decision_card(st, service, decision: dict) -> None:
    st.markdown("<div class='event-label decision'>PROPOSED EXPERIMENT</div>", unsafe_allow_html=True)
    st.markdown(f"**Purpose**  \n{decision['reason']}  \n\n"
                f"**Risk**  \n{decision['risk']}  \n\n"
                f"**Changes**  \n`{decision['proposal'].get('parameters', {})}`")
    approve, edit, reject, why = st.columns([1, 1, 1, 1])
    if approve.button("Approve", key=f"approve-{decision['id']}", type="primary", use_container_width=True):
        service.approve_decision(decision["id"])
        st.rerun()
    if edit.button("Edit", key=f"edit-{decision['id']}", use_container_width=True):
        st.session_state.editing_experiment = decision.get("experiment_id")
    if reject.button("Reject", key=f"reject-{decision['id']}", use_container_width=True):
        service.reject_decision(decision["id"])
        st.rerun()
    if why.button("Why?", key=f"why-{decision['id']}", use_container_width=True):
        st.info(decision["reason"])

