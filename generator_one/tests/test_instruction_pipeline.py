"""
测试指令生成管线
"""
import numpy as np
from pathlib import Path
import sys

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from online_generation.stitch_types import StitchType, get_stitch_name
from online_generation.instruction.instruction_rules import (
    map_stitch_to_instruction,
    validate_instruction_grid
)
from online_generation.instruction.instruction_mapper import InstructionMapper
from online_generation.pipeline import generate_pattern
from utils.logger import logger
from utils.file_io import save_image


def test_stitch_type_enum():
    """测试1：针法类型枚举"""
    logger.info("=" * 60)
    logger.info("测试1：针法类型枚举")
    logger.info("=" * 60)
    
    # 测试枚举值
    assert StitchType.BACKGROUND == 0
    assert StitchType.STOCKINETTE == 1
    assert StitchType.CABLE == 3
    
    # 测试名称获取
    assert get_stitch_name(StitchType.CABLE, "zh") == "麻花"
    assert get_stitch_name(StitchType.RIB, "en") == "rib"
    
    logger.info("✅ 针法类型枚举测试通过")
    return True


def test_instruction_mapping():
    """测试2：指令映射函数"""
    logger.info("=" * 60)
    logger.info("测试2：指令映射函数")
    logger.info("=" * 60)
    
    # 测试背景 → ID=3（四平编织）
    inst = map_stitch_to_instruction(StitchType.BACKGROUND, 0, 0)
    assert inst == 249, f"背景应该映射到ID=249，但得到{inst}"
    logger.info("  ✓ 背景映射正确（四平编织）")
    
    # 测试平针 → ID=1
    inst = map_stitch_to_instruction(StitchType.STOCKINETTE, 0, 0)
    assert inst == 1, f"平针应该映射到ID=1，但得到{inst}"
    logger.info("  ✓ 平针映射正确")
    
    # 测试罗纹 → ID=6（单一指令，不交替）
    inst_0 = map_stitch_to_instruction(StitchType.RIB, 0, 0)
    inst_1 = map_stitch_to_instruction(StitchType.RIB, 0, 1)
    assert inst_0 == 6, f"罗纹应该是ID=6，但得到{inst_0}"
    assert inst_1 == 6, f"罗纹应该是ID=6，但得到{inst_1}"
    logger.info("  ✓ 罗纹映射正确（单一指令）")
    
    # 测试麻花 → 根据行周期
    inst_normal = map_stitch_to_instruction(StitchType.CABLE, 0, 0)
    inst_twist = map_stitch_to_instruction(StitchType.CABLE, 3, 0)
    assert inst_normal == 1, f"麻花普通行应该是ID=1，但得到{inst_normal}"
    assert inst_twist == 20, f"麻花翻针行应该是ID=20，但得到{inst_twist}"
    logger.info("  ✓ 麻花周期映射正确")
    
    # 测试镂空 → 棋盘格
    inst_00 = map_stitch_to_instruction(StitchType.LACE, 0, 0)
    inst_01 = map_stitch_to_instruction(StitchType.LACE, 0, 1)
    assert inst_00 == 1, f"镂空(0,0)应该是ID=1"
    assert inst_01 == 4, f"镂空(0,1)应该是ID=4"
    logger.info("  ✓ 镂空棋盘格映射正确")
    
    # 测试边缘 → ID=6
    inst = map_stitch_to_instruction(StitchType.EDGE, 0, 0)
    assert inst == 6, f"边缘应该是ID=6，但得到{inst}"
    logger.info("  ✓ 边缘映射正确")
    
    logger.info("✅ 指令映射测试通过")
    return True


