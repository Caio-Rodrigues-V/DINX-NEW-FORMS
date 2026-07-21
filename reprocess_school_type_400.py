import argparse
import json
import time

import main as lead_sync


SCHOOL_TYPE_DECODE_MARKERS = (
    "cannot decode field",
    "requestbetaaccessrequest.school_type",
    "from json",
)


def is_school_type_decode_400(record: dict) -> bool:
    """Identifica somente o 400 temporario de decodificacao de school_type."""
    if str(record.get("status", "")).strip() != "400":
        return False

    searchable_parts = [str(record.get("response") or "")]
    for reason in record.get("reasons") or []:
        if isinstance(reason, dict):
            searchable_parts.extend(
                [str(reason.get("field") or ""), str(reason.get("message") or "")]
            )
        else:
            searchable_parts.append(str(reason))

    searchable_text = " ".join(searchable_parts).casefold()
    return all(marker in searchable_text for marker in SCHOOL_TYPE_DECODE_MARKERS)


def load_rejection_record(lead_id: str) -> dict | None:
    raw = lead_sync.redis_client.get(f"dinx:rejected_lead:{lead_id}")
    if not raw:
        return None
    try:
        record = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        lead_sync.log.warning("Registro de rejeicao corrompido para o lead %s", lead_id)
        return None
    return record if isinstance(record, dict) else None


def find_candidates(lead_id: str | None = None) -> tuple[list[str], int]:
    if lead_id:
        lead_ids = [lead_id]
    else:
        lead_ids = sorted(
            lead_sync.redis_client.smembers(lead_sync.REJECTED_REDIS_KEY)
        )

    candidates = []
    unreadable = 0
    for candidate_id in lead_ids:
        record = load_rejection_record(candidate_id)
        if record is None:
            unreadable += 1
            continue
        if is_school_type_decode_400(record):
            candidates.append(candidate_id)
    return candidates, unreadable


def clear_rejection(lead_id: str):
    lead_sync.redis_client.srem(lead_sync.INVALID_REDIS_KEY, lead_id)
    lead_sync.redis_client.srem(lead_sync.REJECTED_REDIS_KEY, lead_id)
    lead_sync.redis_client.delete(f"dinx:rejected_lead:{lead_id}")


def reprocess_school_type_400(
    *,
    lead_id: str | None = None,
    limit: int | None = None,
    delay: float | None = None,
    send: bool = False,
) -> dict:
    candidates, unreadable = find_candidates(lead_id=lead_id)
    if limit is not None:
        candidates = candidates[:limit]

    total = len(candidates)
    sent = 0
    failed = 0
    missing = 0
    skipped_seen = 0
    delay_seconds = lead_sync.SEND_DELAY_SECONDS if delay is None else delay

    mode = "ENVIO" if send else "DRY RUN"
    lead_sync.log.info(
        "%s: %s lead(s) com erro 400 de school_type encontrados",
        mode,
        total,
    )

    for index, candidate_id in enumerate(candidates, start=1):
        if lead_sync.is_seen(candidate_id):
            skipped_seen += 1
            if send:
                clear_rejection(candidate_id)
            lead_sync.log.info(
                "[%s/%s] Lead %s ja consta como enviado%s",
                index,
                total,
                candidate_id,
                "; rejeicao antiga removida" if send else "",
            )
            continue

        raw_lead = lead_sync.fetch_lead(candidate_id)
        if not raw_lead:
            missing += 1
            lead_sync.log.warning(
                "[%s/%s] Lead %s nao encontrado na Meta",
                index,
                total,
                candidate_id,
            )
            continue

        payload = lead_sync.parse_lead(raw_lead)
        if not send:
            lead_sync.log.info(
                "[%s/%s] DRY RUN lead %s payload=%s",
                index,
                total,
                candidate_id,
                lead_sync.mask_payload(payload),
            )
            continue

        if lead_sync.send_to_dinx(payload, candidate_id):
            sent += 1
            lead_sync.mark_seen(candidate_id)
            clear_rejection(candidate_id)
        else:
            failed += 1

        if delay_seconds > 0 and index < total:
            time.sleep(delay_seconds)

    return {
        "mode": mode,
        "total": total,
        "sent": sent,
        "failed": failed,
        "missing": missing,
        "skipped_seen": skipped_seen,
        "unreadable": unreadable,
    }


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Reprocessa exclusivamente rejeicoes 400 causadas pela decodificacao "
            "temporaria do campo school_type. Sem --send, apenas simula."
        )
    )
    parser.add_argument(
        "--send",
        action="store_true",
        help="Confirma o envio para a API Dinx; sem esta opcao roda em dry-run.",
    )
    parser.add_argument(
        "--lead-id",
        default=None,
        help="Reprocessa somente este Lead ID, se ele corresponder ao erro esperado.",
    )
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--delay", type=float, default=None)
    args = parser.parse_args()

    if args.limit is not None and args.limit < 1:
        parser.error("--limit deve ser maior que zero")
    if args.delay is not None and args.delay < 0:
        parser.error("--delay nao pode ser negativo")

    result = reprocess_school_type_400(
        lead_id=args.lead_id,
        limit=args.limit,
        delay=args.delay,
        send=args.send,
    )
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
