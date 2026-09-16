import requests
from bs4 import BeautifulSoup
from datetime import date, datetime, timedelta
from pathlib import Path


COMPANIES = {
    "BTRW": "Barratt Redrow",
    "LGEN": "Legal & General",
    "BARC": "Barclays",
    "PSN": "Persimmon",
    "TW": "Taylor Wimpey",
    "GRG": "Greggs",
    "AV": "Aviva",
}


BASE_URL = "https://dividendregistry.com/dividends/{}/"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-GB,en;q=0.9",
}


TODAY = date.today()

# Keep recently passed dates and future dates.
MIN_DATE = TODAY - timedelta(days=30)
MAX_DATE = TODAY + timedelta(days=450)


def parse_date(value):
    """Convert dates such as '15 Oct 2026' into a Python date."""

    if not value:
        return None

    value = " ".join(value.split())

    formats = [
        "%d %b %Y",
        "%d %B %Y",
        "%d-%b-%Y",
        "%d/%m/%Y",
    ]

    for fmt in formats:
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            pass

    return None


def clean(text):
    return " ".join(text.split())


def get_dividend_rows(ticker, company):
    """Read dividend rows from The Dividend Registry."""

    url = BASE_URL.format(ticker)

    print(f"Getting {ticker} ({company})...")
    print(f"URL: {url}")

    response = requests.get(
        url,
        headers=HEADERS,
        timeout=30,
    )

    response.raise_for_status()

    soup = BeautifulSoup(
        response.text,
        "html.parser",
    )

    results = []

    for table in soup.find_all("table"):

        rows = table.find_all("tr")

        if not rows:
            continue

        header_cells = rows[0].find_all(
            ["th", "td"]
        )

        headers = [
            clean(cell.get_text(" ", strip=True)).lower()
            for cell in header_cells
        ]

        # Find the dividend history table.
        if (
            "amount" not in headers
            or "ex-dividend" not in headers
            or "payment" not in headers
        ):
            continue

        amount_index = headers.index("amount")
        ex_index = headers.index("ex-dividend")
        payment_index = headers.index("payment")

        for row in rows[1:]:

            cells = row.find_all("td")

            if not cells:
                continue

            values = [
                clean(cell.get_text(" ", strip=True))
                for cell in cells
            ]

            if len(values) <= max(
                amount_index,
                ex_index,
                payment_index,
            ):
                continue

            amount = values[amount_index]
            ex_date = parse_date(
                values[ex_index]
            )
            payment_date = parse_date(
                values[payment_index]
            )

            # We need both dates for our calendar.
            if not ex_date or not payment_date:
                continue

            # Ignore old history and very distant dates.
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

            # First column normally contains dividend type.
            dividend_type = values[0]

            results.append(
                {
                    "ticker": ticker,
                    "company": company,
                    "amount": amount,
                    "type": dividend_type,
                    "ex_date": ex_date,
                    "payment_date": payment_date,
                    "source": url,
                }
            )

        # We found the correct table.
        if results:
            break

    print(
        f"  Found {len(results)} dividend record(s)"
    )

    return results


def escape_ics(value):
    """Escape text for ICS format."""

    return (
        str(value)
        .replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\n", "\\n")
    )


def ics_date(value):
    return value.strftime("%Y%m%d")


def make_uid(ticker, event_type, event_date):
    return (
        f"{ticker}-"
        f"{event_type}-"
        f"{event_date.strftime('%Y%m%d')}"
        "@uk-dividend-calendar"
    )


def make_event(
    ticker,
    company,
    amount,
    dividend_type,
    event_type,
    event_date,
    other_date,
    source,
):
    if event_type == "EX-DIVIDEND":

        summary = (
            f"{ticker} — {company} — "
            f"EX-DIVIDEND — {amount}"
        )

        description = (
            f"{company} ({ticker})\n"
            f"Dividend: {amount}\n"
            f"Type: {dividend_type}\n"
            f"Ex-dividend date: "
            f"{event_date.strftime('%d %b %Y')}\n"
            f"Payment date: "
            f"{other_date.strftime('%d %b %Y')}\n"
            f"Source: {source}"
        )

    else:

        summary = (
            f"{ticker} — {company} — "
            f"PAYMENT — {amount}"
        )

        description = (
            f"{company} ({ticker})\n"
            f"Dividend: {amount}\n"
            f"Type: {dividend_type}\n"
            f"Payment date: "
            f"{event_date.strftime('%d %b %Y')}\n"
            f"Ex-dividend date: "
            f"{other_date.strftime('%d %b %Y')}\n"
            f"Source: {source}"
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

    all_dividends = []

    successful_sources = 0

    for ticker, company in COMPANIES.items():

        try:

            records = get_dividend_rows(
                ticker,
                company,
            )

            if records:
                successful_sources += 1

            all_dividends.extend(records)

        except Exception as exc:

            print(
                f"  ERROR for {ticker}: {exc}"
            )

    print("")
    print(
        f"Total dividend records found: "
        f"{len(all_dividends)}"
    )

    print(
        f"Companies with dividend records: "
        f"{successful_sources}/"
        f"{len(COMPANIES)}"
    )

    # Do not silently create an empty calendar.
    if len(all_dividends) == 0:

        raise RuntimeError(
            "No dividend records were found. "
            "The ICS file was NOT updated."
        )

    # Remove duplicate records.
    unique = {}

    for dividend in all_dividends:

        key = (
            dividend["ticker"],
            dividend["ex_date"],
            dividend["payment_date"],
            dividend["amount"],
        )

        unique[key] = dividend

    all_dividends = list(unique.values())

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//UK Dividend Calendar//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:UK Dividends",
        "X-WR-CALDESC:"
        "Dividend ex-dividend and payment dates",
    ]

    for dividend in sorted(
        all_dividends,
        key=lambda x: (
            x["ex_date"],
            x["ticker"],
        ),
    ):

        # EX-DIVIDEND event
        lines.extend(
            make_event(
                dividend["ticker"],
                dividend["company"],
                dividend["amount"],
                dividend["type"],
                "EX-DIVIDEND",
                dividend["ex_date"],
                dividend["payment_date"],
                dividend["source"],
            )
        )

        # PAYMENT event
        lines.extend(
            make_event(
                dividend["ticker"],
                dividend["company"],
                dividend["amount"],
                dividend["type"],
                "PAYMENT",
                dividend["payment_date"],
                dividend["ex_date"],
                dividend["source"],
            )
        )

    lines.append("END:VCALENDAR")

    Path("dividends.ics").write_text(
        "\r\n".join(lines) + "\r\n",
        encoding="utf-8",
    )

    print("")
    print(
        "SUCCESS: dividends.ics created."
    )

    print(
        f"Calendar events created: "
        f"{len(all_dividends) * 2}"
    )


if __name__ == "__main__":
    build_calendar()
