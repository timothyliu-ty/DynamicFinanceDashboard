"""qsdash 配置：标的池、端点、刷新周期。

端点可用性与字段序位**全部来自本机实测**（SPEC-DASH §2），不得凭记忆改动。
改动字段索引前必须先在 verify_mapping*.py 里复现判据。

来源速记：
  sina hq.sinajs.cn    GBK，需 Referer
      gb_* 美股   int_* 全球指数   sh/sz 中国指数   fx_s* 外汇   hf_* 国际期货
  tencent qt.gtimg.cn  GBK（本机作为 hf_/us 的交叉核对源）
  treasury XML         美债名义 + 实际收益率曲线（日频）
  frankfurter / ECB    外汇日频参考
  binance              加密主源（同刻六源互差 0.0813%，SPEC-DASH §2.2f）
  RSS × 15             新闻
"""

from __future__ import annotations

import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

# ----------------------------------------------------------------------------
# HTTP
# ----------------------------------------------------------------------------
HTTP_TIMEOUT = 12
HTTP_RETRIES = 2          # 仅对网络层异常重试；4xx/5xx 不重试（是端点否决，不是抖动）
USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

# ----------------------------------------------------------------------------
# 端点
# ----------------------------------------------------------------------------
SINA_QUOTE = "https://hq.sinajs.cn/list="
TENCENT_QUOTE = "https://qt.gtimg.cn/q="
TREASURY_NOMINAL = ("https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
                    "pages/xml?data=daily_treasury_yield_curve&field_tdr_date_value={year}")
TREASURY_REAL = ("https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
                 "pages/xml?data=daily_treasury_real_yield_curve&field_tdr_date_value={year}")
BINANCE_24HR = "https://api.binance.com/api/v3/ticker/24hr?symbols={symbols}"
FRANKFURTER = "https://api.frankfurter.app/latest?from=USD"
ECB_DAILY = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"

# ----------------------------------------------------------------------------
# 标的池
#   EQUITY 分三组，因为三种 sina 前缀的字段布局不同（SPEC-DASH §2.2a/b/c）
# ----------------------------------------------------------------------------
UNIVERSE = {
    "EQUITY": {
        "us": ["aapl", "msft", "nvda", "googl", "amzn", "meta",
               "tsla", "avgo", "jpm", "xom", "wmt", "lly"],
        "int_idx": ["int_dji", "int_nasdaq", "int_sp500",
                    "int_hangseng", "int_nikkei", "int_ftse"],
        "cn_idx": ["sh000001", "sz399001", "sz399006", "sh000300", "sh000688"],
    },
    "FX": ["fx_susdcny", "fx_seurusd", "fx_susdjpy", "fx_sgbpusd",
           "fx_saudusd", "fx_susdchf", "fx_susdcad", "fx_susdcnh"],
    # 只用国际盘 hf_*；nf_*（上期所）因昨结算索引未证实而排除，见 SPEC-DASH §2.3
    # 18 个候选实测后剔除 6 个 sina 不提供的代码（hf_PL/PA/RB/ZC/ZS/SB -> 字段缺失）
    "COMMODITIES": ["hf_GC", "hf_SI", "hf_HG",              # 金属
                    "hf_CL", "hf_NG", "hf_HO",              # 能源
                    "hf_C", "hf_S", "hf_W",                 # 谷物
                    "hf_KC", "hf_CT", "hf_CC"],             # 软商品
    "BONDS": ["1M", "3M", "6M", "1Y", "2Y", "3Y", "5Y", "7Y", "10Y", "20Y", "30Y"],
    "CRYPTO": ["BTC", "ETH", "SOL", "BNB", "XRP", "DOGE",
               "ADA", "AVAX", "LINK", "SUI"],
}

