"""Deterministic evidence explanations, never market-causality claims or LLM output."""
from math import isfinite

ANALYSIS_VERSION = '1.0.2'


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value)


def explain_event(event):
    signal = event.get('trigger_signal') or {}
    close, observed = event.get('close_return_pct'), event.get('last_observed_return_pct')
    basis = 'close' if number(close) else 'last_observation' if number(observed) else 'unknown'
    change = close if basis == 'close' else observed if basis == 'last_observation' else None
    scope = '推荐当日；次日结果见独立的V1次日偏离分析' if event['strategy_id'] == 'fishing-reversal' else '首次预警后的当日表现'
    facts = []
    if change is not None:
        label = '收盘' if basis == 'close' else '末次盘中观测（非收盘）'
        facts.append({'text': f'{label}相对首次价变化 {change:+.2f}%。',
                      'basis': basis, 'at': (event.get('closing_evidence') or {}).get('quote', {}).get('price_at') if basis == 'close' else event.get('last_observed_at')})
    else:
        facts.append({'text': '没有可验证的后续价格，不能判定涨跌或策略成功。', 'basis': 'unknown'})
    if event.get('post_alert_limit') is not None:
        facts.append({'text': '已有预警后触板证据。' if event['post_alert_limit'] else '有效证据未显示预警后触板。', 'basis': 'closing_evidence'})
    path = event.get('post_signal_path') or {}
    if path.get('sample_count'):
        facts.append({'text': f"预警后{path['sample_count']}个有效时点的采样价格，相对首次价最高 {path['max_return_pct']:+.2f}%，最低 {path['min_return_pct']:+.2f}%；不是连续行情的真实极值。", 'basis':'stored_samples'})
        if path.get('first_below_at'):
            facts.append({'text':'首次观测到价格低于首次价（实际跌破可能发生于采样间隔内）。', 'at':path['first_below_at'], 'basis':'stored_samples'})
        if number(change) and change < 0 and path['max_return_pct'] > 0:
            facts.append({'text':'采样记录显示预警后曾高于首次价，随后所选结果低于首次价，属于已观察到的冲高回落；其成因仍待验证。', 'basis':'stored_samples', 'pattern':'sampled_gain_reversed'})
    hypotheses = []
    if change is not None and change < 0:
        hypotheses = [
            {'key': 'momentum_faded', 'question': '触发时的价格强势/止跌是否随后失效？', 'required': '预警后连续分钟价格、成交量与均价线；仅末次价无法定位转弱时刻。'},
            {'key': 'market_sector_changed', 'question': '是否受到市场或同板块同步走弱影响？', 'required': '同时间段指数、行业成分与强度序列；初次板块强度不能证明后续退潮。'},
            {'key': 'event_risk', 'question': '期间是否出现可核验的公司或行业事件？', 'required': '有发布时间的公告/新闻原文及可靠来源；社区情绪不等于事实。'},
        ]
        for item in hypotheses:
            item['status'] = 'needs_evidence'
    return {
        'version': ANALYSIS_VERSION, 'method': 'stored_evidence_rules', 'scope': scope,
        'trigger': {'reason': signal.get('reason') or '首次触发理由未留档',
                    'run_id': event.get('first_run_id'), 'at': event.get('first_at'),
                    'versions': event.get('versions', []), 'factors': signal.get('factors') or []},
        'outcome': {'basis': basis, 'return_pct': change,
                    'assessment': 'below_first' if change is not None and change < 0 else 'not_below_first' if change is not None else 'unknown'},
        'facts': facts, 'hypotheses': hypotheses, 'causality': 'unverified',
        'conclusion': '观察到价格低于首次价，但现有证据不能确定下跌原因。' if hypotheses else '这里只核对已发生结果，不推断因果或保证后续走势。',
        'limitations': ['触发评分是规则分，不是涨停概率。', '未接大模型、新闻和社区情绪分析；不使用当前参数反推旧版本触发条件。', '价格变化不是可执行交易收益，未计成交、费用和持有约束。'],
    }


def summarize_review(events):
    closes = [event['close_return_pct'] for event in events if number(event.get('close_return_pct'))]
    return {'analysis_version': ANALYSIS_VERSION, 'close_valid_count': len(closes),
            'close_down_count': sum(value < 0 for value in closes),
            'close_flat_count': sum(value == 0 for value in closes),
            'close_up_count': sum(value > 0 for value in closes),
            'close_unknown_count': len(events) - len(closes),
            'conclusion': f'共{len(events)}个去重事件；{len(closes)}个有可比较收盘结果，{len(events)-len(closes)}个仍未知。样本与证据不足时不推断策略优劣。',
            'next_checks': ['优先补齐未知收盘及真实涨停价证据。', '下跌个股逐条核对分钟走势、市场板块和事件来源，未证实原因保持未知。', '按策略版本积累后续样本验证，不因单日表现自动调整策略。']}
