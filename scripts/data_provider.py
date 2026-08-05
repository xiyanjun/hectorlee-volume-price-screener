#!/usr/bin/env python3
"""
纯量价选股 - 数据获取模块
===========================
- 腾讯实时行情 qt.gtimg.cn
- 腾讯日K线 ifzq.gtimg.cn（前复权）
- 东方财富全市场列表
- 并发拉取 + 简单缓存 + 失败重试

返回的 K 线格式: [{date, open, close, high, low, volume}, ...]（升序）
"""

import json
import re
import time
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional, List, Dict, Any
from pattern_detect import _pure  # V3.5 共享代码清洗

TENCENT_QUOTE_URL = "https://qt.gtimg.cn/q={code}"
TENCENT_KLINE_URL = "https://ifzq.gtimg.cn/appstock/app/fqkline/get"
EASTMONEY_LIST_URL = "https://push2.eastmoney.com/api/qt/clist/get"
TENCENT_RANK_URL = "https://proxy.finance.qq.com/cgi/cgi-bin/rank/hs/getBoardRankList"


# ============================================================
# 工具
# ============================================================

def _normalize_code(code: str) -> str:
    """标准化为腾讯格式（sh600000 / sz000001 / bj830001）"""
    code = code.strip().lower()
    if re.match(r"^(sz|sh|bj)\d{6}$", code):
        return code
    if code.isdigit() and len(code) == 6:
        if code.startswith(("60", "68", "9")):
            return f"sh{code}"
        elif code.startswith(("4", "8", "92")):
            return f"bj{code}"
        return f"sz{code}"
    for prefix in ("sh", "sz", "bj"):
        if code.startswith(prefix):
            return code
    return f"sz{code}"


def _market_flag(code: str) -> str:
    """东方财富 secid 市场标记"""
    pure = _pure(code)
    return "1" if pure.startswith(("6", "9")) else "0"


# ============================================================
# 实时行情
# ============================================================

def get_realtime_quote(code: str) -> Optional[dict]:
    """获取实时行情（含名称/价格/换手率/风险标记）"""
    tc = _normalize_code(code)
    try:
        resp = requests.get(TENCENT_QUOTE_URL.format(code=tc), timeout=10)
        resp.encoding = "gbk"
        m = re.search(r'v_(.+?)="(.+?)";', resp.text)
        if not m:
            return None
        f = m.group(2).split("~")
        if len(f) < 50:
            return None
        return {
            "code": tc,
            "pure_code": _pure(tc),
            "name": f[1],
            "price": float(f[3]) if f[3] else 0,
            "prev_close": float(f[4]) if f[4] else 0,
            "open": float(f[5]) if f[5] else 0,
            "volume": int(f[6]) if f[6] else 0,
            "amount": float(f[37]) if len(f) > 37 and f[37] else 0,
            "high": float(f[33]) if len(f) > 33 and f[33] else 0,
            "low": float(f[34]) if len(f) > 34 and f[34] else 0,
            "change_amt": float(f[31]) if len(f) > 31 and f[31] else 0,
            "change_pct": float(f[32]) if len(f) > 32 and f[32] else 0,
            "turnover": float(f[38]) if len(f) > 38 and f[38] else None,  # 换手率(%)
            "market_cap": float(f[45]) if len(f) > 45 and f[45] else 0,
            "circulation_cap": float(f[44]) if len(f) > 44 and f[44] else 0,
            "pe": float(f[39]) if len(f) > 39 and f[39] else 0,
            "pb": float(f[46]) if len(f) > 46 and f[46] else 0,
            "is_st": "ST" in f[1].upper(),
        }
    except Exception as e:
        print(f"[Data] 实时行情失败 {code}: {e}")
        return None


# ============================================================
# 日K线（前复权）
# ============================================================

