"""
LLM 提示词定义 v9.0

第一次调用：自然语言 -> VisualSpec JSON
第二次调用：违反报告 -> RepairPlan JSON

原则：
- LLM 描述的是仿真图视觉目标
- 不直接指定色码图排列
- 不直接指定针法动作
"""

import json
from typing import List, Dict


DESIGN_SYSTEM_PROMPT = """将针织图案描述转换为视觉目标 JSON。

你描述的是"仿真图上想要的视觉形状和效果"，不是色码图的针法排列。
针法排列由后续系统自动完成。

## 输出格式
{
  "layout_type": "centered",
  "regions": [
    {
      "region_id": "ground",
      "visual_shape": "panel",
      "visual_effect": "plain",
      "layout_role": "ground",
      "placement": {"type": "full"},
      "params": {},
      "symmetry": "none",
      "allow_refinement": false
    },
    {
      "region_id": "main",
      "visual_shape": "diamond",
      "visual_effect": "cable",
      "layout_role": "center",
      "placement": {"center": [20, 20], "size": 16},
      "params": {},
      "symmetry": "mirror_lr",
      "allow_refinement": true
    }
  ]
}

## visual_shape 合法值（仿真图形状）
diamond    菱形
wave       波浪
column     柱状
stripe     条纹
panel      矩形面板
frame      边框
mesh       网格形
circle     圆形
allover    满地

## visual_effect 合法值（仿真图视觉效果）
plain        平针（光滑正面）
reverse      反针（凸起反面）
cable        麻花/绞花/扭针
wave_tuck    波浪集圈（起伏凹凸波纹）
rib          罗纹（纵向凹凸条纹）
links        链接组织（横向正反交替）
lace         网眼/镂空
relief       浮雕（凸起纹理）
honeycomb    蜂巢纹
seed         种子针（细密凹凸）

## layout_role 合法值
center       中心主花
ground       背景底布
border       装饰边框
side_band    侧边支撑带
allover      满地重复

## layout_type 合法值
centered        中心主花布局
allover_repeat  满地重复布局
framed          带边框布局
side_bands      两侧边带布局
vertical_repeat 纵向重复布局
mirror_pair     镜像对称布局

## params 字段要求（按 visual_effect）

wave_tuck（波浪吊目）:
  period_y: 3-5（纵向周期，单位行）- 每几行重复一次波浪
  period_x: 4-6（横向周期，单位列）- 波浪宽度
  split_col_offset: 2（split 在周期中的列位置，通常 1-2）
  tuck_col_offset: 3（tuck 在周期中的列位置，通常 2-3）
  example: {"period_y": 4, "period_x": 5, "split_col_offset": 2, "tuck_col_offset": 3}

cable（麻花/绞花）:
  cable_period: 4-6（麻花重复周期）
  cable_pairs: 1-3（麻花宽度/对数）
  side_ratio: 0.25-0.35（相对于 size 的距离）
  example: {"cable_period": 5, "cable_pairs": 2, "side_ratio": 0.3}

relief（浮雕）:
  period_x: 3-4（横向重复周期）
  period_y: 3-4（纵向重复周期）
  stagger: true/false（是否错位）
  example: {"period_x": 4, "period_y": 4, "stagger": true}

honeycomb（蜂巢）:
  period_x: 3（固定为 3）
  period_y: 3（固定为 3）
  stagger: true（总是错位）
  example: {"period_x": 3, "period_y": 3, "stagger": true}

lace（网眼/镂空）:
  period_x: 4-5（孔洞横向周期）
  period_y: 4-5（孔洞纵向周期）
  stagger: true/false（是否错位）
  example: {"period_x": 4, "period_y": 4, "stagger": true}

seed（种子针）:
  无需参数
  example: {}

rib/links/plain/reverse:
  无需参数
  example: {}

## 理解原则
1. 用户说"麻花/绞花/扭针/cable/twist" -> visual_effect=cable
2. 用户说"波浪/吊目/集圈纹/起伏凹凸波纹" -> visual_effect=wave_tuck（不是 plain！）
3. 用户说"网眼/镂空/孔洞" -> visual_effect=lace
4. 用户说"罗纹/rib/双床/竖条纹" -> visual_effect=rib
5. 用户说"双针/links/正反交替" -> visual_effect=links
6. 用户说"蜂巢/honeycomb" -> visual_effect=honeycomb
7. 用户说"浮雕/凸起relief/救凸起纹理" -> visual_effect=relief
8. 用户说"种子针/seed" -> visual_effect=seed
9. 用户没有特别指定纹理效果 -> visual_effect=plain
10. visual_shape=wave 是波浪**形状**（菱形、波浪曲线等），visual_effect=wave_tuck 是波浪**纹理效果**
    两者可以组合：visual_shape="wave" + visual_effect="plain" = 平针波浪边框
    或         visual_shape="panel" + visual_effect="wave_tuck" = 矩形面板内有波浪纹理
11. 用户只说"菱形/diamond/rhombus"，没有说"麻花/绞花/扭针/cable/twist"时，
    必须输出 visual_shape="diamond" + visual_effect="plain"，表示只有菱形轮廓/区域，不要自动加入内部麻花事件。

## 重要
- 只输出合法 JSON，不输出解释
- 网格 40×40
- center 默认 [20, 20]
- size 一般 12~20
"""


