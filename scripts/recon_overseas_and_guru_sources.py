#!/usr/bin/env python3
"""ADR-0235 recon: real, read-only probes of free data sources the
sandbox cannot reach (KRX/FinanceDataReader, the Yale 13F 1999-2017
dataset page, the OpenAP signal documentation, the JKP global factor
dataset). Prints what each source actually returns so the next step is
decided from observation, not docs.

    python3 scripts/recon_overseas_and_guru_sources.py krx|yale13f|openap|jkp
"""

from __future__ import annotations

import argparse
import re
import sys
import urllib.parse
import urllib.request

YALE_PAGE = "https://faculty.som.yale.edu/michaelsinkinson/common-ownership-data/"


def recon_krx() -> None:
    import json
    import urllib.parse as up

    body = up.urlencode({
        "bld": "dbms/MDC/STAT/issue/MDCSTAT23801", "mktId": "ALL", "isuCd": "ALL", "isuCd2": "ALL",
        "strtDd": "20030101", "endDd": "20041231", "share": "1", "csvxls_isNo": "true",
    }).encode()
    for scheme in ("http", "https"):
        req = urllib.request.Request(
            f"{scheme}://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd", data=body,
            headers={"User-Agent": "Mozilla/5.0", "Referer": "http://data.krx.co.kr/contents/MDC/MDI/mdiLoader"},
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                text = resp.read().decode("utf-8", "replace")
                print(scheme, "KRX raw status", resp.status, "len", len(text), "head:", text[:300])
                try:
                    print("keys:", list(json.loads(text).keys()))
                except Exception as exc:  # noqa: BLE001
                    print("not json:", exc)
        except Exception as exc:  # noqa: BLE001
            print(scheme, "KRX raw ERROR", type(exc).__name__, exc)
    import FinanceDataReader as fdr

    delisted = fdr.StockListing("KRX-DELISTING")
    if delisted.empty:
        print("FDR returned an EMPTY delisting list from this network")
        return
    print("delisting columns:", list(delisted.columns))
    print("delisting rows:", len(delisted))
    print(delisted.head(3).to_string())
    date_col = next((c for c in delisted.columns if "Date" in c or "date" in c or "폐지" in c), None)
    code_col = next((c for c in delisted.columns if c in ("Symbol", "Code", "종목코드")), delisted.columns[0])
    print("date_col:", date_col, "code_col:", code_col)
    if date_col is not None:
        years = delisted[date_col].astype(str).str[:4]
        print("delistings 2000-2013:", int(years.between("2000", "2013").sum()))
        sample = delisted[years.between("2003", "2012")].head(12)
    else:
        sample = delisted.head(12)
    for _, row in sample.iterrows():
        code = str(row[code_col])
        try:
            df = fdr.DataReader(f"KRX-DELISTING:{code}", "1995-01-01")
            span = (str(df.index.min())[:10], str(df.index.max())[:10]) if len(df) else None
            print(f"{code}: rows={len(df)} span={span} delisted={row[date_col] if date_col else '?'}")
        except Exception as exc:  # noqa: BLE001
            print(f"{code}: ERROR {type(exc).__name__}: {exc}")


def recon_yale13f() -> None:
    html = urllib.request.urlopen(YALE_PAGE, timeout=30).read().decode("utf-8", "replace")
    links = sorted(set(re.findall(r'href="([^"]+\.(?:zip|csv|gz|dta)[^"]*)"', html)))
    print("data links:", links)
    for link in links:
        url = link if link.startswith("http") else urllib.parse.urljoin(YALE_PAGE, link)
        try:
            req = urllib.request.Request(url, method="HEAD")
            with urllib.request.urlopen(req, timeout=30) as resp:
                print(url, resp.status, resp.headers.get("Content-Length"), resp.headers.get("Content-Type"))
        except Exception as exc:  # noqa: BLE001
            print(url, "ERROR", type(exc).__name__, exc)


def recon_openap() -> None:
    import openassetpricing as oap

    openap = oap.OpenAP()
    print("OpenAP attributes:", [a for a in dir(openap) if not a.startswith("_")])
    doc = openap.dl_signal_doc("pandas")
    print("signal doc columns:", list(doc.columns))
    print("signal count:", len(doc))
    print(doc.head(10).to_string())


def recon_openap_ls() -> None:
    import numpy as np
    import openassetpricing as oap

    openap = oap.OpenAP()
    print("list_port:", openap.list_port())
    ports = openap.dl_port("op", "pandas")
    print("port columns:", list(ports.columns), "rows:", len(ports))
    print(ports.head(3).to_string())
    print("port values:", sorted(ports["port"].astype(str).unique())[:15])
    doc = openap.dl_signal_doc("pandas")[["Acronym", "Predictability in OP", "SampleStartYear", "SampleEndYear", "Cat.Data", "Sign", "T-Stat", "Year"]]
    ls = ports[ports["port"].astype(str).str.upper() == "LS"].copy()
    ls["date"] = ls["date"].astype("datetime64[ns]")
    win = ls[(ls["date"] >= "2000-01-01") & (ls["date"] < "2013-03-21")]
    g = win.groupby("signalname")["ret"].agg(["mean", "std", "count"])
    g["t_raw"] = g["mean"] / g["std"] * np.sqrt(g["count"])
    g = g.join(doc.set_index("Acronym"), how="left")
    clear = g[(g["Predictability in OP"].astype(str) == "1_clear")]
    oos = clear[clear["SampleEndYear"] <= 1999]
    print("signals with LS in window:", len(g), "clear:", len(clear), "clear and sample ended <=1999 (true OOS):", len(oos))
    cols = ["mean", "t_raw", "SampleStartYear", "SampleEndYear", "Cat.Data", "Sign"]
    print("--- true-OOS clear signals, by |t_raw| ---")
    print(oos.reindex(oos["t_raw"].abs().sort_values(ascending=False).index)[cols].head(40).to_string())
    print("--- by Cat.Data (true OOS) ---")
    print(oos.groupby("Cat.Data").size().to_string())
    for name in ("Accruals", "Mom12m", "BM", "Size", "STreversal"):
        if name in g.index:
            print(name, g.loc[name, ["mean", "t_raw", "Sign"]].to_dict())


def recon_jkp() -> None:
    """Probe the JKP (Jensen-Kelly-Pedersen) Global Factor Data: free,
    no account/API key, hosted on Dropbox, pip-installable via the
    `globalfactordata` package. Pulls one non-US country (Korea) and one
    cluster/theme series to confirm it's really reachable and really free.
    License is CC BY-NC 4.0 (non-commercial) -- fine for this project's
    own research, not for resale.
    """
    import globalfactordata as gfd

    print("globalfactordata module file:", gfd.__file__)
    mkt = gfd.get_market_returns(freq="monthly")
    print("market_returns columns:", list(mkt.columns))
    print("market_returns rows:", len(mkt))
    print(mkt.head(3).to_string())

    kor = gfd.get_factor(category="country", name="KOR", freq="monthly")
    print("\nKOR factor columns:", list(kor.columns))
    print("KOR factor rows:", len(kor))
    if "date" in kor.columns:
        print("KOR date range:", kor["date"].min(), "to", kor["date"].max())
    print(kor.head(5).to_string())

    jpn = gfd.get_factor(category="country", name="JPN", freq="monthly")
    print("\nJPN factor rows:", len(jpn))
    if "date" in jpn.columns:
        print("JPN date range:", jpn["date"].min(), "to", jpn["date"].max())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", choices=["krx", "yale13f", "openap", "openap_ls", "jkp"])
    args = parser.parse_args()
    {
        "krx": recon_krx,
        "yale13f": recon_yale13f,
        "openap": recon_openap,
        "openap_ls": recon_openap_ls,
        "jkp": recon_jkp,
    }[args.target]()
    return 0


if __name__ == "__main__":
    sys.exit(main())
