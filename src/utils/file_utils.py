"""
文件工具模块

提供文件读写、内容解析、Excel/CSV处理等工具函数。
"""

import csv
import os
import re
import time
from typing import Optional, List, Any, Union, Tuple, IO

# 尝试导入Excel相关模块
try:
    import xlrd
    import xlwt
    EXCEL_AVAILABLE = True
except ImportError:
    EXCEL_AVAILABLE = False
    print("警告：xlrd/xlwt模块未安装，Excel功能将不可用")
    print("请运行: pip install xlrd xlwt")

# 默认编码
DEFAULT_ENCODING = "u8"


def decode_bytes(data: bytes) -> str:
    """
    将字节数据解码为字符串。
    
    Args:
        data: 要解码的字节数据
        
    Returns:
        解码后的字符串
    """
    return data.decode()


def encode_string(data: str) -> bytes:
    """
    将字符串编码为字节数据。
    
    Args:
        data: 要编码的字符串
        
    Returns:
        编码后的字节数据
    """
    return data.encode()


def read_file(
    filepath: str,
    mode: str = "r",
    encoding: Optional[str] = None
) -> str:
    """
    读取文件内容。
    
    Args:
        filepath: 文件路径
        mode: 打开模式
        encoding: 文件编码
        
    Returns:
        文件内容
    """
    with open(filepath, mode, encoding=encoding) as f:
        return f.read()


def write_file(
    filepath: str,
    content: Union[str, List[List[Any]]],
    mode: str = "w",
    newline: str = "",
    encoding: Optional[str] = None,
    print_message: bool = True,
    file_handle: Optional[IO] = None
) -> Union[str, List[List[Any]]]:
    """
    写入文件内容，支持普通文本和CSV格式。
    
    Args:
        filepath: 文件路径
        content: 要写入的内容（字符串或CSV行数据列表）
        mode: 打开模式
        newline: 换行符
        encoding: 文件编码
        print_message: 是否打印操作消息
        file_handle: 已打开的文件句柄（可选）
        
    Returns:
        写入成功返回空字符串/空列表，否则返回原内容
    """
    message = ""
    is_csv = False
    
    try:
        if file_handle:
            f = file_handle
        elif "b" not in mode:
            f = open(filepath, mode, newline=newline, encoding=encoding)
            # 检查是否为CSV文件
            if filepath[filepath.rfind("."):] == ".csv":
                is_csv = True
                csv_writer = csv.writer(f)
                csv_writer.writerows(content)
                content = []
        else:
            f = open(filepath, mode)
        
        if not is_csv:
            f.write(content)
            content = ""
        
        if not file_handle:
            f.close()
        
        message = "数据更新:" + filepath
        
    except Exception as e:
        message = "更新失败:" + str(e)
    
    if print_message:
        print(message)
    
    return content


def csv_to_xls(filename: str, data: Optional[List[List[Any]]] = None) -> None:
    """
    将CSV文件转换为XLS格式。
    
    Args:
        filename: 文件名（不含扩展名或含.csv扩展名）
        data: CSV数据（可选，不提供则从文件读取）
    """
    if not EXCEL_AVAILABLE:
        raise ImportError("需要xlrd和xlwt模块才能使用Excel功能")
    
    # 去除扩展名
    dot_index = filename.rfind(".")
    if dot_index > -1:
        filename = filename[:dot_index]
    
    workbook = xlwt.Workbook(encoding="utf-8", style_compression=0)
    worksheet = workbook.add_sheet("sheet1", cell_overwrite_ok=True)
    
    if not data:
        with open(filename + ".csv", "r", encoding=DEFAULT_ENCODING) as f:
            data = csv.reader(f)
            row_idx = 0
            for row in data:
                for col_idx, cell in enumerate(row):
                    worksheet.write(row_idx, col_idx, cell)
                row_idx += 1
    else:
        for row_idx, row in enumerate(data):
            for col_idx, cell in enumerate(row):
                worksheet.write(row_idx, col_idx, cell)
    
    workbook.save(filename + ".xls")
    
    # 删除原CSV文件
    if os.path.exists(filename + ".csv"):
        os.remove(filename + ".csv")


