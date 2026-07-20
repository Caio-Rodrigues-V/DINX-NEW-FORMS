import csv
import json
import os
import time

import redis
from dotenv import load_dotenv


load_dotenv()

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
REJECTED_REDIS_KEY = "dinx:rejected_leads"
OUTPUT_DIR = os.getenv("EXPORT_OUTPUT_DIR", "exports")


def first_reason(record):
    reasons = record.get("reasons") or []
    if not reasons:
        return "", ""

    reason = reasons[0] or {}
    return reason.get("field", ""), reason.get("message", "")


def load_rejected_records(client):
    lead_ids = sorted(client.smembers(REJECTED_REDIS_KEY))
    records = []

    for lead_id in lead_ids:
        raw = client.get(f"dinx:rejected_lead:{lead_id}")
        if not raw:
            records.append(
                {
                    "lead_id": lead_id,
                    "status": "",
                    "phone_digits": "",
                    "field": "",
                    "message": "Detalhe da rejeicao nao encontrado no Redis",
                    "created_at": "",
                    "response": "",
                }
            )
            continue

        record = json.loads(raw)
        field, message = first_reason(record)
        records.append(
            {
                "lead_id": record.get("lead_id", lead_id),
                "status": record.get("status", ""),
                "phone_digits": record.get("phone_digits", ""),
                "field": field,
                "message": message,
                "created_at": record.get("created_at", ""),
                "response": record.get("response", ""),
            }
        )

    return records


def export_csv(records):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    output_path = os.path.abspath(os.path.join(OUTPUT_DIR, f"rejected_leads_{timestamp}.csv"))

    columns = [
        "lead_id",
        "status",
        "phone_digits",
        "field",
        "message",
        "created_at",
        "response",
    ]

    with open(output_path, "w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=columns, delimiter=";")
        writer.writeheader()
        writer.writerows(records)

    return output_path


def main():
    client = redis.from_url(REDIS_URL, decode_responses=True)
    records = load_rejected_records(client)
    output_path = export_csv(records)

    print("rejected_count:", len(records))
    print("output:", output_path)


if __name__ == "__main__":
    main()
