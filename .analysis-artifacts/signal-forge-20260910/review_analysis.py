"""Read-only assessment of existing Signal Forge review evidence; no tuning/deployment."""
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from statistics import mean, median, correlation
from urllib.request import urlopen
import hashlib
import json
import math

BASE = 'https://hermes-content-review.taild890b1.ts.net:10000'
START, END = '2026-08-24', '2026-09-09'
OUTPUT = Path(__file__).parent

def extract():
    records, metadata = [], []
    for strategy in ['fishing-reversal', 'limit-up-ambush']:
        url = f'{BASE}/api/review/summary?strategy_id={strategy}&date_from={START}&date_to={END}'
        with urlopen(url, timeout=60) as response:
            raw = response.read()
            report = json.loads(raw)
        metadata.append({'url': url, 'as_of': report['as_of'], 'version': report['calculation_version'],
                         'response_sha256': hashlib.sha256(raw).hexdigest(), 'events': report['event_count'],
                         'metrics': report['metrics'], 'next_day_metrics': report.get('next_day_metrics'),
                         'coverage': report.get('coverage')})
        for event in report['events']:
            analysis = event.get('next_day_analysis') or {}
            next_day = event.get('next_day_close') or {}
            records.append({
                **{k: event.get(k) for k in ['event_id','date','code','name','first_at','first_score','first_price',
                    'first_run_id','versions','close_return_pct','close_positive','close_limit','post_alert_limit',
                    'quality_flags','post_signal_path']},
                'strategy': strategy, 'factors': {f['key']: f.get('value') for f in event['trigger_signal']['factors']},
                'snapshot': event['trigger_signal']['snapshot'],
                'next_day_status': next_day.get('status'), 'next_day_return_pct': analysis.get('outcome',{}).get('return_pct'),
                'next_day_target': analysis.get('target_date'), 'next_day_patterns': [p['key'] for p in analysis.get('patterns',[])],
                'next_day_data_gaps': analysis.get('data_gaps'),
            })
    result = {'metadata': metadata, 'records': records}
    (OUTPUT/'review-extract.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return result

def describe(rows, target):
    values = [r[target] for r in rows if isinstance(r.get(target),(int,float)) and not isinstance(r[target],bool) and math.isfinite(r[target])]
    return {'events':len(rows),'days':len({r['date'] for r in rows}), 'securities':len({r['code'] for r in rows}),
            'known':len(values),'unknown':len(rows)-len(values),'up':sum(x>0 for x in values),
            'up_pct':round(100*sum(x>0 for x in values)/len(values),2) if values else None,
            'mean_pct':round(mean(values),4) if values else None,'median_pct':round(median(values),4) if values else None,
            'min_pct':min(values) if values else None,'max_pct':max(values) if values else None}

def compute(data):
    results = {}
    for strategy in ['fishing-reversal','limit-up-ambush']:
        rows=[r for r in data['records'] if r['strategy']==strategy]
        target='next_day_return_pct' if strategy=='fishing-reversal' else 'close_return_pct'
        assert len(rows)==len({(r['strategy'],r['date'],r['code']) for r in rows})
        by_day={day:describe([r for r in rows if r['date']==day],target) for day in sorted({r['date'] for r in rows})}
        correlations={}
        for key in ['first_score']+sorted({key for r in rows for key in r['factors']}):
            pairs=[(r['first_score'] if key=='first_score' else r['factors'].get(key),r.get(target)) for r in rows]
            pairs=[p for p in pairs if all(isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) for v in p)]
            if len(pairs)>2 and len({p[0] for p in pairs})>1 and len({p[1] for p in pairs})>1:
                correlations[key]={'n':len(pairs),'pearson':round(correlation([p[0] for p in pairs],[p[1] for p in pairs]),3)}
        # Fixed score bands chosen before looking at their outcomes; descriptive only.
        cuts={}
        for label,fn in [('score_lt75',lambda r:r['first_score']<75),('score_75_85',lambda r:75<=r['first_score']<85),('score_ge85',lambda r:r['first_score']>=85),
                         ('morning',lambda r:int(r['first_at'][11:13])<12),('afternoon',lambda r:int(r['first_at'][11:13])>=12),
                         ('board10',lambda r:not r['code'].startswith(('300','301','688'))),('board20',lambda r:r['code'].startswith(('300','301','688'))),
                         ('early_period',lambda r:r['date']<='2026-09-01'),('late_period',lambda r:r['date']>='2026-09-02')]:
            cuts[label]=describe([r for r in rows if fn(r)],target)
        late_rows=[r for r in rows if r['date']>='2026-09-02']
        cuts['late_score_lt75']=describe([r for r in late_rows if r['first_score']<75],target)
        cuts['late_score_ge85']=describe([r for r in late_rows if r['first_score']>=85],target)
        patterns=Counter(p for r in rows for p in r['next_day_patterns'])
        results[strategy]={'scope':{'start':START,'end':END,'target':target},'overall':describe(rows,target),
                           'versions':dict(Counter(tuple(r['versions']) for r in rows)), 'by_day':by_day,'cuts':cuts,
                           'correlations_exploratory_not_causal':correlations,
                           'quality_flags':dict(Counter(f for r in rows for f in r['quality_flags'])),
                           'unknown_next_day_status':dict(Counter(r['next_day_status'] for r in rows if r.get(target) is None)),
                           'patterns':dict(patterns)}
        results[strategy]['versions']={'/'.join(k):v for k,v in results[strategy]['versions'].items()}
        # Independent denominator reconciliation against the live review response.
        meta=next(m for m in data['metadata'] if strategy in m['url'])
        metric=(meta['next_day_metrics'] if strategy=='fishing-reversal' else meta['metrics'])['close_positive_rate']
        assert results[strategy]['overall']['known']==metric['eligible_count']
        assert results[strategy]['overall']['up']==metric['success_count']
        assert results[strategy]['overall']['unknown']==metric['unknown_count']
    return results

if __name__=='__main__':
    data=extract()
    results=compute(data)
    (OUTPUT/'analysis-results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(results,ensure_ascii=False,indent=2))
