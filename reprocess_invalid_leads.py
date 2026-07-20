import argparse
import time

import main as lead_sync


def reprocess_invalid_leads(limit=None, delay=None, dry_run=False):
    lead_ids = sorted(lead_sync.redis_client.smembers(lead_sync.INVALID_REDIS_KEY))
    if limit:
        lead_ids = lead_ids[:limit]

    total = len(lead_ids)
    sent = 0
    failed = 0
    missing = 0
    skipped_seen = 0
    delay_seconds = lead_sync.SEND_DELAY_SECONDS if delay is None else delay

    lead_sync.log.info("Reprocessando %s lead(s) invalidos", total)

    for index, lead_id in enumerate(lead_ids, start=1):
        if lead_sync.is_seen(lead_id):
            skipped_seen += 1
            lead_sync.redis_client.srem(lead_sync.INVALID_REDIS_KEY, lead_id)
            lead_sync.log.info("[%s/%s] Lead %s ja enviado; removido dos invalidos", index, total, lead_id)
            continue

        raw = lead_sync.fetch_lead(lead_id)
        if not raw:
            missing += 1
            lead_sync.log.warning("[%s/%s] Lead %s nao encontrado na Meta", index, total, lead_id)
            continue

        payload = lead_sync.parse_lead(raw)
        if dry_run:
            lead_sync.log.info(
                "[%s/%s] DRY RUN lead %s payload=%s",
                index,
                total,
                lead_id,
                lead_sync.mask_payload(payload),
            )
            continue

        if lead_sync.send_to_dinx(payload, lead_id):
            sent += 1
            lead_sync.mark_seen(lead_id)
            lead_sync.redis_client.srem(lead_sync.INVALID_REDIS_KEY, lead_id)
            lead_sync.redis_client.srem(lead_sync.REJECTED_REDIS_KEY, lead_id)
            lead_sync.redis_client.delete(f"dinx:rejected_lead:{lead_id}")
        else:
            failed += 1

        if delay_seconds > 0:
            time.sleep(delay_seconds)

    return {
        "total": total,
        "sent": sent,
        "failed": failed,
        "missing": missing,
        "skipped_seen": skipped_seen,
        "dry_run": dry_run,
    }


def main():
    parser = argparse.ArgumentParser(description="Reprocessa leads invalidos salvos no Redis.")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--delay", type=float, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    result = reprocess_invalid_leads(limit=args.limit, delay=args.delay, dry_run=args.dry_run)
    print(result)


if __name__ == "__main__":
    main()
