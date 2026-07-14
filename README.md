# Thaumcraft 6 要素配平器

用于辅助 DJ2 整合包的 **神秘时代 6 (Thaumcraft 6)** 要素配平工具。给定要素需求（如 `metallum=30, herba=20`），从数千个物品中搜索出**溢出量最小**的物品组合。

---

## 目录

- [工作原理](#工作原理)
  - [核心概念：要素签名](#核心概念要素签名)
  - [束搜索算法](#束搜索算法)
  - [排序元组](#排序元组)
  - [收敛条件](#收敛条件)
  - [溢出量计算](#溢出量计算)
- [数据文件](#数据文件)
- [安装](#安装)
- [使用说明](#使用说明)
  - [交互模式](#交互模式)
  - [CLI 模式](#cli-模式)
  - [选项参考](#选项参考)
- [输出解读](#输出解读)
- [高级用法](#高级用法)
  - [束宽调优](#束宽调优)
  - [ILP 精确求解](#ilp-精确求解)
  - [Vis Crystal 排除](#vis-crystal-排除)
- [项目结构](#项目结构)
- [许可](#许可)

---

## 工作原理

### 核心概念：要素签名

在 Thaumcraft 6 中，物品被投入炼药锅 (Crucible) 后会分解为要素 (Aspect)。每个物品提供一组固定的要素组合，例如：

| 物品 | 要素分解 |
|---|---|
| `minecraft:iron_ingot` | `metallum=15, machina=5` |
| `quark:iron_button` | `metallum=1` |
| `minecraft:melon` | `herba=8, victus=4` |
| `thaumcraft:crystal_essence` | 全部 41 种要素各 ×1 |

许多物品共享相同的要素组合（如 18 个不同物品都有 `metallum=1`），这些物品构成了一个**要素签名 (Aspect Signature)**。本程序在搜索时不关心具体物品，只在**签名级别**进行推理，大幅缩小搜索空间。

例如，当需求为 `metallum=30` 时：
- 搜索状态是 `{"metallum=1": 30}`（使用 30 个 `metallum=1` 签名）
- 而不是 30 个铁按钮 + 2 个铁锭的具体分配

最终输出时再自动将签名计数分摊给所有可用的实际物品。

### 束搜索算法

束搜索 (Beam Search) 是一种启发式搜索算法，每一步保留最优的 B 个候选状态（B = 束宽）。

```
状态: (overflow, total_vector, sig_counts)
       ↓          ↓              ↓
       溢出量     41维要素向量   签名→数量映射
```

**每一步的扩展规则：**

1. 找出当前状态中"最不满足"的目标要素（差距最大的要素）
2. 从该要素的候选签名池中选择能改善它的签名
3. 添加一个签名单位，生成新状态
4. 按排序元组截取 Top-B 个状态进入下一轮

**候选签名池构建（三种策略）：**

- **策略 1（细粒度优先）**：数值最小的签名优先（如 `metallum=1` 优于 `metallum=15`），便于精确微调
- **策略 2（纯度优先）**：每个数值至少保留一种签名，多侧面要素的签名靠后
- **策略 3（多要素覆盖）**：在需求包含多个目标要素时，优先收集能同时提供多种目标要素的签名

### 排序元组

```
(overflow, -satisfied_count, totals_total, -item_count)
  ↓            ↓                  ↓               ↓
  溢出最小     已满足要素最多     总要素量最小     物品数最少
```

- **overflow**: 总溢出量（首要指标，越小越好）
- **satisfied_count**: 已满足的要素数量（越大越好，负号实现降序）
- **totals_total**: 提供的要素总量（越小越好，减少浪费）
- **item_count**: 使用的物品总件数（越大越好，负号实现降序——物品越碎越灵活）

### 收敛条件

搜索在以下任一条件满足时停止：

1. **达到最大迭代次数**（默认 500）
2. **beam 为空**（所有状态已展开或已判定为解）
3. **已找到零溢出解且颗粒度不再改善**：如果连续多轮没有新的零溢出解且最佳物品数不再增长，认为已穷尽
4. **未找到零溢出解但已达耐心上限**：最慢的情况下每步只加 1 点要素，需要 `sum(target) + 50` 步

### 溢出量计算

**溢出只计超出，不计不足**。对于一个要素：
- 目标需求 `metallum=30`，实际提供 `metallum=35` → 溢出 +5
- 实际提供 `metallum=25` → 溢出 0（不是 -5）

这意味着所有未满足目标的状态都有 `overflow=0`，需要靠排序元组中的二级指标来区分。

---

## 数据文件

本程序需要 `thaumicjei_itemstack_aspects.json` 数据文件，由 **Thaumcraft JEI** 模组导出，包含所有物品的各要素分解值。

> **注意**：此文件未包含在 Git 仓库中（已在 .gitignore 中排除）。
> 你需要手动获取该文件并放置到以下任一位置：
> - 仓库根目录
> - `thaumcraft_aspect_calculator/` 包目录
> - 当前工作目录
>
> 也可通过 `-j` 参数指定路径。

---

## 安装

```bash
# 1. 确保 Python 3.7+
python3 --version

# 2. 克隆仓库
git clone https://github.com/shinyashen/thaumcraft_aspect_calculator.git
cd thaumcraft_aspect_calculator

# 3. 放置数据文件
#    将 thaumicjei_itemstack_aspects.json 复制到仓库根目录

# 4. （可选）安装 PuLP 以获得精确求解能力
pip install pulp

# 5. 运行
python -m thaumcraft_aspect_calculator -t metallum:30
```

---

## 使用说明

### 交互模式

不传 `-t` 参数时进入交互模式：

```bash
python -m thaumcraft_aspect_calculator
```

交互模式逐行输入要素需求，空行结束：

```
╔══════════════════════════════════════════════════════╗
║         Thaumcraft 6 要素配平器                      ║
║                                                     ║
║ 输入需要的要素及数量，一行一个，格式: 要素名 数值    ║
║ 空行结束输入。                                       ║
║ 如: metallum 30                                      ║
║     herba 20                                         ║
╚══════════════════════════════════════════════════════╝

可用要素: aer, alkimia, alienis, aqua, auram, aversio, bestia, ...

 > metallum 30
  ✓ metallum=30
 > herba 20
  ✓ herba=20
 >
```

### CLI 模式

```bash
# 单个要素
python -m thaumcraft_aspect_calculator -t metallum:30

# 多个要素
python -m thaumcraft_aspect_calculator -t metallum:30 herba:20

# 指定显示方案数
python -m thaumcraft_aspect_calculator -t auram:12 alienis:8 -n 10

# 指定数据文件路径
python -m thaumcraft_aspect_calculator \
    -j /path/to/thaumicjei_itemstack_aspects.json \
    -t metallum:30

# 限制每类签名显示的物品数量
python -m thaumcraft_aspect_calculator -t metallum:30 --items-per-group 3
```

### 选项参考

| 选项 | 默认值 | 说明 |
|---|---|---|
| `-t`, `--target` | — | 要素需求，格式 `要素名:数值`（可指定多个） |
| `-n`, `--num-solutions` | 5 | 显示的方案数 |
| `-j`, `--json` | 自动 | 要素 JSON 文件路径 |
| `--beam-width` | 300 | 束搜索束宽（越大结果越好但越慢） |
| `--top-k` | 30 | 每次扩展考虑的签名种类数 |
| `--max-iter` | 500 | 最大迭代次数 |
| `--use-ilp` | 关闭 | 使用 PuLP MILP 求解器（需安装 pulp） |
| `--time-limit` | 30 | ILP 求解器时间限制（秒） |
| `--exclude-vis-crystals` | 开启 | 排除魔力水晶碎片（较难获得） |
| `--no-exclude-vis-crystals` | — | 包含魔力水晶碎片 |
| `--items-per-group` | 5 | 每类签名最多显示多少个物品示例 |

---

## 输出解读

```
═══ 方案 1 ═══
溢出: 0  要素总量: 183  物品数: 33
────────────────────────────────────────
  metallum=1  × 30
    → quark:iron_button
    → minecraft:iron_nugget
    → quark:iron_plate
    … (共 18 个, 显示前 5 个)
  herba=8,victus=4  × 3
    → minecraft:melon
    → minecraft:pumpkin
────────────────────────────────────────
要素合计: herba=24, metallum=30, victus=12
```

各部分含义：

- **方案编号**: 从最优到次优排列
- **溢出**: 超出目标需求的要素总量。`0` 表示完美匹配
- **要素总量**: 所有物品提供的要素之和（包含超出部分）
- **物品数**: 使用的物品总件数
- **签名组**: `签名 × 使用次数`，下方列出所有提供此签名的物品
- **要素合计**: 方案提供的各种要素及其总量

---

## 高级用法

### 束宽调优

```bash
# 大束宽 = 更优解但更慢（用于复杂需求）
python -m thaumcraft_aspect_calculator \
    -t auram:12 alienis:8 ordo:5 \
    --beam-width 500 --top-k 50
```

### ILP 精确求解

安装 [PuLP](https://github.com/coin-or/pulp) 后，可使用 MILP 求解器获得**精确最优解**：

```bash
pip install pulp
python -m thaumcraft_aspect_calculator -t metallum:30 --use-ilp
```

**ILP 与束搜索的对比：**

| 方面 | 束搜索 | ILP |
|---|---|---|
| 最优性 | 启发式，不保证最优 | 精确最优 |
| 速度 | 快（秒级） | 慢（对复杂问题可能数分钟） |
| 多解枚举 | 通过束宽自然提供多种方案 | 需添加排除约束，效率低 |
| 依赖 | 纯 Python | 需 PuLP + CBC 求解器 |

### Vis Crystal 排除

`thaumcraft:crystal_essence`（魔力水晶碎片）提供所有 41 种要素各 ×1，虽然看似万能，但在 DJ2 整合包中难以大量获得。默认启用排除：

```bash
# 包含 Vis Crystal（允许使用）
python -m thaumcraft_aspect_calculator -t auram:8 --no-exclude-vis-crystals
```

---

## 项目结构

```
thaumcraft_aspect_calculator/
├── thaumcraft_aspect_calculator/    # Python 包
│   ├── __init__.py                  # 包入口，导出公共 API
│   ├── __main__.py                  # python -m 支持
│   ├── data_model.py                # 常量、ItemProfile、AspectDatabase
│   ├── solution.py                  # Solution 数据类与显示
│   ├── beam_solver.py               # BeamSolver（束搜索）
│   ├── ilp_solver.py                # ILPSolver（PuLP）+ 回退包装
│   └── cli.py                       # CLI 参数解析、交互输入、main()
├── README.md                        # 本文档
├── LICENSE                          # 开源许可
└── .gitignore                       # 忽略规则
```

**模块依赖关系：**

```
cli.py → beam_solver, ilp_solver, solution, data_model
beam_solver.py → solution, data_model
ilp_solver.py → solution, data_model
solution.py → data_model
```

---

## 许可

本项目基于 MIT 许可证开源。详见 [LICENSE](LICENSE) 文件。
