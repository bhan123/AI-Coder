from __future__ import annotations

import math
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, time, timedelta
from typing import Callable, Iterable, Optional, Protocol
from zoneinfo import ZoneInfo

import requests

from app.models import (
    DailyBar,
    IntradayBar,
    MarketContext,
    MarketSnapshot,
    SectorQuote,
)


class MarketDataProvider(Protocol):
    source_name: str

    def fetch(self, captured_at: datetime) -> list[MarketSnapshot]: ...


class HistoryProvider(Protocol):
    """按股票代码返回最近若干个交易日的日线 K 线。

    P2/P3 的均线、平台、前高都需要这个；返回空列表时策略必须显式标记为
    ``missing_data``，而不是用 0 或者随机数填充。
    """

    source_name: str

    def fetch(self, code: str, end: date, *, limit: int = 30) -> list[DailyBar]: ...


class IntradayProvider(Protocol):
    """返回某只股票当日从开盘到 captured_at 的逐分钟切片。

    P1 用来算均价线和缩量回踩；P3 用来验证突破后维持；P4 用来识别封单衰减。
    """

    source_name: str

    def fetch(self, code: str, captured_at: datetime) -> list[IntradayBar]: ...


class SectorProvider(Protocol):
    """板块行情与个股-板块归属，是 P1 和 P4 的基础。"""

    source_name: str

    def sector_for_code(self, code: str) -> Optional[SectorQuote]: ...

    def sectors(self) -> list[SectorQuote]: ...


def _number(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _tencent_index_quote() -> tuple[float, datetime]:
    """Return SSE Composite change and the source timestamp from Tencent quote."""
    response = requests.get(
        "https://qt.gtimg.cn/q=sh000001",
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=12,
    )
    response.raise_for_status()
    try:
        fields = response.text.split('"')[1].split("~")
        source_at = datetime.strptime(fields[30], "%Y%m%d%H%M%S")
        now = datetime.now(ZoneInfo("Asia/Shanghai"))
        if source_at.date() != now.date():
            raise RuntimeError(f"腾讯指数行情不是当日数据（数据时点 {source_at:%Y-%m-%d %H:%M:%S}）")
        return _number(fields[32]), source_at
    except (IndexError, ValueError) as exc:
        raise RuntimeError("腾讯指数行情返回格式异常") from exc


def _tencent_index_change() -> float:
    return _tencent_index_quote()[0]


class AkshareSpotProvider:
    """Primary adapter: AkShare's Eastmoney A-share snapshot."""

    source_name = "AkShare / Eastmoney"

    def fetch(self, captured_at: datetime) -> list[MarketSnapshot]:
        try:
            import akshare as ak
        except ImportError as exc:  # pragma: no cover - deployment dependency
            raise RuntimeError("未安装 akshare，无法读取实时市场快照") from exc

        market_change = _tencent_index_change()
        frame = ak.stock_zh_a_spot_em()
        rows: list[MarketSnapshot] = []
        for _, row in frame.iterrows():
            try:
                code = str(row["代码"]).zfill(6)
                name = str(row["名称"])
                price = _number(row["最新价"])
                pct_change = _number(row["涨跌幅"])
                day_low = _number(row["最低"])
                turnover_rate = _number(row.get("换手率", 0))
                volume_ratio = _number(row.get("量比", 0))
            except KeyError:
                continue
            if price <= 0 or day_low <= 0 or name.startswith(("ST", "*ST")):
                continue
            rows.append(MarketSnapshot(
                code=code,
                name=name,
                price=price,
                pct_change=pct_change,
                day_low=day_low,
                turnover_rate=turnover_rate,
                volume_ratio=volume_ratio,
                market_pct_change=market_change,
                captured_at=captured_at,
            ))
        if not rows:
            raise RuntimeError("东财行情未返回可用 A 股快照")
        return rows


class TencentSinaSpotProvider:
    """Fallback adapter with two independent, live public quote sources.

    Tencent exposes turnover, volume ratio and percent change for the whole
    market. Sina exposes the intraday low. The two are joined by security code
    during one short snapshot window; no field is fabricated when Eastmoney is
    unavailable.
    """

    source_name = "Tencent + Sina composite"
    _headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://finance.sina.com.cn/"}
    _tencent_url = "https://proxy.finance.qq.com/cgi/cgi-bin/rank/hs/getBoardRankList"
    _sina_url = "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData"
    _sina_count_url = "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeStockCount?node=hs_a"

    @staticmethod
    def _request_json(url: str, *, params: dict[str, str] | None = None) -> object:
        response = requests.get(url, params=params, headers=TencentSinaSpotProvider._headers, timeout=15)
        response.raise_for_status()
        return response.json()

    def _fetch_tencent_rows(self) -> dict[str, dict]:
        params = {
            "_appver": "11.17.0",
            "board_code": "aStock",
            "sort_type": "price",
            "direct": "down",
            "offset": "0",
            "count": "200",
        }
        first = self._request_json(self._tencent_url, params=params)
        try:
            total = int(first["data"]["total"])
            items = list(first["data"]["rank_list"])
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError("腾讯全市场行情返回格式异常") from exc

        offsets = range(200, total, 200)

        def fetch_page(offset: int) -> list[dict]:
            page_params = {**params, "offset": str(offset)}
            payload = self._request_json(self._tencent_url, params=page_params)
            return list(payload["data"]["rank_list"])

        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(fetch_page, offset) for offset in offsets]
            for future in as_completed(futures):
                items.extend(future.result())

        return {str(item["code"])[-6:]: item for item in items if item.get("code")}

    def _fetch_sina_rows(self) -> dict[str, dict]:
        count_response = requests.get(self._sina_count_url, headers=self._headers, timeout=15)
        count_response.raise_for_status()
        count_match = re.search(r"\d+", count_response.text)
        if not count_match:
            raise RuntimeError("新浪全市场股票数量返回格式异常")
        page_count = math.ceil(int(count_match.group()) / 100)

        def fetch_page(page: int) -> list[dict]:
            params = {
                "page": str(page),
                "num": "100",
                "sort": "symbol",
                "asc": "1",
                "node": "hs_a",
                "symbol": "",
                "_s_r_a": "page",
            }
            payload = self._request_json(self._sina_url, params=params)
            if not isinstance(payload, list):
                raise RuntimeError("新浪全市场行情返回格式异常")
            return payload

        items: list[dict] = []
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(fetch_page, page) for page in range(1, page_count + 1)]
            for future in as_completed(futures):
                items.extend(future.result())
        return {str(item["code"]).zfill(6): item for item in items if item.get("code")}

    def fetch(self, captured_at: datetime) -> list[MarketSnapshot]:
        market_change = _tencent_index_change()
        tencent_rows = self._fetch_tencent_rows()
        sina_rows = self._fetch_sina_rows()
        rows: list[MarketSnapshot] = []

        for code, tencent in tencent_rows.items():
            sina = sina_rows.get(code)
            if not sina:
                continue
            name = str(tencent.get("name") or sina.get("name") or "")
            price = _number(sina.get("trade"))
            day_low = _number(sina.get("low"))
            pct_change = _number(tencent.get("zdf"))
            turnover_rate = _number(tencent.get("hsl"))
            volume_ratio = _number(tencent.get("lb"))
            if (
                not code.startswith(("0", "3", "6"))
                or price <= 0
                or day_low <= 0
                or name.startswith(("ST", "*ST"))
            ):
                continue
            rows.append(MarketSnapshot(
                code=code,
                name=name,
                price=price,
                pct_change=pct_change,
                day_low=day_low,
                turnover_rate=turnover_rate,
                volume_ratio=volume_ratio,
                market_pct_change=market_change,
                captured_at=captured_at,
            ))
        if len(rows) < 3000:
            raise RuntimeError(f"腾讯/新浪快照交集异常，仅得到 {len(rows)} 只股票")
        return rows


