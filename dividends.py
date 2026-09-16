import requests
from bs4 import BeautifulSoup
from datetime import date, datetime, timedelta
from pathlib import Path
import re


# ============================================================
# COMPANIES
# ============================================================

UK_COMPANIES = {
    "BTRW": "Barratt Redrow",
    "LGEN": "Legal & General",
    "BARC": "Barclays",
    "PSN": "Persimmon",
    "TW": "Taylor Wimpey",
    "GRG": "Greggs",
    "AV": "Aviva",
    "MRO": "Melrose Industries",
    "BA": "BAE Systems",
    "LMP": "LondonMetric Property",
}

US_COMPANIES = {
    "SKHY": "SK hynix",
    "AMZN": "Amazon",
}


UK_BASE_URL = (
    "https://dividendregistry.com/dividends/{}/"
)

US_BASE_URL = (
    "https://www.financecharts.com/stocks/"
    "{}/dividends/dividends"
)


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/131.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,"
        "application/xml;q=0.9,*/*;q=0.8"
    ),
    "Accept-Language": "en-GB,en;q=0.9",
}


TODAY = date.today()

# Keep recently passed dates so payment events don't
# disappear immediately after the ex-dividend date.
MIN_DATE = TODAY - timedelta(days=30)

# Look ahead approximately 15 months.
MAX_DATE = TODAY + timedelta(days=450)


# ============================================================
# GENERAL FUNCTIONS
# ============================================================

def clean(text):
    return " ".join(text.split())


def parse_date(value):
    """
    Convert common dividend date formats to a Python date.
    """

    if not value:
        return None

    value = clean(value)

    formats = [
        "%d %b %Y",
        "%d %B %Y",
        "%d-%b-%Y",
        "%d-%b-%y",
        "%d/%m/%Y",
        "%m/%d/%Y",
        "%Y-%m-%d",
    ]

    for fmt in formats:
        try:
            return datetime.strptime(
                value,
                fmt
            ).date()
        except ValueError:
            continue

    return None


def escape_ics(value):
    """
    Escape text according to the ICS specification.
    """

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
    clean_ticker = ticker.replace(".", "")

    return (
        f"{clean_ticker}-"
        f"{event_type}-"
        f"{event_date.strftime('%Y%m%d')}"
        "@uk-dividend-calendar"
    )


def is_relevant(ex_date, payment_date):
    """
    Keep events from the last 30 days through the
    next 450 days.
    """

    if not ex_date or not payment_date:
        return False

    if (
        ex_date < MIN_DATE
        and payment_date < MIN_DATE
    ):
        return False

    if (
        ex_date > MAX_DATE
        and payment_date > MAX_DATE
    ):
        return False

    return True


# ============================================================
# UK / DIVIDEND REGISTRY
# ============================================================

def get_uk_dividends(ticker, company):

    url = UK_BASE_URL.format(ticker)

    print("")
    print(
        f"Getting UK: {ticker} "
        f"({company})"
    )

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
            clean(
                cell.get_text(
                    " ",
                    strip=True
                )
            ).lower()
            for cell in header_cells
        ]

        # The Dividend Registry table should contain
        # these columns.
        if "amount" not in headers:
            continue

        if "ex-dividend" not in headers:
            continue

        if "payment" not in headers:
            continue

        amount_index = headers.index(
            "amount"
        )

        ex_index = headers.index(
            "ex-dividend"
        )

        payment_index = headers.index(
            "payment"
        )

        for row in rows[1:]:

            cells = row.find_all("td")

            if not cells:
                continue

            values = [
                clean(
                    cell.get_text(
                        " ",
                        strip=True
                    )
                )
                for cell in cells
            ]

            required_index = max(
                amount_index,
                ex_index,
                payment_index,
            )

            if len(values) <= required_index:
                continue

            amount = values[amount_index]

            ex_date = parse_date(
                values[ex_index]
            )

            payment_date = parse_date(
                values[payment_index]
            )

            if not is_relevant(
                ex_date,
                payment_date
            ):
                continue

            # Try to identify dividend type.
            dividend_type = "Dividend"

            for value in values:
                lower = value.lower()

                if any(
                    word in lower
                    for word in [
                        "interim",
                        "final",
                        "special",
                        "quarterly",
                        "property income",
                    ]
                ):
                    dividend_type = value
                    break

            results.append(
                {
                    "ticker": ticker,
                    "company": company,
                    "market": "UK",
                    "amount": amount,
                    "type": dividend_type,
                    "ex_date": ex_date,
                    "payment_date": payment_date,
                    "source": url,
                }
            )

        # Stop after finding the correct table.
        if results:
            break

    print(
        f"  Found {len(results)} UK "
        f"dividend record(s)"
    )

    return results


# ============================================================
# US / FINANCECHARTS
# ============================================================

