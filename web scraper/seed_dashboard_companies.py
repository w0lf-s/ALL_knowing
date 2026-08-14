from __future__ import annotations

import asyncio
import csv
import io
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(REPO / "not to share" / ".env")

from src.adapters import CompanyContext, SourceResult
from src.adapters.yahoo import YAHOO_HEADERS, fetch_yahoo_quote
from src.http import HttpClient
from src.merge import merge_dossier
from src.paths import company_key
from src.schema import CompanyDossier
from src.store import list_company_records, put_company

SP500_URLS = (
    "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/master/data/constituents.csv",
    "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv",
)

GLOBAL = [
    ("RELIANCE.NS", "Reliance Industries"),
    ("TCS.NS", "Tata Consultancy Services"),
    ("HDFCBANK.NS", "HDFC Bank"),
    ("INFY.NS", "Infosys"),
    ("ICICIBANK.NS", "ICICI Bank"),
    ("HINDUNILVR.NS", "Hindustan Unilever"),
    ("SBIN.NS", "State Bank of India"),
    ("BHARTIARTL.NS", "Bharti Airtel"),
    ("ITC.NS", "ITC"),
    ("LT.NS", "Larsen & Toubro"),
    ("KOTAKBANK.NS", "Kotak Mahindra Bank"),
    ("AXISBANK.NS", "Axis Bank"),
    ("BAJFINANCE.NS", "Bajaj Finance"),
    ("ASIANPAINT.NS", "Asian Paints"),
    ("MARUTI.NS", "Maruti Suzuki"),
    ("SUNPHARMA.NS", "Sun Pharmaceutical"),
    ("TITAN.NS", "Titan Company"),
    ("WIPRO.NS", "Wipro"),
    ("ULTRACEMCO.NS", "UltraTech Cement"),
    ("NESTLEIND.NS", "Nestle India"),
    ("HCLTECH.NS", "HCL Technologies"),
    ("POWERGRID.NS", "Power Grid Corporation of India"),
    ("NTPC.NS", "NTPC"),
    ("TATAMOTORS.NS", "Tata Motors"),
    ("TATASTEEL.NS", "Tata Steel"),
    ("ADANIENT.NS", "Adani Enterprises"),
    ("ADANIPORTS.NS", "Adani Ports"),
    ("ONGC.NS", "Oil and Natural Gas Corporation"),
    ("COALINDIA.NS", "Coal India"),
    ("JSWSTEEL.NS", "JSW Steel"),
    ("BAJAJ-AUTO.NS", "Bajaj Auto"),
    ("HEROMOTOCO.NS", "Hero MotoCorp"),
    ("EICHERMOT.NS", "Eicher Motors"),
    ("DRREDDY.NS", "Dr. Reddy's Laboratories"),
    ("CIPLA.NS", "Cipla"),
    ("DIVISLAB.NS", "Divi's Laboratories"),
    ("GRASIM.NS", "Grasim Industries"),
    ("HINDALCO.NS", "Hindalco Industries"),
    ("INDUSINDBK.NS", "IndusInd Bank"),
    ("TECHM.NS", "Tech Mahindra"),
    ("BPCL.NS", "Bharat Petroleum"),
    ("BRITANNIA.NS", "Britannia Industries"),
    ("SHREECEM.NS", "Shree Cement"),
    ("APOLLOHOSP.NS", "Apollo Hospitals"),
    ("TATACONSUM.NS", "Tata Consumer Products"),
    ("UPL.NS", "UPL"),
    ("SBILIFE.NS", "SBI Life Insurance"),
    ("HDFCLIFE.NS", "HDFC Life"),
    ("BAJAJFINSV.NS", "Bajaj Finserv"),
    ("M&M.NS", "Mahindra & Mahindra"),
    ("SHEL.L", "Shell"),
    ("BP.L", "BP"),
    ("HSBA.L", "HSBC Holdings"),
    ("AZN.L", "AstraZeneca"),
    ("GSK.L", "GSK"),
    ("ULVR.L", "Unilever"),
    ("DGE.L", "Diageo"),
    ("BATS.L", "British American Tobacco"),
    ("RIO.L", "Rio Tinto"),
    ("GLEN.L", "Glencore"),
    ("VOD.L", "Vodafone"),
    ("BT-A.L", "BT Group"),
    ("LLOY.L", "Lloyds Banking Group"),
    ("BARC.L", "Barclays"),
    ("NWG.L", "NatWest Group"),
    ("RR.L", "Rolls-Royce"),
    ("BA.L", "BAE Systems"),
    ("REL.L", "RELX"),
    ("PRU.L", "Prudential"),
    ("AAL.L", "Anglo American"),
    ("SAP.DE", "SAP"),
    ("SIE.DE", "Siemens"),
    ("ALV.DE", "Allianz"),
    ("DTE.DE", "Deutsche Telekom"),
    ("BMW.DE", "BMW"),
    ("MBG.DE", "Mercedes-Benz Group"),
    ("VOW3.DE", "Volkswagen"),
    ("BAS.DE", "BASF"),
    ("BAYN.DE", "Bayer"),
    ("MUV2.DE", "Munich Re"),
    ("DB1.DE", "Deutsche Boerse"),
    ("IFX.DE", "Infineon"),
    ("ADS.DE", "Adidas"),
    ("DHL.DE", "DHL Group"),
    ("RWE.DE", "RWE"),
    ("AIR.PA", "Airbus"),
    ("MC.PA", "LVMH"),
    ("OR.PA", "L'Oreal"),
    ("SAN.PA", "Sanofi"),
    ("TTE.PA", "TotalEnergies"),
    ("BNP.PA", "BNP Paribas"),
    ("AI.PA", "Air Liquide"),
    ("SU.PA", "Schneider Electric"),
    ("KER.PA", "Kering"),
    ("DG.PA", "Vinci"),
    ("ASML.AS", "ASML"),
    ("INGA.AS", "ING Groep"),
    ("UNA.AS", "Unilever"),
    ("PHIA.AS", "Philips"),
    ("NESN.SW", "Nestle"),
    ("ROG.SW", "Roche"),
    ("NOVN.SW", "Novartis"),
    ("UBSG.SW", "UBS"),
    ("CFR.SW", "Richemont"),
    ("7203.T", "Toyota Motor"),
    ("6758.T", "Sony Group"),
    ("9984.T", "SoftBank Group"),
    ("8306.T", "Mitsubishi UFJ"),
    ("6861.T", "Keyence"),
    ("4063.T", "Shin-Etsu Chemical"),
    ("6098.T", "Recruit Holdings"),
    ("8035.T", "Tokyo Electron"),
    ("9983.T", "Fast Retailing"),
    ("4519.T", "Chugai Pharmaceutical"),
    ("005930.KS", "Samsung Electronics"),
    ("000660.KS", "SK Hynix"),
    ("035420.KS", "Naver"),
    ("035720.KS", "Kakao"),
    ("051910.KS", "LG Chem"),
    ("006400.KS", "Samsung SDI"),
    ("068270.KS", "Celltrion"),
    ("105560.KS", "KB Financial"),
    ("2330.TW", "TSMC"),
    ("2317.TW", "Hon Hai Precision"),
    ("2454.TW", "MediaTek"),
    ("0700.HK", "Tencent"),
    ("9988.HK", "Alibaba"),
    ("3690.HK", "Meituan"),
    ("1299.HK", "AIA"),
    ("0939.HK", "China Construction Bank"),
    ("1398.HK", "ICBC"),
    ("9618.HK", "JD.com"),
    ("1810.HK", "Xiaomi"),
    ("BABA", "Alibaba"),
    ("JD", "JD.com"),
    ("PDD", "PDD Holdings"),
    ("BIDU", "Baidu"),
    ("NIO", "NIO"),
    ("LI", "Li Auto"),
    ("XPEV", "XPeng"),
    ("TCEHY", "Tencent"),
    ("SONY", "Sony"),
    ("TM", "Toyota Motor"),
    ("HMC", "Honda Motor"),
    ("SFTBY", "SoftBank"),
    ("VALE", "Vale"),
    ("PBR", "Petrobras"),
    ("ITUB", "Itau Unibanco"),
    ("BBD", "Banco Bradesco"),
    ("ABEV", "Ambev"),
    ("BHP", "BHP Group"),
    ("RIO", "Rio Tinto"),
    ("WES.AX", "Wesfarmers"),
    ("CBA.AX", "Commonwealth Bank"),
    ("NAB.AX", "National Australia Bank"),
    ("WOW.AX", "Woolworths Group"),
    ("CSL.AX", "CSL"),
    ("FMG.AX", "Fortescue"),
    ("RY.TO", "Royal Bank of Canada"),
    ("TD.TO", "Toronto-Dominion Bank"),
    ("SHOP.TO", "Shopify"),
    ("ENB.TO", "Enbridge"),
    ("CNQ.TO", "Canadian Natural Resources"),
    ("NVO", "Novo Nordisk"),
    ("SPOT", "Spotify"),
    ("SE", "Sea Limited"),
    ("GRAB", "Grab Holdings"),
    ("NU", "Nu Holdings"),
    ("MELI", "MercadoLibre"),
    ("GLOB", "Globant"),
    ("TSM", "TSMC"),
    ("INFY", "Infosys"),
    ("WIT", "Wipro"),
    ("IBN", "ICICI Bank"),
    ("HDB", "HDFC Bank"),
    ("TTM", "Tata Motors"),
    ("SIFY", "Sify Technologies"),
    ("IMX.AX", "Iress"),
]


