#!/usr/bin/env python3
"""
OpenTerminal 数据处理入口脚本

功能：
1. 从 data/raw/cast 读取 cast 文件
2. 自动检测版本，调用对应的解析器
3. 输出转换数据到 data/processed/interactions
4. 调用验证器验证提取结果

使用方法:
    python scripts/process_data.py
    python scripts/process_data.py --format both
    python scripts/process_data.py --format turn_based --limit 100
    python scripts/process_data.py --verify-only
    python scripts/process_data.py --no-resume
"""

import os
import time
import glob
import json
import argparse
import sys
import multiprocessing
from typing import List, Dict, Optional, Any

# 项目路径
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from src.parser.detect_version import detect_version
from src.parser.batch_processor import process_single_file
from src.validator.extraction_verifier import verify_single_file, verify_directory


# 默认路径
DEFAULT_INPUT_DIR = os.path.join(PROJECT_ROOT, "data/raw/cast")
DEFAULT_OUTPUT_DIR = os.path.join(PROJECT_ROOT, "data/processed/interactions")
DEFAULT_TXT_DIR = os.path.join(PROJECT_ROOT, "data/raw/txt")
DEFAULT_REPORT_DIR = os.path.join(PROJECT_ROOT, "data/processed")


def find_cast_files(input_dir: str, limit: Optional[int] = None) -> List[str]:
    """查找所有 cast 文件"""
    cast_files = glob.glob(os.path.join(input_dir, "**/*.cast"), recursive=True)
    if not cast_files:
        cast_files = glob.glob(os.path.join(input_dir, "*.cast"))
    
    cast_files.sort()
    
    if limit:
        cast_files = cast_files[:limit]
    
    return cast_files


def _run_single_file_processing(cast_path: str, output_dir: str, format_type: str, verbose: bool) -> Dict:
    """Helper function to run process_single_file in a separate process."""
    try:
        return process_single_file(cast_path, output_dir, format_type, verbose)
    except Exception as e:
        return {
            'file': cast_path,
            'version': None,
            'success': {'turn_based': False, 'event_stream': False},
            'message': f'Error during processing: {str(e)}',
            'duration_ms': 0
        }


