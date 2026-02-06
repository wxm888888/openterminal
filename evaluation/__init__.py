"""
Evaluation module for terminal parsing results.

多模型评估流程：
1. 读取多模型生成结果
2. 检查轮次数量是否半数以上相同，且包含winner
3. 以winner为基准，检查相似模型是否超过半数
4. 计算winner模型与原始文件的相似度
"""

from .evaluator import Evaluator, evaluate_single_file, batch_evaluate

__all__ = [
    'Evaluator',
    'evaluate_single_file',
    'batch_evaluate'
]
