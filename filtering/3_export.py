#!/usr/bin/env python3
"""
复制通过 LLM 筛选的文件（result=true）到 final 目录，同时简化 JSON 格式。

输出格式:
{
  "initial_output": "...",
  "turns": [
    {"action": "git clone ...", "observation": "..."}
  ]
}

用法:
    python filtering/copy_filtered.py
    
    可选参数:
    --input, -i: LLM 结果文件路径 (默认: data/filtered/llm_results_gemini_full.json)
    --source, -s: 源文件目录 (默认: data/processed/interactions)
    --output, -o: 输出目录 (默认: data/filtered/final)
"""

import json
import os
import argparse
from pathlib import Path

from typing import Optional


def simplify_json(data: dict) -> Optional[dict]:
    """
    简化 JSON 格式，只保留 initial_output 和简化的 turns。
    
    处理规则:
    1. 如果任意 turn 的 observation 包含 ^C（用户取消），跳过该轨迹
    2. 去掉最后一轮 action 为 "exit" 的 turn
    3. 如果剩余轮次不大于 1，返回 None（跳过该文件）
    """
    turns = []
    
    for turn in data.get("turns", []):
        simple_turn = {}
        
        # 提取 action content
        if "action" in turn and "content" in turn["action"]:
            simple_turn["action"] = turn["action"]["content"]
        
        # 提取 observation content
        if "observation" in turn and "content" in turn["observation"]:
            obs_content = turn["observation"]["content"]
            # 检查是否包含 ^C（用户取消操作）
            if "^C" in obs_content:
                return None  # 跳过整个轨迹
            simple_turn["observation"] = obs_content
        
        turns.append(simple_turn)
    
    # 去掉最后一轮 action 为 "exit" 的 turn
    if turns and turns[-1].get("action", "").strip().lower() == "exit":
        turns = turns[:-1]
    
    # 如果轮次不大于 1，返回 None
    if len(turns) <= 1:
        return None
    
    return {
        "initial_output": data.get("initial_output", ""),
        "turns": turns
    }


def copy_filtered_files(
    results_path: str,
    source_dir: str,
    output_dir: str,
    dry_run: bool = False
) -> dict:
    """
    复制所有 result=true 的文件到输出目录。
    
    Args:
        results_path: LLM 结果 JSON 文件路径
        source_dir: 源文件所在目录
        output_dir: 输出目录
        dry_run: 如果为 True，只统计不实际复制
        
    Returns:
        统计信息字典
    """
    # 加载结果文件
    print(f"正在加载结果文件: {results_path}")
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    results = data.get('results', [])
    metadata = data.get('metadata', {})
    
    print(f"总计: {metadata.get('total', len(results))} 条记录")
    print(f"Suitable: {metadata.get('suitable', 'N/A')}")
    print(f"Not suitable: {metadata.get('not_suitable', 'N/A')}")
    
    # 筛选 result=true 的文件
    suitable_files = [r['filename'] for r in results if r.get('result') is True]
    print(f"\n找到 {len(suitable_files)} 个通过筛选的文件")
    
    if not suitable_files:
        print("没有需要复制的文件")
        return {'total': 0, 'copied': 0, 'missing': 0}
    
    # 创建输出目录
    if not dry_run:
        os.makedirs(output_dir, exist_ok=True)
    
    # 复制文件
    copied = 0
    missing = 0
    skipped = 0  # 轮次不足跳过的文件
    missing_files = []
    
    for i, filename in enumerate(suitable_files, 1):
        src_path = os.path.join(source_dir, filename)
        dst_path = os.path.join(output_dir, filename)
        
        if os.path.exists(src_path):
            if not dry_run:
                # 读取源文件
                with open(src_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                # 简化格式
                simplified = simplify_json(data)
                # 如果返回 None，跳过该文件
                if simplified is None:
                    skipped += 1
                    continue
                # 写入目标文件
                with open(dst_path, 'w', encoding='utf-8') as f:
                    json.dump(simplified, f, indent=2, ensure_ascii=False)
            copied += 1
        else:
            missing += 1
            missing_files.append(filename)
        
        # 进度显示
        if i % 500 == 0 or i == len(suitable_files):
            print(f"  进度: {i}/{len(suitable_files)} (复制: {copied}, 跳过: {skipped}, 缺失: {missing})")
    
    # 汇总
    print(f"\n{'[Dry Run] ' if dry_run else ''}完成!")
    print(f"  成功复制: {copied} 个文件")
    print(f"  轮次不足跳过: {skipped} 个文件")
    print(f"  文件缺失: {missing} 个文件")
    print(f"  输出目录: {output_dir}")
    
    if missing_files and missing <= 10:
        print("\n缺失的文件:")
        for f in missing_files:
            print(f"  - {f}")
    elif missing > 10:
        print(f"\n缺失的文件 (前10个):")
        for f in missing_files[:10]:
            print(f"  - {f}")
        print(f"  ... 和 {missing - 10} 个其他文件")
    
    return {
        'total': len(suitable_files),
        'copied': copied,
        'missing': missing,
        'missing_files': missing_files
    }


def main():
    parser = argparse.ArgumentParser(
        description='复制通过 LLM 筛选的文件到 final 目录'
    )
    parser.add_argument(
        '--input', '-i',
        default='data/filtered/llm_filtered.json',
        help='LLM 结果文件路径'
    )
    parser.add_argument(
        '--source', '-s',
        default='data/processed/interactions',
        help='源文件目录'
    )
    parser.add_argument(
        '--output', '-o',
        default='data/filtered/final',
        help='输出目录'
    )
    parser.add_argument(
        '--dry-run', '-n',
        action='store_true',
        help='只统计，不实际复制文件'
    )
    
    args = parser.parse_args()
    
    # 转换为绝对路径
    script_dir = Path(__file__).parent.parent
    
    input_path = args.input
    if not os.path.isabs(input_path):
        input_path = os.path.join(script_dir, input_path)
    
    source_dir = args.source
    if not os.path.isabs(source_dir):
        source_dir = os.path.join(script_dir, source_dir)
    
    output_dir = args.output
    if not os.path.isabs(output_dir):
        output_dir = os.path.join(script_dir, output_dir)
    
    # 验证输入路径
    if not os.path.exists(input_path):
        print(f"错误: 结果文件不存在: {input_path}")
        return 1
    
    if not os.path.isdir(source_dir):
        print(f"错误: 源目录不存在: {source_dir}")
        return 1
    
    # 执行复制
    copy_filtered_files(
        results_path=input_path,
        source_dir=source_dir,
        output_dir=output_dir,
        dry_run=args.dry_run
    )
    
    return 0


if __name__ == '__main__':
    exit(main())
