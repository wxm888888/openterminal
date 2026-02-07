#!/usr/bin/env python3
"""
爬虫数据文件验证器

验证 all_data.json 中引用的文件路径是否实际存在。

使用方法:
    python tests/test_crawl_files.py
    python tests/test_crawl_files.py --input data/all_data.json
    python tests/test_crawl_files.py --input data/all_data.json --save-missing
"""

import json
import os
import sys
import argparse
from pathlib import Path

# 添加项目根目录到 path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def validate_data_files(input_file, base_dir=None, save_missing=False):
    """验证数据文件中的路径引用"""
    
    # 读取 JSON 文件
    with open(input_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    # 如果没有指定 base_dir，使用输入文件所在目录
    if base_dir is None:
        base_dir = Path(input_file).parent
    else:
        base_dir = Path(base_dir)
    
    # 统计信息
    total_records = len(data)
    path_fields = ['cast_path', 'gif_path', 'html_path', 'txt_path']
    stats = {field: {'exists': 0, 'missing': 0, 'missing_files': []} for field in path_fields}
    
    print(f"输入文件: {input_file}")
    print(f"基准目录: {base_dir}")
    print(f"开始验证 {total_records} 条记录...\n")
    
    # 验证每条记录
    for i, item in enumerate(data, 1):
        if i % 10000 == 0:
            print(f"已处理 {i}/{total_records} 条记录...")
        
        for field in path_fields:
            if field in item and item[field]:
                # 处理相对路径
                file_path = item[field]
                if file_path.startswith('./'):
                    file_path = base_dir / file_path[2:]
                elif file_path.startswith('raw/'):
                    file_path = base_dir / file_path
                else:
                    file_path = Path(file_path)
                
                if file_path.exists():
                    stats[field]['exists'] += 1
                else:
                    stats[field]['missing'] += 1
                    # 只记录前100个缺失的文件
                    if len(stats[field]['missing_files']) < 100:
                        stats[field]['missing_files'].append({
                            'url': item.get('url', 'unknown'),
                            'path': str(file_path)
                        })
    
    # 打印结果
    print("\n" + "="*60)
    print("验证结果统计:")
    print("="*60)
    
    for field in path_fields:
        exists = stats[field]['exists']
        missing = stats[field]['missing']
        total = exists + missing
        
        if total == 0:
            continue
            
        percentage = (exists / total * 100)
        
        print(f"\n{field}:")
        print(f"  总数: {total}")
        print(f"  存在: {exists} ({percentage:.2f}%)")
        print(f"  缺失: {missing}")
        
        if missing > 0 and stats[field]['missing_files']:
            print(f"  缺失文件示例 (前{min(5, len(stats[field]['missing_files']))}个):")
            for example in stats[field]['missing_files'][:5]:
                print(f"    - {example['path']}")
    
    # 总体统计
    print("\n" + "="*60)
    total_paths = sum(stats[field]['exists'] + stats[field]['missing'] for field in path_fields)
    total_exists = sum(stats[field]['exists'] for field in path_fields)
    total_missing = sum(stats[field]['missing'] for field in path_fields)
    overall_percentage = (total_exists / total_paths * 100) if total_paths > 0 else 0
    
    print(f"总体统计:")
    print(f"  所有路径总数: {total_paths}")
    print(f"  存在: {total_exists} ({overall_percentage:.2f}%)")
    print(f"  缺失: {total_missing}")
    print("="*60)
    
    # 保存缺失文件列表
    if save_missing and total_missing > 0:
        output_file = Path(input_file).parent / 'missing_files.json'
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(stats, f, ensure_ascii=False, indent=2)
        print(f"\n缺失文件列表已保存到: {output_file}")
    
    return total_missing == 0


def main():
    parser = argparse.ArgumentParser(description='验证数据文件中的路径引用')
    parser.add_argument('--input', '-i', type=str, default=None,
                        help='输入的 JSON 文件 (默认: data/all_data.json)')
    parser.add_argument('--base-dir', '-b', type=str, default=None,
                        help='文件路径的基准目录 (默认: 输入文件所在目录)')
    parser.add_argument('--save-missing', '-s', action='store_true',
                        help='保存缺失文件列表到 missing_files.json')
    
    args = parser.parse_args()
    
    # 设置默认输入文件
    if args.input:
        input_file = Path(args.input)
        if not input_file.is_absolute():
            input_file = project_root / input_file
    else:
        input_file = project_root / 'data' / 'all_data.json'
    
    if not input_file.exists():
        print(f"错误: 文件不存在 - {input_file}")
        sys.exit(1)
    
    # 运行验证
    success = validate_data_files(
        input_file,
        base_dir=args.base_dir,
        save_missing=args.save_missing
    )
    
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