def get_kline(code: str, count: int = 90) -> Optional[List[dict]]:
    """获取前复权日K线，升序返回"""
    tc = _normalize_code(code)
    try:
        resp = requests.get(TENCENT_KLINE_URL,
                            params={"param": f"{tc},day,,,{count},qfq"}, timeout=15)
        data = json.loads(resp.text)
        if data.get("code") != 0:
            return None
        node = data.get("data", {}).get(tc, {})
        kdata = node.get("qfqday") or node.get("day") or []
        if not kdata:
            return None
        klines = []
        for k in kdata:
            klines.append({
                "date": k[0],
                "open": float(k[1]),
                "close": float(k[2]),
                "high": float(k[3]),
                "low": float(k[4]),
                "volume": int(float(k[5])) if len(k) > 5 and k[5] else 0,
            })
        return klines
    except Exception as e:
        print(f"[Data] K线失败 {code}: {e}")
        return None


# ============================================================
# 全市场列表
# ============================================================

def get_all_stocks(include_bj: bool = False, include_star: bool = True) -> List[dict]:
    """全市场A股列表（东财主源 + 腾讯备用源 + TDX科创板补充）

    返回: [{code: 'sh600000'|'sz000001'|'bj830001', pure_code, name}, ...]
    V3.3: include_star 默认 True，从 TDX 补充科创板(688)股票
    """
    stocks = _get_all_from_eastmoney(include_bj)
    if not stocks:
        stocks = _get_all_from_tencent(include_bj)

    # V3.3: 补充科创板（腾讯备用源不含688xxx）
    if include_star:
        star_count = sum(1 for s in stocks if "688" in s["pure_code"][:3])
        if star_count < 10:
            _add_codes_from_range(stocks, "sh", 688001, 688600, "科创板")

    # V3.5: 补充北交所（腾讯备用源不含4xx/8xx/920）
    if include_bj:
        bj_count = sum(1 for s in stocks if s["pure_code"].startswith(("4", "8", "920")))
        if bj_count < 10:
            _add_codes_from_range(stocks, "bj", 430001, 430300, "北交所")
            _add_codes_from_range(stocks, "bj", 830001, 830600, "北交所")
            _add_codes_from_range(stocks, "bj", 920001, 920200, "北交所")
    return stocks


def _add_codes_from_range(stocks: List[dict], prefix: str,
                          start: int, end: int, label: str):
    """批量添加代码段到股票列表"""
    seen = {s["pure_code"] for s in stocks}
    for i in range(start, end + 1):
        code = str(i)
        if code not in seen:
            stocks.append({
                "code": f"{prefix}{code}",
                "pure_code": code,
                "name": f"{label}{code}",
            })
            seen.add(code)


def _get_all_from_eastmoney(include_bj: bool) -> List[dict]:
    """东方财富分页拉取全市场"""
    stocks = []
    seen = set()
    try:
        for pn in range(1, 60):   # 最多 59 页 x 100 = 5900 只
            resp = requests.get(EASTMONEY_LIST_URL, params={
                "pn": str(pn), "pz": "100", "po": "1", "np": "1",
                "fltt": "2", "invt": "2", "fid": "f3",
                "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048",
                "fields": "f12,f14",
            }, timeout=15)
            data = resp.json()
            diff = (data.get("data") or {}).get("diff") or []
            if not diff:
                break
            page_count = 0
            for item in diff:
                code = item.get("f12", "")
                name = item.get("f14", "")
                if not code or not name or code in seen:
                    continue
                seen.add(code)
                page_count += 1
                # 北交所: 4/8/920 开头；默认剔除
                if not include_bj and (code.startswith(("4", "8", "920"))):
                    continue
                stocks.append(_make_entry(code, name))
            if len(diff) < 100:
                break   # 最后一页（用原始响应数量，排除去重导致的误判）
        return stocks
    except Exception as e:
        print(f"[Data] 东财全市场列表失败: {e}")
        return []


