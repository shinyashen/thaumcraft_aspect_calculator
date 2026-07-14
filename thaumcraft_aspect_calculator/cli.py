#!/usr/bin/env python3
"""
Thaumcraft 6 要素配平器 — CLI 入口
====================================
命令行参数解析、交互式输入和主流程编排。
"""

import argparse
import os
import sys
from typing import Dict, List, Optional

from .data_model import ALL_ASPECTS_ORDERED, ASPECT_INDEX, NUM_ASPECTS, AspectDatabase
from .beam_solver import BeamSolver
from .ilp_solver import solve_with_ilp_auto
from .solution import Solution


# ═══════════════════════════════════════════════════════════════════════════
# 交互式输入
# ═══════════════════════════════════════════════════════════════════════════

def interactive_input(db: AspectDatabase) -> Dict[str, int]:
    """交互式输入要素需求"""
    # ── Tab 自动补全 ──
    try:
        import readline

        def _completer(text: str, state: int) -> Optional[str]:
            options = [a for a in ALL_ASPECTS_ORDERED if a.startswith(text.lower())]
            return options[state] if state < len(options) else None

        readline.set_completer(_completer)
        readline.set_completer_delims(' \t\n')
        readline.parse_and_bind("tab: complete")
    except ImportError:
        pass  # readline 不可用（如 Windows 无 pyreadline），跳过自动补全

    print(f"""
╔══════════════════════════════════════════════════════╗
║         Thaumcraft 6 要素配平器                      ║
║                                                     ║
║ 输入需要的要素及数量，一行一个，格式: 要素名 数值    ║
║ 空行结束输入。                                       ║
║ 如: metallum 30                                      ║
║     herba 20                                         ║
╚══════════════════════════════════════════════════════╝
""")
    print("可用要素:", ", ".join(ALL_ASPECTS_ORDERED))
    print()

    target = {}
    while True:
        try:
            line = input(" > ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line:
            break
        parts = line.split()
        if len(parts) < 2:
            print("  格式: 要素名 数值（如: metallum 30）")
            continue
        aspect = parts[0].lower()
        try:
            amount = int(parts[1])
        except ValueError:
            print("  数值必须是整数")
            continue
        if aspect not in ASPECT_INDEX:
            print(f"  未知要素 '{aspect}'。可用要素: {', '.join(ALL_ASPECTS_ORDERED)}")
            continue
        if amount <= 0:
            print("  数值必须为正")
            continue
        target[aspect] = amount
        print(f"  ✓ {aspect}={amount}")

    return target


# ═══════════════════════════════════════════════════════════════════════════
# 命令行参数解析
# ═══════════════════════════════════════════════════════════════════════════

def parse_target_arg(target_args: List[str]) -> Dict[str, int]:
    """解析命令行参数 -t metallum:30 herba:20"""
    target = {}
    for token in target_args:
        if ':' in token:
            aspect, amount = token.split(':', 1)
            try:
                target[aspect] = int(amount)
            except ValueError:
                print(f"  无法解析 '{token}'，格式应为 要素名:数值",
                      file=sys.stderr)
    return target


def find_json_file(json_path_arg: Optional[str]) -> Optional[str]:
    """查找要素 JSON 文件路径"""
    if json_path_arg:
        return json_path_arg if os.path.exists(json_path_arg) else None

    # 搜索顺序：当前目录 → 脚本同级目录 → 父目录
    cwd = os.getcwd()
    script_dir = os.path.dirname(os.path.abspath(__file__))
    parent_dir = os.path.dirname(script_dir)

    candidates = [
        os.path.join(cwd, 'thaumicjei_itemstack_aspects.json'),
        os.path.join(script_dir, 'thaumicjei_itemstack_aspects.json'),
        os.path.join(parent_dir, 'thaumicjei_itemstack_aspects.json'),
    ]
    # 去重
    seen = set()
    for p in candidates:
        norm = os.path.normpath(p)
        if norm not in seen and os.path.exists(norm):
            return norm
        seen.add(norm)

    return None


def print_missing_json_error():
    """输出 JSON 数据文件缺失时的引导错误信息"""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    parent_dir = os.path.dirname(script_dir)

    print("❌ 错误: 找不到要素数据文件 'thaumicjei_itemstack_aspects.json'",
          file=sys.stderr)
    print("", file=sys.stderr)
    print("  已将 'thaumicjei_itemstack_aspects.json' 添加至 .gitignore，",
          file=sys.stderr)
    print("  你需要手动将数据文件放置到以下任一位置:", file=sys.stderr)
    print("", file=sys.stderr)
    print(f"    ① 当前目录: {os.getcwd()}/", file=sys.stderr)
    print(f"    ② 包目录:    {script_dir}/", file=sys.stderr)
    print(f"    ③ 仓库根目录: {parent_dir}/", file=sys.stderr)
    print("", file=sys.stderr)
    print("  或使用 -j 参数指定路径:", file=sys.stderr)
    print("    python -m thaumcraft_aspect_calculator \\", file=sys.stderr)
    print("        -j /path/to/thaumicjei_itemstack_aspects.json \\", file=sys.stderr)
    print("        -t metallum:30", file=sys.stderr)
    print("", file=sys.stderr)
    print("  数据文件来源:", file=sys.stderr)
    print("    由 Thaumcraft JEI 导出，包含所有物品的各要素分解值。",
          file=sys.stderr)
    sys.exit(1)


# ═══════════════════════════════════════════════════════════════════════════
# 输出格式化
# ═══════════════════════════════════════════════════════════════════════════

def print_results(solutions: List[Solution], db: AspectDatabase,
                  items_per_group: int):
    """输出求解结果"""
    if not solutions:
        print("❌ 未找到可行方案。")
        return

    best_overflows = set(s.overflow for s in solutions)

    if len(best_overflows) == 1 and 0 in best_overflows:
        print(f"\n✅ 找到 {len(solutions)} 个零溢出方案！")
    elif 0 in best_overflows:
        print("\n✅ 找到零溢出方案！（以及溢出更大的替代方案）")
    else:
        min_o = min(best_overflows)
        print(f"\n⚠  最小溢出 = {min_o}")
        if len(best_overflows) > 1:
            print(f"   溢出范围: {', '.join(str(o) for o in sorted(best_overflows))}")

    print()
    for i, sol in enumerate(solutions):
        print(sol.display(db, index=i + 1,
                          max_items_per_group=items_per_group))

    if len(solutions) >= 2:
        print("📊 方案比较:")
        print(f"   {'方案':<8} {'溢出':<8} {'要素总量':<8} {'物品数':<8}")
        print(f"   {'-' * 32}")
        for i, sol in enumerate(solutions[:min(5, len(solutions))]):
            print(f"   #{i + 1:<6} {sol.overflow:<8} {sol.totals_total:<8} {sol.item_count:<8}")


# ═══════════════════════════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════════════════════════

def build_parser() -> argparse.ArgumentParser:
    """构建参数解析器"""
    parser = argparse.ArgumentParser(
        description="Thaumcraft 6 要素配平器 — 找出最小溢出的物品组合",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
示例:
  %(prog)s -t metallum:30 herba:20
  %(prog)s -t metallum:30 -n 10 --beam-width 500
  %(prog)s -t metallum:30 --use-ilp --time-limit 60
        """,
    )
    parser.add_argument('-t', '--target', nargs='+', metavar='ASPECT:VAL',
                        help='要素需求，如: metallum:30 herba:20')
    parser.add_argument('-n', '--num-solutions', type=int, default=5,
                        help='显示的方案数 (默认: 5)')
    parser.add_argument('-j', '--json', default=None,
                        help='要素 JSON 文件路径 (默认: 自动查找)')
    parser.add_argument('--beam-width', type=int, default=300,
                        help='束搜索束宽 (默认: 300)')
    parser.add_argument('--top-k', type=int, default=30,
                        help='每次扩展考虑的签名种类数 (默认: 30)')
    parser.add_argument('--max-iter', type=int, default=500,
                        help='最大迭代次数 (默认: 500)')
    parser.add_argument('--use-ilp', action='store_true',
                        help='使用 PuLP MILP 求解器 (需 pip install pulp)')
    parser.add_argument('--time-limit', type=int, default=30,
                        help='ILP 求解器时间限制秒数 (默认: 30)')
    parser.add_argument('--exclude-vis-crystals', action='store_true',
                        default=True,
                        help='排除魔力水晶碎片(Vis Crystal, 较难获得) (默认: 启用)')
    parser.add_argument('--no-exclude-vis-crystals',
                        dest='exclude_vis_crystals',
                        action='store_false',
                        help='包含魔力水晶碎片')
    parser.add_argument('--items-per-group', type=int, default=5,
                        help='每类物品组合最多显示的物品数 (默认: 5)')
    return parser


def main():
    """主入口"""
    parser = build_parser()
    args = parser.parse_args()

    # ── 查找 JSON 文件 ──
    json_path = find_json_file(args.json)
    if not json_path:
        print_missing_json_error()

    print(f"📂 加载数据: {json_path}")
    db = AspectDatabase(json_path)
    print(f"   ✓ {len(db.items)} 个物品, {NUM_ASPECTS} 种要素")

    # ── 获取目标 ──
    target = None
    if args.target:
        target = parse_target_arg(args.target)
    else:
        target = interactive_input(db)

    if not target:
        print("未指定要素需求，退出。")
        return

    print(f"\n🎯 目标: {', '.join(f'{a}={v}' for a, v in sorted(target.items()))}")

    # ── 求解 ──
    if args.use_ilp:
        solutions = solve_with_ilp_auto(
            db, target, n_solutions=args.num_solutions,
            time_limit=args.time_limit,
            exclude_vis_crystals=args.exclude_vis_crystals)
    else:
        solver = BeamSolver(
            db, beam_width=args.beam_width,
            top_k_items=args.top_k,
            max_iterations=args.max_iter,
            exclude_vis_crystals=args.exclude_vis_crystals)
        solutions = solver.solve(target, n_solutions=args.num_solutions)

    # ── 输出 ──
    print_results(solutions, db, items_per_group=args.items_per_group)


if __name__ == '__main__':
    main()
