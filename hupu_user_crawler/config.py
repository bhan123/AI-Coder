"""集中配置：目标用户、限速、User-Agent 等。

如需切换抓取目标用户 / 板块，只改这里即可。
"""
from __future__ import annotations

HUPU_BASE = "https://bbs.hupu.com"
TARGET_BOARD = "stock"

# 目标用户："巴萨主教练弗里克"，虎扑个人主页 https://my.hupu.com/19134213076193
TARGET_USER_ID = "19134213076193"
TARGET_USER_NAME = "巴萨主教练弗里克"

# 限速：单次 GET 间隔随机 3-5 秒（参考 hupu-sector-crowding 设计文档 §9.3）
MIN_INTERVAL_SECONDS = 3.0
MAX_INTERVAL_SECONDS = 5.0

# 重试 / 超时
HTTP_TIMEOUT_SECONDS = 15.0
MAX_RETRIES = 3

# 默认抓取页数：50 页 × ~50 帖 ≈ 2500 条最近帖子
DEFAULT_MAX_PAGES = 50

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)

# Cookie 鉴权（用于抓取登录后可见的页面，如个人主页 https://my.hupu.com/{uid}）
# 通过环境变量 HUPU_COOKIE 传入，例如：
#   export HUPU_COOKIE="csrfToken=...; acw_tc=...; u=...; ..."
# 也可以通过 --cookie 参数传入。**严禁写入 git。**
import os
HUPU_COOKIE = os.environ.get("HUPU_COOKIE", "")
