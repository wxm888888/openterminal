import os
import sys
import subprocess
from pathlib import Path
from tqdm import tqdm
import argparse
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

# 添加项目根目录到 path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

# 用于线程安全的计数器
stats_lock = Lock()

def convert_cast_to_gif(cast_path, gif_path):
    """使用 agg 命令将 cast 文件转换为 gif 文件"""
    try:
        # 运行 agg 命令
        result = subprocess.run(
            ['agg', cast_path, gif_path],
            capture_output=True,
            text=True,
            timeout=60  # 60秒超时
        )
        return result.returncode == 0, result.stderr
    except subprocess.TimeoutExpired:
        return False, "转换超时"
    except FileNotFoundError:
        return False, "agg 命令未找到，请确保已安装 agg"
    except Exception as e:
        return False, str(e)

def process_single_file(cast_file, gif_dir, progress_file):
    """处理单个文件的转换"""
    gif_file = gif_dir / f"{cast_file.stem}.gif"
    
    # 如果 gif 文件已存在，跳过
    if gif_file.exists():
        return {
            'status': 'skipped',
            'file': cast_file.name,
            'message': '文件已存在'
        }
    
    # 转换文件
    success, error_msg = convert_cast_to_gif(str(cast_file), str(gif_file))
    
    if success:
        # 记录成功转换的文件
        with stats_lock:
            save_progress(progress_file, cast_file.name, True)
        return {
            'status': 'success',
            'file': cast_file.name
        }
    else:
        # 记录失败的文件
        with stats_lock:
            save_progress(progress_file, cast_file.name, False, error_msg)
        return {
            'status': 'failed',
            'file': cast_file.name,
            'error': error_msg
        }

def save_progress(progress_file, filename, success, error_msg=None):
    """保存转换进度"""
    try:
        # 读取现有进度
        if progress_file.exists():
            with open(progress_file, 'r', encoding='utf-8') as f:
                progress = json.load(f)
        else:
            progress = {'completed': [], 'failed': []}
        
        # 更新进度
        if success:
            if filename not in progress['completed']:
                progress['completed'].append(filename)
        else:
            progress['failed'].append({
                'file': filename,
                'error': error_msg
            })
        
        # 保存进度
        with open(progress_file, 'w', encoding='utf-8') as f:
            json.dump(progress, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"保存进度文件时出错: {e}")

def load_progress(progress_file):
    """加载已完成的进度"""
    if progress_file.exists():
        try:
            with open(progress_file, 'r', encoding='utf-8') as f:
                progress = json.load(f)
                return set(progress.get('completed', [])), progress.get('failed', [])
        except Exception as e:
            print(f"读取进度文件时出错: {e}")
            return set(), []
    return set(), []

def main():
    # 解析命令行参数
    parser = argparse.ArgumentParser(description='批量将 .cast 文件转换为 .gif 文件')
    parser.add_argument('--workers', type=int, default=4, 
                       help='并行工作线程数 (默认: 4)')
    parser.add_argument('--cast-dir', type=str, default=None,
                       help='cast 文件目录 (默认: data/raw/cast)')
    parser.add_argument('--gif-dir', type=str, default=None,
                       help='gif 文件输出目录 (默认: data/raw/gif)')
    parser.add_argument('--progress-file', type=str, default=None,
                       help='进度文件路径 (默认: data/raw/conversion_progress.json)')
    parser.add_argument('--reset', action='store_true',
                       help='重置进度，重新转换所有文件')
    
    args = parser.parse_args()
    
    # 设置默认路径（相对于项目根目录）
    if args.cast_dir:
        cast_dir = Path(args.cast_dir)
        if not cast_dir.is_absolute():
            cast_dir = project_root / cast_dir
    else:
        cast_dir = project_root / 'data' / 'raw' / 'cast'
    
    if args.gif_dir:
        gif_dir = Path(args.gif_dir)
        if not gif_dir.is_absolute():
            gif_dir = project_root / gif_dir
    else:
        gif_dir = project_root / 'data' / 'raw' / 'gif'
    
    if args.progress_file:
        progress_file = Path(args.progress_file)
        if not progress_file.is_absolute():
            progress_file = project_root / progress_file
    else:
        progress_file = project_root / 'data' / 'raw' / 'conversion_progress.json'
    
    # 确保 gif 目录存在
    gif_dir.mkdir(exist_ok=True)
    
    # 如果需要重置进度
    if args.reset and progress_file.exists():
        progress_file.unlink()
        print("已重置转换进度\n")
    
    # 加载已完成的进度
    completed_files, previous_failed = load_progress(progress_file)
    
    # 获取所有 .cast 文件
    cast_files = list(cast_dir.glob('*.cast'))
    total_files = len(cast_files)
    
    if total_files == 0:
        print("未找到任何 .cast 文件")
        return
    
    # 过滤出需要处理的文件（跳过已完成的）
    files_to_process = [f for f in cast_files if f.name not in completed_files]
    already_completed = len(cast_files) - len(files_to_process)
    
    print(f"找到 {total_files} 个 .cast 文件")
    if already_completed > 0:
        print(f"已完成: {already_completed} 个文件 (从上次进度恢复)")
    print(f"待处理: {len(files_to_process)} 个文件")
    print(f"使用 {args.workers} 个工作线程")
    print(f"开始转换...\n")
    
    if len(files_to_process) == 0:
        print("所有文件已转换完成!")
        return
    
    # 统计信息
    success_count = already_completed
    failed_count = 0
    skipped_count = 0
    failed_files = list(previous_failed)  # 包含之前失败的文件
    
    # 使用线程池处理文件
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        # 提交所有任务
        future_to_file = {
            executor.submit(process_single_file, cast_file, gif_dir, progress_file): cast_file 
            for cast_file in files_to_process
        }
        
        # 使用 tqdm 显示进度
        with tqdm(total=len(files_to_process), desc="转换进度", unit="文件") as pbar:
            for future in as_completed(future_to_file):
                result = future.result()
                
                if result['status'] == 'success':
                    success_count += 1
                elif result['status'] == 'failed':
                    failed_count += 1
                    failed_files.append({
                        'file': result['file'],
                        'error': result['error']
                    })
                elif result['status'] == 'skipped':
                    skipped_count += 1
                    success_count += 1
                
                pbar.update(1)
    
    # 打印结果统计
    print("\n" + "="*60)
    print("转换完成!")
    print("="*60)
    print(f"总文件数: {total_files}")
    print(f"成功: {success_count} ({success_count/total_files*100:.2f}%)")
    if skipped_count > 0:
        print(f"跳过 (已存在): {skipped_count}")
    print(f"失败: {failed_count} ({failed_count/total_files*100:.2f}%)")
    
    # 如果有失败的文件，显示详情
    if failed_files:
        print(f"\n失败文件列表 (前10个):")
        for item in failed_files[-10:]:
            print(f"  - {item['file']}: {item['error']}")
        
        print(f"\n完整的失败列表已保存到 {progress_file}")
    
    print("="*60)

if __name__ == '__main__':
    main()