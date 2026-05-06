"""
杂项工具服务
============
不属于其它分类的小工具
"""

from __future__ import annotations

import json
import random


def api_roll(min_val: int = 1, max_val: int = 100) -> str:
    """投骰子"""
    if min_val > max_val:
        min_val, max_val = max_val, min_val
    result = random.randint(min_val, max_val)
    return json.dumps({
        "min": min_val,
        "max": max_val,
        "result": result,
    }, ensure_ascii=False)