async def _load_sp500(http: HttpClient) -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str]] = []
    for url in SP500_URLS:
        try:
            text = await http.get_text(url, timeout=20.0, retries=1)
        except Exception:
            continue
        reader = csv.DictReader(io.StringIO(text))
        for row in reader:
            sym = (row.get("Symbol") or row.get("symbol") or "").strip().replace(".", "-")
            name = (row.get("Name") or row.get("Security") or row.get("name") or "").strip()
            sector = (row.get("Sector") or row.get("GICS Sector") or row.get("sector") or "").strip()
            if sym and name:
                rows.append((sym, name, sector))
        if rows:
            break
    return rows


def _candidates(sp: list[tuple[str, str, str]]) -> list[tuple[str, str]]:
    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for ticker, name, *_rest in GLOBAL + [(a, b) for a, b, *_ in sp]:
        key = ticker.upper()
        if key in seen:
            continue
        seen.add(key)
        out.append((ticker, name))
    return out


async def _seed_one(http: HttpClient, sem: asyncio.Semaphore, ticker: str, name: str) -> bool:
    async with sem:
        ctx = CompanyContext(query=name, ticker=ticker, name=name)
        yh = await fetch_yahoo_quote(http, ctx)
        if yh.ok and isinstance(yh.data, dict):
            used = yh.data.get("symbol")
            if used:
                ctx.ticker = used
            quote = yh.data.get("quote") or {}
            price = quote.get("price") or {}
            profile = quote.get("summaryProfile") or {}
            if price.get("longName"):
                ctx.name = price.get("longName")
            if profile.get("website") and not ctx.website:
                ctx.website = profile.get("website")
        wiki = SourceResult("wikipedia", False, error="skipped_seed")
        generated_at = datetime.now(timezone.utc).isoformat()
        sources = {
            "yahoo": yh,
            "wikipedia": wiki,
            "finnhub": SourceResult("finnhub", False, error="skipped_seed"),
            "alpha_vantage": SourceResult("alpha_vantage", False, error="skipped_seed"),
            "sec_edgar": SourceResult("sec_edgar", False, error="skipped_seed"),
            "nse": SourceResult("nse", False, error="skipped_seed"),
            "github": SourceResult("github", False, error="skipped_seed"),
            "rss": SourceResult("rss", False, error="skipped_seed"),
            "newsapi": SourceResult("newsapi", False, error="skipped_seed"),
            "gnews": SourceResult("gnews", False, error="skipped_seed"),
        }
        try:
            dossier = merge_dossier(
                name,
                ctx,
                sources,
                news_articles=[],
                lookback_days=3,
                generated_at=generated_at,
            )
            dossier = CompanyDossier.model_validate(dossier.model_dump())
            payload = dossier.model_dump()
            payload["news"] = {"digest_summary": None, "lookback_days": 3, "articles": [], "fetched_at": None}
            key = company_key(str(ctx.ticker or ticker))
            put_company(key, payload, disk=False)
            return True
        except Exception:
            return False


