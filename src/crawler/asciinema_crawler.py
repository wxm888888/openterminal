#!/usr/bin/env python3
"""
Asciinema 爬虫

从 asciinema.org 爬取公开的终端录屏数据。

输出结构:
    <output-dir>/
    ├── all_data.json       # 元数据索引
    ├── failed_urls.txt     # 失败的 URL 列表（用于重试）
    └── raw/
        ├── cast/           # .cast 录屏文件
        ├── txt/            # .txt 文本内容
        └── html/           # .html 页面备份

使用方法:
    # 正常爬取
    python src/crawler/asciinema_crawler.py --output-dir data/test_crawl --pages 1-2

    # 重试失败的 URL
    python src/crawler/asciinema_crawler.py --output-dir data/test_crawl --retry

    # 提高并发数
    python src/crawler/asciinema_crawler.py --output-dir data --pages 1-100 --concurrency 10
"""

import os
import sys
import time
import json
import threading
import argparse
from pathlib import Path
from datetime import datetime

# 添加项目根目录到 path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.utils.file_utils import cn, we, strfml, hmrstr, setaskN
from src.utils.http_utils import gethtml


# 请求头
HEADERS = {
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "accept-encoding": "gzip, deflate, br",
    "accept-language": "zh-CN,zh;q=0.9,en;q=0.8",
    "cache-control": "no-cache",
    "pragma": "no-cache",
    "sec-ch-ua-platform": '"macOS"',
    "sec-fetch-dest": "document",
    "sec-fetch-mode": "navigate",
    "sec-fetch-site": "same-origin",
    "upgrade-insecure-requests": "1",
    "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
}

# 全局结果列表和锁
results_lock = threading.Lock()
all_results = []

# 失败 URL 列表和锁
failed_lock = threading.Lock()
failed_urls = []


def log_failed_url(url, error_type, error_msg=""):
    """记录失败的 URL"""
    with failed_lock:
        failed_urls.append({
            "url": url,
            "error_type": error_type,
            "error_msg": error_msg,
            "timestamp": datetime.now().isoformat()
        })


def get_single_data(raw_dir, url, referer, proxy=None, verbose=False):
    """获取单个录屏的数据"""
    code = []
    cast_id = url.split("/a/")[-1]
    
    try:
        cdx = gethtml(url, referer, headers=HEADERS, status_code=code, proxy=proxy)
        
        if code != [200]:
            error_msg = f"HTTP {code[0] if code else 'unknown'}"
            if verbose:
                print(f"  失败 [{cast_id}]: {error_msg}")
            log_failed_url(url, "http_error", error_msg)
            return None
        
        # 保存到各个子目录
        html_path = os.path.join(raw_dir, "html", f"{cast_id}.html")
        txt_path = os.path.join(raw_dir, "txt", f"{cast_id}.txt")
        cast_path = os.path.join(raw_dir, "cast", f"{cast_id}.cast")
        
        # 保存 HTML
        we(html_path, cdx, "wb", print_message=False)
        
        # 保存 TXT
        txt_code = []
        txt_data = gethtml(url + ".txt", url, headers=HEADERS, status_code=txt_code, proxy=proxy)
        if txt_code != [200]:
            log_failed_url(url, "txt_download_error", f"TXT HTTP {txt_code}")
        else:
            we(txt_path, txt_data, "wb", print_message=False)
        
        # 保存 CAST
        cast_code = []
        cast_data = gethtml(url + ".cast", url, headers=HEADERS, status_code=cast_code, proxy=proxy)
        if cast_code != [200]:
            log_failed_url(url, "cast_download_error", f"CAST HTTP {cast_code}")
        else:
            we(cast_path, cast_data, "wb", print_message=False)
        
        # 解析元数据
        cdx = cn(cdx)
        
        trs = list(strfml(cdx, '"even info"', ""))
        
        # 初始化元数据
        metadata = {
            "url": url,
            "title": "",
            "author": {
                "name": "",
                "profile_url": ""
            },
            "date": "",
            "system": "",
            "terminal": "",
            "shell": "",
            "views": "",
            "description": "",
            "cast_path": f"./cast/{cast_id}.cast",
            "txt_path": f"./txt/{cast_id}.txt",
            "html_path": f"./html/{cast_id}.html",
        }
        
        # 解析标题
        result = strfml(cdx, "<h2>", "</h2>", trs[1])
        metadata["title"] = result[0]
        trs[1] = result[1]

        # 解析作者信息
        result = strfml(cdx, "<small>", "</small>", trs[1])
        sm, trs[1] = result[0], result[1]
        if trs[1] > -1:
            metadata["author"]["name"] = hmrstr(strfml(sm, "by", "</a>")[0]).strip()
            metadata["author"]["profile_url"] = "https://asciinema.org " + strfml(sm, 'href="', '"')[0]
            metadata["date"] = strfml(sm, 'datetime="', '"')[0].replace("T", " ").replace("Z", "")

        # 解析系统信息
        result = strfml(cdx, '"odd meta"', "</section>", trs[1])
        sm, trs[1] = result[0], result[1]
        if trs[1] > -1:
            # 从 env-info 类中提取系统信息
            env_info_result = strfml(sm, '"env-info">', "</span>\n</span>")
            if env_info_result[1] > -1:
                env_info = env_info_result[0]
                env_text = hmrstr(env_info).strip()
                parts = [p.strip() for p in env_text.split("•") if p.strip()]
                
                for i, field in enumerate(["system", "terminal", "shell"]):
                    if i < len(parts):
                        clean_value = " ".join(parts[i].split())
                        metadata[field] = clean_value
            
            # 解析 views
            views_result = strfml(sm, 'title="Total views">', "</span>\n")
            if views_result[1] > -1:
                views_section = views_result[0]
                last_span_end = views_section.rfind("</span>")
                if last_span_end > -1:
                    views_text = views_section[last_span_end + 7:].strip()
                    views_num = "".join(c for c in views_text if c.isdigit())
                    if views_num:
                        metadata["views"] = views_num

        # 解析 description
        desc_result = strfml(cdx, 'class="description">', "</div>")
        if desc_result[1] > -1:
            metadata["description"] = desc_result[0].strip()

        # 添加到全局结果
        with results_lock:
            all_results.append(metadata)
        
        if verbose:
            print(f"  保存: {cast_id}")
        
        return metadata
        
    except Exception as e:
        error_msg = str(e)
        if verbose:
            print(f"  异常 [{cast_id}]: {error_msg}")
        log_failed_url(url, "exception", error_msg)
        return None


