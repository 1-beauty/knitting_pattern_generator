# 针织图案生成项目

本项目包含两个阶段：

- 第一阶段 `generator_one/`：根据中文或英文文本生成 40x40 针织色码图。
- 第二阶段 `conditional-flow-matching-main/`：根据第一阶段色码图生成针织仿真效果图。
- 统一入口 `run_pipeline.py`：在项目根目录运行，可单独生成色码图、单独仿真，或端到端运行。

输出默认保存在：

```text
outputs/runs/<run-name>/
```

第一阶段主要输出：

```text
color_map/pattern_output.bmp
color_map/pattern_sim_input.png
color_map/pattern_pattern_plan.json
color_map/pattern_stats.json
```

第二阶段主要输出：

```text
simulation/id_matrix_preview.png
simulation/stage4_result.png
```

## 快速开始

只生成色码图：

```bash
python run_pipeline.py color "菱形内部波浪条纹" --run-name diamond_inner_wave
```

从已有色码图运行仿真：

```bash
python run_pipeline.py simulate --input outputs/runs/diamond_inner_wave/color_map/pattern_sim_input.png --stage 4 --device cuda --batch_size 100
```

端到端运行：

```bash
python run_pipeline.py all "带边框的中心菱形，内部为镂空网眼" --stage 4 --device cuda --batch_size 100 --run-name lace_diamond_full
```

单卡 DDP 训练 Stage 4：

```bash
CUDA_VISIBLE_DEVICES=0,1 torchrun --nproc_per_node=2 knitting/train.py --config configs/stage4.yaml
```

## 常见针织图案 Prompt

```text
菱形内部波浪条纹
大菱形内部细密波浪花纹
圆形内部镂空网眼结构
三角形内部蜂巢纹理
六边形内部浮雕纹理
中心麻花柱状纹理
两侧罗纹边带，中间波浪吊目纹理
带边框的镂空菱形
整幅细密网眼镂空结构
整幅波浪吊目纹理
中心大麻花，两侧小罗纹
菱形边框内部种子针纹理
心形内部镂空花纹
星形内部波浪纹理
人字形波浪条纹
锯齿形浮雕纹理
十字形镂空结构
多个菱形重复排列，内部网眼
满地图案，蜂巢集圈纹理
边框内嵌菱形，菱形内部波浪
```

## 复杂图案 Prompt

这些示例适合展示模型对复合结构、层级裁剪和多区域组合的表达能力。

```text
带矩形边框的中心菱形，菱形内部是波浪条纹，两侧为罗纹边带
大圆形内部镂空网眼，外圈菱形边框
中心六边形蜂巢纹理，周围搭配波浪吊目背景
左右对称双菱形，内部细密网眼，中间竖向麻花-------
中心大菱形内部波浪，下方加入小三角镂空装饰-------
两侧窄罗纹边带，中间是大号波浪吊目，波浪内部叠加少量镂空孔洞，外面加矩形边框
中心大菱形，菱形边缘是麻花轮廓，内部为稀疏镂空网眼，左右两侧有罗纹边带
带边框的圆形镂空结构，背景为平针，圆形内部加入细密波浪
六边形蜂巢中心图案，外围加入锯齿边框，两侧为竖向罗纹
双层菱形结构，外层反针边框，内层波浪吊目，背景加入稀疏网眼
```

## 随机生成 Prompt

根目录方式：

```bash
python run_pipeline.py color "随机生成一个针织图案" --run-name random_01 --save-intermediate
```

更多随机风格：

```text
随机生成一个带边框的针织图案
随机生成一个镂空波浪风格图案
随机生成一个适合毛衣前片的中心纹理
随机生成一个左右对称的针织组织
随机生成一个包含罗纹和波浪的复合图案
```

也可以直接使用第一阶段入口：

```bash
cd generator_one
python main.py random "镂空波浪风格，带轻微边框" --output outputs/images --prefix random_lace_wave
```

## 基于历史结果继续修改

第一阶段会保存可编辑的 `pattern_pattern_plan.json`。后续可以用 `--plan-in` 读取上一次结果，只修改局部意图。

示例：

```bash
python run_pipeline.py color "菱形内部波浪条纹" --run-name edit_base --save-intermediate
```

然后基于上一次继续修改：

```bash
python run_pipeline.py color "让波浪更明显一点" --plan-in outputs/runs/edit_base/color_map/pattern_pattern_plan.json --run-name edit_wave_stronger
```

```bash
python run_pipeline.py color "把图案放大一点，并加入镂空网眼" --plan-in outputs/runs/edit_base/color_map/pattern_pattern_plan.json --run-name edit_add_lace
```

```bash
python run_pipeline.py color "整体更细密一点，向上移动" --plan-in outputs/runs/edit_base/color_map/pattern_pattern_plan.json --run-name edit_dense_up
```

```bash
python run_pipeline.py color "边框稍微加粗，内部纹理保持不变" --plan-in outputs/runs/edit_base/color_map/pattern_pattern_plan.json --run-name edit_thicker_border
```

```bash
python run_pipeline.py color "删除镂空，只保留波浪纹理" --plan-in outputs/runs/edit_add_lace/color_map/pattern_pattern_plan.json --run-name edit_remove_lace
```

## 调试建议

如果怀疑第一阶段层级裁剪有问题，查看：

```text
color_map/pattern_stats.json
```

重点字段：

```json
"layer_clip_audit": {
  "texture_actions_outside_child_layers": 0
}
```

如果这个值为 `0`，说明第一阶段色码层面的子层纹理没有越界；若仿真图仍有轻微扩散，通常是第二阶段模型视觉生成造成的，需要继续训练 Stage 4。

如果输出接近纯背景，优先查看：

```json
"distribution"
```

正常的纹理图案不应只有 `f_knit`。镂空、波浪、蜂巢、浮雕等应包含 transfer、tuck、split 或 miss 等结构动作。

## 说明

`conditional-flow-matching-main/assets/instructions.json` 和 `generator_one/data/instruction_info.json` 的动作顺序不能随意改变，因为 Stage II checkpoint 学到的是固定动作编号。当前优化只调整语义说明和物理参数，不改变颜色和类别顺序。

针织动作参数采用整数等级和保守工艺假设：基础 knit 提供稳定线圈支撑；tuck 增加蓄纱、凸起和弹性但稳定性较低；miss/float 不形成新线圈，不能单独代表镂空孔；transfer 用于移圈、镂空和形变结构。这些设定与针织结构中“线圈支撑、移圈成孔、集圈成纹理”的通用工艺认知一致，但属于项目内工程分级，不等同于论文或机器实测张力值，后续应结合工厂样片校准。
