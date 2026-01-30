"""
HTTP工具模块

提供HTTP请求相关的工具函数，支持gzip和brotli压缩解码、代理配置等功能。
"""

import gzip
import random
import ssl
import time
import urllib.request
import urllib.parse
from typing import Optional, List, Dict, Any, Union

import brotli
import socks
import sockshandler

from utils.file_utils import addrootdir

# 初始化根目录路径
addrootdir()

# 常用对象别名
urlencode = urllib.parse.urlencode

# SSL上下文配置
ssl_context = ssl._create_unverified_context()


def brotli_decompress(compressed_data: bytes, size_multiplier: int = 6) -> bytes:
    """
    使用Brotli算法解压缩数据。
    
    Args:
        compressed_data: 压缩的字节数据
        size_multiplier: 预估解压后大小的倍数（保留参数，实际未使用）
        
    Returns:
        解压后的字节数据
        
    Raises:
        Exception: 解压失败时抛出
    """
    if not compressed_data:
        return b""
    
    return brotli.decompress(compressed_data)


def get_html(
    url: str,
    referer: Optional[Union[str, Dict[str, str]]] = None,
    data: Optional[Union[str, Dict[str, Any]]] = None,
    headers: Optional[Dict[str, str]] = None,
    proxy: Optional[str] = None,
    status_code: Optional[List[int]] = None,
    timeout: int = 28,
    max_retries: int = 3,
    method: Optional[str] = None,
    size_multiplier: int = 6
) -> bytes:
    """
    发送HTTP请求并获取响应内容。
    
    Args:
        url: 请求URL
        referer: Referer头或完整的headers字典
        data: POST数据（字典或字符串）
        headers: 自定义请求头
        proxy: 代理服务器地址（支持http和socks5）
        status_code: 用于返回状态码的列表（通过引用返回）
        timeout: 请求超时时间（秒）
        max_retries: 最大重试次数
        method: HTTP方法（GET/POST等）
        size_multiplier: Brotli解压时的大小倍数
        
    Returns:
        响应内容的字节数据
    """
    result = None
    
    # 默认请求头
    default_headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/119.0.0.0 Safari/537.36"
        ),
        "Content-Type": "application/json; charset=UTF-8",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "close",
    }
    
    print("连接中..")
    
    # 初始化状态码列表
    if status_code is None:
        status_code = []
    status_code.clear()
    status_code.append(0)
    
    # 使用自定义headers
    if headers:
        request_headers = headers
    else:
        request_headers = default_headers
    
    # 处理Referer
    if referer:
        if isinstance(referer, str):
            # 检查header键的大小写
            if "user-agent" in request_headers.keys():
                request_headers["referer"] = referer
            else:
                request_headers["Referer"] = referer
        else:
            request_headers = referer
    
    # 处理POST数据
    encoded_data = None
    if data:
        content_type_key = "Content-Type"
        content_length_key = "Content-Length"
        
        # 检查header键的大小写
        if "user-agent" in request_headers.keys():
            content_type_key = content_type_key.lower()
            content_length_key = content_length_key.lower()
        
        status_code[0] = content_length_key
        
        if not isinstance(data, str):
            if request_headers.get(content_type_key, "").find("json") < 0:
                encoded_data = urlencode(data)
            else:
                encoded_data = str(data).replace('"', '\\"').replace("'", '"')
        else:
            encoded_data = data
        
        encoded_data = encoded_data.encode()
        request_headers[content_length_key] = len(encoded_data)
        
        if not method:
            method = "POST"
    
    # 配置代理
    if proxy:
        if proxy.find("socks") < 0:
            # HTTP代理
            ip = proxy[proxy.find("//") + 2:]
            proxies = {}
            if ip:
                proxies = {"http": ip, "https": ip}
            handler = urllib.request.ProxyHandler(proxies)
        else:
            # SOCKS5代理
            parts = proxy.split(":")
            parts[1] = parts[1][2:]  # 移除"//"
            
            while len(parts) < 5:
                parts.append("")
            
            handler = sockshandler.SocksiPyHandler(
                proxytype=socks.SOCKS5,
                proxyaddr=parts[1],
                proxyport=int(parts[2]),
                username=parts[3] if parts[3] else None,
                password=parts[4] if parts[4] else None,
            )
        
        opener = urllib.request.build_opener(handler)
        urllib.request.install_opener(opener)
    
    # 发送请求（带重试）
    for attempt in range(max_retries):
        try:
            request = urllib.request.Request(
                url, 
                data=encoded_data, 
                headers=request_headers, 
                method=method
            )
            response = urllib.request.urlopen(request, timeout=timeout)
            
            status_code[0] = response.getcode()
            result = response.read()
            response.close()
            
            # 处理内容编码
            content_encoding = response.info().get("Content-Encoding")
            if content_encoding == "gzip":
                result = gzip.decompress(result)
            elif content_encoding == "br":
                result = brotli_decompress(result, size_multiplier)
            
            break
            
        except Exception as e:
            print("连接失败:", e, "尝试重新连接..")
            if attempt < max_retries - 1:
                time.sleep(3 + random.random() * 3)
            result = str(e).encode()
    
    return result


# 兼容性别名（保持向后兼容）
context = ssl_context
gethtml = get_html