def process_all(input_dir: str, output_dir: str, format_type: str = 'turn_based',
                limit: Optional[int] = None, verbose: bool = False,
                resume: bool = True) -> Dict:
    """
    处理所有 cast 文件
    
    Args:
        input_dir: cast 文件输入目录
        output_dir: JSON 输出目录
        format_type: 'turn_based', 'event_stream', 或 'both'
        limit: 限制处理文件数量
        verbose: 详细输出
        resume: 断点续传，跳过已处理的文件
    
    Returns:
        处理报告
    """
    os.makedirs(output_dir, exist_ok=True)
    
    cast_files = find_cast_files(input_dir, limit)
    
    # 断点续传：过滤已处理的文件
    skipped_count = 0
    if resume:
        files_to_process = []
        for cast_path in cast_files:
            basename = os.path.splitext(os.path.basename(cast_path))[0]
            
            # 检查输出文件是否已存在
            tb_exists = os.path.exists(os.path.join(output_dir, f"{basename}.turn_based.json"))
            es_exists = os.path.exists(os.path.join(output_dir, f"{basename}.event_stream.json"))
            
            if format_type == 'turn_based' and tb_exists:
                skipped_count += 1
                continue
            elif format_type == 'event_stream' and es_exists:
                skipped_count += 1
                continue
            elif format_type == 'both' and tb_exists and es_exists:
                skipped_count += 1
                continue
            
            files_to_process.append(cast_path)
        
        cast_files = files_to_process
    
    print("=" * 60)
    print("OpenTerminal 数据处理")
    print("=" * 60)
    print(f"输入目录: {input_dir}")
    print(f"输出目录: {output_dir}")
    print(f"格式类型: {format_type}")
    if resume and skipped_count > 0:
        print(f"已跳过: {skipped_count} (已处理)")
    print(f"待处理: {len(cast_files)}")
    print("=" * 60)
    
    if not cast_files:
        if skipped_count > 0:
            print("所有文件已处理完成！")
            return {'success': True, 'message': 'All files already processed', 
                    'summary': {'total': skipped_count, 'skipped': skipped_count}}
        print("错误: 未找到任何 cast 文件")
        return {'success': False, 'message': 'No cast files found'}
    
    report = {
        'summary': {
            'total': len(cast_files) + skipped_count,
            'processed': 0,
            'skipped': skipped_count,
            'success': 0,
            'failed': 0,
            'by_version': {'v1': 0, 'v2': 0, 'v3': 0}
        },
        'results': []
    }
    
    start_time = time.time()
    
    blacklist = {'734198.cast', '241698.cast'}
    
    for i, cast_path in enumerate(cast_files):
        # 过滤大文件 (> 3MB) 或已知问题文件
        file_size = os.path.getsize(cast_path)
        filename = os.path.basename(cast_path)
        if file_size > 3 * 1024 * 1024 or filename in blacklist:
            print(f"  [SKIP] Skipping problematic/large file: {filename} ({file_size/1024/1024:.2f} MB)")
            report['results'].append({
                'file': cast_path,
                'version': None,
                'success': {'turn_based': False, 'event_stream': False},
                'message': 'Skipped (large file or blacklist)',
                'duration_ms': 0
            })
            report['summary']['skipped'] += 1
            continue

        # 处理单个文件 (带超时保护)
        print(f"  [{i+1}/{len(cast_files)}] Processing {filename}...", end='\r')
        
        pool = multiprocessing.Pool(processes=1)
        async_result = pool.apply_async(_run_single_file_processing, (cast_path, output_dir, format_type, verbose))
        
        try:
            # 设置每个文件最多 60 秒处理时间
            result = async_result.get(timeout=60)
            report['results'].append(result)
            report['summary']['processed'] += 1
            if result['success']['turn_based'] or result['success']['event_stream']:
                report['summary']['success'] += 1
                if result.get('version'):
                    v = result['version']
                    report['summary']['by_version'][v] += 1
            else:
                report['summary']['failed'] += 1
        except multiprocessing.TimeoutError:
            print(f"\n  [TIMEOUT] Skipping file that took too long: {filename}")
            report['results'].append({
                'file': cast_path,
                'version': None,
                'success': {'turn_based': False, 'event_stream': False},
                'message': 'Timeout after 60s',
                'duration_ms': 60000
            })
            report['summary']['failed'] += 1
        
        if result['version']:
            report['summary']['by_version'][result['version']] += 1
        
        # 进度显示
        if (i + 1) % 50 == 0 or (i + 1) == len(cast_files):
            elapsed = time.time() - start_time
            rate = (i + 1) / elapsed if elapsed > 0 else 0
            print(f"  进度: {i + 1}/{len(cast_files)} ({rate:.1f} files/s)")
    
    total_time = time.time() - start_time
    report['summary']['total_time_seconds'] = round(total_time, 2)
    
    # 打印摘要
    print("\n" + "=" * 60)
    print("处理完成")
    print("=" * 60)
    if skipped_count > 0:
        print(f"已跳过: {skipped_count} (已处理)")
    print(f"本次处理: {report['summary']['processed']}")
    print(f"成功: {report['summary']['success']}")
    print(f"失败: {report['summary']['failed']}")
    print(f"版本分布: v1={report['summary']['by_version']['v1']}, "
          f"v2={report['summary']['by_version']['v2']}, "
          f"v3={report['summary']['by_version']['v3']}")
    print(f"总耗时: {total_time:.2f}s")
    
    return report


