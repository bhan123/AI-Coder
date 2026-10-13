"""Build a source-backed assessment and execute its audit notebook; no production writes."""
from pathlib import Path
from datetime import datetime, timezone
import json
import hashlib
import os

ROOT = Path(__file__).parent
os.environ['IPYTHONDIR'] = str(ROOT / '.ipython')
os.environ['JUPYTER_RUNTIME_DIR'] = str(ROOT / '.jupyter-runtime')
import nbformat
from nbclient import NotebookClient
from review_analysis import compute
from review_sql_views import query_views, ALERT_SQL, BAND_SQL

ROOT = Path(__file__).parent
data = json.loads((ROOT / 'review-extract.json').read_text(encoding='utf-8'))
results = compute(data)
v1, ambush = (results[s] for s in ['fishing-reversal', 'limit-up-ambush'])
assert results == json.loads((ROOT / 'analysis-results.json').read_text(encoding='utf-8'))
assert all(r['code'][:3] in {'000','001','002','003','300','301','600','601','603','605','688'} for r in data['records'])
generated = datetime.now(timezone.utc).isoformat()
title = 'Signal Forge Strategy Review'
sections = [
    ('title', '# ' + title, False),
    ('summary', '''## Executive Summary

现有复盘已经能定位值得试验的优化方向，但尚未证明任何新规则能稳定提高成功率。本轮仅分析，不改线上参数。

范围：2026-08-24 至 2026-09-09；按“策略＋日期＋股票”保留首次正式预警，重复命中不重复计样本。

- 涨停伏击：351 条预警、12 个有信号日期、279 只股票。收盘高于首次预警价的比例为 143/351＝40.74%，平均价格变化 -0.61%，中位数 -0.37%。
- V1 尾盘选股：30 条推荐，其中 28 条已取得次日收盘、2 条尚未到次日收盘。次日收盘高于推荐价的比例为 12/28＝42.86%，平均 +0.05%，中位数 -0.49%。
- 两种策略的观察期限不同，不能按这些比例直接比较谁更好。这些都是参考价格变化，不是可成交、扣费后的交易收益。''', True),
    ('scores', '''## 高评分尚未转化为更好的后续表现

涨停伏击按首次评分分组，低于 75 分、75 至不足 85 分、85 分及以上的上涨比例分别为 42.41%、38.67%、41.86%；平均价格变化分别为 -0.20%、-0.81%、-1.39%。高分组没有显示更稳定的优势。

首次评分与收盘相对预警价变化的 Pearson 相关为 -0.175；短时价格动量为 -0.258。这只是已筛选样本中的探索性相关，可能受日期、板块及触发位置共同影响，不能推导“分数越低越好”或“上涨动量导致亏损”。

下图每个点对应一条股票日预警，不使用事后最高评分或最终命中次数。''', True),
    ('regime', '''## 需要区分触发问题和行情依赖

涨停伏击在 8 月 24 日至 9 月 1 日的上涨比例为 89/189＝47.09%；9 月 2 日至 9 日为 54/162＝33.33%。后半段即使仅保留 75 分以下，仍只有 19/57＝33.33%。直接删掉高分预警，并没有在后半段自动提升上涨比例。

上午与下午首次预警的上涨比例接近：40.69% 与 40.83%。现有结果不支持简单地取消上午扫描。前后时段比较均属于已见数据的描述，不是独立样本外验证。不能据此认定行情已被证明是下跌原因。

V1 的 16 条次日收盘低于推荐价的记录中，11 条次日最高价曾超过推荐价，但没有保持到收盘；5 条次日最高价未超过推荐价。其中 4 条收盘还低于推荐时已知的日内低点，属于重叠标签。它们定位的是走势偏离形态，不是已证实的下跌成因。''', True),
    ('actions', '''## 建议的优化顺序

1. **先补齐评价标签。** 将预警后触及涨停、收盘封板、收盘高于首次预警价分开统计；补精确历史涨停价、触板时序、交易日历和数据缺口。V1 固定推荐价到下一交易日收盘的主口径，另列次日最高与最低变化。
2. **优先试验涨停伏击的评分与触发位置。** 原评分奖励强度和短时加速，可试验对过快拉升、离均价线过远的降级，以及回踩后再次确认。但均价线、回踩量能需要补分钟证据；仅凭现有结果无法验证这些新条件。
3. **按行情、板块和时间检查稳定性。** 当前已有市场广度、板块联动和连续快照动量过滤；应检验其实际区分能力，不重复添加同名规则。候选规则在同一批原始输入上与旧版对照。
4. **V1 先收集更多完整次日样本。** 把“低点失守”和“反弹未保持”用于诊断分类；要变成事前过滤条件，必须找到推荐当时可取得的特征并在未来验证，不能把次日结果反填为输入。
5. **建立冻结版本的旁路实验。** 先保留原策略，只并行记录少量候选版本；按完整日期划分验证期，固定方案后积累未见过的未来数据。同步考核上涨比例、平均与中位变化、下行尾部、预警数量和漏掉的赢家，不靠减少预警数美化成功率。

大模型可以补充带来源与时间戳的事件、公告和舆情标签，作为可验证特征；不能把事后解释当作因果证据，也不应直接替代价格、成交量和标签质量验证。''', False),
    ('limits', '''## 证据边界与待解决问题

- 所有 351 条涨停伏击记录的精确涨停价均标为未知；因此不能把 40.74% 宣称为涨停成功率，也不能把未知当作失败。
- 样本仅覆盖 12 个有涨停预警的日期；同日、同行业和同一股票跨日的记录相关，不能按 351 次独立试验估计可信度。
- V1 28 条成熟结果来自 10 个有信号日期；9 月 9 日两条推荐在本次 9 月 10 日凌晨取数时，仍处于次日尚未收盘状态。
- 已保存策略版本：V1 1.1.0、涨停伏击 0.2.0；但逐次配置快照和正式发布时间均标为未知，不能完整还原历史参数及用户实际看到信号的延迟。
- 交易日历未验证。缺运行证据的日期不自动视为无信号或休市；8 月 24 日只有一条涨停预警，也不能据此声称整日覆盖完整。
- 当前分析只有已入选股票的复盘结果，适合检验保留或降级现有信号，不能可靠评估放宽条件后新增股票、全市场漏报率或完全不同策略。
- 不含买卖成交、滑点与费用；非利润承诺。只提高上涨比例可能损失收益幅度或错过少数大涨样本。''', True),
    ('method', '''## 核验方法与复现

只读取得线上 `/api/review/summary` 的两种策略报告，取数时点为 2026-09-10 01:44（北京时间）。使用正式实时、定时采集、可执行运行中的入选信号，以策略＋日期＋股票去重；保留首次价格、首次评分及其当时因子。

价格变化＝（目标收盘价／首次预警价－1）×100%。上涨比例＝目标收盘价高于首次价格的记录数／目标收盘证据已知的记录数。平均值等权按股票日计算；未知结果不进入分母、但单独披露。V1 目标为次一已关联交易日，涨停伏击目标为当日。

已校验：复合键唯一；提取数量与源报告一致；两种策略的已知、未知、上涨数量均与线上复盘指标一致；执行笔记本可从冻结快照复算相同结果。源响应 SHA-256 和时间戳保存在 `review-extract.json`；分析脚本不改源数据库。

下表是按首次预警时间、代码确定顺序的前 10 条涨停预警，供核对数据粒度；完整数据保存在复核材料中。''', True),
    ('research', '''## 方法参考

反复尝试评分权重或阈值，会把有限历史数据中的偶然性拟合成看似有效的策略。因此应记录全部尝试、冻结候选规则并保留真正未见过的未来验证数据。本报告没有估计过拟合概率，也没有把探索分组当成胜率提升证据。[Bailey 等：The Probability of Backtest Overfitting](https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf)''', False),
]

