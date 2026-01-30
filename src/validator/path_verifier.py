import json
import os
from pathlib import Path

# 读取 JSON 文件
with open('all_data_fixed.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

# 统计信息
total_records = len(data)
path_fields = ['cast_path', 'gif_path', 'html_path', 'txt_path']
stats = {field: {'exists': 0, 'missing': 0, 'missing_files': []} for field in path_fields}

print(f"开始验证 {total_records} 条记录...\n")

# 验证每条记录
for i, item in enumerate(data, 1):
    if i % 10000 == 0:
        print(f"已处理 {i}/{total_records} 条记录...")
    
    for field in path_fields:
        if field in item and item[field]:
            file_path = item[field]
            if os.path.exists(file_path):
                stats[field]['exists'] += 1
            else:
                stats[field]['missing'] += 1
                # 只记录前100个缺失的文件
                if len(stats[field]['missing_files']) < 100:
                    stats[field]['missing_files'].append({
                        'url': item.get('url', 'unknown'),
                        'path': file_path
                    })

# 打印结果
print("\n" + "="*60)
print("验证结果统计:")
print("="*60)

for field in path_fields:
    exists = stats[field]['exists']
    missing = stats[field]['missing']
    total = exists + missing
    percentage = (exists / total * 100) if total > 0 else 0
    
    print(f"\n{field}:")
    print(f"  总数: {total}")
    print(f"  存在: {exists} ({percentage:.2f}%)")
    print(f"  缺失: {missing}")
    
    if missing > 0 and stats[field]['missing_files']:
        print(f"  缺失文件示例 (前{min(5, len(stats[field]['missing_files']))}个):")
        for example in stats[field]['missing_files'][:5]:
            print(f"    - {example['path']} (来自 {example['url']})")

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

# 如果有缺失，询问是否保存详细列表
if total_missing > 0:
    print(f"\n发现 {total_missing} 个缺失文件")
    # 可选：保存完整的缺失文件列表
    save_detail = input("\n是否保存完整的缺失文件列表到 missing_files.json? (y/n): ").lower()
    if save_detail == 'y':
        with open('missing_files.json', 'w', encoding='utf-8') as f:
            json.dump(stats, f, ensure_ascii=False, indent=2)
        print("已保存到 missing_files.json")