def test_instruction_mapper():
    """测试3：指令映射器（40×40→40×40）"""
    logger.info("=" * 60)
    logger.info("测试3：指令映射器")
    logger.info("=" * 60)
    
    # 创建测试数据：40×40针法类型网格
    stitch_grid = np.zeros((40, 40), dtype=np.uint8)
    
    # 背景（默认值0=BACKGROUND）
    # 中心区域放麻花
    stitch_grid[15:25, 15:25] = StitchType.CABLE
    
    # 周围放罗纹
    stitch_grid[14, 14:26] = StitchType.RIB
    stitch_grid[25, 14:26] = StitchType.RIB
    stitch_grid[14:26, 14] = StitchType.RIB
    stitch_grid[14:26, 25] = StitchType.RIB
    
    # 映射到指令
    mapper = InstructionMapper()
    instruction_grid = mapper.map(stitch_grid)
    
    # 验证形状
    assert instruction_grid.shape == (40, 40), f"输出应该是40×40，但得到{instruction_grid.shape}"
    logger.info("  ✓ 输出形状正确")
    
    # 验证背景是脱羧四平编织(ID=249)
    assert instruction_grid[0, 0] == 249, f"背景应该是ID=249，但得到{instruction_grid[0, 0]}"
    logger.info("  ✓ 背景映射正确（脱羧四平编织）")
    
    # 验证麻花区域有翻针行(ID=20)
    cable_region = instruction_grid[15:25, 20]
    has_twist = np.any(cable_region == 20)
    assert has_twist, "麻花区域应该包含翻针指令(ID=20)"
    logger.info("  ✓ 麻花区域包含翻针行")
    
    # 验证罗纹边框是单一指令(ID=6)
    rib_row = instruction_grid[14, 14:26]
    all_rib = np.all(rib_row == 6)
    assert all_rib, f"罗纹边框应该全是ID=6，但得到{np.unique(rib_row)}"
    logger.info("  ✓ 罗纹边框连贯正确")
    
    # 验证兼容性
    is_valid, violations = validate_instruction_grid(instruction_grid)
    logger.info(f"  兼容性检查: {len(violations)} 个违规")
    
    logger.info("✅ 指令映射器测试通过")
    return True


def test_upscale():
    """测试4：放大到80×80"""
    logger.info("=" * 60)
    logger.info("测试4：放大到80×80")
    logger.info("=" * 60)
    
    # 创建简单的40×40网格
    grid_40x40 = np.array([
        [1, 2],
        [20, 4]
    ])
    
    # 放大40倍（变成80×80）
    grid_80x80 = InstructionMapper.upscale_for_display(grid_40x40, scale=40)
    
    # 验证
    assert grid_80x80.shape == (80, 80), f"应该是80×80，但得到{grid_80x80.shape}"
    assert grid_80x80[0, 0] == 1, "放大后(0,0)应该是1"
    assert grid_80x80[39, 39] == 1, "放大后(39,39)应该还是1（同一块）"
    assert grid_80x80[40, 0] == 20, "放大后(40,0)应该是20"
    assert grid_80x80[79, 79] == 4, "放大后(79,79)应该是4"
    
    logger.info("  ✓ 放大逻辑正确")
    logger.info("  ✓ 内容保持不变（只是视觉放大）")
    logger.info("✅ 放大测试通过")
    return True


def test_end_to_end():
    """测试5：端到端管线"""
    logger.info("=" * 60)
    logger.info("测试5：端到端管线")
    logger.info("=" * 60)
    
    # 生成图案
    result = generate_pattern(
        user_input="中心麻花菱形，周围罗纹边框"
    )
    
    # 验证输出
    assert result.instruction_grid_40x40 is not None, "应该有40×40指令网格"
    assert result.instruction_grid_40x40.shape == (40, 40), "40×40形状错误"
    logger.info("  ✓ 40×40指令网格正确")
    
    assert result.instruction_grid_display is not None, "应该有80×80显示网格"
    assert result.instruction_grid_display.shape == (80, 80), "80×80形状错误"
    logger.info("  ✓ 80×80显示网格正确")
    
    assert result.rgb_image is not None, "应该有RGB图像"
    assert result.rgb_image.shape == (80, 80, 3), "RGB形状错误"
    logger.info("  ✓ RGB图像正确")
    
    # 检查统计信息
    assert "instruction_mapping" in result.statistics, "应该有指令映射统计"
    logger.info("  ✓ 统计信息完整")
    
    # 保存测试输出
    output_path = Path("outputs/test_instruction_pipeline.png")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    save_image(result.rgb_image, output_path)
    logger.info(f"  ✓ 保存测试图像到: {output_path}")
    
    logger.info("✅ 端到端测试通过")
    return True


def run_all_tests():
    """运行所有测试"""
    tests = [
        ("针法类型枚举", test_stitch_type_enum),
        ("指令映射函数", test_instruction_mapping),
        ("指令映射器", test_instruction_mapper),
        ("放大功能", test_upscale),
        ("端到端管线", test_end_to_end)
    ]
    
    passed = 0
    failed = 0
    failed_tests = []
    
    for test_name, test_func in tests:
        try:
            if test_func():
                passed += 1
        except AssertionError as e:
            logger.error(f"❌ 测试失败: {test_name}")
            logger.error(f"   错误: {e}")
            failed += 1
            failed_tests.append(test_name)
        except Exception as e:
            logger.error(f"❌ 测试异常: {test_name}")
            logger.error(f"   异常: {e}")
            failed += 1
            failed_tests.append(test_name)
    
    logger.info("=" * 60)
    logger.info(f"测试完成: {passed} 通过, {failed} 失败")
    if failed_tests:
        logger.error(f"失败的测试: {', '.join(failed_tests)}")
    logger.info("=" * 60)
    
    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)