class LiveSpotProvider:
    """Use a primary provider first and expose which provider actually won."""

    source_name = "unresolved"

    def fetch(self, captured_at: datetime) -> list[MarketSnapshot]:
        errors: list[str] = []
        for provider in (AkshareSpotProvider(), TencentSinaSpotProvider()):
            try:
                rows = provider.fetch(captured_at)
                self.source_name = provider.source_name
                return rows
            except Exception as exc:
                errors.append(f"{provider.source_name}: {exc}")
        raise RuntimeError("所有实时行情源均不可用；" + " | ".join(errors))


class SampleProvider:
    """Repeatable research fixture, never mixed with real-time market output.

    这里的样例股票、板块、涨跌结构与 P1–P4 样例 provider 保持一致：每个股票
    在日线和分时上都有清晰身份，方便回放各策略的判定路径：
      605000 → P1 板块共振 + 回踩企稳
      002833 → V1 尾盘止跌回升
      003010 → P2 趋势缩量回踩（均线多头 + 平台缩量）
      600872 → P3 平台放量突破（突破 20 日平台）
      000859 → P4 龙头分歧转一致（板块龙头 + 封板）
      603617 → 普通样本，仅 V1 命中
    """

    source_name = "内置研究样例"

    def fetch(self, captured_at: datetime) -> list[MarketSnapshot]:
        rows = [
            ("002833", "弘亚数控", 16.22, -4.1, 15.88, 3.4, 1.8),
            ("003010", "若羽臣", 28.65, -3.4, 28.08, 4.1, 1.4),
            ("605000", "数控龙头", 12.43, 3.2, 12.02, 5.2, 1.6),
            ("605001", "数控联动一", 11.20, 2.0, 10.91, 3.8, 1.3),
            ("605002", "数控联动二", 10.35, 1.5, 10.11, 3.2, 1.2),
            ("605003", "数控联动三", 9.88, 0.8, 9.70, 2.9, 1.1),
            ("603617", "君禾股份", 8.72, -5.3, 8.48, 2.8, 1.4),
            ("000859", "国风新材", 5.49, 9.8, 5.05, 12.5, 3.6),
            ("600872", "中炬高新", 21.85, 2.4, 21.05, 1.1, 2.0),
        ]
        return [MarketSnapshot(
            code=code,
            name=name,
            price=price,
            pct_change=pct,
            day_low=low,
            turnover_rate=turnover,
            volume_ratio=volume,
            market_pct_change=-5.0,
            captured_at=captured_at,
        ) for code, name, price, pct, low, turnover, volume in rows]