def _get_all_from_tencent(include_bj: bool) -> List[dict]:
    """腾讯排行接口备用源（沪深A股，翻页拉取）"""
    stocks = []
    seen = set()
    try:
        for page in range(0, 60):
            resp = requests.get(TENCENT_RANK_URL, params={
                "board_code": "aStock", "sort_type": "price", "direct": "down",
                "offset": str(page * 100), "count": "100",
            }, timeout=15)
            data = resp.json()
            rank = ((data.get("data") or {}).get("rank_list")) or []
            if not rank:
                break
            page_count = 0
            for item in rank:
                code = str(item.get("code", ""))
                name = str(item.get("name", ""))
                if not code or not name or code in seen:
                    continue
                seen.add(code)
                page_count += 1
                pure = _pure(code)
                if not include_bj and pure.startswith(("4", "8", "920")):
                    continue
                stocks.append(_make_entry(pure, name))
            if page_count < 100:
                break
        return stocks
    except Exception as e:
        print(f"[Data] 腾讯全市场列表失败: {e}")
        return []


def _make_entry(code: str, name: str) -> dict:
    """构造股票条目（代码段 → 市场前缀）"""
    if code.startswith(("6", "9")):
        prefix = "sh"
    elif code.startswith(("4", "8", "92")):
        prefix = "bj"
    else:
        prefix = "sz"
    return {"code": f"{prefix}{code}", "pure_code": code, "name": name}


# ============================================================
# 并发拉取（批量K线 + 行情）
# ============================================================

def fetch_klines_batch(codes: List[str], count: int = 90, workers: int = 10,
                       retries: int = 2) -> Dict[str, Optional[List[dict]]]:
    """并发拉取多只股票K线，带重试。V3.3: 688xxx/4xx/8xx 自动走 TDX"""
    def fetch_one(code: str) -> tuple:
        for attempt in range(retries + 1):
            kl = get_kline(code, count)
            if kl:
                return code, kl
            time.sleep(0.3 * (attempt + 1))
        # V3.3: 腾讯失败时，科创板/北交所尝试 TDX
        pure = "".join(c for c in code if c.isdigit())
        if pure.startswith(("688", "4", "8", "920")):
            try:
                from tdx_data_provider import get_tdx_kline
                setc = "1" if pure.startswith(("6", "68")) else "0"
                kl = get_tdx_kline(pure, setcode=setc, want_num=count)
                if kl:
                    return code, kl
            except ImportError:
                pass
        return code, None

    results: Dict[str, Optional[List[dict]]] = {}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(fetch_one, c) for c in codes]
        for fut in as_completed(futs):
            code, kl = fut.result()
            results[code] = kl
    return results


def fetch_quotes_batch(codes: List[str], workers: int = 10) -> Dict[str, Optional[dict]]:
    """并发拉取实时行情"""
    results: Dict[str, Optional[dict]] = {}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(get_realtime_quote, c) for c in codes]
        for fut in as_completed(futs):
            q = fut.result()
            if q:
                results[q["code"]] = q
    return results


# ============================================================
# 搜索
# ============================================================

def search_stock(keyword: str) -> List[dict]:
    """腾讯搜索（名称/代码 → 股票）"""
    url = f"https://smartbox.gtimg.cn/s3/?t=all&q={keyword}"
    try:
        resp = requests.get(url, timeout=10)
        resp.encoding = "gbk"
        results = []
        for m in re.findall(r'(\d{6})\^([^\^]+)\^(\d)', resp.text):
            code, name, flag = m
            prefix = "sh" if flag == "1" else "sz"
            results.append({"code": f"{prefix}{code}", "pure_code": code, "name": name})
        return results
    except Exception as e:
        print(f"[Data] 搜索失败 {keyword}: {e}")
        return []


if __name__ == "__main__":
    print("=== 测试实时行情 ===")
    q = get_realtime_quote("000001")
    if q:
        print(f"  {q['name']} ({q['code']}): {q['price']} 换手{q['turnover']}%")
    print("=== 测试K线 ===")
    kl = get_kline("000001", 10)
    if kl:
        print(f"  获取 {len(kl)} 根，最新 {kl[-1]}")
    print("=== 测试全市场 ===")
    all_stocks = get_all_stocks()
    print(f"  共 {len(all_stocks)} 只")