PATTERN_PLAN_SYSTEM_PROMPT = """将针织图案需求转换为可编辑 PatternPlan JSON，或对已有 PatternPlan 输出增量编辑 JSON。

你负责理解用户意图和图案组合，不直接指定机器针法动作。
后续系统会把 PatternPlan 渲染为 VisualSpec，再编译成色码图。

## 新建图案时输出
{
  "schema_version": "pattern_plan/v1",
  "canvas": {"width": 40, "height": 40},
  "layout_type": "centered",
  "motifs": [
    {
      "motif_id": "main",
      "motif_type": "wave",
      "effect": "wave_tuck",
      "region": {"center": [20, 20], "size": 16},
      "params": {"period_x": 5, "period_y": 4, "thickness": 2},
      "role": "center",
      "symmetry": "none",
      "allow_refinement": true
    }
  ]
}

## 修改已有图案时输出
{
  "operation": "modify",
  "target": "main",
  "changes": {
    "region": {"size": 18},
    "params": {"period_x": 4}
  }
}

也可以添加结构:
{
  "operation": "add",
  "motif": {
    "motif_id": "eyelet_1",
    "motif_type": "mesh",
    "effect": "lace",
    "region": {"center": [20, 20], "size": 14},
    "params": {"period_x": 4, "period_y": 4, "stagger": true},
    "role": "center"
  }
}

## motif_type 合法值
panel, diamond, wave, mesh, frame, stripe, column, circle, allover

## effect 合法值
plain, reverse, cable, wave_tuck, rib, links, lace, relief, honeycomb, seed

## layout_type 合法值
centered, allover_repeat, framed, side_bands, vertical_repeat, mirror_pair

## 语义原则
1. 波浪/水波/起伏 -> motif_type=wave 或 effect=wave_tuck。若用户说波浪纹理，优先 effect=wave_tuck。
2. 镂空/网眼/孔洞/蕾丝 -> effect=lace；若是图案结构，可用 motif_type=mesh。
3. 麻花/绞花/扭针 -> effect=cable。
4. 菱形只是形状时 effect=plain；不要自动加 cable。
5. 用户说“更大/更小/更密/更疏/加一点镂空/往上移”等，并且输入里包含 current_plan 时，必须输出 operation，而不是重新生成整个 plan。
6. “一点/稍微”表示小幅改动；“明显/更/大幅”表示更大改动。
7. 随机生成时可以组合 1-3 个 motif，但必须参数合理、可渲染。
8. 边框加宽时，border_thickness 每次最多加 1（用户明确说“明显/大幅”才加 2），上限为 3（用户说“加粗/很粗”时上限 4）。正常加宽只需多加一层色块即可，不要让边框宽到连接起来。
9. 用户说“加宽边框”但没有说程度时，默认只加 1 层。

只输出 JSON，不输出解释。
"""


REPAIR_SYSTEM_PROMPT = """你是针织色码图修复专家。
根据规则违反报告，给出最小修复方案。只输出 JSON。

{
  "strategy": "minimal",
  "semantic_edits": [],
  "action_edits": [
    {"row": 10, "col": 15, "new_action": "f_split", "reason": "..."}
  ],
  "config_updates": {}
}

## 允许的 new_action
f_knit / b_knit / xfer_f_b / xfer_b_f / b_tuck / miss / xfer_l1 / f_tuck /
f_split / b_split / f_tuck_2 / carrier / split_v / b_tuck_2 / xfer_r1 

## 修复原则
1. 最小改动
2. split_v 只用于复合结构衔接
3. f_tuck_2 / b_tuck_2 只用于细纹理微调
4. carrier 不参与像素级填充
5. 无需修复时输出空 edits
"""