# ---------------------------------------------------------------------------
# 历史日线 / 分时 / 板块：P1–P4 的真正数据来源
# ---------------------------------------------------------------------------

class AkshareHistoryProvider:
    """通过 AkShare 拉取最近 N 个交易日的日线 K 线。"""

    source_name = "AkShare history"

    def fetch(self, code: str, end: date, *, limit: int = 30) -> list[DailyBar]:
        try:
            import akshare as ak
        except ImportError as exc:
            raise RuntimeError("未安装 akshare，无法读取历史日线") from exc

        symbol = _akshare_symbol(code)
        end_str = end.strftime("%Y%m%d")
        frame = ak.stock_zh_a_hist(
            symbol=symbol,
            period="daily",
            start_date="",
            end_date=end_str,
            adjust="qfq",
        )
        if frame is None or frame.empty:
            return []
        frame = frame.tail(limit)
        bars: list[DailyBar] = []
        for _, row in frame.iterrows():
            trade_date = _parse_akshare_date(str(row["日期"]))
            bars.append(DailyBar(
                code=code,
                trade_date=trade_date,
                open=_number(row["开盘"]),
                high=_number(row["最高"]),
                low=_number(row["最低"]),
                close=_number(row["收盘"]),
                volume=_number(row.get("成交量", 0)),
                turnover_rate=_number(row.get("换手率", 0)),
            ))
        return bars


def _akshare_symbol(code: str) -> str:
    """AkShare 用 sh600000 / sz000001 形式的代码；这里做最小校验。"""
    if not code or len(code) != 6 or not code.isdigit():
        raise RuntimeError(f"无效股票代码 {code!r}")
    return code