rows = sorted((r for r in data['records'] if r['strategy']=='limit-up-ambush'),key=lambda r:(r['first_at'],r['code']))
scatter = [{'point':r['date']+' '+r['code'], 'date':r['date'], 'code':r['code'], 'name':r['name'],
            'first_at':r['first_at'],'first_score':r['first_score'], 'first_price':r['first_price'],
            'close_return_pct':r['close_return_pct'], 'version':'/'.join(r['versions']),
            'sample_size':1,'turnover_rate':r['snapshot']['turnover_rate'],
            'board':'创业板/科创板' if r['code'].startswith(('300','301','688')) else '主板'} for r in rows]
bands = [{'band':label,'n':ambush['cuts'][key]['known'],'up':ambush['cuts'][key]['up'],
          'up_pct':ambush['cuts'][key]['up_pct'],'mean_pct':ambush['cuts'][key]['mean_pct'],
          'median_pct':ambush['cuts'][key]['median_pct'],'order':i}
         for i,(key,label) in enumerate([('score_lt75','低于 75'),('score_75_85','75 至不足 85'),('score_ge85','85 及以上')])]
sql_alerts, sql_bands = query_views(data)
assert sql_alerts == scatter
for expected, actual in zip(bands, sql_bands, strict=True):
    assert all(expected[k] == actual[k] for k in ['band','n','up','up_pct','mean_pct'])
