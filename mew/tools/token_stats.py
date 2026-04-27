"""本地 Token 统计脚本 - python tools/token_stats.py"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.token_commands import get_token_stats
if __name__ == "__main__":
    print(get_token_stats())
