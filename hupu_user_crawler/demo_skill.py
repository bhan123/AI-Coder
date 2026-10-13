"""端到端测试：加载模板，填入模拟数据，输出可粘贴到 Claude 的完整 prompt。"""
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")


def demo():
    print("=" * 70)
    print("端到端测试：模拟用户调用 hupu-stock-recap skill")
    print("=" * 70)
    print()

    # 模拟用户输入
    user_market = """- 上证指数：3890 点（+0.8%，+30 点）
- 深成指：12500 点（+1.2%，+150 点）
- 创业板：2680 点（+1.5%，+40 点）
- 成交量：2.5 万亿（较 5 日均 +20%，显著放量）
- 北向资金：净流入 85 亿
- 涨跌停比：78:5
- 领涨板块：半导体 +3.2%、PCB +2.8%、机器人 +2.1%
- 持仓表现：
  - 沪电股份 +4.5%（14.5% → 15.15%）
  - 石头科技 +1.2%
  - 国芳集团 +0.8%
  - 大元泵业 +0.5%
  - 科创 50ETF +1.8%"""

    # Step 1: 选模板
    print("Step 1: 模板选择（按 selector.md 决策树）")
    print("-" * 70)
    print("  - 时点 = 收盘后")
    print("  - 大盘 +0.8%（涨幅 > 0.5%）")
    print("  - 量能放量、跌停少 → 满足「反弹修复」条件")
    print("→ 选模板: 01_bounce_recovery")
    print()

    # Step 2: 加载模板并提取「调用 prompt」段
    print("Step 2: 加载模板并提取「调用 prompt」段")
    print("-" * 70)
    template_path = Path("skill/templates/01_bounce_recovery.md")
    content = template_path.read_text(encoding="utf-8")
    # 提取 ## 调用 prompt 到 ## 反模式 之间的内容
    m = re.search(r"## 调用 prompt\n+(.+?)\n## 反模式", content, re.DOTALL)
    if not m:
        print("找不到「调用 prompt」段")
        return
    template_prompt = m.group(1).strip()
    print(f"模板 prompt 长度: {len(template_prompt)} 字符")
    print()

    # Step 3: 替换占位符
    print("Step 3: 填入今日数据")
    print("-" * 70)
    final_prompt = template_prompt.replace(
        "{用户输入：今日指数点位/涨跌、成交量、北向资金、热点板块、持仓股行情}",
        user_market,
    ).replace(
        "[此处插入上面两个示例的全文]",
        "[完整 0804 复盘 + 0805 复盘已在模板上方列出，此处省略以节省 token]"
    )
    print("✓ 数据已填入")
    print()

    # Step 4: 显示完整 prompt
    print("Step 4: 完整 prompt（可粘贴到 Claude API/claude.ai）")
    print("=" * 70)
    print(final_prompt)
    print("=" * 70)
    print()
    print(f"总字数: {len(final_prompt)} 字符")
    print(f"折合 token 约: {len(final_prompt) // 3} tokens")
    print()
    print("把这个 prompt 粘到 Claude 对话框（或 Claude API），就能得到风格化复盘。")


if __name__ == "__main__":
    demo()