scatter = sql_alerts
bands = sql_bands
source = {'id':'review-export','label':'Signal Forge 正式复盘 API 冻结快照',
          'href':'https://hermes-content-review.taild890b1.ts.net:10000/#review-center',
          'query':{'language':'python','engine':'Python 3',
                   'sql':"import json\nfrom pathlib import Path\nfrom review_analysis import compute\ndata = json.loads(Path('review-extract.json').read_text(encoding='utf-8'))\nresults = compute(data)\nprint(results)",
                   'description':'GET 两个策略的 review/summary，冻结响应提取；复算首次预警到目标收盘的价格变化和描述性分组。',
                   'tables_used':['strategy_runs','strategy_signals','alert_events','alert_event_points','closing_evidence'],
                   'filters':{'date_from':'2026-08-24','date_to':'2026-09-09','mode':'live','capture_origin':'scheduled','execution_status':'tradable','eligible':True},
                   'metric_definitions':{'close_return_pct':'100 * (target_close / first_price - 1); not trading P&L',
                       'positive_rate':'count(target_close > first_price) / count(known target_close)',
                       'grain':'strategy + date + code; first alert only'},
                   'api_responses':data['metadata']}}
blocks=[]
for key,body,backed in sections:
    blocks.append({'id':key,'type':'markdown','body':body,**({'sourceId':'review-export'} if backed else {})})
    if key=='scores':
        blocks += [{'id':'scores-table','type':'table','tableId':'bands'}, {'id':'scores-chart','type':'chart','chartId':'score-return'}]
    if key=='method':
        blocks.append({'id':'sample-table','type':'table','tableId':'sample'})
manifest={'version':1,'surface':'report','title':title,'generatedAt':generated,'blocks':blocks,'sources':[source],
    'charts':[{'id':'score-return','title':'首次评分与当日收盘相对预警价变化',
               'description':'高评分没有呈现明确的后续上涨优势；关联不代表因果。',
               'type':'scatter','dataset':'alerts','sourceId':'alert-sql',
               'encodings':{'x':{'field':'first_score','label':'首次评分'},'y':{'field':'close_return_pct','label':'到收盘变化（%）'},'label':{'field':'point'}}}],
    'tables':[{'id':'bands','title':'涨停伏击首次评分分组','dataset':'bands','sourceId':'band-sql',
               'columns':[{'field':f,'label':l} for f,l in [('band','首次评分'),('n','样本'),('up','上涨数'),('up_pct','上涨比例（%）'),('mean_pct','平均变化（%）')]],
               'defaultSort':{'field':'n','direction':'desc'}},
              {'id':'sample','title':'前 10 条预警证据','dataset':'sample','sourceId':'sample-sql',
               'columns':[{'field':f,'label':l} for f,l in [('first_at','首次时间'),('code','代码'),('name','股票'),('first_score','首次评分'),('first_price','首次价'),('close_return_pct','到收盘变化（%）')]],
               'defaultSort':{'field':'first_at','direction':'asc'}}]}
for ident,label,sql in [('alert-sql','首次预警记录：冻结 JSON 的实际 SQLite 查询',ALERT_SQL),
                        ('band-sql','首次评分分组：冻结 JSON 的实际 SQLite 查询',BAND_SQL),
                        ('sample-sql','前 10 条：冻结 JSON 的实际 SQLite 查询',ALERT_SQL+' LIMIT 10')]:
    manifest['sources'].append({'id':ident,'label':label,'href':data['metadata'][1]['url'],
        'query':{'language':'sql','engine':'SQLite JSON1','sql':sql,
                 'description':'将 review-extract.json 的 records 数组以 JSON 文本绑定到 :records；没有直接查询或修改生产库。',
                 'tables_used':['json_each(:records) from review-extract.json'],
                 'filters':{'strategy':'limit-up-ambush','date_from':'2026-08-24','date_to':'2026-09-09'},
                 'metric_definitions':source['query']['metric_definitions'],
                 'response_sha256':data['metadata'][1]['response_sha256']}})
