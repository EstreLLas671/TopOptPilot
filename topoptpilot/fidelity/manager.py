from topoptpilot.nomenclature import normalize_stage, stage_label


class FidelityManager:
    LEVELS = tuple(stage_label(f"STEP{index}") for index in range(1, 5))

    def promote(self, current: str) -> str:
        try:
            index = self.LEVELS.index(current)
        except ValueError:
            return self.LEVELS[0]
        return self.LEVELS[min(index + 1, len(self.LEVELS) - 1)]

    def is_high_fidelity(self, fidelity: str) -> bool:
        return fidelity in self.LEVELS[2:]

    CODES = ("STEP1", "STEP2", "STEP3", "STEP4")

    def promote_code(self, current: str) -> str:
        try:
            index = self.CODES.index(current)
        except ValueError:
            return "STEP1"
        return self.CODES[min(index + 1, len(self.CODES) - 1)]

    @staticmethod
    def backend_for(fidelity: str) -> str:
        code = normalize_stage(fidelity)
        return {"STEP1": "python", "STEP2": "python", "STEP3": "python3d", "STEP4": "matlab"}[code]

    @staticmethod
    def mesh_level(fidelity: str) -> str:
        return {"STEP1": "coarse", "STEP2": "coarse", "STEP3": "coarse3d", "STEP4": "fine3d"}[normalize_stage(fidelity)]

    @staticmethod
    def estimated_cost(fidelity: str) -> float:
        return {"STEP1": 1.0, "STEP2": 3.0, "STEP3": 8.0, "STEP4": 30.0}[normalize_stage(fidelity)]
