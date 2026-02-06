"""
Multi-Model Evaluator

多模型评估流程：
1. 读取多模型生成结果
2. 检查轮次数量是否半数以上相同，且包含winner
3. 以winner为基准，检查相似模型是否超过半数
4. 计算winner模型与原始文件的相似度
"""

import json
from typing import Dict, List, Tuple
from pathlib import Path
from difflib import SequenceMatcher


class Evaluator:
    """多模型评估器"""

    def __init__(self, similarity_threshold: float = 0.9, final_similarity_threshold: float = 0.85):
        """
        初始化评估器

        Args:
            similarity_threshold: 轮次内容相似度阈值
            final_similarity_threshold: 最终与原始文件相似度阈值
        """
        self.similarity_threshold = similarity_threshold
        self.final_similarity_threshold = final_similarity_threshold

    # ==================== 步骤1: 读取多模型生成结果 ====================
    def load_multi_model_results(self, json_file: str) -> Dict:
        """
        读取多模型生成结果文件

        Args:
            json_file: JSON文件路径

        Returns:
            包含所有必要信息的字典
        """
        with open(json_file, 'r', encoding='utf-8') as f:
            data = json.load(f)

        return {
            'all_results': data.get('all_results', {}),
            'winner': data.get('winner', ''),
            'winner_model': data.get('winner_model', ''),
            'input_file': data.get('input_file', ''),
            'models': data.get('models', {}),
            'json_success': data.get('success', True),  # JSON文件中的success字段
            'judgment': data.get('judgment', {})
        }

    # ==================== 步骤2: 检查轮次数量是否半数以上相同且包含winner ====================
    def check_turn_count_majority(self, all_results: Dict[str, Dict], winner: str) -> Tuple[bool, List[str], int]:
        """
        检查是否有半数以上模型的轮次数量相同，且winner在其中

        Args:
            all_results: 所有模型的解析结果
            winner: winner模型的key

        Returns:
            (是否通过, 轮次数量相同的模型列表, 共识轮次数)
        """
        total_models = len(all_results)
        threshold = total_models / 2

        # 统计每个模型的轮次数
        turn_counts = {}
        for model, result in all_results.items():
            turn_counts[model] = len(result.get('turns', []))

        # 按轮次数分组
        count_to_models = {}
        for model, count in turn_counts.items():
            if count not in count_to_models:
                count_to_models[count] = []
            count_to_models[count].append(model)

        # 找到winner所在的组
        winner_turn_count = turn_counts.get(winner)
        if winner_turn_count is None:
            return False, [], 0

        winner_group = count_to_models.get(winner_turn_count, [])

        # 检查winner所在组是否超过半数
        is_majority = len(winner_group) > threshold

        return is_majority, winner_group, winner_turn_count

    # ==================== 步骤3: 以winner为基准检查内容相似度 ====================
    def _get_turn_content(self, turn: Dict) -> Tuple[str, str]:
        """提取轮次的input和output内容"""
        input_content = ''
        if 'input' in turn:
            input_content = turn['input'].get('content', '')
        elif 'action' in turn:
            input_content = turn['action'].get('content', '')

        output_content = ''
        if 'output' in turn:
            output_content = turn['output'].get('content', '')
        elif 'observation' in turn:
            output_content = turn['observation'].get('content', '')

        return input_content, output_content

    def _calculate_similarity(self, text1: str, text2: str) -> float:
        """计算两个文本的相似度"""
        if not text1 and not text2:
            return 1.0
        if not text1 or not text2:
            return 0.0
        return SequenceMatcher(None, text1, text2).ratio()

    def _calculate_model_similarity(
        self,
        all_results: Dict[str, Dict],
        winner: str,
        model: str,
        turn_count: int
    ) -> float:
        """计算模型与winner所有轮次的平均相似度"""
        winner_turns = all_results[winner].get('turns', [])
        model_turns = all_results[model].get('turns', [])

        total_similarity = 0.0
        count = 0

        for turn_idx in range(turn_count):
            winner_input, winner_output = self._get_turn_content(winner_turns[turn_idx])
            model_input, model_output = self._get_turn_content(model_turns[turn_idx])

            input_sim = self._calculate_similarity(winner_input, model_input)
            output_sim = self._calculate_similarity(winner_output, model_output)

            # 每轮有input和output两个相似度
            total_similarity += input_sim + output_sim
            count += 2

        return total_similarity / count if count > 0 else 0.0

    def check_content_similarity_with_winner(
        self,
        all_results: Dict[str, Dict],
        candidate_models: List[str],
        turn_count: int,
        winner: str
    ) -> Tuple[bool, List[str], Dict[str, float]]:
        """
        以winner为基准，检查有多少模型与winner内容相似

        Args:
            all_results: 所有模型的解析结果
            candidate_models: 轮次数量相同的候选模型列表
            turn_count: 共识轮次数
            winner: winner模型的key

        Returns:
            (是否通过, 与winner相似的模型列表, 各模型相似度)
        """
        total_models = len(all_results)
        threshold = total_models / 2

        # 以winner为基准，计算每个模型与它的平均相似度
        similar_models = [winner]
        model_similarities = {winner: 1.0}

        for model in candidate_models:
            if model == winner:
                continue

            avg_similarity = self._calculate_model_similarity(
                all_results, winner, model, turn_count
            )
            model_similarities[model] = avg_similarity

            if avg_similarity >= self.similarity_threshold:
                similar_models.append(model)

        # 检查相似模型数量是否超过所有模型的半数
        is_majority = len(similar_models) > threshold

        return is_majority, similar_models, model_similarities

    # ==================== 步骤4: 计算winner模型与原始文件的相似度 ====================
    def _reconstruct_text_from_result(self, parse_result: Dict) -> str:
        """从解析结果重建文本"""
        lines = []

        # 添加initial_output
        initial_output = parse_result.get('initial_output', '')
        if initial_output:
            lines.append(initial_output)

        # 处理每个轮次
        for turn in parse_result.get('turns', []):
            prompt = turn.get('prompt', '')
            input_content, output_content = self._get_turn_content(turn)

            # 重建轮次文本
            if prompt:
                lines.append(f"{prompt}{input_content}")
            elif input_content:
                lines.append(input_content)

            if output_content:
                lines.append(output_content)

        return '\n'.join(lines)

    def _normalize_text(self, text: str) -> str:
        """规范化文本用于比较"""
        lines = text.split('\n')
        lines = [line.rstrip() for line in lines]

        # 移除连续空行
        normalized_lines = []
        prev_empty = False
        for line in lines:
            is_empty = len(line.strip()) == 0
            if is_empty and prev_empty:
                continue
            normalized_lines.append(line)
            prev_empty = is_empty

        return '\n'.join(normalized_lines).strip()

    def calculate_final_similarity(
        self,
        winner_result: Dict,
        original_file: str
    ) -> Tuple[bool, float]:
        """
        计算winner模型重建文本与原始文件的相似度

        Args:
            winner_result: winner模型的解析结果
            original_file: 原始txt文件路径

        Returns:
            (是否通过, 相似度分数)
        """
        # 读取原始文件
        with open(original_file, 'r', encoding='utf-8', errors='ignore') as f:
            original_text = f.read()

        # 重建文本
        reconstructed_text = self._reconstruct_text_from_result(winner_result)

        # 规范化
        norm_original = self._normalize_text(original_text)
        norm_reconstructed = self._normalize_text(reconstructed_text)

        # 计算相似度
        similarity = self._calculate_similarity(norm_original, norm_reconstructed)

        is_pass = similarity >= self.final_similarity_threshold

        return is_pass, similarity

    # ==================== 主评估流程 ====================
    def evaluate(self, json_file: str) -> Dict:
        """
        执行完整的评估流程

        Args:
            json_file: 多模型结果JSON文件路径

        Returns:
            评估结果字典
        """
        result = {
            'file': json_file,
            'success': False,
            'fail_reason': None,
            'fail_reason_code': None,
            'details': {}
        }

        # 步骤1: 读取多模型生成结果
        try:
            data = self.load_multi_model_results(json_file)
        except Exception as e:
            result['fail_reason'] = f'读取文件失败: {str(e)}'
            result['fail_reason_code'] = 'file_read_error'
            return result

        all_results = data['all_results']
        winner = data['winner']
        input_file = data['input_file']
        json_success = data['json_success']
        judgment = data['judgment']

        # 检查JSON文件中的success字段
        if not json_success:
            rejection_reason = judgment.get('rejection_reason', '未知原因')
            result['fail_reason'] = f'裁判判定不适合训练: {rejection_reason}'
            result['fail_reason_code'] = 'judge_rejected'
            result['details']['judgment'] = judgment
            return result

        if not all_results:
            result['fail_reason'] = '没有找到模型结果'
            result['fail_reason_code'] = 'no_results'
            return result

        if not winner:
            result['fail_reason'] = '没有找到winner模型'
            result['fail_reason_code'] = 'no_winner'
            return result

        result['details']['total_models'] = len(all_results)
        result['details']['winner'] = winner

        # 步骤2: 检查轮次数量是否半数以上相同且包含winner
        turn_majority_pass, turn_majority_models, consensus_turn_count = \
            self.check_turn_count_majority(all_results, winner)

        result['details']['step2_turn_count'] = {
            'pass': turn_majority_pass,
            'majority_models': turn_majority_models,
            'consensus_turn_count': consensus_turn_count,
            'majority_count': len(turn_majority_models)
        }

        if not turn_majority_pass:
            result['fail_reason'] = f'Winner所在轮次组不过半: {len(turn_majority_models)}/{len(all_results)}个模型'
            result['fail_reason_code'] = 'turn_count_minority'
            return result

        # 步骤3: 以winner为基准检查内容相似度
        content_similarity_pass, similar_models, model_similarities = self.check_content_similarity_with_winner(
            all_results, turn_majority_models, consensus_turn_count, winner
        )

        result['details']['step3_content_similarity'] = {
            'pass': content_similarity_pass,
            'similar_models': similar_models,
            'similar_count': len(similar_models),
            'threshold': self.similarity_threshold,
            'model_similarities': model_similarities
        }

        if not content_similarity_pass:
            result['fail_reason'] = f'与winner相似的模型不过半: {len(similar_models)}/{len(all_results)}个模型'
            result['fail_reason_code'] = 'similar_models_minority'
            return result

        # 步骤4: 计算winner模型与原始文件的相似度
        if not input_file:
            result['fail_reason'] = '没有找到原始文件路径'
            result['fail_reason_code'] = 'no_input_file'
            return result

        winner_result = all_results[winner]
        final_pass, final_similarity = self.calculate_final_similarity(winner_result, input_file)

        result['details']['step4_final_similarity'] = {
            'pass': final_pass,
            'similarity': final_similarity,
            'threshold': self.final_similarity_threshold
        }

        if not final_pass:
            result['fail_reason'] = f'最终相似度不足: {final_similarity:.4f} < {self.final_similarity_threshold}'
            result['fail_reason_code'] = 'low_final_similarity'
            return result

        # 全部通过
        result['success'] = True
        result['fail_reason'] = None

        return result


