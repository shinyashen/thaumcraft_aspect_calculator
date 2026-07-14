#!/usr/bin/env python3
"""
Thaumcraft 6 要素配平器 — 解决方案
===================================
定义求解结果的数据结构(Solution)和格式化输出。
"""

from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, List, Tuple

from .data_model import ALL_ASPECTS_ORDERED, AspectDatabase


@dataclass
class Solution:
    """一个解决方案"""

    counts: Dict[str, int]     # item_key → 使用数量
    totals: Dict[str, int]     # 各要素最终总量
    overflow: int              # 总溢出量
    item_count: int = 0        # 物品总件数

    def __post_init__(self):
        self.item_count = sum(self.counts.values())

    @property
    def totals_total(self) -> int:
        """所有要素总和 = 物品提供的要素总量（排序用：越小越好）"""
        return sum(self.totals.values())

    def satisfied_count(self, target: Dict[str, int]) -> int:
        """已满足的要素数量"""
        return sum(1 for a in target if self.totals.get(a, 0) >= target[a])

    # ── 要素签名分组 ─────────────────────────────────────────────────────

    def _group_counts_by_signature(self, db: AspectDatabase) -> List[Tuple[str, int, List]]:
        """
        将 counts 按要素签名分组。
        返回 [(signature, total_count, [ItemProfile...])]，按数量降序。
        """
        groups = defaultdict(list)  # sig → [(item, count)]
        for key, cnt in self.counts.items():
            if cnt <= 0:
                continue
            item = db.items.get(key)
            if item:
                sig = db.aspect_signature(item.aspects)
                groups[sig].append((item, cnt))

        result = []
        for sig, items in groups.items():
            total_cnt = sum(c for _, c in items)
            all_items = [it for it, _ in items]
            result.append((sig, total_cnt, all_items))
        result.sort(key=lambda x: -x[1])
        return result

    # ── 格式化输出 ───────────────────────────────────────────────────────

    def display(self, db: AspectDatabase, index: int = 1,
                max_items_per_group: int = 5,
                target: Dict[str, int] = None) -> str:
        """格式化为要素签名分组的输出"""
        lines = []
        sep = "─" * 40
        lines.append(f"═══ 方案 {index} ═══")
        lines.append(f"溢出: {self.overflow}  要素总量: {self.totals_total}  物品数: {self.item_count}")
        lines.append(sep)

        groups = self._group_counts_by_signature(db)
        for sig, cnt, items_in_group in groups:
            # 将签名中的要素拆分为目标要素与无关要素（附带浪费）
            aspect_parts = sig.split(",")
            target_parts = []
            waste_parts = []
            for ap in aspect_parts:
                name = ap.split("=")[0]
                if target and name in target:
                    target_parts.append(f"★ {ap}")
                else:
                    waste_parts.append(f"· {ap}")
            # 目标要素在前，无关要素在后
            display_parts = target_parts + waste_parts
            aspect_str = "  ".join(display_parts)
            lines.append(f"  {aspect_str}  × {cnt}")
            # 获取数据库中所有同签名的物品
            all_sig_items = db.get_items_for_signature(sig)
            total_available = len(all_sig_items)
            show_items = all_sig_items[:max_items_per_group]
            for it in show_items:
                lines.append(f"    → {it.display_name()}")
            if total_available > max_items_per_group:
                lines.append(f"    … (共 {total_available} 个, 显示前 {max_items_per_group} 个)")

        lines.append(sep)
        aspects_shown = {a for a in ALL_ASPECTS_ORDERED if self.totals.get(a, 0) > 0}
        if aspects_shown:
            parts = [f"{a}={self.totals[a]}" for a in sorted(aspects_shown)]
            lines.append(f"要素合计: {', '.join(parts)}")
        lines.append("")
        return "\n".join(lines)