def crawl_page(page_num, raw_dir, proxy=None, verbose=False, max_items=None, concurrency=3):
    """爬取一页的数据"""
    url = f"https://asciinema.org/explore/public?order=date&page= {page_num}"
    referer = None
    if page_num > 1:
        referer = f"https://asciinema.org/explore/public?order=date&page= {page_num - 1}"
    
    idx = cn(gethtml(url, referer, headers=HEADERS, proxy=proxy))
    
    task_list = []
    trs = ["", 0]
    count = 0
    
    while True:
        trs = strfml(idx, '"asciicast-card"', "", trs[1])
        if trs[1] < 0:
            break
        
        item_url = strfml(idx, 'href="', '"', trs[1])[0]
        cast_id = item_url.split("/a/")[-1] if "/a/" in item_url else item_url
        
        # 检查是否已存在
        cast_file = os.path.join(raw_dir, "cast", f"{cast_id}.cast")
        if os.path.exists(cast_file):
            if verbose:
                print(f"  跳过已存在: {cast_id}")
            continue
        
        full_url = "https://asciinema.org " + item_url
        task_list.append(threading.Thread(
            target=get_single_data, 
            args=[raw_dir, full_url, url, proxy, verbose]
        ))
        count += 1
        
        if max_items and count >= max_items:
            break
    
    if task_list:
        setaskN(task_list, min(len(task_list), concurrency))
        time.sleep(0.5)
    
    return count


def crawl_urls(url_list, raw_dir, proxy=None, verbose=False, concurrency=3):
    """爬取指定的 URL 列表（用于重试）"""
    task_list = []
    
    for url in url_list:
        cast_id = url.split("/a/")[-1] if "/a/" in url else url
        
        # 检查是否已存在
        cast_file = os.path.join(raw_dir, "cast", f"{cast_id}.cast")
        if os.path.exists(cast_file):
            if verbose:
                print(f"  跳过已存在: {cast_id}")
            continue
        
        task_list.append(threading.Thread(
            target=get_single_data, 
            args=[raw_dir, url, None, proxy, verbose]
        ))
    
    if task_list:
        print(f"开始重试 {len(task_list)} 个 URL...")
        setaskN(task_list, min(len(task_list), concurrency))
    
    return len(task_list)


def load_failed_urls(filepath):
    """加载失败的 URL 列表"""
    if not os.path.exists(filepath):
        return []
    
    urls = []
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                # 支持 JSON 格式和纯 URL 格式
                if line.startswith("{"):
                    try:
                        data = json.loads(line)
                        urls.append(data.get("url", ""))
                    except json.JSONDecodeError:
                        pass
                else:
                    urls.append(line)
    return [u for u in urls if u]


