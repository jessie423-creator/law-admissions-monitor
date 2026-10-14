#!/usr/bin/env python3
"""116 academic-year NTU/SCU master's EXAM admission announcements monitor."""
import argparse
import hashlib
import json
import logging
import os
import re
import smtplib
import sys
import time
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import urljoin, urlparse, urldefrag
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

YEAR = os.environ.get("ADMISSION_YEAR", "116")
STATE_FILE = Path(os.environ.get("STATE_FILE", "state.json"))
TAIPEI = ZoneInfo("Asia/Taipei")
SOURCES = [
    ("NTU", "臺灣大學｜碩士班一般入學考試", "https://www.aca.ntu.edu.tw/w/aca/LocalAdmissionClass_21072014071675661"),
    ("NTU", "臺灣大學｜一般入學考試報名系統", "https://exam.aca.ntu.edu.tw/grab/"),
    ("NTU", "臺灣大學｜考試簡章頁", "https://exam.aca.ntu.edu.tw/grab/Brochure/main"),
    ("NTU", "臺灣大學｜法律學系各組簡章", "https://exam.aca.ntu.edu.tw/grab/Brochure/detail.aspx"),
    ("SCU", "東吳大學｜碩士班考試公告", "https://entrance.exam.scu.edu.tw/news/碩博士學位招生/碩士班考試"),
]
KEYWORDS = re.compile(r"簡章|招生|考試|報名|筆試|放榜|錄取|日程|法律|缺額|更正|異動|時程|節次|碩士|碩專", re.I)
EXCLUDE = re.compile(r"甄試|博士班|在職專班|EMBA|碩士在職", re.I)
YEAR_RE = re.compile(rf"(?<!\d){re.escape(YEAR)}\s*學年度")
HEADER_RE = re.compile(rf"(?:國立臺灣大學|東吳大學|臺灣大學)[^\n]{{0,40}}{YEAR}\s*學年度[^\n]{{0,50}}(?:碩士班|招生)")
USER_AGENT = "LawAdmissionsMonitor/1.0 (daily public admissions pages; contact repository owner)"


def clean(s):
    return re.sub(r"\s+", " ", s or "").strip()