def _extract_file_id(json_file: str) -> str:
    """从文件路径提取file_id"""
    filename = Path(json_file).stem  # 如 100025_multi
    # 去掉 _multi 后缀
    if filename.endswith('_multi'):
        return filename[:-6]
    return filename


def _save_result(result: Dict, output_dir: str = 'evaluation/result') -> str:
    """保存评估结果到文件，根据成功/失败原因分类保存"""
    # 根据结果决定子目录
    if result['success']:
        sub_dir = 'success'
    else:
        sub_dir = result.get('fail_reason_code') or 'unknown'

    output_path = Path(output_dir) / sub_dir
    output_path.mkdir(parents=True, exist_ok=True)

    file_id = _extract_file_id(result['file'])
    output_file = output_path / f"{file_id}.json"

    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    return str(output_file)


def evaluate_single_file(json_file: str,
                         similarity_threshold: float = 0.9,
                         final_similarity_threshold: float = 0.85,
                         output_dir: str = 'evaluation/result') -> Dict:
    """
    评估单个文件并保存结果

    Args:
        json_file: JSON文件路径
        similarity_threshold: 轮次内容相似度阈值
        final_similarity_threshold: 最终相似度阈值
        output_dir: 结果保存目录

    Returns:
        评估结果
    """
    evaluator = Evaluator(
        similarity_threshold=similarity_threshold,
        final_similarity_threshold=final_similarity_threshold
    )

    result = evaluator.evaluate(json_file)

    # 保存结果到文件
    _save_result(result, output_dir)

    return result


