from __future__ import annotations


def render_timeline(st, research: dict) -> None:
    st.markdown("### Research Timeline")
    experiments = research["experiments"]
    if not experiments:
        st.info("No experiments have been proposed yet.")
        return
    for index, experiment in enumerate(experiments):
        symbol = {"WAITING": "○", "RUNNING": "▶", "SUCCESS": "✓",
                  "FAILED": "✗", "CANCELLED": "⚠"}.get(experiment["status"], "○")
        st.markdown(f"<div class='timeline-node'><b>{symbol} {experiment['id']}</b>"
                    f"<span>{experiment['purpose']}</span><em>{experiment['status']}</em></div>",
                    unsafe_allow_html=True)
        if index < len(experiments) - 1:
            st.markdown("<div class='timeline-line'>│<br>▼</div>", unsafe_allow_html=True)

