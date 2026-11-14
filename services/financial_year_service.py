from datetime import date, datetime


def _as_date(value):
    if isinstance(value, datetime):
        return value.date()

    if isinstance(value, date):
        return value

    if isinstance(value, str):
        return datetime.strptime(value[:10], "%Y-%m-%d").date()

    raise ValueError("A valid date is required.")


def financial_year_for_date(value):
    value_date = _as_date(value)
    start_year = value_date.year if value_date.month >= 7 else value_date.year - 1
    return f"{start_year:04d}-{(start_year + 1) % 100:02d}"


def financial_year_sort_key(financial_year):
    try:
        return int(str(financial_year).split("-", 1)[0])
    except (TypeError, ValueError):
        return 0


def current_financial_year(now=None):
    now = now or datetime.now()
    start_year = now.year if now.month >= 7 else now.year - 1
    return f"{start_year:04d}-{(start_year + 1) % 100:02d}"
