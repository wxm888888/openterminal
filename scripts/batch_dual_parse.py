import os
import glob
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dual_model_parse import dual_model_parse_and_save

def process_single_file(input_file, output_dir, model_a, model_b, judge_model, file_index, total_files):
    """处理单个文件的辅助函数"""
    filename = os.path.splitext(os.path.basename(input_file))[0]
    output_file = os.path.join(output_dir, f'{filename}_dual.json')
    
    print(f"\n[{file_index}/{total_files}] 🔄 Started: {filename}.txt")
    
    try:
        result = dual_model_parse_and_save(
            input_file=input_file,
            output_file=output_file,
            model_a=model_a,
            model_b=model_b,
            judge_model=judge_model
        )
        
        if result.get('success', False):
            print(f"[{file_index}/{total_files}] ✅ Success: {filename}.txt")
            return ('success', filename, None)
        else:
            reason = result.get('judgment', {}).get('reason', 'Unknown')
            print(f"[{file_index}/{total_files}] ⚠️ Skipped: {filename}.txt (Reason: {reason[:50]}...)")
            return ('skipped', filename, reason)
    
    except Exception as e:
        error_msg = str(e)
        print(f"[{file_index}/{total_files}] ❌ Failed: {filename}.txt (Error: {error_msg[:50]}...)")
        return ('failed', filename, error_msg)


def batch_process_txt_files(
    input_dir='data/raw/txt',
    output_dir='data/judge',
    model_a='gpt-5.2-2025-12-11',
    model_b='claude-opus-4-5-20251101',
    judge_model='claude-sonnet-4-5-20250929-thinking',
    max_workers=3,
    use_multithreading=True
):
    """
    批量处理目录下所有 txt 文件，对每个文件执行 dual_model_parse_and_save
    
    Args:
        input_dir: 输入 txt 文件所在目录
        output_dir: 输出 JSON 文件保存目录
        model_a: 模型 A 名称
        model_b: 模型 B 名称
        judge_model: 裁判模型名称
        max_workers: 最大并发线程数（默认3，建议2-5之间）
        use_multithreading: 是否使用多线程（默认True）
    """
    # 确保输出目录存在
    os.makedirs(output_dir, exist_ok=True)
    
    # 获取所有 txt 文件
    txt_pattern = os.path.join(input_dir, '*.txt')
    txt_files = sorted(glob.glob(txt_pattern))
    
    if not txt_files:
        print(f"⚠️ No .txt files found in {input_dir}")
        return
    
    print(f"{'='*70}")
    print(f"Batch Dual Model Parsing {'(Multithreading)' if use_multithreading else '(Sequential)'}")
    print(f"{'='*70}")
    print(f"Input directory: {input_dir}")
    print(f"Output directory: {output_dir}")
    print(f"Total files: {len(txt_files)}")
    print(f"Model A: {model_a}")
    print(f"Model B: {model_b}")
    print(f"Judge Model: {judge_model}")
    if use_multithreading:
        print(f"Max workers: {max_workers}")
    print(f"{'='*70}\n")
    
    start_time = time.time()
    
    # 统计信息
    success_count = 0
    failed_count = 0
    skipped_count = 0
    failed_files = []
    skipped_files = []
    
    if use_multithreading:
        # 多线程处理
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # 提交所有任务
            future_to_file = {
                executor.submit(
                    process_single_file,
                    input_file,
                    output_dir,
                    model_a,
                    model_b,
                    judge_model,
                    i,
                    len(txt_files)
                ): input_file
                for i, input_file in enumerate(txt_files, 1)
            }
            
            # 处理完成的任务
            for future in as_completed(future_to_file):
                status, filename, extra_info = future.result()
                
                if status == 'success':
                    success_count += 1
                elif status == 'skipped':
                    skipped_count += 1
                    skipped_files.append((filename, extra_info))
                elif status == 'failed':
                    failed_count += 1
                    failed_files.append((filename, extra_info))
    
    else:
        # 顺序处理
        for i, input_file in enumerate(txt_files, 1):
            status, filename, extra_info = process_single_file(
                input_file,
                output_dir,
                model_a,
                model_b,
                judge_model,
                i,
                len(txt_files)
            )
            
            if status == 'success':
                success_count += 1
            elif status == 'skipped':
                skipped_count += 1
                skipped_files.append((filename, extra_info))
            elif status == 'failed':
                failed_count += 1
                failed_files.append((filename, extra_info))
    
    elapsed_time = time.time() - start_time
    
    # 打印汇总信息
    print(f"\n{'='*70}")
    print(f"Batch Processing Summary")
    print(f"{'='*70}")
    print(f"Total files: {len(txt_files)}")
    print(f"✅ Successful: {success_count}")
    print(f"⚠️ Skipped: {skipped_count}")
    print(f"❌ Failed: {failed_count}")
    print(f"⏱️  Total time: {elapsed_time:.2f}s ({elapsed_time/len(txt_files):.2f}s per file)")
    
    if skipped_files:
        print(f"\nSkipped files:")
        for filename, reason in skipped_files[:5]:
            print(f"  - {filename}.txt: {reason[:60]}...")
        if len(skipped_files) > 5:
            print(f"  ... and {len(skipped_files) - 5} more")
    
    if failed_files:
        print(f"\nFailed files:")
        for filename, error in failed_files[:5]:
            print(f"  - {filename}.txt: {error[:60]}...")
        if len(failed_files) > 5:
            print(f"  ... and {len(failed_files) - 5} more")
    
    print(f"{'='*70}")


if __name__ == "__main__":
    # 配置参数
    INPUT_DIR = 'data/test'
    OUTPUT_DIR = 'data/results'
    MODEL_A = 'gpt-5.2-2025-12-11'
    MODEL_B = 'claude-opus-4-5-20251101'
    JUDGE_MODEL = 'claude-sonnet-4-5-20250929-thinking'
    
    # 多线程配置
    USE_MULTITHREADING = True  # 是否使用多线程（True=并发处理，False=顺序处理）
    MAX_WORKERS = 5  # 最大并发线程数，建议2-5（太高可能被API限流）
    
    # 执行批量处理
    batch_process_txt_files(
        input_dir=INPUT_DIR,
        output_dir=OUTPUT_DIR,
        model_a=MODEL_A,
        model_b=MODEL_B,
        judge_model=JUDGE_MODEL,
        max_workers=MAX_WORKERS,
        use_multithreading=USE_MULTITHREADING
    )
