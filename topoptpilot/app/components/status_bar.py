from __future__ import annotations


def render_status_bar(st, research: dict, health: dict) -> None:
    matlab = "●" if health.get("matlab") else "○"
    used, total = research["budget_used"], research["budget_total"]
    st.markdown(
        f"""<div class="top-status">
        <div class="brand">TOPOPT<span>PILOT</span></div>
        <div><small>PROJECT</small><strong>{research['id']}</strong></div>
        <div><small>MODE</small><strong>{research['mode']}</strong></div>
        <div><small>AGENT</small><strong>Pi RPC · {health.get('agent_model', '—')} · {health.get('pi_rpc', {}).get('qwen_status', '—')}</strong></div>
        <div><small>SOLVERS</small><strong><i class="ready">●</i> 2D&nbsp;&nbsp;● 3D&nbsp;&nbsp;{matlab} MATLAB</strong></div>
        <div><small>BUDGET</small><strong>{used} / {total}</strong></div>
        <div><small>STATUS</small><strong class="state-{research['status'].lower()}">{research['status']}</strong></div>
        </div>""",
        unsafe_allow_html=True,
    )