def save_failed_urls(filepath, failed_list):
    """保存失败的 URL 列表"""
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(f"# 失败的 URL 列表 - 生成于 {datetime.now().isoformat()}\n")
        f.write(f"# 共 {len(failed_list)} 个失败\n")
        f.write("#\n")
        for item in failed_list:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")


def main():
    parser = argparse.ArgumentParser(description='Asciinema 爬虫')
    parser.add_argument('--output-dir', '-o', default='data/test_crawl', 
                        help='输出目录 (默认: data/test_crawl)')
    parser.add_argument('--pages', '-p', default='1', 
                        help='页码范围，如 "1" 或 "1-5" (默认: 1)')
    parser.add_argument('--proxy', default=None,
                        help='代理地址，如 http://127.0.0.1:7890 ')
    parser.add_argument('--max-per-page', '-m', type=int, default=None,
                        help='每页最多爬取数量 (默认: 不限制)')
    parser.add_argument('--concurrency', '-c', type=int, default=3,
                        help='并发数 (默认: 3)')
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='显示详细输出')
    parser.add_argument('--retry', '-r', action='store_true',
                        help='重试模式：只处理 failed_urls.txt 中的 URL')
    
    args = parser.parse_args()
    
    # 创建输出目录结构
    output_dir = args.output_dir
    if not os.path.isabs(output_dir):
        output_dir = os.path.join(project_root, output_dir)
    
    raw_dir = os.path.join(output_dir, "raw")
    os.makedirs(os.path.join(raw_dir, "cast"), exist_ok=True)
    os.makedirs(os.path.join(raw_dir, "txt"), exist_ok=True)
    os.makedirs(os.path.join(raw_dir, "html"), exist_ok=True)
    
    failed_urls_path = os.path.join(output_dir, "failed_urls.txt")
    all_data_path = os.path.join(output_dir, "all_data.json")
    
    print(f"输出目录: {output_dir}")
    print(f"并发数: {args.concurrency}")
    if args.proxy:
        print(f"代理: {args.proxy}")
    print()
    
    total_count = 0
    
    if args.retry:
        # 重试模式
        print("=== 重试模式 ===")
        retry_urls = load_failed_urls(failed_urls_path)
        if not retry_urls:
            print("没有需要重试的 URL")
            return
        
        print(f"找到 {len(retry_urls)} 个待重试的 URL")
        total_count = crawl_urls(
            retry_urls, raw_dir,
            proxy=args.proxy,
            verbose=args.verbose,
            concurrency=args.concurrency
        )
    else:
        # 正常爬取模式
        if '-' in args.pages:
            start, end = map(int, args.pages.split('-'))
            pages = range(start, end + 1)
        else:
            pages = [int(args.pages)]
        
        print(f"页码: {list(pages)}")
        if args.max_per_page:
            print(f"每页最多: {args.max_per_page} 条")
        print()
        
        for page in pages:
            print(f"正在爬取第 {page} 页...")
            count = crawl_page(
                page, raw_dir, 
                proxy=args.proxy, 
                verbose=args.verbose,
                max_items=args.max_per_page,
                concurrency=args.concurrency
            )
            total_count += count
            print(f"  第 {page} 页完成，获取 {count} 条\n")
    
    # 保存失败的 URL
    if failed_urls:
        save_failed_urls(failed_urls_path, failed_urls)
        print(f"\n⚠ 有 {len(failed_urls)} 个 URL 失败，已保存到: {failed_urls_path}")
        print(f"  使用 --retry 参数可以重试这些 URL")
    
    # 保存元数据索引到 all_data.json
    existing_data = []
    if os.path.exists(all_data_path):
        with open(all_data_path, "r", encoding="utf-8") as f:
            try:
                existing_data = json.load(f)
            except json.JSONDecodeError:
                existing_data = []
    
    # 合并新数据（避免重复）
    existing_urls = {item["url"] for item in existing_data}
    for item in all_results:
        if item["url"] not in existing_urls:
            existing_data.append(item)
    
    # 保存
    with open(all_data_path, "w", encoding="utf-8") as f:
        json.dump(existing_data, f, ensure_ascii=False, indent=2)
    
    print(f"\n全部完成！共获取 {total_count} 条新数据")
    print(f"元数据已保存到: {all_data_path}")
    print(f"总记录数: {len(existing_data)}")


if __name__ == "__main__":
    main()