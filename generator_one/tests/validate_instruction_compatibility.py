"""
验证指令兼容性矩阵（一次性验证）
"""
import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
from online_generation.instruction.instruction_rules import (
    INSTRUCTION_COMPATIBILITY_MATRIX,
    CORE_INSTRUCTION_IDS,
    get_instruction_compatibility
)
from utils.logger import logger


def validate_matrix_symmetry():
    """验证矩阵对称性"""
    logger.info("验证矩阵对称性...")
    
    errors = []
    for i in range(len(CORE_INSTRUCTION_IDS)):
        for j in range(len(CORE_INSTRUCTION_IDS)):
            val_ij = INSTRUCTION_COMPATIBILITY_MATRIX[i, j]
            val_ji = INSTRUCTION_COMPATIBILITY_MATRIX[j, i]
            
            if val_ij != val_ji:
                inst_i = CORE_INSTRUCTION_IDS[i]
                inst_j = CORE_INSTRUCTION_IDS[j]
                errors.append(
                    f"不对称: ID{inst_i}→ID{inst_j}={val_ij}, "
                    f"ID{inst_j}→ID{inst_i}={val_ji}"
                )
    
    if errors:
        for error in errors:
            logger.error(f"  ❌ {error}")
        return False
    
    logger.info("  ✅ 矩阵对称性验证通过")
    return True


def validate_background_compatibility():
    """验证背景(ID=0)与所有指令兼容"""
    logger.info("验证背景兼容性...")
    
    errors = []
    for inst_id in CORE_INSTRUCTION_IDS:
        compat = get_instruction_compatibility(249, inst_id)
        if compat != 1.0:
            errors.append(
                f"ID=0（背景）与ID={inst_id}兼容性应为1.0，实际{compat}"
            )
    
    if errors:
        for error in errors:
            logger.error(f"  ❌ {error}")
        return False
    
    logger.info("  ✅ 背景兼容性验证通过")
    return True


def validate_stockinette_compatibility():
    """验证平针(ID=1)与所有指令兼容（万能过渡）"""
    logger.info("验证平针兼容性...")
    
    errors = []
    for inst_id in CORE_INSTRUCTION_IDS:
        compat = get_instruction_compatibility(1, inst_id)
        if compat != 1.0:
            errors.append(
                f"ID=1（平针）与ID={inst_id}兼容性应为1.0，实际{compat}"
            )
    
    if errors:
        for error in errors:
            logger.error(f"  ❌ {error}")
        return False
    
    logger.info("  ✅ 平针兼容性验证通过")
    return True


def validate_forbidden_pairs():
    """验证已知的禁止对"""
    logger.info("验证禁止对...")
    
    forbidden_pairs = [
        (20, 4),   # 麻花 ↔ 镂空
        (20, 15),  # 麻花 ↔ 落布
        (21, 4),   # 左翻麻花 ↔ 镂空
        (31, 4),   # 右翻麻花 ↔ 镂空
        (20, 184), # 麻花 ↔ 假针
        (20, 188), # 麻花 ↔ 压针
        (4, 184),  # 镂空 ↔ 假针
        (15, 184), # 落布 ↔ 假针
    ]
    
    errors = []
    for inst_a, inst_b in forbidden_pairs:
        compat = get_instruction_compatibility(inst_a, inst_b)
        if compat != 0.0:
            errors.append(
                f"ID{inst_a}↔ID{inst_b}应禁止（0.0），实际{compat}"
            )
    
    if errors:
        for error in errors:
            logger.error(f"  ❌ {error}")
        return False
    
    logger.info("  ✅ 禁止对验证通过")
    return True


def validate_transition_pairs():
    """验证已知的需要过渡的对"""
    logger.info("验证过渡对...")
    
    transition_pairs = [
        (2, 20),  # 后床编织 ↔ 麻花（需要过渡）
        (6, 20),  # 罗纹 ↔ 麻花（需要过渡）
    ]
    
    errors = []
    for inst_a, inst_b in transition_pairs:
        compat = get_instruction_compatibility(inst_a, inst_b)
        if compat != 0.5:
            errors.append(
                f"ID{inst_a}↔ID{inst_b}应需要过渡（0.5），实际{compat}"
            )
    
    if errors:
        for error in errors:
            logger.error(f"  ❌ {error}")
        return False
    
    logger.info("  ✅ 过渡对验证通过")
    return True


def print_matrix_statistics():
    """打印矩阵统计"""
    logger.info("=" * 60)
    logger.info("兼容性矩阵统计")
    logger.info("=" * 60)
    
    total = INSTRUCTION_COMPATIBILITY_MATRIX.size
    compatible = np.sum(INSTRUCTION_COMPATIBILITY_MATRIX == 1.0)
    transition = np.sum(INSTRUCTION_COMPATIBILITY_MATRIX == 0.5)
    forbidden = np.sum(INSTRUCTION_COMPATIBILITY_MATRIX == 0.0)
    
    logger.info(f"总计: {total} 对")
    logger.info(f"兼容（1.0）: {compatible} ({compatible/total:.1%})")
    logger.info(f"需要过渡（0.5）: {transition} ({transition/total:.1%})")
    logger.info(f"禁止（0.0）: {forbidden} ({forbidden/total:.1%})")


def run_validation():
    """运行所有验证"""
    logger.info("=" * 60)
    logger.info("开始验证指令兼容性矩阵")
    logger.info("=" * 60)
    
    tests = [
        validate_matrix_symmetry,
        validate_background_compatibility,
        validate_stockinette_compatibility,
        validate_forbidden_pairs,
        validate_transition_pairs
    ]
    
    all_passed = True
    for test in tests:
        if not test():
            all_passed = False
    
    print_matrix_statistics()
    
    logger.info("=" * 60)
    if all_passed:
        logger.info("✅ 所有验证通过！兼容性矩阵正确")
    else:
        logger.error("❌ 验证失败，请检查兼容性矩阵")
    logger.info("=" * 60)
    
    return all_passed


if __name__ == "__main__":
    success = run_validation()
    sys.exit(0 if success else 1)