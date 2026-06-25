#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据集分析脚本 - 统计针织色码图的真实分布和相邻关系

功能：
1. 指令频率统计：统计数据集中所有指令ID的出现频率
2. 指令相邻关系：统计哪些指令ID经常相邻出现（水平和垂直）
3. 行级模式分析：提取样本的首行、末行、中间行模式
4. 未识别色块统计：找出数据集中存在但映射文件中没有的颜色

注意：
- 输入图片是 80×80，每个色块是 2×2
- 实际指令矩阵是 40×40
- RGB 通过 instruction_info.json 查询对应的指令ID和名称
"""

import os
import sys
import json
import argparse
import random
from pathlib import Path
from collections import Counter, defaultdict
from typing import Dict, Tuple, List, Optional

import numpy as np
from PIL import Image

from config import INSTRUCTION_INFO_PATH


class InstructionMapper:
    """RGB到指令ID的映射器"""
    
    def __init__(self, mapping_file: str):
        """
        初始化映射器
        
        Args:
            mapping_file: 指令映射JSON文件路径 (instruction_info.json)
        """
        self.rgb_to_id: Dict[Tuple[int, int, int], int] = {}
        self.id_to_name: Dict[int, str] = {}
        self.id_to_rgb: Dict[int, Tuple[int, int, int]] = {}
        self.id_to_hex: Dict[int, str] = {}
        
        self._load_mapping(mapping_file)
    
    def _hex_to_rgb(self, hex_color: str) -> Tuple[int, int, int]:
        """将十六进制颜色转换为RGB元组"""
        hex_color = hex_color.lstrip('#')
        return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
    
    def _load_mapping(self, mapping_file: str):
        """加载映射文件"""
        with open(mapping_file, 'r', encoding='utf-8') as f:
            data = json.load(f)

        core_instructions = data.get('core_instructions', [])
        if not core_instructions:
            raise ValueError(f"{mapping_file} 中未找到 core_instructions")

        for info in core_instructions:
            instr_id = info['id']
            hex_color = info['color']
            rgb = self._hex_to_rgb(hex_color)
            name = info.get('name_zh') or info.get('name_en') or f"未知指令({instr_id})"

            self.rgb_to_id[rgb] = instr_id
            self.id_to_name[instr_id] = name
            self.id_to_rgb[instr_id] = rgb
            self.id_to_hex[instr_id] = hex_color

        print(f"✓ 已加载 {len(self.rgb_to_id)} 个指令映射 (来自 instruction_info.json)")
    
    def get_instruction_id(self, rgb: Tuple[int, int, int]) -> int:
        """根据RGB获取指令ID，找不到返回 -1"""
        return self.rgb_to_id.get(rgb, -1)
    
    def get_instruction_name(self, instr_id: int) -> str:
        """根据指令ID获取名称"""
        return self.id_to_name.get(instr_id, f"未知指令({instr_id})")
    
    def get_instruction_hex(self, instr_id: int) -> str:
        """根据指令ID获取十六进制颜色"""
        return self.id_to_hex.get(instr_id, "#UNKNOWN")


class DatasetAnalyzer:
    """数据集分析器"""
    
    def __init__(self, mapper: InstructionMapper):
        self.mapper = mapper
        
        # 统计数据
        self.instruction_counter = Counter()       # 指令频率
        self.horizontal_adjacency = Counter()      # 水平相邻 (左, 右)
        self.vertical_adjacency = Counter()        # 垂直相邻 (上, 下)
        self.row_patterns: List[dict] = []         # 行级模式样本
        
        # 元数据
        self.total_pixels = 0
        self.total_images = 0
        self.processed_images = 0
        self.unknown_colors: Counter = Counter()   # 未识别的颜色
        self.category_stats: Dict[str, int] = defaultdict(int)  # 每个类别的图片数
    
    def _image_to_instruction_matrix(self, img_path: str) -> Optional[np.ndarray]:
        """
        将80×80图片转换为40×40指令矩阵
        
        Args:
            img_path: 图片路径
            
        Returns:
            40×40 的指令ID矩阵，失败返回 None
        """
        try:
            img = Image.open(img_path).convert('RGB')
            img_array = np.array(img)
            
            H, W = img_array.shape[:2]
            
            # 计算实际的指令矩阵尺寸（假设每个色块是2×2）
            matrix_h = H // 2
            matrix_w = W // 2
            
            if H < 2 or W < 2:
                print(f"  ⚠️ 图片太小，跳过: {img_path}")
                return None
            
            instruction_matrix = np.zeros((matrix_h, matrix_w), dtype=np.int32)
            
            for r in range(matrix_h):
                for c in range(matrix_w):
                    # 取 2×2 块的左上角像素
                    rgb = tuple(img_array[r * 2, c * 2])
                    instr_id = self.mapper.get_instruction_id(rgb)
                    
                    if instr_id == -1:
                        self.unknown_colors[rgb] += 1
                    
                    instruction_matrix[r, c] = instr_id
            
            return instruction_matrix
            
        except Exception as e:
            print(f"  ❌ 处理图片失败: {img_path}, 错误: {e}")
            return None
    
    def _analyze_frequency(self, matrix: np.ndarray):
        """分析指令频率"""
        for instr_id in matrix.flatten():
            if instr_id != -1:
                self.instruction_counter[instr_id] += 1
                self.total_pixels += 1
    
    def _analyze_adjacency(self, matrix: np.ndarray):
        """分析指令相邻关系"""
        H, W = matrix.shape
        
        # 水平相邻 (同一行，左右相邻)
        for r in range(H):
            for c in range(W - 1):
                id_left = matrix[r, c]
                id_right = matrix[r, c + 1]
                if id_left != -1 and id_right != -1:
                    self.horizontal_adjacency[(id_left, id_right)] += 1
        
        # 垂直相邻 (同一列，上下相邻)
        for r in range(H - 1):
            for c in range(W):
                id_top = matrix[r, c]
                id_bottom = matrix[r + 1, c]
                if id_top != -1 and id_bottom != -1:
                    self.vertical_adjacency[(id_top, id_bottom)] += 1
    
    def _extract_row_pattern(self, matrix: np.ndarray, img_path: str):
        """提取行级模式"""
        H, W = matrix.shape
        
        pattern = {
            'file': os.path.basename(img_path),
            'category': os.path.basename(os.path.dirname(img_path)),
            'size': f"{H}×{W}",
            'row_0': matrix[0, :].tolist(),
            'row_last': matrix[-1, :].tolist(),
        }
        
        if H > 10:
            pattern['row_10'] = matrix[9, :].tolist()
        if H > 20:
            pattern['row_20'] = matrix[19, :].tolist()
        
        self.row_patterns.append(pattern)
    
    def analyze_image(self, img_path: str, category: str, extract_row_pattern: bool = False):
        """分析单张图片"""
        matrix = self._image_to_instruction_matrix(img_path)
        if matrix is None:
            return
        
        self.processed_images += 1
        self.category_stats[category] += 1
        self._analyze_frequency(matrix)
        self._analyze_adjacency(matrix)
        
        if extract_row_pattern:
            self._extract_row_pattern(matrix, img_path)
    
    def analyze_dataset(self, dataset_root: str, row_pattern_samples: int = 10):
        """分析整个数据集"""
        print(f"\n{'='*70}")
        print(f"开始分析数据集: {dataset_root}")
        print(f"{'='*70}\n")
        
        # 收集所有图片路径
        all_images = []
        for category_folder in os.listdir(dataset_root):
            folder_path = os.path.join(dataset_root, category_folder)
            if not os.path.isdir(folder_path):
                continue
            
            for img_file in os.listdir(folder_path):
                if img_file.lower().endswith(('.png', '.jpg', '.jpeg', '.bmp')):
                    all_images.append({
                        'path': os.path.join(folder_path, img_file),
                        'category': category_folder
                    })
        
        self.total_images = len(all_images)
        print(f"找到 {self.total_images} 张图片")
        
        if self.total_images == 0:
            print("❌ 没有找到任何图片！请检查数据集路径。")
            return
        
        # 随机选择用于行级模式分析的样本
        row_pattern_indices = set()
        if row_pattern_samples > 0:
            indices = list(range(len(all_images)))
            random.shuffle(indices)
            row_pattern_indices = set(indices[:row_pattern_samples])
        
        # 分析每张图片
        for i, img_info in enumerate(all_images):
            if (i + 1) % 100 == 0 or i == self.total_images - 1:
                print(f"  处理进度: {i + 1}/{self.total_images}")
            
            extract_row = i in row_pattern_indices
            self.analyze_image(img_info['path'], img_info['category'], extract_row_pattern=extract_row)
        
        print(f"\n✓ 分析完成！成功处理 {self.processed_images}/{self.total_images} 张图片")
    
    def print_frequency_report(self, top_n: int = 50):
        """打印指令频率报告"""
        print(f"\n{'='*70}")
        print("📊 指令频率统计报告")
        print(f"{'='*70}")
        print(f"总像素数: {self.total_pixels:,}")
        print(f"数据集中出现的不同指令数: {len(self.instruction_counter)}")
        print(f"映射文件中的总指令数: {len(self.mapper.id_to_name)}")
        
        print(f"\n{'ID':>5} | {'颜色':>9} | {'出现次数':>12} | {'占比':>8} | 名称")
        print("-" * 85)
        
        for instr_id, count in self.instruction_counter.most_common(top_n):
            percentage = count / self.total_pixels * 100
            name = self.mapper.get_instruction_name(instr_id)
            hex_color = self.mapper.get_instruction_hex(instr_id)
            # 截断过长的名称
            if len(name) > 35:
                name = name[:32] + "..."
            print(f"{instr_id:>5} | {hex_color:>9} | {count:>12,} | {percentage:>7.2f}% | {name}")
        
        if len(self.instruction_counter) > top_n:
            print(f"\n... 还有 {len(self.instruction_counter) - top_n} 个指令未显示")
        
        # 高频指令列表
        high_freq_ids = [id_ for id_, count in self.instruction_counter.items() 
                        if count / self.total_pixels > 0.01]
        print(f"\n高频指令（占比 > 1%）: {sorted(high_freq_ids)}")
        print(f"高频指令数量: {len(high_freq_ids)}")
        
        # 低频指令
        low_freq_ids = [id_ for id_, count in self.instruction_counter.items() 
                       if count / self.total_pixels < 0.001]
        print(f"\n低频指令（占比 < 0.1%）数量: {len(low_freq_ids)}")
        if low_freq_ids:
            print(f"低频指令ID: {sorted(low_freq_ids)}")
    
    def print_adjacency_report(self, top_n: int = 50):
        """打印相邻关系报告"""
        print(f"\n{'='*70}")
        print("🔗 指令相邻关系统计报告")
        print(f"{'='*70}")
        
        total_h_pairs = sum(self.horizontal_adjacency.values())
        total_v_pairs = sum(self.vertical_adjacency.values())
        unique_h_pairs = len(self.horizontal_adjacency)
        unique_v_pairs = len(self.vertical_adjacency)
        
        print(f"水平相邻: {total_h_pairs:,} 次 ({unique_h_pairs} 种组合)")
        print(f"垂直相邻: {total_v_pairs:,} 次 ({unique_v_pairs} 种组合)")
        
        # 水平相邻
        print(f"\n【水平相邻 TOP {top_n}】(同一行，左→右)")
        print(f"{'左ID':>5} → {'右ID':>5} | {'次数':>10} | {'占比':>7} | 组合说明")
        print("-" * 90)
        for (id_left, id_right), count in self.horizontal_adjacency.most_common(top_n):
            percentage = count / total_h_pairs * 100 if total_h_pairs > 0 else 0
            name_left = self.mapper.get_instruction_name(id_left)[:12]
            name_right = self.mapper.get_instruction_name(id_right)[:12]
            print(f"{id_left:>5} → {id_right:>5} | {count:>10,} | {percentage:>6.2f}% | {name_left} → {name_right}")
        
        # 垂直相邻
        print(f"\n【垂直相邻 TOP {top_n}】(同一列，上→下)")
        print(f"{'上ID':>5} → {'下ID':>5} | {'次数':>10} | {'占比':>7} | 组合说明")
        print("-" * 90)
        for (id_top, id_bottom), count in self.vertical_adjacency.most_common(top_n):
            percentage = count / total_v_pairs * 100 if total_v_pairs > 0 else 0
            name_top = self.mapper.get_instruction_name(id_top)[:12]
            name_bottom = self.mapper.get_instruction_name(id_bottom)[:12]
            print(f"{id_top:>5} → {id_bottom:>5} | {count:>10,} | {percentage:>6.2f}% | {name_top} → {name_bottom}")
    
    def print_unknown_colors_report(self):
        """打印未识别颜色报告"""
        if not self.unknown_colors:
            print(f"\n{'='*70}")
            print("✓ 所有颜色都已成功识别，没有未知颜色")
            return
        
        print(f"\n{'='*70}")
        print("⚠️ 未识别颜色报告")
        print(f"{'='*70}")
        print(f"共有 {len(self.unknown_colors)} 种颜色在映射文件中找不到")
        print(f"未识别像素总数: {sum(self.unknown_colors.values()):,}")
        
        print(f"\n{'RGB':>20} | {'HEX':>9} | {'出现次数':>10}")
        print("-" * 50)
        for rgb, count in self.unknown_colors.most_common(30):
            hex_color = '#{:02X}{:02X}{:02X}'.format(*rgb)
            print(f"{str(rgb):>20} | {hex_color:>9} | {count:>10,}")
    
    def print_category_report(self):
        """打印类别统计报告"""
        print(f"\n{'='*70}")
        print("📁 数据集类别统计")
        print(f"{'='*70}")
        print(f"{'类别名称':<30} | {'图片数量':>10}")
        print("-" * 45)
        for category, count in sorted(self.category_stats.items(), key=lambda x: -x[1]):
            print(f"{category:<30} | {count:>10}")
    
    def print_row_pattern_report(self):
        """打印行级模式报告"""
        if not self.row_patterns:
            return
        
        print(f"\n{'='*70}")
        print("📝 行级模式样本报告")
        print(f"{'='*70}")
        
        for i, pattern in enumerate(self.row_patterns):
            print(f"\n【样本 {i+1}】{pattern['file']}")
            print(f"  类别: {pattern['category']}, 尺寸: {pattern['size']}")
            print(f"  第 1 行: {self._format_row(pattern['row_0'])}")
            print(f"  最后行: {self._format_row(pattern['row_last'])}")
            
            if 'row_10' in pattern:
                print(f"  第10行: {self._format_row(pattern['row_10'])}")
            if 'row_20' in pattern:
                print(f"  第20行: {self._format_row(pattern['row_20'])}")
    
    def _format_row(self, row: List[int], max_display: int = 25) -> str:
        """格式化行数据显示"""
        if len(row) <= max_display:
            return str(row)
        else:
            half = max_display // 2
            return f"[{', '.join(map(str, row[:half]))}, ..., {', '.join(map(str, row[-half:]))}]"
    
    def generate_compatibility_matrix(self) -> Dict:
        """基于数据集统计生成兼容性矩阵建议"""
        print(f"\n{'='*70}")
        print("🔧 基于数据统计的兼容性矩阵建议")
        print(f"{'='*70}")
        
        # 获取所有出现过的指令ID
        all_ids = sorted(self.instruction_counter.keys())
        print(f"数据集中共出现 {len(all_ids)} 种指令")
        
        # 合并水平和垂直相邻关系
        combined_adjacency = Counter()
        for pair, count in self.horizontal_adjacency.items():
            combined_adjacency[pair] += count
        for pair, count in self.vertical_adjacency.items():
            combined_adjacency[pair] += count
        
        # 找出从未相邻的指令对（可能是禁止组合）
        never_adjacent = []
        for id_a in all_ids:
            for id_b in all_ids:
                if combined_adjacency.get((id_a, id_b), 0) == 0:
                    if id_a != id_b:  # 排除自己和自己
                        never_adjacent.append((id_a, id_b))
        
        print(f"\n从未相邻出现的指令对数量: {len(never_adjacent)}")
        if never_adjacent and len(never_adjacent) <= 100:
            print("这些组合可能是物理禁止的:")
            for id_a, id_b in never_adjacent[:50]:
                name_a = self.mapper.get_instruction_name(id_a)[:15]
                name_b = self.mapper.get_instruction_name(id_b)[:15]
                print(f"  ({id_a}, {id_b}): {name_a} ↔ {name_b}")
        
        return {
            'all_ids': all_ids,
            'combined_adjacency': dict(combined_adjacency),
            'never_adjacent': never_adjacent
        }
    
    def save_report(self, output_file: str):
        """保存完整报告到文件"""
        import io
        
        # 确保输出目录存在
        output_dir = os.path.dirname(output_file)
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir)
            print(f"✓ 已创建输出目录: {output_dir}")
        
        # 捕获所有打印输出
        old_stdout = sys.stdout
        sys.stdout = buffer = io.StringIO()
        
        self.print_frequency_report(top_n=100)
        self.print_adjacency_report(top_n=100)
        self.print_unknown_colors_report()
        self.print_category_report()
        self.print_row_pattern_report()
        self.generate_compatibility_matrix()
        
        report_content = buffer.getvalue()
        sys.stdout = old_stdout
        
        # 保存到文件
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(report_content)
        
        print(f"\n✓ 完整报告已保存到: {output_file}")
        
        # 同时在控制台显示
        print(report_content)
    
    def save_statistics_json(self, output_file: str):
        """将统计数据保存为JSON格式"""
        
        # 确保输出目录存在
        output_dir = os.path.dirname(output_file)
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir)
        
        def to_native(obj):
            """递归转换 numpy 类型为 Python 原生类型"""
            if isinstance(obj, (np.integer, np.int32, np.int64)):
                return int(obj)
            elif isinstance(obj, (np.uint8, np.uint16, np.uint32, np.uint64)):
                return int(obj)
            elif isinstance(obj, (np.floating, np.float32, np.float64)):
                return float(obj)
            elif isinstance(obj, np.ndarray):
                return [to_native(x) for x in obj.tolist()]
            elif isinstance(obj, dict):
                return {to_native(k): to_native(v) for k, v in obj.items()}
            elif isinstance(obj, (list, tuple)):
                return [to_native(item) for item in obj]
            else:
                return obj
        
        # 生成高频指令列表（占比 > 1%）
        high_freq_instructions = []
        for id_, count in self.instruction_counter.most_common():
            if self.total_pixels > 0 and count / self.total_pixels > 0.01:
                high_freq_instructions.append({
                    "id": int(id_),
                    "count": int(count),
                    "percentage": round(count / self.total_pixels * 100, 4),
                    "name": self.mapper.get_instruction_name(id_),
                    "hex_color": self.mapper.get_instruction_hex(id_)
                })
        
        # 处理 unknown_colors - 显式转换 RGB 值
        unknown_colors_list = []
        for rgb, count in self.unknown_colors.most_common():
            rgb_list = [int(x) for x in rgb]  # 显式转换 uint8 -> int
            unknown_colors_list.append({
                "rgb": rgb_list,
                "hex": '#{:02X}{:02X}{:02X}'.format(rgb_list[0], rgb_list[1], rgb_list[2]),
                "count": int(count)
            })
        
        # 处理 instruction_frequency
        instruction_frequency_list = []
        for id_, count in self.instruction_counter.most_common():
            percentage = round(count / self.total_pixels * 100, 4) if self.total_pixels > 0 else 0
            instruction_frequency_list.append({
                "id": int(id_),
                "count": int(count),
                "percentage": percentage,
                "name": self.mapper.get_instruction_name(id_),
                "hex_color": self.mapper.get_instruction_hex(id_)
            })
        
        # 处理 horizontal_adjacency
        horizontal_adjacency_list = []
        for (id_left, id_right), count in self.horizontal_adjacency.most_common(200):
            horizontal_adjacency_list.append({
                "left_id": int(id_left),
                "right_id": int(id_right),
                "count": int(count),
                "left_name": self.mapper.get_instruction_name(id_left),
                "right_name": self.mapper.get_instruction_name(id_right)
            })
        
        # 处理 vertical_adjacency
        vertical_adjacency_list = []
        for (id_top, id_bottom), count in self.vertical_adjacency.most_common(200):
            vertical_adjacency_list.append({
                "top_id": int(id_top),
                "bottom_id": int(id_bottom),
                "count": int(count),
                "top_name": self.mapper.get_instruction_name(id_top),
                "bottom_name": self.mapper.get_instruction_name(id_bottom)
            })
        
        # 处理 row_pattern_samples
        row_patterns_clean = []
        for pattern in self.row_patterns:
            clean_pattern = {}
            for key, value in pattern.items():
                if isinstance(value, list):
                    clean_pattern[key] = [int(x) if isinstance(x, (np.integer, np.uint8)) else x for x in value]
                else:
                    clean_pattern[key] = value
            row_patterns_clean.append(clean_pattern)
        
        stats = {
            "metadata": {
                "total_images": int(self.total_images),
                "processed_images": int(self.processed_images),
                "total_pixels": int(self.total_pixels),
                "unique_instructions_in_dataset": len(self.instruction_counter),
                "total_instructions_in_mapping": len(self.mapper.id_to_name)
            },
            "instruction_frequency": instruction_frequency_list,
            "high_frequency_instructions": high_freq_instructions,
            "horizontal_adjacency": horizontal_adjacency_list,
            "vertical_adjacency": vertical_adjacency_list,
            "unknown_colors": unknown_colors_list,
            "category_stats": {str(k): int(v) for k, v in self.category_stats.items()},
            "row_pattern_samples": row_patterns_clean
        }
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(stats, f, ensure_ascii=False, indent=2)
        
        print(f"✓ 统计数据JSON已保存到: {output_file}")


def main():
    parser = argparse.ArgumentParser(
        description="针织数据集分析脚本 - 统计指令频率、相邻关系",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例用法:
    python analyze_dataset.py -d ./data -m ./online_generation/instruction/instruction_info.json
    python analyze_dataset.py -d ./data -m ./online_generation/instruction/instruction_info.json -o ./output/report.txt --samples 20
        """
    )
    
    parser.add_argument('-d', '--dataset', type=str,
                        default='dataset/stitch code patterns',
                        help='数据集根目录路径')
    parser.add_argument('-m', '--mapping', type=str,
                        default=str(INSTRUCTION_INFO_PATH),
                        help='指令映射JSON文件路径 (instruction_info.json)')
    parser.add_argument('-o', '--output', type=str, default='outputs/dataset_analysis_report.txt',
                        help='输出报告文件路径')
    parser.add_argument('--json-output', type=str, default='outputs/dataset_statistics.json',
                        help='统计数据JSON输出路径')
    parser.add_argument('-s', '--samples', type=int, default=10,
                        help='行级模式分析的样本数量')
    
    args = parser.parse_args()
    
    # 验证路径
    if not os.path.isdir(args.dataset):
        print(f"❌ 数据集目录不存在: {args.dataset}")
        sys.exit(1)
    
    if not os.path.isfile(args.mapping):
        print(f"❌ 映射文件不存在: {args.mapping}")
        sys.exit(1)
    
    # 初始化并分析
    print("=" * 70)
    print("针织数据集分析工具 v2.0")
    print("=" * 70)
    
    mapper = InstructionMapper(args.mapping)
    analyzer = DatasetAnalyzer(mapper)
    
    analyzer.analyze_dataset(args.dataset, row_pattern_samples=args.samples)
    analyzer.save_report(args.output)
    analyzer.save_statistics_json(args.json_output)
    
    print("\n" + "=" * 70)
    print("✓ 分析完成！")
    print("=" * 70)


if __name__ == "__main__":
    main()