def verify_all(output_dir: str, input_dir: str, txt_dir: Optional[str] = None,
               report_path: Optional[str] = None, verbose: bool = False,
               format_type: str = 'both') -> Dict:
    """
    验证所有提取结果
    
    Args:
        output_dir: 包含提取 JSON 的目录
        input_dir: 包含原始 cast 文件的目录
        txt_dir: 包含 txt 截图的目录（用于对比验证）
        report_path: 验证报告保存路径
        verbose: 详细输出
        format_type: 验证格式 ('turn_based', 'event_stream', 'both')
    """
    print("\n" + "=" * 60)
    print("验证提取结果")
    print("=" * 60)
    
    reports = {}
    
    # 验证 Turn-based
    if format_type in ('turn_based', 'both'):
        print("\n正在验证 Turn-based 格式...")
        from src.validator.extraction_verifier import verify_directory as verify_tb
        reports['turn_based'] = verify_tb(output_dir, txt_dir, report_path, 
                                          cast_dir=input_dir, verbose=verbose)
    
    # 验证 Event-stream
    if format_type in ('event_stream', 'both'):
        print("\n正在验证 Event-stream 格式...")
        from src.validator.event_stream_verifier import verify_directory as verify_es
        # 注意: event_stream_verifier 的 verify_directory 签名略有不同，我们刚修改过
        es_report_path = report_path.replace('.json', '_es.json') if report_path else None
        reports['event_stream'] = verify_es(output_dir, es_report_path, 
                                            cast_dir=input_dir, verbose=verbose)
        
    return reports


def main():
    parser = argparse.ArgumentParser(
        description='OpenTerminal 数据处理入口脚本',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
    # 处理所有文件并验证
    python scripts/process_data.py
    
    # 只处理前100个文件
    python scripts/process_data.py --limit 100
    
    # 只提取 turn_based 格式
    python scripts/process_data.py --format turn_based
    
    # 只运行验证（假设已处理过）
    python scripts/process_data.py --verify-only
    
    # 跳过验证
    python scripts/process_data.py --skip-verify
        """
    )
    
    parser.add_argument('--input-dir', '-i', default=DEFAULT_INPUT_DIR,
                        help=f'cast 文件输入目录 (默认: {DEFAULT_INPUT_DIR})')
    parser.add_argument('--output-dir', '-o', default=DEFAULT_OUTPUT_DIR,
                        help=f'JSON 输出目录 (默认: {DEFAULT_OUTPUT_DIR})')
    parser.add_argument('--txt-dir', '-t', default=DEFAULT_TXT_DIR,
                        help=f'txt 截图目录，用于验证 (默认: {DEFAULT_TXT_DIR})')
    parser.add_argument('--format', '-f', choices=['turn_based', 'event_stream', 'both'],
                        default='turn_based', help='提取格式 (默认: turn_based)')
    parser.add_argument('--limit', '-l', type=int, default=None,
                        help='限制处理文件数量')
    parser.add_argument('--verify-only', action='store_true',
                        help='只运行验证，跳过处理')
    parser.add_argument('--skip-verify', action='store_true',
                        help='跳过验证步骤')
    parser.add_argument('--no-resume', action='store_true',
                        help='禁用断点续传，重新处理所有文件')
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='详细输出')
    parser.add_argument('--report', '-r', default=None,
                        help='报告输出路径')
    
    args = parser.parse_args()
    
    # 处理阶段
    process_report = None
    if not args.verify_only:
        if not os.path.isdir(args.input_dir):
            print(f"错误: 输入目录不存在: {args.input_dir}")
            sys.exit(1)
        
        process_report = process_all(
            args.input_dir,
            args.output_dir,
            args.format,
            args.limit,
            args.verbose,
            resume=not args.no_resume
        )
        
        # 保存处理报告
        if args.report:
            report_path = args.report
        else:
            report_path = os.path.join(DEFAULT_REPORT_DIR, 'process_report.json')
        
        os.makedirs(os.path.dirname(report_path), exist_ok=True)
        with open(report_path, 'w', encoding='utf-8') as f:
            json.dump(process_report, f, indent=2, ensure_ascii=False)
        print(f"\n处理报告已保存: {report_path}")
    
    # 验证阶段
    if not args.skip_verify:
        txt_dir = args.txt_dir if os.path.isdir(args.txt_dir) else None
        verify_report_path = os.path.join(DEFAULT_REPORT_DIR, 'verify_report.json')
        
        verify_report = verify_all(
            args.output_dir,
            args.input_dir,
            txt_dir,
            verify_report_path,
            args.verbose,
            args.format
        )
    
    print("\n✅ 全部完成!")


if __name__ == "__main__":
    main()