def batch_evaluate(judge_dir: str,
                   output_dir: str = 'evaluation/result',
                   similarity_threshold: float = 0.9,
                   final_similarity_threshold: float = 0.85) -> Dict:
    """
    批量评估目录下的所有文件并保存结果

    Args:
        judge_dir: 包含JSON文件的目录
        output_dir: 结果保存目录
        similarity_threshold: 轮次内容相似度阈值
        final_similarity_threshold: 最终相似度阈值

    Returns:
        汇总结果字典
    """
    judge_path = Path(judge_dir)
    results = []

    evaluator = Evaluator(
        similarity_threshold=similarity_threshold,
        final_similarity_threshold=final_similarity_threshold
    )

    json_files = list(judge_path.glob("*_multi.json"))

    success_count = 0
    fail_counts = {}

    for json_file in json_files:
        result = evaluator.evaluate(str(json_file))
        results.append(result)

        # 保存单个结果
        _save_result(result, output_dir)

        if result['success']:
            success_count += 1
        else:
            reason = result['fail_reason'] or 'Unknown'
            short_reason = reason.split(':')[0] if ':' in reason else reason
            fail_counts[short_reason] = fail_counts.get(short_reason, 0) + 1

    # 汇总结果
    aggregated = {
        'total': len(results),
        'success': success_count,
        'failed': len(results) - success_count,
        'success_rate': success_count / len(results) if results else 0,
        'fail_reasons': fail_counts,
        'results': results
    }

    # 保存汇总结果
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    summary_file = output_path / 'summary.json'

    with open(summary_file, 'w', encoding='utf-8') as f:
        json.dump(aggregated, f, ensure_ascii=False, indent=2)

    return aggregated


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("用法:")
        print("  python -m evaluation.evaluator <json_file>")
        print("  python -m evaluation.evaluator --batch <judge_dir>")
        print("\n选项:")
        print("  --output-dir <dir>        结果保存目录 (默认: evaluation/result)")
        print("  --threshold <value>       轮次内容相似度阈值 (默认: 0.9)")
        print("  --final-threshold <value> 最终相似度阈值 (默认: 0.85)")
        sys.exit(1)

    # 解析参数
    similarity_threshold = 0.9
    final_similarity_threshold = 0.85
    output_dir = 'evaluation/result'

    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == '--threshold' and i + 1 < len(args):
            similarity_threshold = float(args[i + 1])
            args = args[:i] + args[i+2:]
        elif args[i] == '--final-threshold' and i + 1 < len(args):
            final_similarity_threshold = float(args[i + 1])
            args = args[:i] + args[i+2:]
        elif args[i] == '--output-dir' and i + 1 < len(args):
            output_dir = args[i + 1]
            args = args[:i] + args[i+2:]
        else:
            i += 1

    if args[0] == '--batch':
        judge_dir = args[1] if len(args) > 1 else 'data/judge'
        batch_evaluate(
            judge_dir,
            output_dir=output_dir,
            similarity_threshold=similarity_threshold,
            final_similarity_threshold=final_similarity_threshold
        )
    else:
        json_file = args[0]
        evaluate_single_file(
            json_file,
            similarity_threshold=similarity_threshold,
            final_similarity_threshold=final_similarity_threshold,
            output_dir=output_dir
        )
