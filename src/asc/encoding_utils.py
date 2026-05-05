"""
字符编码检测与处理工具
用于处理CAN信号解码中的中文乱码问题
"""


def safe_decode_string(value, source_encoding='utf-8') -> str:
    """
    安全解码字符串，处理可能的编码问题
    
    Args:
        value: 输入值（可能是字符串或字节）
        source_encoding: 源编码
    
    Returns:
        解码后的Unicode字符串
    """
    if value is None:
        return ""
    
    # 如果已经是字符串，直接返回
    if isinstance(value, str):
        return value
    
    # 如果是字节，尝试解码
    if isinstance(value, bytes):
        # 先尝试指定的编码
        try:
            return value.decode(source_encoding)
        except (UnicodeDecodeError, LookupError):
            pass
        
        # 尝试常见编码
        for encoding in ['utf-8', 'gbk', 'gb2312', 'gb18030']:
            try:
                return value.decode(encoding)
            except (UnicodeDecodeError, LookupError):
                continue
        
        # 如果所有编码都失败，使用replace模式
        return value.decode('utf-8', errors='replace')
    
    # 其他类型转为字符串
    return str(value)


def fix_mixed_encoding(text: str) -> str:
    """
    修复混合编码导致的乱码（如UTF-8被错误解码为GBK后又被编码）
    
    常见场景：
    1. UTF-8字符串 → 错误解码为GBK → 再编码为UTF-8 = 乱码
    2. 修复后：乱码字符串 → 编码为UTF-8字节 → 解码为GBK = 原始UTF-8字符串
    
    Args:
        text: 可能包含乱码的字符串
    
    Returns:
        修复后的字符串
    """
    if not isinstance(text, str):
        return str(text)
    
    # 检查是否需要修复
    if not contains_obvious_gibberish(text):
        return text
    
    try:
        # 尝试修复：UTF-8 → GBK → UTF-8 的错误转换
        # 乱码 = original_utf8.encode('utf-8').decode('gbk')
        # 修复 = gibberish.encode('utf-8').decode('gbk')
        bytes_data = text.encode('utf-8', errors='ignore')
        for encoding in ['gbk', 'gb2312', 'gb18030']:
            try:
                decoded = bytes_data.decode(encoding)
                # 检查修复后是否看起来更合理（不再包含明显乱码）
                if not contains_obvious_gibberish(decoded):
                    return decoded
            except UnicodeDecodeError:
                continue
    except Exception:
        pass
    
    return text


def contains_obvious_gibberish(text: str) -> bool:
    """
    检测字符串是否包含明显的乱码字符
    
    Args:
        text: 待检测字符串
    
    Returns:
        是否包含乱码
    """
    if not isinstance(text, str):
        return False
    
    # 常见的UTF-8误解码为GBK产生的乱码字符
    gibberish_patterns = [
        '锟斤拷', '烫烫烫', '圻埑', '鍗曟', '閲嶅', '鏂囦',
        '涓', '浜嬫', '鎻忚', '闈炲', '姹傚', '浣跨',
        '棰戦', '鑾峰', '寮傚', '鎵嬫', '鏄庢', '鍏舵',
        '鈥�', '绗�', '鍦�', '涓�', '鐩�', '鏄�',
        '浜�', '鎴�', '閲�', '闈�', '姹�', '浣�',
    ]
    
    for pattern in gibberish_patterns:
        if pattern in text:
            return True
    
    return False


def try_decode_with_multiple_encodings(value) -> str:
    """
    尝试用多种编码解码值
    
    Args:
        value: 输入值
        
    Returns:
        解码后的字符串
    """
    if value is None:
        return ""
    
    if isinstance(value, str):
        # 先尝试修复混合编码问题
        fixed = fix_mixed_encoding(value)
        if fixed != value:
            return fixed
        return value
    
    if isinstance(value, bytes):
        # 尝试多种编码
        for encoding in ['utf-8', 'gbk', 'gb2312', 'gb18030']:
            try:
                decoded = value.decode(encoding)
                # 如果解码结果看起来合理（不包含乱码），返回它
                if not contains_obvious_gibberish(decoded):
                    return decoded
            except UnicodeDecodeError:
                continue
        
        # 如果所有编码都失败，使用replace模式
        return value.decode('utf-8', errors='replace')
    
    return str(value)
