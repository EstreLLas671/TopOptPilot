"""Reproducible Random/Grid/TPE/Rule/Pi benchmark and ablation harness."""

from __future__ import annotations

import itertools
import json
import random
import time
from pathlib import Path

from solver.topopt_engine import run_topopt
from .metrics import campaign_metrics


class BenchmarkRunner:
    METHODS = ("Random", "Grid", "TPE", "Rule", "Pi")

    def __init__(self, seed: int = 2026):
        self.seed = seed

    def candidates(self, method: str, budget: int) -> list[dict]:
        rng = random.Random(self.seed)
        grid = list(itertools.product((2.0, 4.0, 8.0, 16.0), (1.25, 1.75, 2.25), (2.0, 3.0, 4.0)))
        if method == "Random": rng.shuffle(grid)
        elif method == "Grid": pass
        elif method == "TPE":
            # Initial design only; subsequent proposals are history-adaptive in run().
            rng.shuffle(grid)
        elif method == "Rule":
            grid = [(1, 1.5, 3), (2, 1.5, 3), (4, 1.75, 3), (8, 2.0, 3), (16, 2.25, 3)]
        elif method == "Pi":
            raise ValueError("Pi candidates must come from a live Pi campaign, not a hard-coded list")
        else: raise ValueError(f"Unknown method {method}")
        return [{"beta": b, "rmin": r, "penal": p} for b, r, p in grid[:budget]]

    def run(self, method: str, budget: int = 5, max_iter: int = 30) -> dict:
        runs = []
        history = []
        for index in range(1, budget + 1):
            params = (self._tpe_suggest(history, random.Random(self.seed + index))
                      if method == "TPE" else self.candidates(method, budget)[index - 1])
            result = run_topopt({"task_id": f"{method}-{index}", "load_case": "vertical",
                "mesh_level": "coarse", "projection": "heaviside_projection" if params["beta"] > 1 else "none",
                "controller": "periodic_controller" if params["beta"] > 1 else "fixed_controller",
                "filter": "density_filter" if params["beta"] > 1 else "sensitivity_filter",
                "params": {**params, "beta_max": params["beta"], "max_iter": max_iter, "volfrac": .4}})
            runs.append({"parameters": params, "objective": result["objective"], "quality": result["quality"]})
            history.append(runs[-1])
        feasible = [r for r in runs if r["quality"]["connected_components"] == 1]
        best = min(feasible or runs, key=lambda r: r["objective"]["compliance"])
        records = [{"id": f"{method}-{i}", "status": ("SUCCESS" if r["quality"]["connected_components"] == 1 else "FAILED"),
                    "fidelity": "F0", "parameters": r["parameters"],
                    "result": {"objective": r["objective"], "quality": r["quality"]}}
                   for i, r in enumerate(runs, 1)]
        return {"method": method, "seed": self.seed, "budget": budget, "runs": runs, "best": best,
                "metrics": campaign_metrics(records)}

    @staticmethod
    def _tpe_suggest(history: list[dict], rng: random.Random) -> dict:
        if len(history) < 3:
            return {"beta": rng.choice([2., 4., 8., 16.]),
                    "rmin": rng.choice([1.25, 1.75, 2.25]),
                    "penal": rng.choice([2., 3., 4.])}
        ordered = sorted(history, key=lambda item: item["objective"]["compliance"]
                         * (1 + 5 * (item["quality"]["connected_components"] != 1)))
        good = ordered[:max(1, len(ordered) // 3)]
        anchor = rng.choice(good)["parameters"]
        return {"beta": min(32., max(1., rng.gauss(anchor["beta"], 2.0))),
                "rmin": min(4., max(.75, rng.gauss(anchor["rmin"], .25))),
                "penal": min(5., max(1., rng.gauss(anchor["penal"], .35)))}

    def run_pi_campaign(self, service, budget: int = 5, timeout: float = 180) -> dict:
        research = service.create_research({"name": "Pi baseline", "mode": "AUTONOMOUS",
            "budget_total": budget, "budgets": {"total": budget, "f0": budget,
                                                   "f1": 0, "f2": 0, "f3": 0}})
        service.start_autonomous_research(research["id"])
        deadline = time.time() + timeout
        while time.time() < deadline:
            state = service.get_research(research["id"])
            session = service.store.get_agent_session(research["id"]) or {}
            if state.get("termination_reason") or (state["budget_used"] >= budget
                                                    and session.get("status") != "STREAMING"):
                break
            time.sleep(.2)
        else:
            service.execute_command(research["id"], "/stop")
            raise TimeoutError("Pi baseline campaign timed out")
        events = service.store.list_events(research["id"])
        safe_mode = any(item["title"] == "PI SAFE MODE" for item in events)
        state = service.get_research(research["id"])
        return {"method": "Rule-fallback" if safe_mode else "Pi", "research_id": research["id"],
                "budget": budget, "metrics": campaign_metrics(state["experiments"], events,
                                                                 state["decisions"])}

    def ablations(self) -> dict:
        return {"no_scientific_memory": self.candidates("Random", 5),
                "no_safety_policy": [{"beta": 32, "rmin": .75, "penal": 5}],
                "no_fidelity_manager": self.candidates("Grid", 5),
                "no_warm_start": self.candidates("Rule", 5)}

    @staticmethod
    def save(result: dict, path: str | Path) -> Path:
        target = Path(path); target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return target
