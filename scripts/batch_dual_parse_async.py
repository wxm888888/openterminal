import os
import glob
import time
import asyncio
from dual_model_parse_async import dual_model_parse_and_save_async


async def process_single_file_async(input_file, output_dir, model_a, model_b, judge_model, file_index, total_files):
    """Async version: Process a single file"""
    filename = os.path.splitext(os.path.basename(input_file))[0]
    output_file = os.path.join(output_dir, f'{filename}_dual.json')
    
    try:
        result = await dual_model_parse_and_save_async(
            input_file=input_file,
            output_file=output_file,
            model_a=model_a,
            model_b=model_b,
            judge_model=judge_model
        )
        
        if result.get('success', False):
            print(f"[{file_index}/{total_files}] ✅ {filename}.txt - Winner: {result['winner']}")
            return ('success', filename, None)
        else:
            reason = result.get('judgment', {}).get('reason', 'Unknown')
            print(f"[{file_index}/{total_files}] ⚠️ {filename}.txt - Skipped")
            return ('skipped', filename, reason)
    
    except Exception as e:
        error_msg = str(e)
        print(f"[{file_index}/{total_files}] ❌ {filename}.txt - Failed: {error_msg[:50]}")
        return ('failed', filename, error_msg)


async def batch_process_txt_files_async(
    input_dir='data/raw/txt',
    output_dir='data/judge',
    model_a='gpt-5.2-2025-12-11',
    model_b='claude-opus-4-5-20251101',
    judge_model='claude-sonnet-4-5-20250929-thinking',
    max_concurrent=5
):
    """
    Async batch processing: Process all txt files with controlled concurrency
    
    Args:
        input_dir: Input txt file directory
        output_dir: Output JSON file directory
        model_a: Model A name
        model_b: Model B name
        judge_model: Judge model name
        max_concurrent: Maximum concurrent file processing (default 5)
    """
    os.makedirs(output_dir, exist_ok=True)
    
    txt_pattern = os.path.join(input_dir, '*.txt')
    txt_files = sorted(glob.glob(txt_pattern))
    
    if not txt_files:
        print(f"⚠️ No .txt files found in {input_dir}")
        return
    
    print(f"{'='*70}")
    print(f"Async Batch Dual Model Parsing")
    print(f"{'='*70}")
    print(f"Input directory: {input_dir}")
    print(f"Output directory: {output_dir}")
    print(f"Total files: {len(txt_files)}")
    print(f"Model A: {model_a}")
    print(f"Model B: {model_b}")
    print(f"Judge Model: {judge_model}")
    print(f"Max concurrent: {max_concurrent}")
    print(f"{'='*70}\n")
    
    start_time = time.time()
    
    success_count = 0
    failed_count = 0
    skipped_count = 0
    failed_files = []
    skipped_files = []
    
    # Create semaphore to limit concurrency
    semaphore = asyncio.Semaphore(max_concurrent)
    
    async def process_with_semaphore(input_file, index):
        async with semaphore:
            return await process_single_file_async(
                input_file,
                output_dir,
                model_a,
                model_b,
                judge_model,
                index,
                len(txt_files)
            )
    
    # Process all files concurrently with limited concurrency
    tasks = [
        process_with_semaphore(input_file, i)
        for i, input_file in enumerate(txt_files, 1)
    ]
    
    results = await asyncio.gather(*tasks)
    
    # Collect statistics
    for status, filename, extra_info in results:
        if status == 'success':
            success_count += 1
        elif status == 'skipped':
            skipped_count += 1
            skipped_files.append((filename, extra_info))
        elif status == 'failed':
            failed_count += 1
            failed_files.append((filename, extra_info))
    
    elapsed_time = time.time() - start_time
    
    # Print summary
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
    async def main():
        INPUT_DIR = 'data/test'
        OUTPUT_DIR = 'data/results'  # Results will also be saved to data/judge/ automatically
        MODEL_A = 'gpt-5.2-2025-12-11'
        MODEL_B = 'claude-opus-4-5-20251101'
        JUDGE_MODEL = 'claude-sonnet-4-5-20250929-thinking'
        MAX_CONCURRENT = 5  # Maximum concurrent file processing
        
        await batch_process_txt_files_async(
            input_dir=INPUT_DIR,
            output_dir=OUTPUT_DIR,
            model_a=MODEL_A,
            model_b=MODEL_B,
            judge_model=JUDGE_MODEL,
            max_concurrent=MAX_CONCURRENT
        )
    
    asyncio.run(main())
