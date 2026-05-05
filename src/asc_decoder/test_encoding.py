#!/usr/bin/env python3
"""
测试DBC文件编码检测脚本
"""
import sys
import os

# 添加src/asc目录到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'asc'))

from encoding_utils import fix_mixed_encoding, contains_obvious_gibberish


def test_dbc_encodings(dbc_path):
    """测试不同编码加载DBC文件的效果"""
    print(f"🔍 正在测试DBC文件: {dbc_path}")
    print("=" * 60)
    
    try:
        import cantools
    except ImportError:
        print("⚠️  cantools模块未安装，跳过DBC加载测试")
        return
    
    # 尝试用不同编码加载
    encodings_to_try = ['utf-8', 'gbk', 'gb2312', 'gb18030', 'cp1252']
    
    for encoding in encodings_to_try:
        print(f"\n📝 尝试编码: {encoding}")
        try:
            db = cantools.database.load_file(dbc_path, strict=False, encoding=encoding)
            
            # 检查是否有中文内容
            has_chinese = False
            sample_signals = []
            
            for msg in db.messages[:5]:  # 只检查前5个消息
                for signal in msg.signals[:3]:  # 只检查前3个信号
                    # 检查信号名称
                    if any('\u4e00' <= c <= '\u9fff' for c in signal.name):
                        has_chinese = True
                        sample_signals.append(('信号名称', signal.name))
                    
                    # 检查信号单位
                    if signal.unit and any('\u4e00' <= c <= '\u9fff' for c in signal.unit):
                        has_chinese = True
                        sample_signals.append(('单位', signal.unit))
                    
                    # 检查choices（如果有）
                    if signal.choices:
                        for val, desc in list(signal.choices.items())[:3]:
                            if desc and any('\u4e00' <= c <= '\u9fff' for c in str(desc)):
                                has_chinese = True
                                sample_signals.append(('choices', str(desc)))
            
            if has_chinese:
                print("   ✅ 发现中文字符，内容如下:")
                for type_name, content in sample_signals[:5]:
                    print(f"      [{type_name}] {content}")
            else:
                print("   ℹ️  未发现中文字符")
                
        except Exception as e:
            print(f"   ❌ 加载失败: {type(e).__name__}: {str(e)[:100]}")


def test_decoding_with_fix():
    """测试乱码修复功能"""
    print("=" * 60)
    print("🧪 测试乱码修复功能")
    
    # 测试包含乱码的字符串
    test_cases = [
        ('正常中文测试', '正常字符串'),
        ('锟斤拷锟斤拷', 'UTF-8误解码为GBK'),
    ]
    
    for text, desc in test_cases:
        has_gibberish = contains_obvious_gibberish(text)
        fixed = fix_mixed_encoding(text)
        print(f"\n   原始: {text} ({desc})")
        print(f"   是否乱码: {has_gibberish}")
        print(f"   修复后: {fixed}")


if __name__ == "__main__":
    # 始终运行乱码修复测试
    test_decoding_with_fix()
    
    if len(sys.argv) < 2:
        print("\n" + "=" * 60)
        print("用法: python test_encoding.py <dbc_file_path>")
        print("=" * 60)
        sys.exit(0)
    
    dbc_path = sys.argv[1]
    
    if not os.path.exists(dbc_path):
        print(f"❌ 文件不存在: {dbc_path}")
        sys.exit(1)
    
    print("\n" + "=" * 60)
    test_dbc_encodings(dbc_path)