def get_us_dividends(ticker, company):

    url = US_BASE_URL.format(ticker)

    print("")
    print(
        f"Getting US: {ticker} "
        f"({company})"
    )

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

    # FinanceCharts uses a table containing fields such as:
    #
    # Ex-Dividend Date
    # Declare Date
    # Record Date
    # Payment Date
    # Frequency
    # Divs/Share

    for table in soup.find_all("table"):

        rows = table.find_all("tr")

        if not rows:
            continue

        header_cells = rows[0].find_all(
            ["th", "td"]
        )

        headers = [
            clean(
                cell.get_text(
                    " ",
                    strip=True
                )
            ).lower()
            for cell in header_cells
        ]

        # Locate a FinanceCharts dividend table.
        ex_index = None
        payment_index = None
        amount_index = None

        for i, header in enumerate(headers):

            if (
                "ex-dividend" in header
                or "ex div" in header
            ):
                ex_index = i

            if "payment date" in header:
                payment_index = i

            if (
                "divs/share" in header
                or "dividend/share" in header
            ):
                amount_index = i

        if (
            ex_index is None
            or payment_index is None
        ):
            continue

        for row in rows[1:]:

            cells = row.find_all("td")

            if not cells:
                continue

            values = [
                clean(
                    cell.get_text(
                        " ",
                        strip=True
                    )
                )
                for cell in cells
            ]

            required_index = max(
                ex_index,
                payment_index,
                amount_index
                if amount_index is not None
                else 0,
            )

            if len(values) <= required_index:
                continue

            ex_date = parse_date(
                values[ex_index]
            )

            payment_date = parse_date(
                values[payment_index]
            )

            if not ex_date or not payment_date:
                continue

            if not is_relevant(
                ex_date,
                payment_date
            ):
                continue

            if amount_index is not None:
                amount = values[amount_index]
            else:
                amount = "Dividend"

            results.append(
                {
                    "ticker": ticker,
                    "company": company,
                    "market": "US",
                    "amount": amount,
                    "type": "Dividend",
                    "ex_date": ex_date,
                    "payment_date": payment_date,
                    "source": url,
                }
            )

        if results:
            break

    print(
        f"  Found {len(results)} US "
        f"dividend record(s)"
    )

    return results


# ============================================================
# OUTLOOK / ICS EVENT CREATION
# ============================================================

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
            f"Market: {source}\n"
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

    start_date = ics_date(
        event_date
    )

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


# ============================================================
# BUILD CALENDAR
# ============================================================

def build_calendar():

    all_dividends = []

    successful_sources = 0

    failed_sources = []

    # --------------------------------------------------------
    # UK companies
    # --------------------------------------------------------

    for ticker, company in UK_COMPANIES.items():

        try:

            records = get_uk_dividends(
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

            failed_sources.append(
                ticker
            )

    # --------------------------------------------------------
    # US companies
    # --------------------------------------------------------

    for ticker, company in US_COMPANIES.items():

        try:

            records = get_us_dividends(
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

            failed_sources.append(
                ticker
            )

    # --------------------------------------------------------
    # Special handling for Amazon
    # --------------------------------------------------------

    if "AMZN" in US_COMPANIES:

        print("")
        print(
            "AMZN: Amazon currently has "
            "no dividend records."
        )

    # --------------------------------------------------------
    # Summary
    # --------------------------------------------------------

    print("")
    print("=" * 60)

    print(
        f"Total dividend records found: "
        f"{len(all_dividends)}"
    )

    print(
        f"Sources with records: "
        f"{successful_sources}/"
        f"{len(UK_COMPANIES) + len(US_COMPANIES)}"
    )

    if failed_sources:

        print(
            "Sources with errors: "
            + ", ".join(failed_sources)
        )

    print("=" * 60)

    # Do NOT create an empty calendar.
    #
    # This protects your Outlook calendar if a website
    # changes its format or becomes temporarily unavailable.

    if len(all_dividends) == 0:

        raise RuntimeError(
            "No dividend records were found. "
            "The existing ICS file was not replaced."
        )

    # --------------------------------------------------------
    # Remove duplicates
    # --------------------------------------------------------

    unique = {}

    for dividend in all_dividends:

        key = (
            dividend["ticker"],
            dividend["ex_date"],
            dividend["payment_date"],
            dividend["amount"],
        )

        unique[key] = dividend

    all_dividends = list(
        unique.values()
    )

    # --------------------------------------------------------
    # Start ICS calendar
    # --------------------------------------------------------

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//UK Dividend Calendar//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:UK Dividends",
        "X-WR-CALDESC:"
        "UK and US dividend ex-dividend "
        "and payment dates",
    ]

    # --------------------------------------------------------
    # Create two events per dividend
    # --------------------------------------------------------

    for dividend in sorted(
        all_dividends,
        key=lambda x: (
            x["ex_date"],
            x["ticker"],
        ),
    ):

        # EX-DIVIDEND
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

        # PAYMENT
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

    lines.append(
        "END:VCALENDAR"
    )

    # --------------------------------------------------------
    # Write ICS
    # --------------------------------------------------------

    Path(
        "dividends.ics"
    ).write_text(
        "\r\n".join(lines) + "\r\n",
        encoding="utf-8",
    )

    print("")
    print(
        "SUCCESS: dividends.ics created."
    )

    print(
        f"Dividend records: "
        f"{len(all_dividends)}"
    )

    print(
        f"Calendar events: "
        f"{len(all_dividends) * 2}"
    )


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":
    build_calendar()
