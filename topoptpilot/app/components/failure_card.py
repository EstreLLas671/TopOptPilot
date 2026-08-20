def render_failure_card(st, failure: dict) -> None:
    with st.container(border=True):
        st.markdown("<div class='event-label safety-policy'>FAILURE EVIDENCE</div>",
                    unsafe_allow_html=True)
        st.markdown(f"**{failure.get('type', 'UNKNOWN')}**")
        st.json(failure.get("evidence", {}))