def _parse_akshare_date(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        try:
            return datetime.strptime(value, "%Y%m%d").date()
        except ValueError as exc:
            raise RuntimeError(f"无法解析日期 {value!r}") from exc


class AkshareIntradayProvider:
    """通过 AkShare 拉取当日分钟级行情，截取到 captured_at。"""

    source_name = "AkShare intraday"

    def fetch(self, code: str, captured_at: datetime) -> list[IntradayBar]:
        try:
            import akshare as ak
        except ImportError as exc:
            raise RuntimeError("未安装 akshare，无法读取分时数据") from exc

        symbol = _akshare_symbol(code)
        date_str = captured_at.strftime("%Y-%m-%d")
        frame = ak.stock_zh_a_hist_min_em(symbol=symbol, period="1", adjust="")
        if frame is None or frame.empty:
            return []
        frame["时间"] = frame["时间"].astype(str)
        today = frame[frame["时间"].str.startswith(date_str)]
        cutoff = captured_at.strftime("%H:%M")
        before = today[today["时间"] <= f"{date_str} {cutoff}:59"]
        if before.empty:
            return []
        bars: list[IntradayBar] = []
        running_volume = 0.0
        running_amount = 0.0
        running_price_volume = 0.0
        for _, row in before.iterrows():
            stamp = str(row["时间"]).split(" ")[-1]
            minutes = _minutes_since_open(stamp)
            if minutes is None:
                continue
            volume = _number(row.get("成交量", 0))
            running_volume += volume
            price = _number(row["收盘"])
            amount = _number(row.get("成交额", 0))
            running_amount += amount
            running_price_volume += price * volume
            if running_volume <= 0:
                avg = price
            elif running_amount > 0:
                # 东财分钟成交量单位为手、成交额单位为元；1 手 = 100 股。
                avg = running_amount / (running_volume * 100)
            else:
                avg = running_price_volume / running_volume
            bars.append(IntradayBar(
                code=code,
                minutes_after_open=minutes,
                price=price,
                avg_price=avg,
                volume=volume,
            ))
        return bars


def _minutes_since_open(stamp: str) -> Optional[int]:
    try:
        hh, mm = stamp.split(":")[:2]
        minutes = int(hh) * 60 + int(mm)
    except (ValueError, AttributeError):
        return None
    open_minutes = 9 * 60 + 30
    close_minutes = 15 * 60
    if minutes < open_minutes or minutes > close_minutes:
        return None
    if minutes <= 11 * 60 + 30:
        return minutes - open_minutes
    if minutes < 13 * 60:
        return 120
    return 120 + (minutes - 13 * 60)


class AkshareSectorProvider:
    """通过 AkShare 读取申万行业分类和板块行情。"""

    source_name = "AkShare sectors"

    def __init__(self) -> None:
        self._sectors_by_code: dict[str, SectorQuote] = {}
        self._sector_by_stock: dict[str, SectorQuote] = {}
        self._loaded_at: Optional[datetime] = None

    def _ensure_loaded(self) -> None:
        try:
            import akshare as ak
        except ImportError as exc:
            raise RuntimeError("未安装 akshare，无法读取板块归属") from exc
        # 简单缓存：每次进程内只拉一次，避免重复打接口
        if self._loaded_at and (datetime.now() - self._loaded_at) < timedelta(hours=1):
            return
        try:
            board_frame = ak.stock_board_industry_name_em()
        except Exception as exc:
            raise RuntimeError(f"akshare 行业板块列表失败: {exc}") from exc
        sectors: list[SectorQuote] = []
        for _, row in board_frame.iterrows():
            code = str(row.get("板块代码", "")).strip()
            name = str(row.get("板块名称", "")).strip()
            if not code or not name:
                continue
            pct = _number(row.get("涨跌幅"))
            sectors.append(SectorQuote(
                code=code,
                name=name,
                pct_change=pct,
                leader_name=str(row.get("领涨股票", "")).strip() or None,
                leader_pct_change=_number(row.get("领涨股票-涨跌幅")),
            ))
        sectors_by_code = {s.code: s for s in sectors}

        def fetch_members(sector: SectorQuote) -> tuple[SectorQuote, list[str]]:
            frame = ak.stock_board_industry_cons_em(symbol=sector.code)
            codes = [
                str(value).zfill(6)
                for value in frame.get("代码", [])
                if str(value).strip()
            ]
            return sector, codes

        sector_by_stock: dict[str, SectorQuote] = {}
        with ThreadPoolExecutor(max_workers=6) as executor:
            futures = [executor.submit(fetch_members, sector) for sector in sectors]
            for future in as_completed(futures):
                try:
                    sector, codes = future.result()
                except Exception:
                    continue
                for stock_code in codes:
                    sector_by_stock.setdefault(stock_code, sector)

        self._sectors_by_code = sectors_by_code
        self._sector_by_stock = sector_by_stock
        self._loaded_at = datetime.now()

    def sectors(self) -> list[SectorQuote]:
        self._ensure_loaded()
        return list(self._sectors_by_code.values())

    def sector_for_code(self, code: str) -> Optional[SectorQuote]:
        self._ensure_loaded()
        return self._sector_by_stock.get(code)


class EastMoneySectorProvider:
    """通过东方财富的 ``push2delay.eastmoney.com`` 直接读取行业板块。

    ISSUE-5 (2026-08-06): 部署机上的 akshare 调用的 ``17.push2.eastmoney.com``
    域名被云厂商屏蔽，导致 P1/P4 每次都因 ``akshare 行业板块列表失败`` 整体失败。
    该 provider 复刻 akshare ``stock_board_industry_name_em`` + ``stock_board_industry_cons_em``
    调用的 EM 同源 endpoint，``17.`` 前缀替换成 ``push2delay.``（在腾讯云上可达）。

    字段语义与 akshare 对齐：
      - f12  → BK代码（与 akshare ``板块代码`` 等价）
      - f14  → 板块名
      - f3   → 涨跌幅（basis points，**÷ 100**）
      - f128 → 领涨股票名
      - f140 → 领涨股票代码
      - f141 → 领涨股票涨跌幅（basis points，**÷ 100**）
      - f105 → 板块内股票总数（用于 limit_up_count 估算）
    """

    base_source_name = "EastMoney sectors (push2delay)"
    source_name = base_source_name
    _headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://quote.eastmoney.com/"}
    _list_url = "https://push2delay.eastmoney.com/api/qt/clist/get"
    _members_url = "https://push2delay.eastmoney.com/api/qt/clist/get"
    _cache_ttl = timedelta(hours=1)

    def __init__(self) -> None:
        self._sectors_by_code: dict[str, SectorQuote] = {}
        self._sector_by_stock: dict[str, SectorQuote] = {}
        self._loaded_at: Optional[datetime] = None

    def _ensure_loaded(self) -> None:
        if self._loaded_at and (datetime.now() - self._loaded_at) < self._cache_ttl:
            return
        sectors = self._fetch_sector_list()
        if not sectors:
            raise RuntimeError("EastMoney 行业板块列表为空（接口可能被风控）")
        sectors_by_code = {s.code: s for s in sectors}

        sector_by_stock: dict[str, SectorQuote] = {}

        def fetch_members(sector: SectorQuote) -> tuple[SectorQuote, list[str]]:
            return sector, self._fetch_sector_members(sector.code)

        member_failures: list[str] = []
        member_successes = 0
        with ThreadPoolExecutor(max_workers=6) as executor:
            futures = [executor.submit(fetch_members, sector) for sector in sectors]
            for future in as_completed(futures):
                try:
                    sector, codes = future.result()
                except Exception as exc:
                    member_failures.append(str(exc))
                    continue
                member_successes += 1
                for stock_code in codes:
                    sector_by_stock.setdefault(stock_code, sector)

        if not member_successes:
            raise RuntimeError(
                f"EastMoney 行业板块成员列表全部失败（{len(member_failures)}/{len(sectors)}）"
            )

        self._sectors_by_code = sectors_by_code
        self._sector_by_stock = sector_by_stock
        self._loaded_at = datetime.now()
        suffix = f"成员映射 {member_successes}/{len(sectors)}"
        if member_failures:
            suffix += f"，失败 {len(member_failures)}"
        self.source_name = f"{self.base_source_name} · {suffix}"

    def _fetch_sector_list(self) -> list[SectorQuote]:
        params = {
            "pn": "1", "pz": "500", "po": "1", "np": "1",
            "fltt": "2", "invt": "2", "fs": "m:90+t:2",
            "fields": "f3,f12,f14,f128,f140,f141,f105",
        }
        response = requests.get(
            self._list_url, params=params, headers=self._headers, timeout=15,
        )
        response.raise_for_status()
        payload = response.json()
        diff = payload.get("data", {}).get("diff") if isinstance(payload, dict) else None
        if not diff:
            return []
        # EM returns dict 形式 in pz<=80, list 形式 in pz>80 — normalize.
        items = [diff[k] for k in diff] if isinstance(diff, dict) else diff
        sectors: list[SectorQuote] = []
        for item in items:
            code = str(item.get("f12", "")).strip()
            name = str(item.get("f14", "")).strip()
            if not code or not name:
                continue
            leader_code = str(item.get("f140", "")).strip() or None
            leader_name = str(item.get("f128", "")).strip() or None
            sectors.append(SectorQuote(
                code=code,
                name=name,
                pct_change=_number(item.get("f3")) / 100.0,
                leader_code=leader_code,
                leader_name=leader_name,
                leader_pct_change=_number(item.get("f141")) / 100.0,
                # f105 是板块成员总数；真实涨停家数需要再拉一次快照，
                # 但 akshare 路径下也是 0。这里保持一致：留 0，由 priority_tag evidence 注明。
                limit_up_count=0,
            ))
        return sectors

    def _fetch_sector_members(self, sector_code: str) -> list[str]:
        params = {
            "pn": "1", "pz": "500", "po": "1", "np": "1",
            "fltt": "2", "invt": "2",
            "fs": f"b:{sector_code}+f:!50",
            "fields": "f12",
        }
        response = requests.get(
            self._members_url, params=params, headers=self._headers, timeout=15,
        )
        response.raise_for_status()
        payload = response.json()
        diff = payload.get("data", {}).get("diff") if isinstance(payload, dict) else None
        if not diff:
            return []
        items = [diff[k] for k in diff] if isinstance(diff, dict) else diff
        return [str(item.get("f12", "")).zfill(6) for item in items
                if str(item.get("f12", "")).strip()]

    def sectors(self) -> list[SectorQuote]:
        self._ensure_loaded()
        return list(self._sectors_by_code.values())

    def sector_for_code(self, code: str) -> Optional[SectorQuote]:
        self._ensure_loaded()
        return self._sector_by_stock.get(code)


class LiveSectorProvider:
    """Try AkShare first; if it fails (network / domain blocked), fall back to EM direct.

    ISSUE-5 (2026-08-06): deployment host blocks ``17.push2.eastmoney.com`` which
    akshare hardcodes, so a single-provider chain failed daily. LiveSectorProvider
    chains AkshareSectorProvider → EastMoneySectorProvider; both must succeed in
    loading before :meth:``sectors`` returns. If both fail, the caller should
    treat the strategies that ``require_sectors`` as ``missing_data`` rather
    than crashing the whole batch.

    性能注意：每个 ``assemble`` 调用都会触发 ~5000 次 ``sector_for_code``。
    没有缓存时，每次都会重走 akShare → EM 失败链（akShare 断连重试每次
    都要等 ~10s connect timeout）。所以这里缓存的是**哪个 provider 赢了**，
    而不是它自己的数据——下层 provider 自身的缓存仍在生效。
    """

    source_name = "unresolved"

    def __init__(self) -> None:
        self._inner: Optional[SectorProvider] = None
        self._last_error: Optional[str] = None

    def _providers(self) -> list[SectorProvider]:
        return [AkshareSectorProvider(), EastMoneySectorProvider()]

    def _ensure_loaded(self) -> SectorProvider:
        if self._inner is not None:
            return self._inner
        errors: list[str] = []
        for provider in self._providers():
            try:
                provider.sectors()  # 触发 _ensure_loaded
                self._inner = provider
                self.source_name = provider.source_name
                self._last_error = None
                return provider
            except Exception as exc:
                errors.append(f"{provider.source_name}: {exc}")
        self._last_error = " | ".join(errors)
        raise RuntimeError(f"所有实时板块源均不可用：{self._last_error}")

    def sectors(self) -> list[SectorQuote]:
        inner = self._ensure_loaded()
        return inner.sectors()

    def sector_for_code(self, code: str) -> Optional[SectorQuote]:
        inner = self._ensure_loaded()
        return inner.sector_for_code(code)


# ---------------------------------------------------------------------------
# 研究样例数据：与实时模式严格隔离
# ---------------------------------------------------------------------------

_SAMPLE_SECTOR_MAP: dict[str, tuple[str, str]] = {
    "002833": ("BK0001", "样本-数控装备"),
    "003010": ("BK0001", "样本-数控装备"),
    "605000": ("BK0001", "样本-数控装备"),
    "605001": ("BK0001", "样本-数控装备"),
    "605002": ("BK0001", "样本-数控装备"),
    "605003": ("BK0001", "样本-数控装备"),
    "600872": ("BK0003", "样本-调味品"),
    "000859": ("BK0002", "样本-水务电气"),
    "603617": ("BK0099", "样本-普通股"),
}


class SampleHistoryProvider:
    """为研究样例构造 30 个交易日的日线 K 线。

    数据完全确定，仅供回放链路；不得混入任何实时场景。"""

    source_name = "内置研究样例"

    def fetch(self, code: str, end: date, *, limit: int = 30) -> list[DailyBar]:
        seed = _sample_seed(code)
        bars: list[DailyBar] = []
        cursor = end
        valid_offsets: list[int] = []
        offset = 0
        while len(valid_offsets) < limit:
            day = cursor - timedelta(days=offset)
            if day.weekday() < 5:
                valid_offsets.append(offset)
            offset += 1
        for index, offset in enumerate(valid_offsets):
            day = cursor - timedelta(days=offset)
            position = (limit - index) / float(limit)
            trend = seed["trend"] * (position - 0.5) * 1.5
            drift = seed["drift"] * (limit - index) * 0.05
            platform = math.sin(index * 1.3) * seed["platform_jitter"]
            amplitude = math.sin(index * 0.7) * seed["amplitude"]
            close = round(seed["base"] + trend + drift + platform + amplitude, 2)
            open_ = round(close + math.sin(index * 0.5) * 0.05, 2)
            high = round(max(close, open_) + abs(math.sin(index * 0.9)) * 0.2 + 0.05, 2)
            low = round(min(close, open_) - abs(math.sin(index * 0.9)) * 0.2 - 0.05, 2)
            bars.append(DailyBar(
                code=code,
                trade_date=day,
                open=open_,
                high=high,
                low=low,
                close=close,
                volume=seed["volume"],
                turnover_rate=seed["turnover"],
            ))
        bars.reverse()
        if code == "003010":
            # The final three sessions are the deliberately lower-volume
            # pullback leg used by the P2 research fixture.
            bars[-3:] = [
                bar.model_copy(update={"volume": seed["volume"] * 0.55})
                for bar in bars[-3:]
            ]
        return bars[-limit:]


def _sample_seed(code: str) -> dict[str, float]:
    """为研究样例提供近 30 日 K 线种子。

    003010: 接近线性的上升趋势，使 5/10/20 日均线呈多头排列。
    600872: 在 21.0–21.4 区间窄幅震荡，形成 20 日平台。
    605000: 普通上行，支撑 P1 同板块共振。
    002833 / 000859: 普通形态，不为 V1 之外的策略背书。
    603617: 下跌趋势，V1 仅可在 -2%~-7% 范围内命中。
    """
    presets = {
        "002833": {"base": 16.0, "drift": 0.0, "amplitude": 0.4, "platform_jitter": 0.0,
                    "volume": 8_400_000, "turnover": 4.5, "trend": 0.0},
        "003010": {"base": 26.0, "drift": 0.12, "amplitude": 0.5, "platform_jitter": 0.0,
                    "volume": 5_100_000, "turnover": 5.1, "trend": 1.0},
        "605000": {"base": 12.0, "drift": 0.04, "amplitude": 0.3, "platform_jitter": 0.0,
                    "volume": 6_200_000, "turnover": 5.0, "trend": 0.3},
        "603617": {"base": 9.4, "drift": -0.05, "amplitude": 0.3, "platform_jitter": 0.0,
                    "volume": 6_200_000, "turnover": 3.0, "trend": -0.5},
        "000859": {"base": 5.0, "drift": 0.02, "amplitude": 0.2, "platform_jitter": 0.0,
                    "volume": 14_500_000, "turnover": 11.0, "trend": 0.5},
        "600872": {"base": 21.0, "drift": 0.0, "amplitude": 0.15, "platform_jitter": 0.3,
                    "volume": 3_800_000, "turnover": 1.4, "trend": 0.0},
    }
    return presets.get(code, {"base": 10.0, "drift": 0.0, "amplitude": 0.3,
                              "platform_jitter": 0.0, "volume": 1_000_000,
                              "turnover": 1.0, "trend": 0.0})


class SampleIntradayProvider:
    """为研究样例生成当日分钟切片，明确写出 P1/P3/P4 需要的状态。"""

    source_name = "内置研究样例"

    def fetch(self, code: str, captured_at: datetime) -> list[IntradayBar]:
        seed = _intraday_seed(code, captured_at)
        bars: list[IntradayBar] = []
        running_volume = 0.0
        for minute in range(seed["start_min"], seed["end_min"] + 1):
            price = seed["path"](minute)
            volume = seed["volume_path"](minute)
            running_volume += volume
            avg = (running_volume and (price * 0.4 + seed["vwap"](minute) * 0.6)) or price
            bars.append(IntradayBar(
                code=code,
                minutes_after_open=minute,
                price=round(price, 3),
                avg_price=round(avg, 3),
                volume=volume,
            ))
        return bars


def _intraday_seed(code: str, captured_at: datetime) -> dict[str, object]:
    """每个样例股票在分时上有明确身份：P1 回踩 / P2 缩量 / P3 突破 / P4 封板 / 普通。"""
    end_min = max(0, _minutes_from_time(captured_at))
    if code == "002833":
        # V1 候选：保留止跌回升分时，但负涨幅会被 P1 的 1%–5% 门槛排除。
        return {
            "start_min": 0,
            "end_min": end_min,
            "path": lambda m: 16.05 + 0.08 * math.sin(m / 15.0) + (0.15 if m >= 180 else 0.0),
            "volume_path": lambda m: 60_000 if m < 180 else 25_000,
            "vwap": lambda m: 16.02 + 0.03 * math.sin(m / 30.0),
        }
    if code == "003010":
        # P2 候选：午后平台窄幅缩量。
        return {
            "start_min": 0,
            "end_min": end_min,
            "path": lambda m: 28.6 + 0.10 * math.sin(m / 20.0) + (-0.05 if m >= 180 else 0.0),
            "volume_path": lambda m: 50_000 if m < 180 else 20_000,
            "vwap": lambda m: 28.42,
        }
    if code == "605000":
        # P1 候选：全天在均价线上，14:00 后缩量回踩，14:35 后重新转强。
        def p1_path(minute: int) -> float:
            if minute < 180:
                return 12.08 + minute * 0.0016
            if minute <= 205:
                return 12.368 - (minute - 180) * 0.0014
            return 12.333 + (minute - 205) * 0.004

        return {
            "start_min": 0,
            "end_min": end_min,
            "path": p1_path,
            "volume_path": lambda m: 60_000 if m < 180 else 20_000,
            "vwap": lambda m: 12.02 + m * 0.0007,
        }
    if code == "000859":
        # P4 候选：13:30 后触板，14:00 后封板且封单稳定。
        return {
            "start_min": 0,
            "end_min": end_min,
            "path": lambda m: 5.05 + 0.04 * math.sin(m / 18.0) + (0.45 if m >= 150 else 0.0),
            "volume_path": lambda m: 70_000 + (30_000 if 150 <= m < 200 else 0) + (10_000 if m >= 200 else 0),
            "vwap": lambda m: 5.08 + (0.42 if m >= 150 else 0.0),
        }
    if code == "600872":
        # P3 候选：14:00 后平台放量突破。
        return {
            "start_min": 0,
            "end_min": end_min,
            "path": lambda m: 21.10 + 0.08 * math.sin(m / 18.0) + (0.80 if m >= 180 else 0.0),
            "volume_path": lambda m: 30_000 if m < 180 else 110_000,
            "vwap": lambda m: 21.18 + (0.60 if m >= 180 else 0.0),
        }
    # 普通下跌样本
    return {
        "start_min": 0,
        "end_min": end_min,
        "path": lambda m: 9.0 - 0.20 * (m / 240.0),
        "volume_path": lambda m: 35_000,
        "vwap": lambda m: 9.0 - 0.10 * (m / 240.0),
    }


def _minutes_from_time(captured_at: datetime) -> int:
    minutes = captured_at.hour * 60 + captured_at.minute
    return max(0, min(240, minutes - 9 * 60 - 30))


class SampleSectorProvider:
    source_name = "内置研究样例"

    def sectors(self) -> list[SectorQuote]:
        return [
            SectorQuote(code="BK0001", name="样本-数控装备", pct_change=2.4,
                         leader_code="605000", leader_name="数控配套", leader_pct_change=2.7, limit_up_count=0),
            SectorQuote(code="BK0002", name="样本-水务电气", pct_change=1.6,
                         leader_code="000859", leader_name="国风新材", leader_pct_change=7.4, limit_up_count=1),
            SectorQuote(code="BK0003", name="样本-调味品", pct_change=0.8,
                         leader_code="600872", leader_name="中炬高新", leader_pct_change=2.1, limit_up_count=0),
        ]

    def sector_for_code(self, code: str) -> Optional[SectorQuote]:
        if code not in _SAMPLE_SECTOR_MAP:
            return None
        sector_code, _ = _SAMPLE_SECTOR_MAP[code]
        for quote in self.sectors():
            if quote.code == sector_code:
                return quote
        return None


# ---------------------------------------------------------------------------
# 上下文装配：把三种数据源并成每个股票一个 MarketContext
# ---------------------------------------------------------------------------

class ContextAssembler:
    """为某个运行把所有上下文数据聚合成 code -> MarketContext 字典。"""

    def __init__(
        self,
        history: HistoryProvider,
        intraday: IntradayProvider,
        sectors: SectorProvider,
    ) -> None:
        self.history = history
        self.intraday = intraday
        self.sectors = sectors

    def assemble(
        self,
        snapshots: Iterable[MarketSnapshot],
        captured_at: datetime,
        *,
        recent_snapshots: Optional[dict[str, list[MarketSnapshot]]] = None,
        sector_peers: Optional[dict[str, list[MarketSnapshot]]] = None,
        history_required: bool = True,
        intraday_required: bool = True,
        sector_required: bool = True,
        enrich_predicate: Optional[Callable[[MarketContext], bool]] = None,
        enrich_limit: Optional[int] = None,
        enrich_priority: Optional[Callable[[MarketContext], float]] = None,
    ) -> dict[str, MarketContext]:
        snapshots = list(snapshots)
        recent_snapshots = recent_snapshots or {}
        market_breadth_pct = (
            sum(1 for snapshot in snapshots if snapshot.pct_change > 0) / len(snapshots) * 100
            if snapshots else 0.0
        )
        sector_peers = sector_peers or {}
        sector_quotes: dict[str, SectorQuote] = {}
        sector_quotas: dict[str, list[MarketSnapshot]] = {}
        if sector_required:
            for snap in snapshots:
                sector = self.sectors.sector_for_code(snap.code)
                if sector is None:
                    continue
                sector_quotes[snap.code] = sector
                sector_quotas.setdefault(sector.code, []).append(snap)

            try:
                ordered_sectors = sorted(
                    self.sectors.sectors(), key=lambda item: item.pct_change, reverse=True
                )
            except Exception:
                ordered_sectors = []
        else:
            ordered_sectors = []
        sector_total = len(ordered_sectors)
        sector_ranking = {
            sector.code: (index, sector_total)
            for index, sector in enumerate(ordered_sectors, 1)
        }

        contexts: dict[str, MarketContext] = {}
        enrichable: list[MarketContext] = []
        for snap in snapshots:
            sector = sector_quotes.get(snap.code)
            peers = sector_peers.get(snap.code) if sector_peers else sector_quotas.get(sector.code, []) if sector else []
            peers = [p for p in peers if p.code != snap.code]
            sector_points: dict[datetime, list[float]] = {}
            for member in [snap, *peers]:
                for point in recent_snapshots.get(member.code, []):
                    sector_points.setdefault(point.captured_at, []).append(point.pct_change)
            recent_sector_average_pcts = [
                sum(values) / len(values)
                for _, values in sorted(sector_points.items())
                if values
            ]
            rank_pair = sector_ranking.get(sector.code) if sector else None
            context = MarketContext(
                snapshot=snap,
                recent_snapshots=recent_snapshots.get(snap.code, []),
                market_breadth_pct=market_breadth_pct,
                recent_sector_average_pcts=recent_sector_average_pcts,
                sector=sector,
                sector_peers=peers,
                sector_rank=rank_pair[0] if rank_pair else None,
                sector_total=rank_pair[1] if rank_pair else None,
            )
            should_enrich = enrich_predicate(context) if enrich_predicate else True
            if should_enrich:
                enrichable.append(context)
            contexts[snap.code] = context

        if enrich_priority:
            enrichable.sort(key=enrich_priority, reverse=True)
        if enrich_limit is not None:
            enrichable = enrichable[:max(0, enrich_limit)]

        end_date = captured_at.date() if hasattr(captured_at, "date") else captured_at
        def enrich(context: MarketContext) -> None:
            if history_required:
                try:
                    context.daily_history = self.history.fetch(context.snapshot.code, end_date, limit=30)
                except Exception:
                    context.daily_history = []
            if intraday_required:
                try:
                    context.intraday_bars = self.intraday.fetch(context.snapshot.code, captured_at)
                except Exception:
                    context.intraday_bars = []

        # Independent per-stock requests are bounded so the 14:50 scheduled
        # run finishes in the tail-session window without overwhelming the
        # public data source.
        if len(enrichable) <= 1:
            for context in enrichable:
                enrich(context)
        else:
            with ThreadPoolExecutor(max_workers=min(4, len(enrichable))) as executor:
                list(executor.map(enrich, enrichable))
        return contexts