def xls_append(target_file: str, source_file: str) -> None:
    """
    将一个XLS文件的数据追加到另一个XLS文件。
    
    Args:
        target_file: 目标文件路径
        source_file: 源文件路径
    """
    if not EXCEL_AVAILABLE:
        raise ImportError("需要xlrd和xlwt模块才能使用Excel功能")
    
    # 打开目标文件
    target_book = xlrd.open_workbook(target_file)
    target_sheet = target_book.sheets()[0]
    
    # 打开源文件
    source_book = xlrd.open_workbook(source_file)
    source_sheet = source_book.sheets()[0]
    
    # 创建新工作簿
    output_book = xlwt.Workbook(encoding="utf-8", style_compression=0)
    output_sheet = output_book.add_sheet("sheet1", cell_overwrite_ok=True)
    
    # 复制目标文件内容
    for row_idx in range(target_sheet.nrows):
        for col_idx in range(target_sheet.ncols):
            output_sheet.write(row_idx, col_idx, target_sheet.row(row_idx)[col_idx].value)
    
    # 追加源文件内容（跳过标题行）
    for row_idx in range(1, source_sheet.nrows):
        for col_idx in range(source_sheet.ncols):
            output_sheet.write(
                row_idx + target_sheet.nrows - 1, 
                col_idx, 
                source_sheet.row(row_idx)[col_idx].value
            )
    
    # 释放资源并保存
    target_book.release_resources()
    source_book.release_resources()
    output_book.save(target_file)


def format_time(timestamp: float, style: str = "%Y.%m.%d") -> str:
    """
    将时间戳格式化为指定格式的字符串。
    
    Args:
        timestamp: Unix时间戳
        style: 时间格式字符串（如 '%H:%M:%S'、'%Y.%m.%d'）
        
    Returns:
        格式化后的时间字符串
    """
    time_array = time.localtime(timestamp)
    return time.strftime(style, time_array)


def find_url_in_text(
    data: str,
    search_str: str,
    start_pos: int = 0,
    offset: int = 0,
    prefix: str = 'href="',
    suffix: str = '"'
) -> Tuple[str, int]:
    """
    在文本中查找URL。
    
    Args:
        data: 要搜索的文本数据
        search_str: 搜索的字符串标记
        start_pos: 搜索起始位置
        offset: 前缀偏移量
        prefix: URL前缀
        suffix: URL后缀
        
    Returns:
        元组：(找到的URL, 标记位置) 或 (错误信息, -1/-2)
    """
    tag_pos = data.find(search_str, start_pos)
    
    if tag_pos < 0:
        return (f"没有'{search_str}'字符", -2)
    
    prefix_pos = data.rfind(prefix, start_pos, tag_pos)
    
    if prefix_pos < 0:
        return ("", -1)
    
    content_start = prefix_pos + len(prefix) + offset
    content_end = data.find(suffix, content_start)
    
    return (data[content_start:content_end], tag_pos)


def strfml(
    data: str,
    search_str: str,
    suffix: str = "<",
    start_pos: int = 0,
    offset: int = 0
) -> Tuple[str, int]:
    """
    提取两个标记之间的字符串。
    
    Args:
        data: 要搜索的文本数据
        search_str: 开始搜索的字符串
        suffix: 结束字符串
        start_pos: 搜索起始位置
        offset: 开始字符串后的偏移量
        
    Returns:
        元组：(提取的字符串, 结束位置) 或 ("", -1)
    """
    start = data.find(search_str, start_pos)
    
    if start < 0:
        return ("", -1)
    
    content_start = start + len(search_str) + offset
    content_end = data.find(suffix, content_start)
    
    return (data[content_start:content_end], content_end)


def remove_tags(
    text: str,
    start_tag: str = "<",
    end_tag: str = ">"
) -> str:
    """
    移除文本中的标签内容（如HTML标签）。
    
    Args:
        text: 输入文本
        start_tag: 开始标签
        end_tag: 结束标签
        
    Returns:
        移除标签后的文本
    """
    start_len = len(start_tag)
    end_len = len(end_tag)
    
    while True:
        start_pos = text.find(start_tag)
        
        if start_pos < 0:
            return text
        
        end_pos = text.find(end_tag, start_pos)
        
        if end_pos < 0:
            return text
        
        # 查找最后一个嵌套的开始标签
        nested_pos = text.find(start_tag, start_pos + start_len, end_pos)
        while nested_pos > -1:
            start_pos = nested_pos
            nested_pos = text.find(start_tag, start_pos + start_len, end_pos)
        
        text = text[:start_pos] + text[end_pos + end_len:]


