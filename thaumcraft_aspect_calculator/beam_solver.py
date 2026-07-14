#!/usr/bin/env python3
"""
Thaumcraft 6 要素配平器 — 束搜索求解器
========================================
实现签名级束搜索算法(BeamSolver)。
"""

from collections import defaultdict
from typing import Dict, List, Set, Tuple

from .data_model import ALL_ASPECTS_ORDERED, ASPECT_INDEX, NUM_ASPECTS, AspectDatabase
from .solution import Solution


class BeamSolver:
    """
    束搜索求解器。

    从空方案开始，每一步添加一个能改善"最不满足要素"的签名单位，
    维护束宽 B 个候选方案，最终返回 TopN 个最优方案。

    注意：搜索在"要素签名"层级进行，不关心具体物品。
    签名 ≈ {metallum=1} 或 {alienis=1,terra=1}。
    最终输出时再将签名计数分配到所有可用物品上。
    """

    def __init__(self, db: AspectDatabase, beam_width: int = 300,
                 top_k_items: int = 30, max_iterations: int = 500,
                 expand_limit: int = 0,
                 exclude_vis_crystals: bool = True):
        """
        Args:
            db: AspectDatabase 实例
            beam_width: 束宽
            top_k_items: 每次扩展考虑多少候选签名
            max_iterations: 最大迭代次数
            expand_limit: 每轮最多展开多少个非可行状态（0 = 全部展开）
            exclude_vis_crystals: 排除魔力水晶碎片
        """
        self.db = db
        self.beam_width = beam_width
        self.top_k_items = top_k_items
        self.max_iterations = max_iterations
        self.expand_limit = expand_limit or beam_width
        self.exclude_vis_crystals = exclude_vis_crystals

    # ═══════════════════════════════════════════════════════════════════════
    # 主求解入口
    # ═══════════════════════════════════════════════════════════════════════

    def solve(self, target: Dict[str, int], n_solutions: int = 5) -> List[Solution]:
        """
        求解：返回按溢出量升序排列的 TopN 方案。

        Args:
            target: {"metallum": 30, "herba": 20, ...}
            n_solutions: 返回方案数

        Returns:
            按 (溢出, 已满足数, 总要素量, 物品数) 排序的方案列表
        """
        target_aspects = {a for a in target if target[a] > 0}
        if not target_aspects:
            return []

        # ── 准备候选签名池 ───────────────────────────────────────────────
        relevant = self.db.get_relevant_items(target_aspects)
        if not relevant:
            return []
        relevant = self.db.filter_pool(relevant, exclude_vis_crystals=self.exclude_vis_crystals)
        relevant_sigs = set()
        for item in relevant:
            relevant_sigs.add(AspectDatabase.aspect_signature(item.aspects))

        aspect_sig_pool = self._build_sig_pool(target_aspects, relevant_sigs)

        # ── 束搜索 ───────────────────────────────────────────────────────
        # State: (overflow, total_vector, sig_counts: Dict[signature, int])
        target_vec = [target.get(a, 0) for a in ALL_ASPECTS_ORDERED]

        initial_counts: Dict[str, int] = {}
        initial_total = [0] * NUM_ASPECTS
        initial_overflow = self._compute_overflow(initial_total, target_vec)

        beam = [(initial_overflow, initial_total, initial_counts)]
        expanded: Set[Tuple] = set()
        sol_sigs: Set[Tuple] = set()
        all_solutions: List[Solution] = []
        prev_solution_count = 0
        no_new_solution_count = 0
        best_granularity = 0
        granularity_stale = 0

        for iteration in range(self.max_iterations):
            if not beam:
                break

            candidates = []
            expand_count = 0

            for overflow, total, sig_counts in beam:
                if self._is_satisfied(total, target_vec):
                    key = tuple(sorted(sig_counts.items()))
                    if key not in sol_sigs:
                        sol_sigs.add(key)
                        all_solutions.append(
                            self._sig_counts_to_solution(sig_counts, target))
                    continue

                expand_count += 1
                if expand_count > self.expand_limit:
                    continue

                worst_idx = self._find_worst_aspect(total, target_vec)
                worst_name = ALL_ASPECTS_ORDERED[worst_idx]

                sig_candidates = aspect_sig_pool.get(worst_name, [])
                if not sig_candidates:
                    continue

                for sig in sig_candidates[:self.top_k_items * 2]:
                    new_sc = dict(sig_counts)
                    new_sc[sig] = new_sc.get(sig, 0) + 1

                    key = tuple(sorted(new_sc.items()))
                    if key in expanded or key in sol_sigs:
                        continue
                    expanded.add(key)

                    sig_vec = self.db.sig_vectors[sig]
                    new_total = [total[i] + sig_vec[i] for i in range(NUM_ASPECTS)]
                    new_overflow = self._compute_overflow(new_total, target_vec)
                    candidates.append((new_overflow, new_total, new_sc))

            if not candidates:
                break

            # 排序元组: (overflow, -satisfied_count, totals_total, -item_count)
            candidates.sort(key=lambda x: (
                x[0],
                -sum(1 for i, tg in enumerate(target_vec)
                     if tg > 0 and x[1][i] >= tg),
                sum(x[1]),
                -sum(x[2].values()),
            ))
            beam = candidates[:self.beam_width]

            # ── 收敛检查 ──────────────────────────────────────────────
            if len(all_solutions) > prev_solution_count:
                prev_solution_count = len(all_solutions)
                no_new_solution_count = 0
            else:
                no_new_solution_count += 1

            has_zero = any(s.overflow == 0 for s in all_solutions)

            if has_zero:
                best_gran = max(
                    (s.item_count for s in all_solutions if s.overflow == 0),
                    default=0)
                if best_gran > best_granularity:
                    best_granularity = best_gran
                    granularity_stale = 0
                else:
                    granularity_stale += 1

            # 当前 beam 全部满足 → 收集后退出
            if all(self._is_satisfied(t, target_vec) for _, t, _ in beam):
                for _, total, sig_counts in beam:
                    key = tuple(sorted(sig_counts.items()))
                    if key not in sol_sigs:
                        sol_sigs.add(key)
                        all_solutions.append(
                            self._sig_counts_to_solution(sig_counts, target))
                break

            if has_zero:
                if (granularity_stale >= max(10, sum(target.values()) // 5)
                        and no_new_solution_count
                        >= max(20, len(target_aspects) * 10)):
                    break
            else:
                # 未找到解时需足够耐心：最细粒度签名每次只加 1
                no_new_limit = max(sum(target.values()) + 50,
                                   len(target_aspects) * 50)
                if no_new_solution_count >= no_new_limit:
                    break

        # 最终排序
        all_solutions.sort(key=lambda s: (
            s.overflow,
            -s.satisfied_count(target),
            s.totals_total,
            -s.item_count,
        ))
        return all_solutions[:n_solutions]

    # ═══════════════════════════════════════════════════════════════════════
    # 签名候选池构建（三种策略）
    # ═══════════════════════════════════════════════════════════════════════

    def _build_sig_pool(self, target_aspects: Set[str],
                        relevant_sigs: Set[str]) -> Dict[str, List[str]]:
        """
        为每个目标要素构建签名候选池。
        策略1：细粒度优先
        策略2：每个数值至少保留一条（纯度优先）
        策略3：多要素覆盖（仅多目标时启用）
        """
        aspect_sig_pool = {}

        for aspect in target_aspects:
            candidates = []
            for sig in relevant_sigs:
                vec = self.db.sig_vectors[sig]
                idx = ASPECT_INDEX[aspect]
                val = vec[idx]
                if val <= 0:
                    continue
                num_aspects = sum(1 for v in vec if v > 0)
                candidates.append((val, num_aspects, sig))

            # 排序：数值小（细粒度）→ 纯度高（少侧面要素）
            candidates.sort(key=lambda x: (x[0], x[1]))

            pool = []
            seen = set()

            # 策略1：细粒度优先
            for val, num_a, sig in candidates[:self.top_k_items]:
                if sig not in seen:
                    seen.add(sig)
                    pool.append(sig)

            # 策略2：每个数值至少保留一条（纯度优先）
            val_best = {}
            for val, num_a, sig in candidates:
                if val not in val_best or num_a < val_best[val][0]:
                    val_best[val] = (num_a, sig)
            for val in sorted(val_best.keys())[:50]:
                _, sig = val_best[val]
                if sig not in seen:
                    seen.add(sig)
                    pool.append(sig)

            # 策略3：多要素覆盖（仅目标要素 >1 时）
            if len(target_aspects) > 1:
                other_aspects = target_aspects - {aspect}
                for val, num_a, sig in candidates:
                    if sig in seen:
                        continue
                    vec = self.db.sig_vectors[sig]
                    for other in other_aspects:
                        if vec[ASPECT_INDEX[other]] > 0:
                            seen.add(sig)
                            pool.append(sig)
                            break

            aspect_sig_pool[aspect] = pool

        return aspect_sig_pool

    # ═══════════════════════════════════════════════════════════════════════
    # 内部工具方法
    # ═══════════════════════════════════════════════════════════════════════

    @staticmethod
    def _compute_overflow(total: List[int], target: List[int]) -> int:
        """计算总溢出 = sum(max(0, total[i] - target[i]))"""
        overflow = 0
        for t, tg in zip(total, target):
            if t > tg:
                overflow += t - tg
        return overflow

    @staticmethod
    def _is_satisfied(total: List[int], target: List[int]) -> bool:
        """所有目标要素是否已满足"""
        for t, tg in zip(total, target):
            if tg > 0 and t < tg:
                return False
        return True

    @staticmethod
    def _find_worst_aspect(total: List[int], target: List[int]) -> int:
        """找到差距最大的目标要素索引"""
        max_gap = 0
        worst_idx = 0
        for i, (t, tg) in enumerate(zip(total, target)):
            if tg > 0:
                gap = tg - t
                if gap > max_gap:
                    max_gap = gap
                    worst_idx = i
        return worst_idx

    def _sig_counts_to_solution(self, sig_counts: Dict[str, int],
                                 target: Dict[str, int]) -> Solution:
        """将签名计数分配到具体物品上，生成 Solution"""
        counts = {}
        totals = defaultdict(int)

        for sig, cnt in sorted(sig_counts.items()):
            if cnt <= 0:
                continue
            items = self.db.get_items_for_signature(sig)
            if self.exclude_vis_crystals:
                items = self.db.filter_vis_crystals(items)
            if not items:
                continue

            item_list = sorted(items, key=lambda it: it.key)
            per_item = cnt // len(item_list)
            remainder = cnt % len(item_list)
            for i, item in enumerate(item_list):
                item_cnt = per_item + (1 if i < remainder else 0)
                if item_cnt > 0:
                    counts[item.key] = item_cnt
                    for a, c in item.aspects.items():
                        totals[a] += c * item_cnt

        total_vec = [totals.get(a, 0) for a in ALL_ASPECTS_ORDERED]
        target_vec = [target.get(a, 0) for a in ALL_ASPECTS_ORDERED]
        overflow = self._compute_overflow(total_vec, target_vec)

        return Solution(
            counts=counts,
            totals=dict(totals),
            overflow=overflow,
        )
