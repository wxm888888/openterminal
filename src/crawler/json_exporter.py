#!/usr/bin/env python3
"""
CSV 转 JSON 工具

将指定目录下的 CSV 文件转换为统一的 JSON 格式 (mschema.json)。

使用方法:
    python src/crawler/metadata_converter.py --input-dir <目录路径>
    python src/crawler/metadata_converter.py -i <目录路径> -o <输出文件名>
"""

import argparse
import csv
import json
import os
import re


# CSV 列名定义
CSV_COLUMNS = [
    "name",
    "profile_url",
    "date",
    "description",
    "system",
    "terminal",
    "shell",
    "title",
    "url",
    "views",
]

# 默认输出文件名
DEFAULT_OUTPUT_FILE = "mschema.json"


def natural_sort_key(s):
    """
    自然排序的 key 函数
    将字符串中的数字部分转换为整数进行比较
    例如: file1, file2, file10 -> file1, file2, file10 (而不是 file1, file10, file2)
    """
    return [int(text) if text.isdigit() else text.lower() 
            for text in re.split(r'(\d+)', s)]


def get_column_value(row, column_name):
    """从 CSV 行中获取指定列的值"""
    return row[CSV_COLUMNS.index(column_name)]


def format_date(date_str):
    """格式化日期字符串，移除 T 和 Z"""
    return date_str.replace("T", " ").replace("Z", "")


def create_json_record(row, base_name):
    """
    根据 CSV 行数据创建 JSON 记录

    Args:
        row: CSV 行数据
        base_name: 文件基础名称（不含扩展名）

    Returns:
        dict: JSON 格式的记录
    """
    return {
        "url": get_column_value(row, "url"),
        "title": get_column_value(row, "title"),
        "author": {
            "name": get_column_value(row, "name"),
            "profile_url": get_column_value(row, "profile_url"),
        },
        "date": format_date(get_column_value(row, "date")),
        "system": get_column_value(row, "system"),
        "terminal": get_column_value(row, "terminal"),
        "shell": get_column_value(row, "shell"),
        "views": get_column_value(row, "views"),
        "description": get_column_value(row, "description"),
        "cast_path": f"./cast/{base_name}.cast",
        "text_path": f"./text/{base_name}.txt",
        "gif_path": f"./gif/{base_name}.gif",
        "html_path": f"./html/{base_name}.html",
    }


def write_to_file(filepath, content, mode="w", encoding="utf-8"):
    """写入文件的辅助函数"""
    with open(filepath, mode, encoding=encoding) as f:
        f.write(content)


def process_csv_file(csv_path, is_first_record, output_file):
    """
    处理单个 CSV 文件

    Args:
        csv_path: CSV 文件完整路径
        is_first_record: 是否为第一条记录
        output_file: 输出的 JSON 文件名

    Returns:
        bool: 处理后 is_first_record 的状态
    """
    base_name = os.path.splitext(os.path.basename(csv_path))[0]
    print(f"  处理: {os.path.basename(csv_path)}")

    with open(csv_path, "r", newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        for row in reader:
            record = create_json_record(row, base_name)
            json_str = json.dumps(record, ensure_ascii=False)

            if is_first_record:
                write_to_file(output_file, json_str, "a")
                is_first_record = False
            else:
                write_to_file(output_file, f",\n{json_str}", "a")

    return is_first_record


def convert_csv_to_json(root_dir, output_file=DEFAULT_OUTPUT_FILE):
    """
    将目录下所有 CSV 文件转换为 JSON

    Args:
        root_dir: CSV 文件所在的根目录
        output_file: 输出的 JSON 文件名
    """
    # 初始化输出文件
    write_to_file(output_file, "[\n")

    is_first_record = True
    total_files = 0

    for root, dirs, files in os.walk(root_dir):
        # 获取当前目录下的 CSV 文件列表并自然排序
        csv_files = [f for f in files if f.endswith(".csv")]
        csv_files.sort(key=natural_sort_key)

        for filename in csv_files:
            csv_path = os.path.join(root, filename)
            is_first_record = process_csv_file(csv_path, is_first_record, output_file)
            total_files += 1

    # 关闭 JSON 数组
    write_to_file(output_file, "\n]", "a")
    
    print(f"\n共处理 {total_files} 个 CSV 文件")
    print(f"输出文件: {output_file}")


def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description="将 CSV 文件转换为 JSON 格式",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
    python src/crawler/metadata_converter.py --input-dir ./data
    python src/crawler/metadata_converter.py -i ./data -o output.json
        """,
    )
    parser.add_argument(
        "-i",
        "--input-dir",
        type=str,
        required=True,
        help="CSV 文件所在的根目录路径",
    )
    parser.add_argument(
        "-o",
        "--output-file",
        type=str,
        default=DEFAULT_OUTPUT_FILE,
        help=f"输出的 JSON 文件名 (默认: {DEFAULT_OUTPUT_FILE})",
    )
    return parser.parse_args()


def main():
    """主函数"""
    args = parse_args()

    # 清理路径中可能存在的引号
    input_dir = args.input_dir.replace('"', "")

    if not os.path.isdir(input_dir):
        print(f"错误: 目录不存在: {input_dir}")
        return 1

    convert_csv_to_json(input_dir, args.output_file)

    print("全部完成")
    return 0


if __name__ == "__main__":
    exit(main())