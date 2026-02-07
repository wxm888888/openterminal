#!/usr/bin/env python3
"""
API 连接测试脚本

用于验证 OpenAI API 配置是否正确。
"""

import os
from openai import OpenAI


def test_api_connection():
    """测试 API 连接是否正常工作。"""
    
    # 从环境变量读取配置，避免硬编码敏感信息
    api_key = os.getenv("OPENAI_API_KEY", "<your api_key>")
    base_url = os.getenv("OPENAI_BASE_URL", "<your base_url>")
    
    client = OpenAI(
        api_key=api_key,
        base_url=base_url
    )

    messages = [
        {
            "role": "system",
            "content": "你是一个专业的AI助手，能够帮助用户解决各种问题。"
        },
        {
            "role": "user",
            "content": "你好"
        }
    ]

    # 可选模型：gpt-4o, gpt-4o-mini, claude-3-5-sonnet-20241022, llama-3.2-3b-preview 等
    model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini-2025-04-14")
    
    response = client.chat.completions.create(
        messages=messages,
        model=model
    ).model_dump()

    # 输出结果
    print("=" * 50)
    print("API 响应内容:")
    print(response["choices"][0]["message"]["content"])
    print("=" * 50)
    print("\n完整响应:")
    print(response)
    
    return response


if __name__ == "__main__":
    test_api_connection()