# 美债曲线字段名 → 展示期限
TREASURY_TENOR_FIELD = {
    "1M": "BC_1MONTH", "3M": "BC_3MONTH", "6M": "BC_6MONTH", "1Y": "BC_1YEAR",
    "2Y": "BC_2YEAR", "3Y": "BC_3YEAR", "5Y": "BC_5YEAR", "7Y": "BC_7YEAR",
    "10Y": "BC_10YEAR", "20Y": "BC_20YEAR", "30Y": "BC_30YEAR",
}
TREASURY_REAL_FIELD = {"5Y": "TC_5YEAR", "10Y": "TC_10YEAR", "20Y": "TC_20YEAR", "30Y": "TC_30YEAR"}

# ----------------------------------------------------------------------------
# 新闻源（15 个，本机实测全部可达 —— SPEC-DASH §2.2g）
# ----------------------------------------------------------------------------
NEWS_FEEDS = [
    ("CNBC Top",      "https://www.cnbc.com/id/100003114/device/rss/rss.html",                    "GENERAL"),
    ("CNBC Markets",  "https://www.cnbc.com/id/20910258/device/rss/rss.html",                     "GENERAL"),
    ("MarketWatch",   "https://feeds.content.dowjones.io/public/rss/mw_topstories",               "GENERAL"),
    ("Yahoo Finance", "https://finance.yahoo.com/news/rssindex",                                  "GENERAL"),
    ("FT",            "https://www.ft.com/rss/home",                                              "GENERAL"),
    ("BBC Business",  "https://feeds.bbci.co.uk/news/business/rss.xml",                           "GENERAL"),
    ("Investing",     "https://www.investing.com/rss/news.rss",                                   "GENERAL"),
    ("Investing Econ","https://www.investing.com/rss/news_14.rss",                                "MACRO"),
    ("Seeking Alpha", "https://seekingalpha.com/market_currents.xml",                             "GENERAL"),
    ("ZeroHedge",     "https://feeds.feedburner.com/zerohedge/feed",                              "GENERAL"),
    ("GoogleNews Mkt","https://news.google.com/rss/search?q=stock+market+when:1d&hl=en-US&gl=US&ceid=US:en", "GENERAL"),
    ("Reuters(via GN)","https://news.google.com/rss/search?q=when:1d+site:reuters.com+business&hl=en-US&gl=US&ceid=US:en", "GENERAL"),
    ("CoinTelegraph", "https://cointelegraph.com/rss",                                            "CRYPTO"),
    ("The Block",     "https://www.theblock.co/rss.xml",                                          "CRYPTO"),
    ("Decrypt",       "https://decrypt.co/feed",                                                  "CRYPTO"),
]

# ----------------------------------------------------------------------------
# 刷新周期（秒）—— 见 AC-D4.1
# ----------------------------------------------------------------------------
REFRESH = {
    "EQUITY": 10,
    "FX": 10,
    "COMMODITIES": 15,
    "BONDS": 900,
    "CRYPTO": 5,
    "NEWS": 90,
}

ASSET_CLASSES = ["EQUITY", "FX", "COMMODITIES", "BONDS", "CRYPTO"]

# 面板中文/英文标注（Bloomberg 风格用英文缩写，副标注用中文）
CLASS_LABEL = {
    "EQUITY":      ("EQUITIES",     "股票"),
    "FX":          ("FX",           "外汇"),
    "COMMODITIES": ("COMMODITIES",  "大宗商品"),
    "BONDS":       ("BONDS",        "债券"),
    "CRYPTO":      ("CRYPTO",       "加密货币"),
    "NEWS":        ("NEWS",         "市场情报"),
}

# 加密展示名与 binance 符号
CRYPTO_SYMBOLS = {s: s + "USDT" for s in UNIVERSE["CRYPTO"]}
CRYPTO_NAMES = {
    "BTC": "Bitcoin", "ETH": "Ethereum", "SOL": "Solana", "BNB": "BNB",
    "XRP": "XRP", "DOGE": "Dogecoin", "ADA": "Cardano", "AVAX": "Avalanche",
    "LINK": "Chainlink", "SUI": "Sui",
}
CURRENCY_BY_CLASS = {"EQUITY": "USD", "FX": "", "COMMODITIES": "USD",
                     "BONDS": "%", "CRYPTO": "USD"}

os.makedirs(DATA_DIR, exist_ok=True)
