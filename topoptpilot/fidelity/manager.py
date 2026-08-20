class FidelityManager:
    LEVELS = ("F0 — 2D Coarse", "F1 — 2D Fine", "F2 — Python 3D", "F3 — MATLAB 3D")

    def promote(self, current: str) -> str:
        try:
            index = self.LEVELS.index(current)
        except ValueError:
            return self.LEVELS[0]
        return self.LEVELS[min(index + 1, len(self.LEVELS) - 1)]

    def is_high_fidelity(self, fidelity: str) -> bool:
        return fidelity in self.LEVELS[2:]

    CODES = ("F0", "F1", "F2", "F3")

    def promote_code(self, current: str) -> str:
        try:
            index = self.CODES.index(current)
        except ValueError:
            return "F0"
        return self.CODES[min(index + 1, len(self.CODES) - 1)]

    @staticmethod
    def backend_for(fidelity: str) -> str:
        return {"F0": "python", "F1": "python", "F2": "python3d", "F3": "matlab"}[fidelity]

    @staticmethod
    def mesh_level(fidelity: str) -> str:
        return {"F0": "coarse", "F1": "medium", "F2": "coarse3d", "F3": "fine3d"}[fidelity]

    @staticmethod
    def estimated_cost(fidelity: str) -> float:
        return {"F0": 1.0, "F1": 3.0, "F2": 8.0, "F3": 30.0}[fidelity]

    @staticmethod
    def budget(research: dict, experiments: list[dict]) -> dict:
        configured = research.get("budgets") or {}
        limits = {
            "total": int(configured.get("total", research.get("budget_total", 12))),
            "F0": int(configured.get("f0", 6)), "F1": int(configured.get("f1", 4)),
            "F2": int(configured.get("f2", 2)), "F3": int(configured.get("f3", 1)),
        }
        used = {code: 0 for code in ("F0", "F1", "F2", "F3")}
        for experiment in experiments:
            if experiment.get("run_id"):
                code = str(experiment.get("fidelity", "F0")).split()[0]
                if code in used:
                    used[code] += 1
        return {
            "limits": limits, "used": {"total": sum(used.values()), **used},
            "remaining": {"total": max(0, limits["total"] - sum(used.values())),
                          **{code: max(0, limits[code] - used[code]) for code in used}},
            "time_remaining": configured.get("time_seconds"),
        }