FEW_SHOT_DESIGN_EXAMPLES: List[Dict] = [
    {
        "input": "一个菱形",
        "output": {
            "layout_type": "centered",
            "regions": [
                {
                    "region_id": "ground",
                    "visual_shape": "panel",
                    "visual_effect": "plain",
                    "layout_role": "ground",
                    "placement": {"type": "full"},
                    "params": {},
                    "symmetry": "none",
                    "allow_refinement": False
                },
                {
                    "region_id": "main",
                    "visual_shape": "diamond",
                    "visual_effect": "plain",
                    "layout_role": "center",
                    "placement": {"center": [20, 20], "size": 16, "shape": "diamond"},
                    "params": {},
                    "symmetry": "mirror_lr",
                    "allow_refinement": False
                }
            ]
        }
    },
    {
        "input": "中心麻花菱形",
        "output": {
            "layout_type": "centered",
            "regions": [
                {
                    "region_id": "ground",
                    "visual_shape": "panel",
                    "visual_effect": "plain",
                    "layout_role": "ground",
                    "placement": {"type": "full"},
                    "params": {},
                    "symmetry": "none",
                    "allow_refinement": False
                },
                {
                    "region_id": "main",
                    "visual_shape": "diamond",
                    "visual_effect": "cable",
                    "layout_role": "center",
                    "placement": {"center": [20, 20], "size": 16, "shape": "diamond"},
                    "params": {},
                    "symmetry": "mirror_lr",
                    "allow_refinement": True
                }
            ]
        }
    },
    {
        "input": "整幅波浪吊目纹理",
        "output": {
            "layout_type": "allover_repeat",
            "regions": [
                {
                    "region_id": "main",
                    "visual_shape": "allover",
                    "visual_effect": "wave_tuck",
                    "layout_role": "allover",
                    "placement": {"type": "full"},
                    "params": {"period_y": 4, "period_x": 5},
                    "symmetry": "none",
                    "allow_refinement": True
                }
            ]
        }
    },
    {
        "input": "两侧罗纹边带，中间蜂巢浮雕",
        "output": {
            "layout_type": "side_bands",
            "regions": [
                {
                    "region_id": "ground",
                    "visual_shape": "panel",
                    "visual_effect": "plain",
                    "layout_role": "ground",
                    "placement": {"type": "full"},
                    "params": {},
                    "symmetry": "none",
                    "allow_refinement": False
                },
                {
                    "region_id": "left_band",
                    "visual_shape": "stripe",
                    "visual_effect": "rib",
                    "layout_role": "side_band",
                    "placement": {"side": "left", "width": 5},
                    "params": {},
                    "symmetry": "none",
                    "allow_refinement": False
                },
                {
                    "region_id": "main",
                    "visual_shape": "panel",
                    "visual_effect": "honeycomb",
                    "layout_role": "center",
                    "placement": {"center": [20, 20], "size": 14, "shape": "panel"},
                    "params": {},
                    "symmetry": "none",
                    "allow_refinement": True
                },
                {
                    "region_id": "right_band",
                    "visual_shape": "stripe",
                    "visual_effect": "rib",
                    "layout_role": "side_band",
                    "placement": {"side": "right", "width": 5},
                    "params": {},
                    "symmetry": "none",
                    "allow_refinement": False
                }
            ]
        }
    },
    {
        "input": "两个柱子，柱子中间波浪",
        "output": {
            "layout_type": "side_bands",
            "regions": [
                {
                    "region_id": "ground",
                    "visual_shape": "panel",
                    "visual_effect": "plain",
                    "layout_role": "ground",
                    "placement": {"type": "full"},
                    "params": {},
                    "symmetry": "none",
                    "allow_refinement": False
                },
                {
                    "region_id": "left_column",
                    "visual_shape": "column",
                    "visual_effect": "plain",
                    "layout_role": "side_band",
                    "placement": {"side": "left", "width": 6},
                    "params": {},
                    "symmetry": "none",
                    "allow_refinement": False
                },
                {
                    "region_id": "center_wave",
                    "visual_shape": "wave",
                    "visual_effect": "wave_tuck",
                    "layout_role": "center",
                    "placement": {"center": [20, 20], "size": 12, "shape": "panel"},
                    "params": {"period_y": 4, "period_x": 5},
                    "symmetry": "none",
                    "allow_refinement": True
                },
                {
                    "region_id": "right_column",
                    "visual_shape": "column",
                    "visual_effect": "plain",
                    "layout_role": "side_band",
                    "placement": {"side": "right", "width": 6},
                    "params": {},
                    "symmetry": "none",
                    "allow_refinement": False
                }
            ]
        }
    },
    {
        "input": "带边框的菱形网眼",
        "output": {
            "layout_type": "framed",
            "regions": [
                {
                    "region_id": "ground",
                    "visual_shape": "panel",
                    "visual_effect": "plain",
                    "layout_role": "ground",
                    "placement": {"type": "full"},
                    "params": {},
                    "symmetry": "none",
                    "allow_refinement": False
                },
                {
                    "region_id": "border",
                    "visual_shape": "diamond",
                    "visual_effect": "reverse",
                    "layout_role": "border",
                    "placement": {"center": [20, 20], "size": 18, "shape": "diamond"},
                    "params": {},
                    "symmetry": "none",
                    "allow_refinement": False
                },
                {
                    "region_id": "main",
                    "visual_shape": "diamond",
                    "visual_effect": "lace",
                    "layout_role": "center",
                    "placement": {"center": [20, 20], "size": 14, "shape": "diamond"},
                    "params": {},
                    "symmetry": "none",
                    "allow_refinement": True
                }
            ]
        }
    },
    {
        "input": "整幅横向条纹",
        "output": {
            "layout_type": "allover_repeat",
            "regions": [
                {
                    "region_id": "main",
                    "visual_shape": "stripe",
                    "visual_effect": "wave_tuck",
                    "layout_role": "allover",
                    "placement": {"type": "full"},
                    "params": {"period_y": 4, "period_x": 5},
                    "symmetry": "none",
                    "allow_refinement": True
                }
            ]
        }
    },
    {
        "input": "整幅纵向柱状纹理",
        "output": {
            "layout_type": "allover_repeat",
            "regions": [
                {
                    "region_id": "main",
                    "visual_shape": "column",
                    "visual_effect": "wave_tuck",
                    "layout_role": "allover",
                    "placement": {"type": "full"},
                    "params": {"period_y": 3, "period_x": 4},
                    "symmetry": "none",
                    "allow_refinement": True
                }
            ]
        }
    }
]