artifact={'surface':'report','manifest':manifest,'snapshot':{'version':1,'status':'ready','generatedAt':generated,
             'datasets':{'alerts':scatter,'bands':bands,'sample':scatter[:10]}},'sources':manifest['sources']}
(ROOT/'report-artifact.json').write_text(json.dumps(artifact,ensure_ascii=False,indent=2),encoding='utf-8')
summary_table='\n\n| 首次评分 | 样本 | 收盘上涨比例 | 平均变化 |\n|---|---:|---:|---:|\n'+''.join(f"| {r['band']} | {r['n']} | {r['up_pct']:.2f}% | {r['mean_pct']:+.2f}% |\n" for r in bands)
(ROOT/'strategy-review.md').write_text('\n\n'.join(body+(summary_table if key=='scores' else '') for key,body,_ in sections),encoding='utf-8')

nb = nbformat.v4.new_notebook()
nb.metadata['kernelspec']={'display_name':'Python 3','language':'python','name':'python3'}
nb.cells=[
    nbformat.v4.new_markdown_cell('# Signal Forge Strategy Review — Reproducible Audit\n\n只读冻结快照；不联网重取，不训练或修改策略。运行目录为本笔记本所在文件夹。'),
    nbformat.v4.new_code_cell("from pathlib import Path\nimport json\nfrom collections import Counter\nfrom review_analysis import compute\nDATA = Path('review-extract.json')\ndata = json.loads(DATA.read_text(encoding='utf-8'))\nresults = compute(data)\nassert results == json.loads(Path('analysis-results.json').read_text(encoding='utf-8'))\nfor strategy, result in results.items():\n    print(strategy, result['overall'])"),
    nbformat.v4.new_markdown_cell('## 预先指定的描述分组\n\n不是最优阈值搜索，也不是未来验证。使用首次评分，不使用事后最高评分或命中次数。'),
    nbformat.v4.new_code_cell("ambush = results['limit-up-ambush']\nfor key in ['score_lt75','score_75_85','score_ge85','early_period','late_period','late_score_lt75','late_score_ge85','morning','afternoon']:\n    print(key, ambush['cuts'][key])\nprint('exploratory correlations', ambush['correlations_exploratory_not_causal'])"),
    nbformat.v4.new_code_cell("for strategy, result in results.items():\n    print(strategy, 'versions', result['versions'], 'flags', result['quality_flags'])\n    print('patterns', result['patterns'], 'unknown', result['unknown_next_day_status'])\n    rows = [r for r in data['records'] if r['strategy']==strategy]\n    assert len(rows)==len(set((r['strategy'],r['date'],r['code']) for r in rows))\n    print('limit labels', Counter(str(r['post_alert_limit']) for r in rows))\nprint('All source denominator and snapshot reproducibility checks passed.')"),
    nbformat.v4.new_code_cell("from review_sql_views import query_views\nalerts, bands = query_views(data)\nartifact=json.loads(Path('report-artifact.json').read_text(encoding='utf-8'))\nassert alerts == artifact['snapshot']['datasets']['alerts']\nassert bands == artifact['snapshot']['datasets']['bands']\nprint('Chart and table SQL outputs exactly match the report snapshot.',len(alerts),len(bands))"),
    nbformat.v4.new_markdown_cell('## 边界\n\n已入选样本、少量相关日期、缺失精确涨停价和逐次配置。V1 次日结果与涨停伏击当日结果不能混为同一个交易胜率。未来测试必须按时间保留，不可随机拆同日股票以宣称独立验证。'),
]
NotebookClient(nb,timeout=120,kernel_name='python3',resources={'metadata':{'path':str(ROOT)}}).execute()
nbformat.write(nb,ROOT/'strategy-review.ipynb')
assert all(c.get('execution_count') is not None for c in nb.cells if c.cell_type=='code')
assert not any(o.get('output_type')=='error' for c in nb.cells if c.cell_type=='code' for o in c.get('outputs',[]))
(ROOT/'validation.json').write_text(json.dumps({'status':'passed','event_key_unique':True,'source_denominators_reconciled':True,
    'computed_results_match':True,'notebook_executed_without_errors':True,'event_count':len(data['records']),
    'extract_sha256':hashlib.sha256((ROOT/'review-extract.json').read_bytes()).hexdigest(),
    'artifact_bytes':(ROOT/'report-artifact.json').stat().st_size},indent=2),encoding='utf-8')
print(json.dumps({'status':'passed','files':[p.name for p in ROOT.iterdir() if p.is_file()]},ensure_ascii=False))
