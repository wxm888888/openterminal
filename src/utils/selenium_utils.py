"""
Selenium工具模块

提供基于Selenium的浏览器自动化工具函数，包括元素查找、驱动获取和网络响应处理。
"""

import copy
import os
from typing import Optional, Callable, Any, List

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from utils.file_utils import strfml


# 全局错误级别变量
_error_level: str = ""


def get_error_level(value: str = "") -> str:
    """
    获取或设置全局错误级别。
    
    Args:
        value: 要设置的错误级别值，为空则只获取当前值
        
    Returns:
        当前错误级别值
    """
    global _error_level
    if value != "":
        _error_level = value
    return _error_level


def find_element_with_retry(
    driver: Any,
    by: str,
    value: str,
    callback: Callable = get_error_level,
    max_retries: int = 1
) -> Any:
    """
    自定义元素查找函数，支持重试机制。
    
    Args:
        driver: WebDriver实例
        by: 查找方式（如By.XPATH）
        value: 查找值
        callback: 错误回调函数
        max_retries: 最大重试次数
        
    Returns:
        找到的元素
    """
    global _error_level
    _error_level = '：' + strfml(value.replace("'", "\""), "\"", "\"")[0]
    
    retries = max_retries
    element = None
    
    while retries:
        if retries > 0:
            retries -= 1
        try:
            element = WebDriverWait(driver, 1.4).until(
                EC.presence_of_element_located((by, value))
            )
            _error_level = None
            break
        except Exception:
            print("等待", _error_level)
            element = WebDriverWait(driver, 3).until(
                EC.presence_of_element_located((By.XPATH, "./*"))
            )
    
    callback(_error_level)
    return element


# 默认路径配置（Mac/Linux）
DEFAULT_DIRS: List[str] = [
    os.path.expanduser("~/.config/chromium"),  # 用户数据目录
    "",  # chromedriver路径（留空使用系统PATH）
    ""   # chrome二进制路径（留空使用默认位置）
]


def get_driver(
    hide: int = 10,
    proxy: Optional[str] = None,
    download_path: Optional[str] = None,
    user_agent: Optional[str] = None,
    use_user_data_dir: bool = False,
    maximize: bool = False,
    driver_dirs: List[str] = None,
    incognito: bool = None,
    enable_logging: bool = False
) -> Any:
    """
    获取配置好的Chrome WebDriver实例。
    
    Args:
        hide: 设置为1时隐藏浏览器（无头模式）
        proxy: 代理服务器地址
        download_path: 默认下载路径
        user_agent: 自定义User-Agent
        use_user_data_dir: 是否使用用户配置目录
        maximize: 是否最大化窗口
        driver_dirs: 驱动路径配置列表
        incognito: 是否启用无痕模式
        enable_logging: 是否启用性能日志
        
    Returns:
        配置好的WebDriver实例
    """
    if driver_dirs is None:
        driver_dirs = DEFAULT_DIRS
    
    # 初始化Chrome选项
    chrome_options = ChromeOptions()
    chrome_options.add_argument("--disable-popup-blocking")
    chrome_options.add_argument("--profile-directory=Default")
    chrome_options.add_argument("--ignore-certificate-errors")
    chrome_options.add_argument("--disable-plugins-discovery")
    chrome_options.add_argument('--no-first-run')
    chrome_options.add_argument('--no-service-autorun')
    chrome_options.add_argument('--no-default-browser-check')
    chrome_options.add_argument('--password-store=basic')
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')  # Linux 兼容性
    chrome_options.add_experimental_option("prefs", {
        "credentials_enable_service": False,
        "profile.password_manager_enabled": False,
        'profile.default_content_setting_values': {
            'notifications': 2
        }
    })
    chrome_options.add_experimental_option(
        "excludeSwitches", 
        ["enable-automation", "enable-logging"]
    )
    chrome_options.add_argument('--disable-blink-features=AutomationControlled')
    
    if use_user_data_dir:
        chrome_options.add_argument('--user-data-dir=%s' % driver_dirs[0])
    
    if download_path:
        chrome_options.add_experimental_option("prefs", {
            'profile.default_content_settings.popups': 0, 
            'download.default_directory': download_path
        })
    
    if hide == 1:
        chrome_options.add_argument('--headless=new')
    
    if maximize:
        chrome_options.add_argument("--start-maximized")
    
    if incognito:
        chrome_options.add_argument("--incognito")
    
    if proxy:
        print("当前代理为:", proxy)
        chrome_options.add_argument('--proxy-server=%s' % proxy)
    
    if enable_logging:
        chrome_options.set_capability(
            "goog:loggingPrefs", 
            {"performance": "ALL", "browser": "ALL"}
        )
    
    # 设置User-Agent
    default_user_agent = (
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/119.0.0.0 Safari/537.36'
    )
    headers = user_agent if user_agent else default_user_agent
    chrome_options.add_argument('--user-agent=%s' % headers)
    
    # 设置chrome二进制路径（如果指定）
    if driver_dirs[2]:
        chrome_options.binary_location = driver_dirs[2]
    
    # 创建驱动
    if driver_dirs[1]:
        service = ChromeService(executable_path=driver_dirs[1])
        browser = webdriver.Chrome(service=service, options=chrome_options)
    else:
        browser = webdriver.Chrome(options=chrome_options)
    
    return browser