async def main_async() -> int:
    existing = {r["key"] for r in list_company_records() if r.get("key")}
    target = 500
    http = HttpClient()
    try:
        sp = await _load_sp500(http)
        wanted = _candidates(sp)
        sem = asyncio.Semaphore(5)
        jobs = []
        for ticker, name in wanted:
            if len(existing) + len(jobs) >= target:
                break
            key = company_key(ticker)
            alt = company_key(name)
            if key in existing or alt in existing:
                continue
            jobs.append((ticker, name))
        results = await asyncio.gather(*[_seed_one(http, sem, t, n) for t, n in jobs], return_exceptions=True)
        ok = sum(1 for r in results if r is True)
        return 0 if ok or existing else 1
    finally:
        await http.aclose()


async def _v7_quotes(http: HttpClient, symbols: list[str]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for i in range(0, len(symbols), 40):
        chunk = symbols[i : i + 40]
        try:
            data = await http.get_json(
                "https://query1.finance.yahoo.com/v7/finance/quote",
                params={"symbols": ",".join(chunk)},
                headers=YAHOO_HEADERS,
                retries=2,
                timeout=20.0,
            )
        except Exception:
            continue
        rows = ((data or {}).get("quoteResponse") or {}).get("result") or []
        for row in rows:
            sym = str(row.get("symbol") or "").upper()
            if sym:
                out[sym] = row
        await asyncio.sleep(0.2)
    return out


async def _wiki_summary(http: HttpClient, sem: asyncio.Semaphore, title: str) -> dict:
    async with sem:
        try:
            data = await http.get_json(
                f"https://en.wikipedia.org/api/rest_v1/page/summary/{quote(title)}",
                headers={
                    "User-Agent": "AllKnowingCompanySearch/1.0 (educational research; contact@example.com)",
                    "Accept": "application/json",
                },
                retries=1,
                timeout=10.0,
            )
        except Exception:
            return {}
        if not isinstance(data, dict):
            return {}
        if str(data.get("type") or "").lower() == "disambiguation":
            return {}
        extract = str(data.get("extract") or "").strip()
        desc = str(data.get("description") or "").strip()
        if "may refer to" in extract.lower() or "disambiguation" in desc.lower():
            return {}
        return {"extract": extract, "description": desc}


async def enrich_async() -> int:
    recs = list_company_records()
    http = HttpClient()
    try:
        sp = await _load_sp500(http)
        sector_map: dict[str, str] = {}
        for ticker, _name, sector in sp:
            if ticker and sector:
                sector_map[ticker.upper().replace(".", "-")] = sector
                sector_map[ticker.upper()] = sector
        symbols = []
        for rec in recs:
            d = rec.get("dossier") or {}
            t = str(((d.get("resolved") or {}).get("ticker") or "")).upper()
            if t:
                symbols.append(t)
        quotes = await _v7_quotes(http, symbols)
        sem = asyncio.Semaphore(8)
        wiki_jobs = []
        names = []
        for rec in recs:
            d = rec.get("dossier") or {}
            name = (d.get("resolved") or {}).get("name") or d.get("query") or ""
            names.append(name)
            wiki_jobs.append(_wiki_summary(http, sem, str(name)))
        wiki_rows = await asyncio.gather(*wiki_jobs, return_exceptions=True)
        for rec, wiki in zip(recs, wiki_rows):
            if not isinstance(wiki, dict):
                wiki = {}
            d = rec.get("dossier") or {}
            resolved = dict(d.get("resolved") or {})
            overview = dict(d.get("overview") or {})
            financials = dict(d.get("financials") or {})
            ticker = str(resolved.get("ticker") or "").upper()
            q = quotes.get(ticker) or quotes.get(ticker.replace("-", ".")) or {}
            if q.get("marketCap") and not financials.get("market_cap"):
                financials["market_cap"] = q.get("marketCap")
            if q.get("trailingPE") and not financials.get("pe_ratio"):
                financials["pe_ratio"] = q.get("trailingPE")
            if q.get("fiftyTwoWeekHigh") and not financials.get("week_52_high"):
                financials["week_52_high"] = q.get("fiftyTwoWeekHigh")
            if q.get("fiftyTwoWeekLow") and not financials.get("week_52_low"):
                financials["week_52_low"] = q.get("fiftyTwoWeekLow")
            if q.get("epsTrailingTwelveMonths") and not financials.get("eps"):
                financials["eps"] = q.get("epsTrailingTwelveMonths")
            if q.get("beta") and not financials.get("beta"):
                financials["beta"] = q.get("beta")
            cur = q.get("currency") or q.get("financialCurrency")
            if cur:
                overview["currency"] = overview.get("currency") or cur
                financials["currency"] = financials.get("currency") or cur
            if q.get("longName"):
                resolved["name"] = resolved.get("name") or q.get("longName")
                overview["legal_name"] = overview.get("legal_name") or q.get("longName")
            sector = sector_map.get(ticker) or sector_map.get(ticker.replace("-", "."))
            if sector and not overview.get("sector"):
                overview["sector"] = sector
                overview["industry"] = overview.get("industry") or sector
            if wiki.get("description") and not overview.get("short_description"):
                overview["short_description"] = wiki["description"]
                if not overview.get("industry"):
                    overview["industry"] = wiki["description"]
            if wiki.get("extract") and not overview.get("description"):
                overview["description"] = wiki["extract"]
            d["resolved"] = resolved
            d["overview"] = overview
            d["financials"] = financials
            put_company(rec["key"], d, disk=False)
        return 0
    finally:
        await http.aclose()


async def enrich_market_caps() -> int:
    import os

    key = (os.getenv("FINNHUB_API_KEY") or "").strip()
    recs = list_company_records()
    http = HttpClient()
    try:
        for rec in recs:
            d = rec.get("dossier") or {}
            fin = dict(d.get("financials") or {})
            if fin.get("market_cap"):
                continue
            ticker = str(((d.get("resolved") or {}).get("ticker") or "")).upper()
            if not ticker or not key:
                continue
            try:
                await asyncio.sleep(1.05)
                profile = await http.get_json(
                    "https://finnhub.io/api/v1/stock/profile2",
                    params={"symbol": ticker, "token": key},
                    retries=1,
                    timeout=12.0,
                )
            except Exception:
                continue
            if not isinstance(profile, dict):
                continue
            mc = profile.get("marketCapitalization")
            if mc is None:
                continue
            try:
                val = float(mc)
            except Exception:
                continue
            if val < 1e6:
                val = val * 1_000_000
            fin["market_cap"] = val
            overview = dict(d.get("overview") or {})
            if profile.get("finnhubIndustry") and not overview.get("industry"):
                overview["industry"] = profile.get("finnhubIndustry")
            if profile.get("weburl") and not overview.get("website"):
                overview["website"] = profile.get("weburl")
            if profile.get("country") and not overview.get("country"):
                overview["country"] = profile.get("country")
            d["financials"] = fin
            d["overview"] = overview
            put_company(rec["key"], d, disk=False)
        return 0
    finally:
        await http.aclose()


if __name__ == "__main__":
    recs = list_company_records()
    if len(recs) < 500:
        raise SystemExit(asyncio.run(main_async()))
    raise SystemExit(0)
