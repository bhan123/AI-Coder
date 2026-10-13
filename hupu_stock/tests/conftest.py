"""测试配置：把 src/ 加入 PYTHONPATH，让测试可以 import crawler. 等模块。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
