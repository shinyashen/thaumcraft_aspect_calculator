#!/usr/bin/env python3
"""
Thaumcraft 6 要素配平器 — 束搜索求解器
========================================
实现签名级束搜索算法(BeamSolver)。
"""

import math
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

        aspect_sig_pool, pure_less_set = self._build_sig_pool(
            target_aspects, relevant_sigs)

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
        all_sig_counts: List[Dict[str, int]] = []  # parallel to all_solutions
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
                        all_sig_counts.append(dict(sig_counts))
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

            # 混合排序: 对无纯源要素的进展给予溢出折扣
            def _candidate_sort_key(cand):
                overflow, total, sig_counts = cand
                # 无纯源要素每达成 1 点，从 overflow 扣除折扣系数
                progress_discount = 0
                for i, tg in enumerate(target_vec):
                    if tg > 0 and ALL_ASPECTS_ORDERED[i] in pure_less_set:
                        progress_discount += min(total[i], tg) * 0.5
                adj_overflow = max(0, math.ceil(overflow - progress_discount))
                return (
                    adj_overflow,
                    -sum(1 for i, tg in enumerate(target_vec)
                         if tg > 0 and total[i] >= tg),
                    sum(total),
                    -sum(sig_counts.values()),
                )

            candidates.sort(key=_candidate_sort_key)
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
                        all_sig_counts.append(dict(sig_counts))
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

        # ── 后处理：精炼 ────────────────────────────────────────────────
        # 对每个方案，用高效签名替换低效签名组合
        for i in range(len(all_solutions)):
            raw_counts = all_sig_counts[i]
            refined = self._refine_counts(raw_counts, target, target_aspects,
                                          aspect_sig_pool, pure_less_set)
            if refined is not raw_counts:
                new_sol = self._sig_counts_to_solution(refined, target)
                all_solutions[i] = new_sol

        # 去重：精炼可能导致不同 sig_counts 收敛到相同物品组合
        seen: Set[Tuple] = set()
        deduped: List[Solution] = []
        for sol in all_solutions:
            key = tuple(sorted(sol.counts.items()))
            if key not in seen:
                seen.add(key)
                deduped.append(sol)
        all_solutions = deduped

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
                        relevant_sigs: Set[str]) -> Tuple[Dict[str, List[str]], Set[str]]:
        """
        为每个目标要素构建签名候选池。
        策略1：细粒度优先（同等条件下优先多要素覆盖）
        策略1.5A：效率注入 — 无纯源要素的高效签名（调整后效率优先）
        策略1.5B：覆盖注入 — 跨目标签名注入池中部（确保在 top_k×2 范围内）
        策略2：每个数值至少保留一条（纯度优先）
        策略3：多要素覆盖（仅多目标时启用）

        Returns:
            (aspect_sig_pool, pure_less_set) — 候选池 + 无纯源的目标要素集合
        """
        aspect_sig_pool = {}
        pure_less_set: Set[str] = set()

        for aspect in target_aspects:
            other_aspects = (target_aspects - {aspect}) if len(target_aspects) > 1 else set()

            candidates = []
            # 对 relevant_sigs 排序以确保确定性
            for sig in sorted(relevant_sigs):
                vec = self.db.sig_vectors[sig]
                idx = ASPECT_INDEX[aspect]
                val = vec[idx]
                if val <= 0:
                    continue
                num_aspects = sum(1 for v in vec if v > 0)
                # 计算该签名覆盖了多少其他目标要素
                other_coverage = sum(1 for o in other_aspects if vec[ASPECT_INDEX[o]] > 0)
                candidates.append((val, num_aspects, -other_coverage, sig))

            # 排序：数值小（细粒度）→ 纯度高（少侧面要素）→ 多目标覆盖优先 → 签名名（确定）
            candidates.sort(key=lambda x: (x[0], x[1], x[2], x[3]))

            pool = []
            seen = set()

            # 策略1：细粒度优先
            for val, num_a, _, sig in candidates[:self.top_k_items]:
                if sig not in seen:
                    seen.add(sig)
                    pool.append(sig)

            # 策略1.5A：效率注入 — 无纯源要素的高效签名（调整后效率）
            # 纯源不存在时，将高 val/(总要素-其他目标覆盖) 的签名注入池中
            has_pure = any(num_a == 1 for _, num_a, _, _ in candidates)
            if not has_pure:
                pure_less_set.add(aspect)
                efficient = []
                for val, num_a, _, sig in candidates:
                    if sig not in seen:
                        vec = self.db.sig_vectors[sig]
                        total = sum(vec)
                        other_cover = sum(vec[ASPECT_INDEX[o]] for o in other_aspects)
                        adj_eff = val / (total - other_cover) if total > other_cover else val
                        efficient.append((adj_eff, val, sig))
                efficient.sort(key=lambda x: (-x[0], x[1]))
                for adj_eff, val, sig in efficient:
                    if len(pool) >= self.top_k_items * 2:
                        break
                    if sig not in seen:
                        seen.add(sig)
                        pool.append(sig)

            # 策略1.5B：覆盖注入 — 跨目标签名注入池中部
            # 确保深层的跨目标签名仍在扩展循环可达范围内
            if other_aspects:
                for val, num_a, _, sig in candidates:
                    if sig not in seen and len(pool) < self.top_k_items * 2:
                        vec = self.db.sig_vectors[sig]
                        if any(vec[ASPECT_INDEX[o]] > 0 for o in other_aspects):
                            seen.add(sig)
                            pool.append(sig)

            # 策略2：每个数值至少保留一条（纯度优先）
            val_best = {}
            for val, num_a, _, sig in candidates:
                if val not in val_best or num_a < val_best[val][0]:
                    val_best[val] = (num_a, sig)
            for val in sorted(val_best.keys())[:50]:
                _, sig = val_best[val]
                if sig not in seen:
                    seen.add(sig)
                    pool.append(sig)

            # 策略3：多要素覆盖（仅目标要素 >1 时）
            if other_aspects:
                for val, num_a, _, sig in candidates:
                    if sig not in seen:
                        vec = self.db.sig_vectors[sig]
                        if any(vec[ASPECT_INDEX[o]] > 0 for o in other_aspects):
                            seen.add(sig)
                            pool.append(sig)

            aspect_sig_pool[aspect] = pool

        return aspect_sig_pool, pure_less_set

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

    # ═══════════════════════════════════════════════════════════════════════
    # 精炼后处理
    # ═══════════════════════════════════════════════════════════════════════

    def _refine_counts(self,
                       counts: Dict[str, int],
                       target: Dict[str, int],
                       target_aspects: Set[str],
                       aspect_sig_pool: Dict[str, List[str]],
                       pure_less_set: Set[str]) -> Dict[str, int]:
        """
        用更高效的签名替换当前方案中低效的签名组合，减少溢出。
        仅处理无纯源要素：用效率更高的池签名替换效率最低的已用签名。
        """
        new_counts = dict(counts)
        target_vec = [target.get(a, 0) for a in ALL_ASPECTS_ORDERED]

        for aspect in sorted(pure_less_set):
            need = target.get(aspect, 0)
            if need <= 0:
                continue

            # 收集当前方案中提供该要素的签名
            current = []  # (adj_eff, val, sig, cnt, waste_per_unit)
            for sig, cnt in list(new_counts.items()):
                if cnt <= 0:
                    continue
                vec = self.db.sig_vectors[sig]
                val = vec[ASPECT_INDEX[aspect]]
                if val <= 0:
                    continue
                total = sum(vec)
                other_targets = sum(
                    vec[ASPECT_INDEX[o]] for o in target_aspects if o != aspect)
                adj_eff = val / (total - other_targets) if total > other_targets else 0
                waste_per_unit = total - other_targets - val
                current.append((adj_eff, val, sig, cnt, waste_per_unit))

            if not current:
                continue

            # 当前签名按效率升序（最差的在前）
            current.sort(key=lambda x: x[0])
            worst_current = current[0]

            # 构建效率排序的池签名（在本方案中未使用）
            pool = aspect_sig_pool.get(aspect, [])
            efficient = []
            for sig in pool:
                if sig in new_counts:
                    continue
                vec = self.db.sig_vectors[sig]
                val = vec[ASPECT_INDEX[aspect]]
                if val <= 0:
                    continue
                total = sum(vec)
                other_targets = sum(
                    vec[ASPECT_INDEX[o]] for o in target_aspects if o != aspect)
                adj_eff = val / (total - other_targets) if total > other_targets else 0
                waste_per_unit = total - other_targets - val
                efficient.append((adj_eff, val, sig, waste_per_unit))

            efficient.sort(key=lambda x: (-x[0], x[1]))  # 最效率的在前

            if not efficient or efficient[0][0] <= worst_current[0]:
                continue  # 无改进空间

            # 尝试替换：移除 N 份低效签名，加入 M 份高效签名
            for pool_eff, pool_val, pool_sig, pool_waste in efficient:
                if pool_sig in new_counts:
                    continue
                for cur_eff, cur_val, cur_sig, cur_cnt, cur_waste in current:
                    if cur_eff >= pool_eff:
                        continue
                    # 计算等价替换量
                    # 需要: M * pool_val >= N * cur_val
                    for N in range(1, cur_cnt + 1):
                        M = math.ceil(N * cur_val / pool_val)
                        if M * pool_waste >= N * cur_waste:
                            continue  # 没有减少溢出

                        # 验证替换后方案仍然有效
                        test_counts = dict(new_counts)
                        test_counts[cur_sig] -= N
                        if test_counts[cur_sig] <= 0:
                            del test_counts[cur_sig]
                        test_counts[pool_sig] = (
                            test_counts.get(pool_sig, 0) + M)

                        # 重新计算所有目标是否仍被满足
                        test_total = [0] * NUM_ASPECTS
                        for s, c in test_counts.items():
                            sv = self.db.sig_vectors[s]
                            for i in range(NUM_ASPECTS):
                                test_total[i] += sv[i] * c

                        if self._is_satisfied(test_total, target_vec):
                            new_counts = test_counts
                            break
                    if new_counts is not counts:
                        break
                if new_counts is not counts:
                    break

        return new_counts
