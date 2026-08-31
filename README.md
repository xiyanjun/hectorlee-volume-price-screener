# hectorlee-volume-price-screener 量价选股系统

[![CI](https://github.com/xiyanjun/hectorlee-volume-price-screener/actions/workflows/ci.yml/badge.svg)](https://github.com/xiyanjun/hectorlee-volume-price-screener/actions/workflows/ci.yml) ![Version](https://img.shields.io/badge/version-3.7.1-blue) ![License](https://img.shields.io/badge/license-MIT--0-green) ![Python](https://img.shields.io/badge/python-3.10%2B-yellow)

纯量价关系 A 股选股系统：**6 种量价形态识别 + 130 分制多因子评分 + 多周期确认 + 行业共振 + 关注池曝光度追踪**。纯量价、零基本面依赖，覆盖全 A 股约 5,200 只（沪主板 + 深主板 + 创业板 + 科创板，可选北交所）。

本系统是三段式量化流水线的第一层滤网：

```
┌─────────────────────┐     ┌─────────────────────┐     ┌─────────────────────┐
│  VPS 量价初筛        │     │  DPP 每日精选        │     │  MPA 持仓管理        │
│  全A ~5,200 → ~159  │ ──▶ │  4层漏斗 → 1-3 只    │ ──▶ │  HOLD/WATCH/        │
│  （本仓库）          │     │  （姊妹仓库）        │     │  REDUCE/SELL        │
└─────────────────────┘     └─────────────────────┘     └─────────────────────┘
```

- 下游精选：[hectorlee-daily-precision-picker](https://github.com/xiyanjun/hectorlee-daily-precision-picker)
- 持仓管理：[hectorlee-momentum-position-advisor](https://github.com/xiyanjun/hectorlee-momentum-position-advisor)

## 六种量价形态

| 变体 | 标签 | 强度 | 描述 |
|:----:|:-----|:----:|:-----|
| D | 🔥 突破延续 | ★★★★★ | 放量后持续上涨≥5%，拒绝回调，不强制缩量 |
| E | 💜 蓄力突破 | ★★★★★ | 放量前连续≥5日阳线蓄力，标准缩量整理 |
| C | ✅ 回踩确认 | ★★★★☆ | 缩量回踩放量日高点不破，反弹站稳 |
| B | 📈 高位平台 | ★★★☆☆ | 缩量后价格在放量日区间上方窄幅运行 |
| A | 📦 标准横盘 | ★★☆☆☆ | 缩量后价格在放量日区间内横盘 |
| R | 🔄 底部反转 | ★★★★★ | 暴跌>15% + 地量 + 首阳放量≥2倍 |

核心逻辑是捕捉「**放量 → 缩量 → 横盘/整理 → 突破**」的收敛蓄力过程，按板块差异化设置阈值（主板 3%-5%，创业板 6%，科创板 4%，北交所 5%）。

## 评分体系（130 分制 + 多周期确认 -5~+10）

| 模块 | 分值 | 核心因子 |
|:-----|:----:|:---------|
| 放量质量 | 30 | 放量倍数 + 拉升幅度 + 60日新高 |
| 缩量质量 | 20 | 缩量深度 + 缩量天数 |
| 变体质量 | 25 | 振幅/位置/回调/精准度/延续性 |
| 趋势量能 | 15 | 60日新高 + MA10/MA20 支撑 + 量能多头 |
| 加分信号 | 15 | 量价齐升 / 量缩价跌 / 连阳蓄力 |
| 多因子融合 | 20 | 市值流动性 + 波动率(ATR) + 趋势强度 |
| 关注池曝光度 | 5 | 近50日历史命中次数 |
| 多周期确认 | -5~+10 | 周线 MACD 金叉 / MA10 验证 |

分层：**≥100 强势形态 | 75~99 标准形态 | <75 关注形态**。另有 7 项风险硬过滤（ST / 退市风险 / 次新 / 一字板 / 连板 / 跌势反弹 / 低换手）。

## 快速开始

```bash
git clone https://github.com/xiyanjun/hectorlee-volume-price-screener.git
cd hectorlee-volume-price-screener
pip install requests numpy  # 可选：scikit-learn pytest

cd scripts

# 全市场扫描（约2~5分钟，5,200只 × 90根K线，12并发）
python screener.py --all --top 30 --detail

# 单股诊断
python screener.py 600406 --detail

# 盘中监控（今日放量突破）
python intraday.py --today --top 20

# 持仓批量诊断
python position_diagnosis.py positions.json --detail

# 信号追踪（对比两日信号：NEW/GONE/UPGRADE/DOWNGRADE）
python signal_tracker.py --today data/signals_YYYYMMDD.json

# 参数覆盖 / 包含北交所
python screener.py --all --params '{"vol_ratio_min":2.0}' --include-bj
```

内置 59 个 pytest 用例（合成 K 线生成器覆盖全部形态与边界）：`pytest tests/`

## 数据源

| 数据 | 来源（优先级） | 说明 |
|:-----|:-----|:-----|
| 日 K 线 | hithink 本地 DuckDB 库 → 腾讯接口 → TDX | 90 根前复权；hithink 为可选加速项 |
| 全市场列表 | hithink 本地库 → 腾讯排行 → 东财 | 默认不含北交所，`--include-bj` 开启 |
| 实时行情 | 腾讯 `qt.gtimg.cn` 批量接口 | 换手率 / 名称 / ST 判断 |
| 5 分钟 K 线 | 通达信 MCP | 盘中监控（可选） |

全部为公开免费接口，开箱即用；hithink 本地库（同花顺前复权日K，需安装 hithink-finance CLI）与 TDX 适配器为可选增强，不存在时自动降级。

## 版本演进

V1.0 放量→缩量→横盘三阶段基准 → V3.0 四种变体 → V3.5 蓄力突破/多因子/多周期/行业共振/曝光度 → V3.6 自适应振幅阈值 → V3.7 背离预警扣分（横盘期放量滞涨=出货嫌疑）。详见 [SKILL.md](SKILL.md)。

## 免责声明

本项目仅供技术研究和学习交流，所有信号基于历史量价数据的统计规律，**不构成任何投资建议**。股市有风险，入市需谨慎。

## License

[MIT-0](LICENSE)
