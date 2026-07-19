#!/usr/bin/env python3
"""
Thaumcraft 6 要素配平器 — PuLP MILP 求解器
=============================================
需要 pip install pulp。提供精确最优解和次优解枚举。
"""

import sys
from collections import defaultdict
from typing import Dict, List, Set

from .data_model import ALL_ASPECTS_ORDERED, AspectDatabase
from .solution import Solution


class ILPSolver:
    """PuLP MILP 求解器"""

    def __init__(self, db: AspectDatabase, time_limit: int = 30,
                 exclude_vis_crystals: bool = True,
                 exclude_item_keys: Set[str] = None):
        self.db = db
        self.time_limit = time_limit
        self.exclude_vis_crystals = exclude_vis_crystals
        self.exclude_item_keys = exclude_item_keys or set()

    def solve(self, target: Dict[str, int], n_solutions: int = 5) -> List[Solution]:
        try:
            import pulp
        except ImportError:
            print("⚠ PuLP 未安装，回退到束搜索。安装: pip install pulp",
                  file=sys.stderr)
            return []

        target_aspects = {a for a in target if target[a] > 0}
        relevant = self.db.get_relevant_items(target_aspects)
        if not relevant:
            return []
        relevant = self.db.filter_pool(
            relevant, exclude_vis_crystals=self.exclude_vis_crystals,
            exclude_keys=self.exclude_item_keys)
        if not relevant:
            return []

        # ── 构造 MILP 模型 ──
        prob = pulp.LpProblem("AspectBalancer", pulp.LpMinimize)

        # 变量：x_i = 物品 i 的使用数量（非负整数）
        x_vars = {}
        for item in relevant:
            safe_name = item.key.replace(':', '_').replace('@', '_')
            x_vars[item.key] = pulp.LpVariable(
                f"x_{safe_name}", lowBound=0, cat=pulp.LpInteger)

        # 溢出变量：对所有 41 个要素
        overflow_vars = {}
        for a in ALL_ASPECTS_ORDERED:
            overflow_vars[a] = pulp.LpVariable(
                f"overflow_{a}", lowBound=0, cat=pulp.LpContinuous)

        # 目标：最小化总溢出
        prob += pulp.lpSum([overflow_vars[a] for a in ALL_ASPECTS_ORDERED])

        # 约束
        for a in ALL_ASPECTS_ORDERED:
            contribution = []
            for item in relevant:
                val = item.aspects.get(a, 0)
                if val > 0:
                    contribution.append(val * x_vars[item.key])

            if not contribution:
                continue

            expr = pulp.lpSum(contribution)
            t = target.get(a, 0)

            prob += expr - t <= overflow_vars[a]
            if t > 0:
                prob += expr >= t

        # ── 求解 ──
        prob.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=self.time_limit))

        if pulp.LpStatus[prob.status] not in ('Optimal', 'Not Solved'):
            return []

        solutions = []
        solutions.append(self._extract_solution(relevant, x_vars, target))

        # ── 枚举次优解（添加排除约束）──
        for sol_idx in range(1, n_solutions):
            existing_sol = solutions[-1]
            diff_expr = []
            for item in relevant:
                curr_val = existing_sol.counts.get(item.key, 0)
                safe_name = f"z{sol_idx}_{item.key.replace(':', '_').replace('@', '_')}"
                z = pulp.LpVariable(safe_name, lowBound=0, cat=pulp.LpInteger)
                prob += z >= x_vars[item.key] - curr_val
                prob += z >= curr_val - x_vars[item.key]
                diff_expr.append(z)

            prob += pulp.lpSum(diff_expr) >= 1

            prob.solve(pulp.PULP_CBC_CMD(msg=False,
                                         timeLimit=self.time_limit))

            if pulp.LpStatus[prob.status] not in ('Optimal', 'Not Solved'):
                break

            solutions.append(
                self._extract_solution(relevant, x_vars, target))

        solutions.sort(key=lambda s: (
            s.overflow,
            -s.satisfied_count(target),
            s.totals_total,
            -s.item_count,
        ))
        return solutions[:n_solutions]

    def _extract_solution(self, relevant, x_vars, target) -> Solution:
        """从求解状态中提取一个 Solution"""
        import pulp
        counts = {}
        totals = defaultdict(int)
        for item in relevant:
            val = int(pulp.value(x_vars[item.key]) + 0.5)
            if val > 0:
                counts[item.key] = val
                for a, c in item.aspects.items():
                    totals[a] += c * val

        overflow_val = 0
        for a in ALL_ASPECTS_ORDERED:
            t = target.get(a, 0)
            if totals[a] > t:
                overflow_val += totals[a] - t

        return Solution(
            counts=counts,
            totals=dict(totals),
            overflow=int(overflow_val),
        )


def solve_with_ilp_auto(db: AspectDatabase, target: Dict[str, int],
                        n_solutions: int = 5, time_limit: int = 30,
                        exclude_vis_crystals: bool = True,
                        exclude_item_keys: Set[str] = None) -> List[Solution]:
    """包装函数：自动尝试 ILP，失败时回退到束搜索"""
    print("🔧 尝试 PuLP MILP 求解器...")
    solver_ilp = ILPSolver(
        db, time_limit=time_limit,
        exclude_vis_crystals=exclude_vis_crystals,
        exclude_item_keys=exclude_item_keys)
    solutions = solver_ilp.solve(target, n_solutions=n_solutions)
    if solutions:
        return solutions
    print("⚠ ILP 求解未返回结果，使用束搜索作为回退。", file=sys.stderr)
    from .beam_solver import BeamSolver
    solver_beam = BeamSolver(db, exclude_vis_crystals=exclude_vis_crystals,
                              exclude_item_keys=exclude_item_keys)
    return solver_beam.solve(target, n_solutions=n_solutions)
