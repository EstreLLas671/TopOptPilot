from __future__ import annotations


def render_topology(st, experiment: dict) -> None:
    result = experiment.get("result") or {}
    density = result.get("artifacts", {}).get("density")
    if density is None:
        st.info("Topology becomes available as soon as the solver completes.")
        return
    import matplotlib.pyplot as plt
    import numpy as np

    field = np.asarray(density)
    if field.ndim == 3:
        fig, axes = plt.subplots(1, 3, figsize=(8, 2.7), facecolor="#111419")
        views = [(field.max(axis=0), "XY max projection"),
                 (field.max(axis=1), "XZ max projection"),
                 (field[field.shape[0] // 2], "Mid-Z slice")]
        for ax, (view, title) in zip(axes, views):
            ax.imshow(1 - view, cmap="gray", interpolation="nearest", aspect="auto")
            ax.set_title(title, color="#d9dde3", fontsize=8)
            ax.set_axis_off()
    else:
        fig, ax = plt.subplots(figsize=(8, 2.7), facecolor="#111419")
        ax.imshow(1 - field, cmap="gray", interpolation="nearest", aspect="auto")
        ax.set_axis_off()
    fig.tight_layout(pad=0)
    st.pyplot(fig, use_container_width=True)
    plt.close(fig)


def render_convergence(st, experiment: dict) -> None:
    history = (experiment.get("result") or {}).get("artifacts", {}).get("history", [])
    if not history:
        st.info("Convergence history is not available yet.")
        return
    try:
        import pandas as pd
        frame = pd.DataFrame(history).set_index("iteration")
        columns = [name for name in ("compliance", "gray_ratio", "volume_fraction", "beta")
                   if name in frame.columns]
        st.line_chart(frame[columns], use_container_width=True)
    except ImportError:
        st.json(history[-10:])
