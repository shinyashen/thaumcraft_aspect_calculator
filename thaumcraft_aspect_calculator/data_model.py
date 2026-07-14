#!/usr/bin/env python3
"""
Thaumcraft 6 要素配平器 — 数据模型
=====================================
定义要素常量、物品画像(ItemProfile)和数据库加载(AspectDatabase)。
"""

import json
import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, List, Optional, Set


# ═══════════════════════════════════════════════════════════════════════════
# 全局要素常量 — Thaumcraft 6 的 41 种要素
# ═══════════════════════════════════════════════════════════════════════════

ALL_ASPECTS_ORDERED = [
    'aer', 'alkimia', 'alienis', 'aqua', 'auram', 'aversio', 'bestia',
    'cognitio', 'desiderium', 'diabolus', 'exanimis', 'fabrico', 'gelum',
    'herba', 'humanus', 'ignis', 'instrumentum', 'luna', 'lux', 'machina',
    'metallum', 'mortuus', 'motus', 'ordo', 'perditio', 'permutatio',
    'potentia', 'praecantatio', 'praemunio', 'sensus', 'sol', 'spiritus',
    'stellae', 'tenebrae', 'terra', 'vacuos', 'victus', 'vinculum',
    'vitium', 'vitreus', 'volatus',
]

ASPECT_INDEX = {a: i for i, a in enumerate(ALL_ASPECTS_ORDERED)}
NUM_ASPECTS = len(ALL_ASPECTS_ORDERED)  # = 41


# ═══════════════════════════════════════════════════════════════════════════
# ItemProfile — 单一物品的要素画像
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class ItemProfile:
    """单一物品的要素画像"""

    key: str                     # "minecraft:iron_ingot@0"
    item_id: str                 # "minecraft:iron_ingot"
    damage: int                  # 0
    aspects: Dict[str, int]      # {"metallum": 15, "machina": 5}
    total_aspects: int = 0       # 预计算：所有要素之和

    def __post_init__(self):
        self.total_aspects = sum(self.aspects.values())

    def aspect_vector(self) -> List[int]:
        """返回 NUM_ASPECTS 维要素向量"""
        vec = [0] * NUM_ASPECTS
        for a, c in self.aspects.items():
            idx = ASPECT_INDEX.get(a)
            if idx is not None:
                vec[idx] = c
        return vec

    def display_name(self) -> str:
        """用户友好的物品名（去掉 mod: 前缀，对常见 mod 缩写）"""
        name = self.item_id
        short = {
            'minecraft:': '',
            'thaumcraft:': 'tc:',
            'botania:': 'bot:',
            'thermalfoundation:': 'tf:',
            'tconstruct:': 'tcon:',
            'quark:': '',
            'enderio:': 'eio:',
            'chisel:': '',
        }
        for prefix, repl in short.items():
            if name.startswith(prefix):
                name = repl + name[len(prefix):]
                break
        if self.damage != 0:
            name += f'#{self.damage}'
        return name


# ═══════════════════════════════════════════════════════════════════════════
# AspectDatabase — 从 JSON 加载并索引所有物品
# ═══════════════════════════════════════════════════════════════════════════

class AspectDatabase:
    """从 JSON 加载并索引所有物品"""

    VIS_CRYSTAL_IDS = {
        'thaumcraft:crystal_essence',  # 魔力水晶碎片（提供所有要素×1）
    }

    def __init__(self, json_path: str):
        self.json_path = json_path
        self.items: Dict[str, ItemProfile] = {}       # key → ItemProfile
        self._aspect_items: Dict[str, List[str]] = defaultdict(list)  # aspect → [item_keys]
        self.sig_vectors: Dict[str, List[int]] = {}   # signature → 41维向量
        self.load()

    # ── JSON 加载 ─────────────────────────────────────────────────────────

    def load(self):
        """从 JSON 文件解析物品数据并构建索引"""
        with open(self.json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # 第一步：聚合同一物品的多个要素条目
        temp: Dict[str, dict] = {}
        for entry in data:
            aspect = entry['aspect']
            for item_str in entry['items']:
                m = re.search(r'id:"([^"]+)"', item_str)
                cm = re.search(r'Count:(\d+)s', item_str)
                dm = re.search(r'Damage:(-?\d+)s', item_str)
                if not m or not cm:
                    continue
                item_id = m.group(1)
                count = int(cm.group(1))
                damage = int(dm.group(1)) if dm else 0
                key = f'{item_id}@{damage}'
                if key not in temp:
                    temp[key] = {'item_id': item_id, 'damage': damage, 'aspects': {}}
                temp[key]['aspects'][aspect] = count

        # 第二步：创建 ItemProfile 并建立索引
        for key, data in temp.items():
            profile = ItemProfile(
                key=key,
                item_id=data['item_id'],
                damage=data['damage'],
                aspects=data['aspects'],
            )
            self.items[key] = profile
            for aspect in profile.aspects:
                self._aspect_items[aspect].append(key)

        # 预计算要素签名 → 41维向量（用于签名级束搜索）
        for key, item in self.items.items():
            sig = self.aspect_signature(item.aspects)
            if sig not in self.sig_vectors:  # 相同签名的物品共享同一向量
                self.sig_vectors[sig] = item.aspect_vector()

    # ── 物品/签名查询 ────────────────────────────────────────────────────

    def get_relevant_items(self, target_aspects: Set[str]) -> List[ItemProfile]:
        """获取所有与目标要素相关的物品（至少提供一种目标要素）"""
        seen = set()
        result = []
        for aspect in target_aspects:
            for key in self._aspect_items.get(aspect, []):
                if key not in seen:
                    seen.add(key)
                    result.append(self.items[key])
        return result

    # ── Vis Crystal 检测 ─────────────────────────────────────────────────

    @classmethod
    def is_vis_crystal(cls, key: str) -> bool:
        """判断一个物品是否是 Vis Crystal（较难获得的纯净要素水晶）"""
        item_id = key.split('@')[0]
        return item_id in cls.VIS_CRYSTAL_IDS

    def filter_vis_crystals(self, items: List[ItemProfile]) -> List[ItemProfile]:
        """从物品列表中移除 Vis Crystal"""
        return [it for it in items if not self.is_vis_crystal(it.key)]

    def filter_pool(self, items: List[ItemProfile],
                    exclude_vis_crystals: bool = True) -> List[ItemProfile]:
        """综合过滤物品池"""
        result = list(items)
        if exclude_vis_crystals:
            result = self.filter_vis_crystals(result)
        return result

    # ── 要素签名 ─────────────────────────────────────────────────────────

    @staticmethod
    def aspect_signature(aspects: Dict[str, int]) -> str:
        """
        生成要素签名。
        例: {'metallum': 1, 'herba': 1} → 'herba=1,metallum=1'
        """
        return ",".join(f"{a}={aspects[a]}" for a in sorted(aspects))

    def get_items_for_signature(self, signature: str) -> List[ItemProfile]:
        """根据要素签名获取所有匹配物品"""
        if not hasattr(self, '_sig_index'):
            self._sig_index = defaultdict(list)
            for key, item in self.items.items():
                sig = self.aspect_signature(item.aspects)
                self._sig_index[sig].append(key)
        return [self.items[k] for k in self._sig_index.get(signature, [])]
