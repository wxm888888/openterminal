"""
测试脚本：不调用大模型，只测试终端解析功能
"""
import sys
import json
from terminal_parser import TerminalParser

def test_parser(file_path):
    """测试解析器是否能正确识别每一轮交互"""
    parser = TerminalParser()
    
    print(f"正在解析文件: {file_path}")
    print("="*70)
    
    parsed_data = parser.parse_file_line_by_line(file_path)
    
    # 显示初始内容
    if parsed_data['initial_output']:
        print(f"\n【初始内容】 ({len(parsed_data['initial_output'])} 字符)")
        print(parsed_data['initial_output'][:200])
        if len(parsed_data['initial_output']) > 200:
            print("...")
    
    # 显示每一轮的解析结果
    print(f"\n\n【共发现 {len(parsed_data['turns'])} 轮交互】")
    print("="*70)
    
    for turn in parsed_data['turns']:
        print(f"\n轮次 {turn['turn_id']}:")
        print(f"  原始提示符行: {turn['action']['raw_prompt_line']}")
        print(f"  提取的命令: {turn['action']['content']}")
        print(f"  输出行数: {len(turn['observation']['raw_output_lines'])}")
        print(f"  是否有错误: {turn['metadata']['has_error']}")
        
        if turn['observation']['content']:
            print(f"  命令输出预览:")
            output_preview = turn['observation']['content'][:200]
            print(f"    {output_preview.replace(chr(10), chr(10) + '    ')}")
            if len(turn['observation']['content']) > 200:
                print("    ...")
        else:
            print(f"  命令输出: (无输出)")
        
        print(f"  原始行数: {len(turn['raw_lines'])}")
        print("-"*70)
    
    # 保存到JSON文件
    output_path = file_path.replace('.txt', '_parsed.json').replace('raw/txt', 'analyzed')
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(parsed_data, f, ensure_ascii=False, indent=2)
    
    print(f"\n✓ 解析结果已保存到: {output_path}")
    return parsed_data

if __name__ == "__main__":
    if len(sys.argv) > 1:
        file_path = sys.argv[1]
    else:
        file_path = 'data/raw/txt/7016.txt'
    
    test_parser(file_path)
