"""Actual SQLite queries over the frozen JSON extract for report-native evidence."""
import json
import sqlite3

ALERT_SQL = """SELECT
 json_extract(value, '$.date') || ' ' || json_extract(value, '$.code') AS point,
 json_extract(value, '$.date') AS date,
 json_extract(value, '$.code') AS code,
 json_extract(value, '$.name') AS name,
 json_extract(value, '$.first_at') AS first_at,
 json_extract(value, '$.first_score') AS first_score,
 json_extract(value, '$.first_price') AS first_price,
 json_extract(value, '$.close_return_pct') AS close_return_pct,
 json_extract(value, '$.versions[0]') AS version,
 1 AS sample_size,
 json_extract(value, '$.snapshot.turnover_rate') AS turnover_rate,
 CASE WHEN substr(json_extract(value, '$.code'), 1, 3) IN ('300','301','688')
      THEN '创业板/科创板' ELSE '主板' END AS board
FROM json_each(:records)
WHERE json_extract(value, '$.strategy') = 'limit-up-ambush'
ORDER BY first_at, code"""

BAND_SQL = """WITH alerts AS (
 SELECT json_extract(value, '$.first_score') AS score,
        json_extract(value, '$.close_return_pct') AS change
 FROM json_each(:records)
 WHERE json_extract(value, '$.strategy') = 'limit-up-ambush'
), classified AS (
 SELECT CASE WHEN score < 75 THEN 0 WHEN score < 85 THEN 1 ELSE 2 END AS bucket, change
 FROM alerts WHERE change IS NOT NULL
)
SELECT CASE bucket WHEN 0 THEN '低于 75' WHEN 1 THEN '75 至不足 85' ELSE '85 及以上' END AS band,
 COUNT(*) AS n, SUM(change > 0) AS up,
 ROUND(100.0 * SUM(change > 0) / COUNT(*), 2) AS up_pct,
 ROUND(AVG(change), 4) AS mean_pct, bucket AS sort_order
FROM classified GROUP BY bucket ORDER BY bucket"""

def query_views(data):
    with sqlite3.connect(':memory:') as connection:
        connection.row_factory = sqlite3.Row
        params={'records':json.dumps(data['records'],ensure_ascii=False)}
        alerts=[dict(row) for row in connection.execute(ALERT_SQL,params)]
        bands=[dict(row) for row in connection.execute(BAND_SQL,params)]
        sample=[dict(row) for row in connection.execute(ALERT_SQL+' LIMIT 10',params)]
        assert sample == alerts[:10]
    return alerts,bands