def get_response_body(
    browser: Any,
    url_keyword: Optional[str] = None,
    request_id: Optional[str] = None,
    content_types: Optional[List[str]] = None
) -> Optional[str]:
    """
    从浏览器性能日志中获取指定请求的响应体。
    
    Args:
        browser: WebDriver实例
        url_keyword: URL匹配关键字
        request_id: 请求ID
        content_types: 允许的内容类型列表
        
    Returns:
        响应体内容，未找到时返回None
    """
    performance_log = browser.get_log('performance')
    
    # 要过滤的MIME类型
    filtered_types = [
        'application/javascript', 
        'application/x-javascript', 
        'text/css', 
        'webp', 
        'image/png', 
        'image/gif',
        'image/jpeg', 
        'image/x-icon', 
        'application/octet-stream'
    ]
    
    for log_entry in performance_log:
        message = log_entry.get('message')
        
        # 只处理responseReceived类型的消息
        if strfml(message, 'method', '"', ind=3)[0] != 'Network.responseReceived':
            continue
        
        packet_type = strfml(message, 'mimeType', '"', ind=3)[0]
        
        # 过滤内容类型
        if content_types and (packet_type not in content_types):
            continue
        elif packet_type in filtered_types:
            continue
        
        url = strfml(message, '"url"', '"', ind=2)[0]
        req_id = strfml(message, 'requestId', '"', ind=3)[0]
        
        if url.find(url_keyword) > -1 or (request_id and req_id == request_id):
            return browser.execute_cdp_cmd(
                'Network.getResponseBody', 
                {'requestId': req_id}
            )["body"]
    
    return None


def get_log_message(
    browser: Any,
    keyword: Optional[str] = None,
    method: str = 'Network.requestWillBeSent'
) -> Optional[str]:
    """
    从浏览器性能日志中获取包含指定关键字的消息。
    
    Args:
        browser: WebDriver实例
        keyword: 匹配关键字
        method: 日志方法类型
        
    Returns:
        匹配的消息内容，未找到时返回None
    """
    performance_log = browser.get_log('performance')
    
    for log_entry in performance_log:
        message = log_entry.get('message')
        
        if method and strfml(message, 'method', '"', ind=3)[0] != method:
            continue
        
        if message.find(keyword) > -1:
            return message
    
    return None


def close_browser_tabs(browser: Any, keep_first: int = 0) -> None:
    """
    关闭浏览器标签页。
    
    Args:
        browser: WebDriver实例
        keep_first: 保留的第一个标签页索引，0表示关闭所有
    """
    for i in range(keep_first, len(browser.window_handles)):
        browser.switch_to.window(browser.window_handles[-1])
        browser.close()
    
    if keep_first:
        browser.switch_to.window(browser.window_handles[-1])


# 兼容性别名（保持向后兼容）
Errorlevel = get_error_level
nfind_element = find_element_with_retry
dir = DEFAULT_DIRS
getresponse = get_response_body
getmessage = get_log_message
quit = close_browser_tabs
