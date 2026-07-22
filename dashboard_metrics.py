from datetime import date, datetime, timedelta, timezone


DASHBOARD_TIMEZONE = timezone(timedelta(hours=-3), name="America/Sao_Paulo")


def parse_record_datetime(value):
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(DASHBOARD_TIMEZONE)


def resolve_date_filter(raw_value, today=None):
    current_date = today or datetime.now(DASHBOARD_TIMEZONE).date()
    normalized = str(raw_value or "").strip().lower()
    if normalized == "all":
        return None, "all", "Todo o periodo"

    try:
        selected_date = date.fromisoformat(normalized) if normalized else current_date
    except ValueError:
        selected_date = current_date

    label = "Hoje" if selected_date == current_date else selected_date.strftime("%d/%m/%Y")
    return selected_date, selected_date.isoformat(), label


def filter_records_by_date(records, selected_date):
    if selected_date is None:
        return list(records)

    filtered = []
    for record in records:
        created_at = parse_record_datetime(record.get("created_at"))
        if created_at and created_at.date() == selected_date:
            filtered.append(record)
    return filtered


def calculate_stats(
    sent_records,
    rejected_records,
    invalid_ids,
    filtered_records,
    total_sent=None,
):
    return {
        "total_sent": len(sent_records) if total_sent is None else total_sent,
        "sent": len(sent_records),
        "approved": sum(record.get("decision") == "approved" for record in sent_records),
        "qualified": sum(record.get("decision") == "pending" for record in sent_records),
        "rejected": len(rejected_records),
        "invalid": sum(record.get("lead_id") in invalid_ids for record in rejected_records),
        "filtered": len(filtered_records),
    }