def digest(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def canonical(url):
    return urldefrag(url)[0]


def fetch(session, url):
    for attempt in range(3):
        try:
            response = session.get(url, timeout=(12, 35), headers={"User-Agent": USER_AGENT, "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.5"})
            response.raise_for_status()
            if not response.content:
                raise ValueError("Empty page")
            if response.encoding is None or response.encoding.lower() == "iso-8859-1":
                response.encoding = response.apparent_encoding or "utf-8"
            return response.text, response.url
        except (requests.RequestException, ValueError):
            if attempt == 2:
                raise
            time.sleep(2 * (attempt + 1))


def extract(html, url, school, source_label):
    soup = BeautifulSoup(html, "html.parser")
    for node in soup(["script", "style", "noscript", "svg", "footer", "nav"]):
        node.decompose()
    # Header detection intentionally checks for an explicitly announced target year;
    # it does not assume that a 115 page represents 116.
    page_title = clean(soup.title.get_text(" ", strip=True)) if soup.title else ""
    headings = [clean(x.get_text(" ", strip=True)) for x in soup.select("h1,h2,h3")]
    top_text = clean(soup.get_text(" ", strip=True))[:900]
    target_page = bool(YEAR_RE.search(page_title + " " + " ".join(headings[:4]) + " " + top_text[:180]))
    records = {}

    def add(title, link, detail):
        title, detail = clean(title), clean(detail)
        if not title or not KEYWORDS.search(title + " " + detail):
            return
        if EXCLUDE.search(title) or (EXCLUDE.search(detail[:65]) and not YEAR_RE.search(title)):
            return
        link = canonical(urljoin(url, link or url))
        if urlparse(link).scheme not in ("http", "https"):
            return
        identity = school + "|" + link + "|" + title
        records[digest(identity)] = {"school": school, "source": source_label, "title": title[:220], "url": link, "fingerprint": digest(title + "|" + link + "|" + detail[:450])}

    for a in soup.select("a[href]"):
        href = a.get("href", "")
        if href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        title = clean(a.get_text(" ", strip=True)) or clean(a.get("title"))
        parent = a.find_parent(["li", "tr", "article", "p", "div"])
        context = clean(parent.get_text(" ", strip=True))[:330] if parent else title
        local_year = YEAR_RE.search(title + " " + context)
        is_pdf = ".pdf" in href.lower()
        is_legal = bool(re.search(r"法律學系|法律研究所|法學", title + " " + context))
        is_exam = bool(re.search(r"考試|一般入學|簡章|筆試|報名|放榜|錄取|日程|節次", title + " " + context))
        # When a page itself is explicitly for 116, include links in its brochure area.
        if local_year and KEYWORDS.search(title + " " + context):
            add(context if len(context) <= 180 else title, href, context)
        elif target_page and (is_exam or is_legal or (is_pdf and KEYWORDS.search(context))):
            add(title or context, href, context)

    # Standalone headline/text updates, including replacement of 115 with 116 on
    # a page that has not yet exposed a clickable PDF.
    for heading in soup.select("h1,h2,h3,h4"):
        title = clean(heading.get_text(" ", strip=True))
        if YEAR_RE.search(title) and KEYWORDS.search(title) and not EXCLUDE.search(title):
            add(title, url, title)
    return records


def email_notice(events, errors, dry_run=False):
    if not events and not errors:
        return True
    now = datetime.now(TAIPEI).strftime("%Y-%m-%d %H:%M")
    lines = [f"116學年度法律研究所考試入學監測｜{now}（臺灣時間）", "", "只監測考試入學，不含甄試入學。", ""]
    for event in events:
        obj = event["data"]
        lines.extend([f"[{event['kind']}] {obj['source']}", obj["title"], obj["url"], ""])
    if errors:
        lines += ["網站讀取失敗（本次保留舊紀錄，請人工確認）：", *errors, ""]
    lines += ["公告內容及時程請以學校最新正式簡章為準。"]
    body = "\n".join(lines)
    if dry_run:
        print(body)
        return True
    sender = os.environ.get("SMTP_USER", "")
    password = os.environ.get("SMTP_APP_PASSWORD", "").replace(" ", "")
    recipients = [x.strip() for x in os.environ.get("EMAIL_TO", "").split(",") if x.strip()]
    if not sender or not password or not recipients:
        raise RuntimeError("Missing SMTP_USER, SMTP_APP_PASSWORD or EMAIL_TO secrets")
    msg = EmailMessage()
    msg["From"], msg["To"] = sender, ", ".join(recipients)
    msg["Subject"] = f"[法研所招生監測] {len(events)} 項更新 / {len(errors)} 項異常｜{YEAR}學年度"
    msg.set_content(body)
    host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    port = int(os.environ.get("SMTP_PORT", "465"))
    if port == 465:
        with smtplib.SMTP_SSL(host, port, timeout=25) as smtp:
            smtp.login(sender, password)
            smtp.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=25) as smtp:
            smtp.starttls()
            smtp.login(sender, password)
            smtp.send_message(msg)
    return True


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true", help="print notifications without email or state writes")
    p.add_argument("--test-email", action="store_true", help="send a test email, without fetching URLs")
    p.add_argument("--reset-baseline", action="store_true", help="rebuild baseline, no change notifications")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if args.test_email:
        demo = {"kind":"測試通知", "data":{"school":"TEST", "source":"系統自我測試", "title":"Email SMTP 設定成功", "url":"https://www.aca.ntu.edu.tw/"}}
        email_notice([demo], [], dry_run=args.dry_run)
        return 0
    state = json.loads(STATE_FILE.read_text(encoding="utf-8")) if STATE_FILE.exists() else {}
    prior = state.get("sources", {})
    next_sources = dict(prior)
    events, errors = [], []
    with requests.Session() as session:
        for school, label, url in SOURCES:
            logging.info("Checking %s: %s", label, url)
            try:
                html, final_url = fetch(session, url)
                found = extract(html, final_url, school, label)
                previous = prior.get(url, {})
                if url not in prior or args.reset_baseline:
                    logging.info("Baseline saved: %s (%d records)", label, len(found))
                else:
                    for key, value in found.items():
                        if key not in previous:
                            events.append({"kind":"新增公告或連結", "data":value})
                        elif previous[key]["fingerprint"] != value["fingerprint"]:
                            events.append({"kind":"公告文字或連結變更", "data":value})
                # Retain disappeared records so old notices don't spam on page movement.
                merged = {**previous, **found}
                next_sources[url] = merged
            except Exception as exc:
                logging.exception("Failed %s", url)
                errors.append(f"{label}：{url}；{type(exc).__name__}: {exc}")
    # Do not save new state when sending fails: retry notifications on next run.
    if events or errors:
        email_notice(events, errors, dry_run=args.dry_run)
    if not args.dry_run:
        STATE_FILE.write_text(json.dumps({"year": YEAR, "updated_at": datetime.now(TAIPEI).isoformat(), "sources": next_sources}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Finished: {len(events)} changes, {len(errors)} errors, {len(SOURCES)} URLs checked")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
