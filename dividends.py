import requests
from bs4 import BeautifulSoup
from datetime import date, datetime, timedelta
from pathlib import Path
import re

COMPANIES = {
    "BTRW": "Barratt Redrow",
    "LGEN": "Legal & General",
    "BARC": "Barclays",
    "PSN": "Persimmon",
    "TW.": "Taylor Wimpey",
    "GRG": "Greggs",
    "AV.": "Aviva",
}

BASE_URL = (
    "https://www.dividenddata.co.uk/"
    "ex-dividend-date-search.py?searchTerm="
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 "
        "(compatible; UKDividendCalendar/1.0)"
    )
}

TODAY = date.today()
MIN_DATE = TODAY - timedelta(days=14)
MAX_DATE = TODAY + timedelta(days=450)


def parse_date(value):
    value = value.strip()

    formats = [
        "%d-%b-%y",
        "%d-%b-%Y",
        "%d/%m/%Y",
    ]

    for fmt in formats:
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            pass

    match = re.match(
        r"(\d{1,2})-([A-Za-z]{3})-(\d{2,4})",
        value,
    )

    if match:
        day, month, year = match.groups()

        if len(year) == 2:
            year = "20" + year

        return datetime.strptime(
            f"{day}-{month}-{year}",
            "%d-%b-%Y",
        ).date()

    return None


def clean(text):
    return " ".join(text.split())


def get_tables(html):
    soup = BeautifulSoup(html, "html.parser")
    tables = []

    for table in soup.find_all("table"):
        rows = []

        for tr in table.find_all("tr"):
            cells = [
                clean(c.get_text(" ", strip=True))
                for c in tr.find_all(["th", "td"])
            ]

            if cells:
                rows.append(cells)

        if rows:
            tables.append(rows)

    return tables


def find_dividend_events(ticker, company):
    url = BASE_URL + requests.utils.quote(ticker)

    response = requests.get(
        url,
        headers=HEADERS,
        timeout=30,
    )

    response.raise_for_status()

    tables = get_tables(response.text)
    events = []

    for rows in tables:
        if not rows:
            continue

        header = " ".join(rows[0]).lower()

        if (
            "ex-dividend" not in header
            or "payment" not in header
        ):
            continue

        for row in rows[1:]:
            if len(row) < 6:
                continue

            try:
                dividend = row[0]
                div_type = row[1]
                declaration = row[2]

                ex_date = parse_date(row[4])
                payment_date = parse_date(row[5])

                if not ex_date or not payment_date:
                    continue

                if (
                    ex_date < MIN_DATE
                    and payment_date < MIN_DATE
                ):
                    continue

                if (
                    ex_date > MAX_DATE
                    and payment_date > MAX_DATE
                ):
                    continue

                events.append(
                    {
                        "ticker": ticker,
                        "company": company,
                        "dividend": dividend,
                        "type": div_type,
                        "declaration": declaration,
                        "ex_date": ex_date,
                        "payment_date": payment_date,
                    }
                )

            except (ValueError, IndexError):
                continue

    return events


def escape_ics(value):
    return (
        str(value)
        .replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\n", "\\n")
    )


def ics_date(d):
    return d.strftime("%Y%m%d")


def make_uid(ticker, event_type, event_date):
    clean_ticker = ticker.replace(".", "")

    return (
        f"{clean_ticker}-"
        f"{event_type}-"
        f"{event_date.strftime('%Y%m%d')}"
        "@uk-dividend-calendar"
    )


def make_event(
    ticker,
    company,
    dividend,
    div_type,
    event_type,
    event_date,
):
    if event_type == "EX-DIVIDEND":
        summary = (
            f"{ticker} — {company} — "
            f"EX-DIVIDEND — {dividend}"
        )

        description = (
            f"{company} ({ticker})\n"
            f"Dividend: {dividend}\n"
            f"Type: {div_type}\n"
            f"Event: Ex-dividend date"
        )

    else:
        summary = (
            f"{ticker} — {company} — "
            f"PAYMENT — {dividend}"
        )

        description = (
            f"{company} ({ticker})\n"
            f"Dividend: {dividend}\n"
            f"Type: {div_type}\n"
            f"Event: Dividend payment date"
        )

    stamp = datetime.utcnow().strftime(
        "%Y%m%dT%H%M%SZ"
    )

    uid = make_uid(
        ticker,
        event_type,
        event_date,
    )

    start_date = ics_date(event_date)
    end_date = ics_date(
        event_date + timedelta(days=1)
    )

    return [
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTAMP:{stamp}",
        f"DTSTART;VALUE=DATE:{start_date}",
        f"DTEND;VALUE=DATE:{end_date}",
        f"SUMMARY:{escape_ics(summary)}",
        f"DESCRIPTION:{escape_ics(description)}",
        "TRANSP:TRANSPARENT",
        "END:VEVENT",
    ]


def build_calendar():
    all_events = []

    for ticker, company in COMPANIES.items():
        print(f"Getting {ticker}...")

        try:
            events = find_dividend_events(
                ticker,
                company,
            )

            all_events.extend(events)

            print(
                f"  Found {len(events)} "
                f"dividend records"
            )

        except Exception as exc:
            print(f"  ERROR: {exc}")

    unique = {}

    for event in all_events:
        key = (
            event["ticker"],
            event["ex_date"],
            event["payment_date"],
            event["dividend"],
        )

        unique[key] = event

    all_events = list(unique.values())

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//UK Dividend Calendar//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:UK Dividends",
        "X-WR-CALDESC:"
        "Ex-dividend and payment dates",
    ]

    for event in sorted(
        all_events,
        key=lambda x: (
            x["ex_date"],
            x["ticker"],
        ),
    ):
        lines.extend(
            make_event(
                event["ticker"],
                event["company"],
                event["dividend"],
                event["type"],
                "EX-DIVIDEND",
                event["ex_date"],
            )
        )

        lines.extend(
            make_event(
                event["ticker"],
                event["company"],
                event["dividend"],
                event["type"],
                "PAYMENT",
                event["payment_date"],
            )
        )

    lines.append("END:VCALENDAR")

    Path("dividends.ics").write_text(
        "\r\n".join(lines) + "\r\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    build_calendar()