def find_all_in_range(
    data: str,
    start_pos: int = 0,
    end_pos: int = 0,
    start_str: str = '">',
    end_str: str = "<",
    result_list: Optional[List[str]] = None
) -> List[str]:
    """
    在指定范围内查找所有匹配的字符串。
    
    Args:
        data: 要搜索的文本数据
        start_pos: 搜索起始位置
        end_pos: 搜索结束位置（0表示无限制）
        start_str: 开始字符串
        end_str: 结束字符串
        result_list: 结果列表（可选）
        
    Returns:
        匹配的字符串列表
    """
    if result_list is None:
        result_list = []
    
    current_result = ("", start_pos)
    
    while True:
        current_result = strfml(data, start_str, end_str, current_result[1])
        
        if current_result[1] > -1:
            if end_pos > 0 and current_result[1] > end_pos:
                return result_list
            result_list.append(current_result[0])
        else:
            return result_list


def parse_config_file(
    filepath: str,
    delimiter: str = "="
) -> List[str]:
    """
    解析配置文件，提取键值对的值部分。
    
    Args:
        filepath: 配置文件路径
        delimiter: 键值分隔符
        
    Returns:
        配置值列表
    """
    try:
        lines = read_file(filepath).splitlines()
    except Exception:
        lines = read_file(filepath, encoding="u8").splitlines()
    
    config_values = []
    
    for line in lines:
        # 移除注释
        comment_pos = line.find("#")
        if comment_pos > -1:
            line = line[:comment_pos]
        
        # 查找分隔符
        delimiter_pos = line.find(delimiter)
        if delimiter_pos < 0:
            continue
        
        # 提取值并去除空白
        value = line[delimiter_pos + len(delimiter):].strip()
        
        # 去除引号
        if len(value) > 1:
            if (value[0] == "'" and value[-1] == "'") or \
               (value[0] == '"' and value[-1] == '"'):
                value = value[1:-1]
        
        config_values.append(value)
    
    return config_values


def get_chunk_ranges(total: int, chunk_size: int = 1) -> List[List[int]]:
    """
    将总数分割为多个块的范围列表。
    
    Args:
        total: 总数
        chunk_size: 每块大小
        
    Returns:
        范围列表，每个元素为 [起始, 结束]
    """
    if chunk_size < 0:
        chunk_size = total
    
    num_chunks = total // chunk_size
    if total == chunk_size:
        num_chunks -= 1
    
    remainder = total % chunk_size
    ranges = []
    
    for i in range(num_chunks + 1):
        start = i * chunk_size
        end = (i + 1) * chunk_size
        
        if i == num_chunks and remainder:
            end = total
        
        ranges.append([start, end])
    
    return ranges


def run_tasks_in_batches(task_list: List[Any], batch_size: int = 1) -> None:
    """
    分批运行任务列表。
    
    Args:
        task_list: 任务列表（需要有start()和join()方法）
        batch_size: 每批任务数量
    """
    for chunk in get_chunk_ranges(len(task_list), batch_size):
        # 启动当前批次的所有任务
        for task in task_list[chunk[0]:chunk[1]]:
            task.start()
        
        # 等待当前批次的所有任务完成
        for task in task_list[chunk[0]:chunk[1]]:
            task.join()


# 平台名称（自动检测当前操作系统）
import sys as _sys
_platform_name: str = _sys.platform


def platform(name: Optional[str] = None) -> str:
    """
    获取或设置平台名称。
    
    Args:
        name: 要设置的平台名称（可选）
        
    Returns:
        当前平台名称
    """
    global _platform_name
    if name:
        _platform_name = name
    return _platform_name


def addrootdir() -> None:
    """
    将libs目录添加到DLL搜索路径中。
    """
    rootdir = os.path.join(os.path.dirname(__file__), "libs")
    try:
        os.add_dll_directory(rootdir)
    except AttributeError:
        # Python 3.7 及以下版本 或非 Windows 平台
        os.environ["PATH"] = rootdir + os.pathsep + os.environ["PATH"]


# 兼容性别名（保持向后兼容）
cn = decode_bytes
en = encode_string
op = read_file
we = write_file
cde = DEFAULT_ENCODING
csvToxls = csv_to_xls
xlsadd = xls_append
get_time = format_time
urlftr = find_url_in_text
hmrstr = remove_tags
lstftr = find_all_in_range
setpz = parse_config_file
geteps = get_chunk_ranges
setaskN = run_tasks_in_batches
platformName = _platform_name
