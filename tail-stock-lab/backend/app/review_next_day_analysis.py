"""V1 next-session outcome diagnostics from stored evidence, not causal claims."""
from decimal import Decimal, InvalidOperation

from app.review_analysis import number


ANALYSIS_VERSION = '1.0.0'


def _price(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = Decimal(str(value))
    except InvalidOperation:
        return None
    return parsed if parsed.is_finite() and parsed > 0 else None


def _change(value, base):
    return round(float((value / base - 1) * 100), 4)


def explain_next_day(event):
    """Consume only as-of-filtered evidence already associated with this event."""
    outcome = event.get('next_day_close') or {}
    signal = event.get('trigger_signal') or {}
    calendar = outcome.get('calendar') or {}
    result = {
        'version': ANALYSIS_VERSION, 'method': 'stored_next_session_evidence',
        'scope': 'V1下一计划交易日；推荐价口径与推荐日收盘口径分别比较',
        'target_date': calendar.get('next_date'), 'status': outcome.get('status', 'calendar_unknown'),
        'trigger': {'reason': signal.get('reason') or '首次触发理由未留档',
                    'run_id': event.get('first_run_id'), 'at': event.get('first_at'),
                    'versions': event.get('versions', []), 'factors': signal.get('factors') or []},
        'outcome': {'basis': 'unknown', 'return_pct': None, 'assessment': 'unknown',
                    'session_return_pct': None, 'session_assessment': 'unknown'},
        'facts': [], 'patterns': [], 'hypotheses': [],
        'data_gaps': [{'key': 'corporate_actions_unverified', 'text': '未接除权除息等价格可比性核验；不复权跨日价格变化不能直接当作经济损失或公司利空证据。'}],
        'causality': 'unverified',
        'conclusion': '尚无可比较的次日收盘证据，不能判定下跌或解释其原因。',
        'limitations': [
            '相对首次推荐价的变化与次日相对推荐日收盘的变化不是同一口径，均非实际交易收益。',
            '价格形态只定位预期与结果的偏离，不证明资金出逃、公司利空或板块退潮等成因。',
            '日线高点没有精确发生时刻，不能还原连续走势、首次跌破时间或可成交机会。',
            '不使用推荐当日采样或旧规则模拟退出推断次日走势；未接大模型、新闻与社区。',
            '计划日历不证明临时休市、个股停牌或历史发布可见性。',
        ],
    }
    record = outcome.get('closing_evidence') or {}
    change = outcome.get('close_return_pct')
    if outcome.get('status') != 'close_available' or record.get('conflict') or not number(change):
        result['data_gaps'].append({'key': result['status'], 'text': '次日收盘未就绪、日历未覆盖或证据异常时保留未知，不使用其他日期或模拟退出替代。'})
        return result

    quote = record['quote']
    closed, first = _price(quote['close']), _price(event['first_price'])
    evidence_id = record['evidence_id']
    result['outcome'].update(basis='next_session_close', return_pct=change,
        assessment='below_first' if closed < first else 'above_first' if closed > first else 'at_first')

    def fact(key, text, value=None, ids=None, at=None):
        result['facts'].append({'key': key, 'text': text, 'value_pct': value,
            'evidence_ids': ids or [evidence_id], 'at': at,
            'basis': 'stored_closing_evidence'})

    def pattern(key, text, fact_keys):
        result['patterns'].append({'key': key, 'text': text, 'fact_keys': fact_keys,
            'status': 'observed_pattern_not_cause'})

    fact('next_close_vs_reference', f"次日收盘 {closed:.2f}，相对首次推荐价 {first:.2f} 为 {change:+.2f}%。",
         change, at=quote['price_at'])
    previous = event.get('closing_evidence') or {}
    previous_close = None if previous.get('conflict') else _price(previous.get('quote', {}).get('close'))
    if previous_close is not None:
        session_change = _change(closed, previous_close)
        result['outcome']['session_return_pct'] = session_change
        result['outcome']['session_assessment'] = 'down' if closed < previous_close else 'up' if closed > previous_close else 'flat'
        fact('next_close_vs_signal_close', f"次日收盘相对推荐日收盘 {previous_close:.2f} 变化 {session_change:+.2f}%；不同于相对推荐价的变化。",
             session_change, ids=[previous['evidence_id'], evidence_id], at=quote['price_at'])
    else:
        result['data_gaps'].append({'key': 'signal_close_unavailable', 'text': '推荐日收盘缺失或来源冲突，无法判断次日相对前一收盘的涨跌。'})

    high = _price(quote.get('day_high'))
    if high is not None:
        high_change = _change(high, first)
        fact('next_high_vs_reference', f"次日已存日线最高价 {high:.2f}，相对首次推荐价 {high_change:+.2f}%；高点时刻未知。", high_change)
        if closed < first:
            if high > first:
                pattern('rebound_not_held', '次日曾高于推荐价，但收盘回到推荐价下方，反弹未保持到收盘。',
                        ['next_high_vs_reference', 'next_close_vs_reference'])
            else:
                pattern('no_recovery_above_reference', '次日日线最高价也未超过推荐价，未观察到高于该参考价的修复。',
                        ['next_high_vs_reference', 'next_close_vs_reference'])
    else:
        result['data_gaps'].append({'key': 'next_high_unavailable', 'text': '缺次日日线最高价，无法判断期间是否曾高于推荐价。'})

    snapshot = signal.get('snapshot') or {}
    low_value = snapshot.get('day_low')
    low = _price(low_value) if number(low_value) else None
    if low is not None and low <= first:
        low_change = _change(closed, low)
        fact('next_close_vs_signal_low', f"次日收盘相对推荐时已记录的日内低点 {low:.2f} 变化 {low_change:+.2f}%；这是当时已知低点，不是事后重构支撑位。",
             low_change, at=quote['price_at'])
        result['facts'][-1]['signal_run_id'] = event['first_run_id']
        if closed < low:
            pattern('closed_below_signal_low', '次日收盘低于推荐时的日内低点，原低点位置未保持到次日收盘；首次跌破时刻未知。',
                    ['next_close_vs_signal_low'])
    else:
        result['data_gaps'].append({'key': 'signal_low_unavailable', 'text': '推荐时低点缺失或不一致，不推断原低点是否失守。'})

    session_assessment = result['outcome']['session_assessment']
    if closed < first or session_assessment == 'down':
        result['conclusion'] = '次日收盘低于首次推荐价。以下定位已观察到的偏离形态，真实下跌成因仍待证据核查。'
        if closed >= first:
            position = '仍高于' if closed > first else '等于'
            result['conclusion'] = f'次日收盘{position}推荐价，但低于推荐日收盘：发生了次日价格回落，不等于相对推荐价亏损；回落成因仍待核查。'
            pattern('session_decline_above_reference', '相对推荐日收盘回落，但未跌至推荐价下方。',
                    ['next_close_vs_reference', 'next_close_vs_signal_close'])
        elif session_assessment == 'up':
            result['conclusion'] = '次日收盘低于推荐价，但高于推荐日收盘：相对推荐价仍亏损，不等于股票次日本身下跌。修复为何未收回推荐价仍待核查。'
            pattern('reference_loss_but_session_gain', '次日相对前一收盘上涨，但仍未收回首次推荐价；两个比较基准不能混为一谈。',
                    ['next_close_vs_reference', 'next_close_vs_signal_close'])
        result['hypotheses'] = [
            {'key': 'rebound_persistence', 'question': '推荐后的价格修复在哪个阶段走弱？',
             'required': '次日分钟价格、成交量和均价线，区分低开、盘中回落与缩量弱反弹。'},
            {'key': 'market_sector_changed', 'question': '次日是否有市场或同板块同步走弱？',
             'required': '同一时段指数、当时板块成分与强度序列；原触发时板块强度不能代表次日。'},
            {'key': 'overnight_or_session_event', 'question': '推荐后至次日收盘是否发生可核验的公司或行业事件？',
             'required': '有原文、发布时间及首次采集时间的公告/可靠新闻；不可用无来源的情绪判断代替。'},
        ]
        for item in result['hypotheses']:
            item['status'] = 'needs_evidence'
    else:
        result['conclusion'] = '次日收盘未低于首次推荐价，不给出相对推荐价下跌的原因；不代表盘中无风险或实际交易盈利。'
    return result


def summarize_next_day(events):
    analyses = [event['next_day_analysis'] for event in events]
    outcomes = [item['outcome'] for item in analyses]
    patterns = {}
    for item in analyses:
        for pattern in item['patterns']:
            row = patterns.setdefault(pattern['key'], {'key': pattern['key'], 'text': pattern['text'], 'count': 0})
            row['count'] += 1
    return {
        'analysis_version': ANALYSIS_VERSION, 'event_count': len(events),
        'below_reference_count': sum(item['assessment'] == 'below_first' for item in outcomes),
        'unknown_count': sum(item['assessment'] == 'unknown' for item in outcomes),
        'session_decline_count': sum(item['session_assessment'] == 'down' for item in outcomes),
        'session_unknown_count': sum(item['session_assessment'] == 'unknown' for item in outcomes),
        'unresolved_cause_count': sum(bool(item['hypotheses']) for item in analyses),
        'confirmed_cause_count': 0,
        'patterns': [patterns[key] for key in sorted(patterns)],
        'note': '仅统计次日证据的偏离形态；标签可重叠，不是成因占比或策略胜率。缺证据不计失败。',
    }