class PromptBuilder:
    def __init__(self, max_examples: int = 4):
        self.max_examples = max_examples

    def build_design_messages(self, user_input: str) -> List[Dict[str, str]]:
        examples = self._select_examples(user_input)
        messages = [{"role": "system", "content": DESIGN_SYSTEM_PROMPT}]
        for ex in examples:
            messages.append({"role": "user", "content": ex["input"]})
            messages.append({
                "role": "assistant",
                "content": json.dumps(ex["output"], ensure_ascii=False, indent=2)
            })
        messages.append({"role": "user", "content": user_input})
        return messages

    def build_pattern_plan_messages(self, user_input: str, current_plan=None) -> List[Dict[str, str]]:
        payload = {"user_input": user_input}
        if current_plan is not None:
            if hasattr(current_plan, "to_dict"):
                payload["current_plan"] = current_plan.to_dict()
            else:
                payload["current_plan"] = current_plan

        examples = [
            {
                "input": {"user_input": "整幅波浪吊目纹理"},
                "output": {
                    "schema_version": "pattern_plan/v1",
                    "canvas": {"width": 40, "height": 40},
                    "layout_type": "allover_repeat",
                    "motifs": [
                        {
                            "motif_id": "main",
                            "motif_type": "allover",
                            "effect": "wave_tuck",
                            "region": {"type": "full"},
                            "params": {"period_x": 5, "period_y": 4},
                            "role": "allover",
                            "symmetry": "none",
                            "allow_refinement": True,
                        }
                    ],
                },
            },
            {
                "input": {
                    "user_input": "波浪更大一点",
                    "current_plan": {
                        "schema_version": "pattern_plan/v1",
                        "canvas": {"width": 40, "height": 40},
                        "layout_type": "centered",
                        "motifs": [
                            {
                                "motif_id": "main",
                                "motif_type": "wave",
                                "effect": "wave_tuck",
                                "region": {"center": [20, 20], "size": 14},
                                "params": {"period_x": 5, "period_y": 4, "thickness": 2},
                                "role": "center",
                            }
                        ],
                    },
                },
                "output": {
                    "operation": "modify",
                    "target": "main",
                    "changes": {
                        "region": {"size": 17},
                        "params": {"thickness": 3},
                    },
                },
            },
            {
                "input": {
                    "user_input": "中间加一点镂空",
                    "current_plan": {
                        "schema_version": "pattern_plan/v1",
                        "canvas": {"width": 40, "height": 40},
                        "layout_type": "centered",
                        "motifs": [
                            {
                                "motif_id": "main",
                                "motif_type": "wave",
                                "effect": "wave_tuck",
                                "region": {"center": [20, 20], "size": 16},
                                "params": {"period_x": 5, "period_y": 4},
                                "role": "center",
                            }
                        ],
                    },
                },
                "output": {
                    "operation": "add",
                    "motif": {
                        "motif_id": "eyelet_1",
                        "motif_type": "mesh",
                        "effect": "lace",
                        "region": {"center": [20, 20], "size": 14},
                        "params": {"period_x": 4, "period_y": 4, "stagger": True},
                        "role": "center",
                    },
                },
            },
        ]

        messages = [{"role": "system", "content": PATTERN_PLAN_SYSTEM_PROMPT}]
        for ex in examples[: self.max_examples]:
            messages.append({"role": "user", "content": json.dumps(ex["input"], ensure_ascii=False, indent=2)})
            messages.append({"role": "assistant", "content": json.dumps(ex["output"], ensure_ascii=False, indent=2)})
        messages.append({"role": "user", "content": json.dumps(payload, ensure_ascii=False, indent=2)})
        return messages

    def build_repair_messages(
        self,
        user_input: str,
        violation_report: Dict,
        summary: Dict,
    ) -> List[Dict[str, str]]:
        payload = {
            "user_input": user_input,
            "violation_report": violation_report,
            "summary": summary,
        }
        return [
            {"role": "system", "content": REPAIR_SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False, indent=2)}
        ]

    def _select_examples(self, user_input: str) -> List[Dict]:
        text = user_input.lower()
        selected = []

        # 优先匹配多区域+中间布局
        if any(k in user_input for k in ["两个", "两侧", "柱子", "边带"]) and any(k in user_input for k in ["中间", "中心"]):
            selected.append(FEW_SHOT_DESIGN_EXAMPLES[4])  # "两个柱子，柱子中间波浪"

        if any(k in user_input for k in ["麻花", "绞花", "交叉"]) or "cable" in text:
            selected.append(FEW_SHOT_DESIGN_EXAMPLES[1])
        elif any(k in user_input for k in ["菱形", "菱", "diamond", "rhombus"]):
            selected.append(FEW_SHOT_DESIGN_EXAMPLES[0])
        if any(k in user_input for k in ["波浪", "吊目", "集圈"]) or "wave" in text or "tuck" in text:
            selected.append(FEW_SHOT_DESIGN_EXAMPLES[2])
        if any(k in user_input for k in ["边带", "罗纹", "蜂巢", "两侧"]) or "rib" in text or "band" in text:
            selected.append(FEW_SHOT_DESIGN_EXAMPLES[3])
        if any(k in user_input for k in ["网眼", "镂空", "边框"]) or "lace" in text or "frame" in text:
            selected.append(FEW_SHOT_DESIGN_EXAMPLES[5])
        if any(k in user_input for k in ["条纹", "横向", "水平"]) or "stripe" in text:
            selected.append(FEW_SHOT_DESIGN_EXAMPLES[6])  # "整幅横向条纹"
        if any(k in user_input for k in ["柱", "纵向", "竖向", "竖"]) or "column" in text:
            selected.append(FEW_SHOT_DESIGN_EXAMPLES[7])  # "整幅纵向柱状纹理"

        if not selected:
            selected = FEW_SHOT_DESIGN_EXAMPLES[:2]

        deduped = []
        for ex in selected:
            if ex not in deduped:
                deduped.append(ex)
        return deduped[:self.max_examples]
