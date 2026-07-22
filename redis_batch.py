import json


REDIS_MGET_BATCH_SIZE = 500


def load_json_details(client, lead_ids, key_prefix, batch_size=REDIS_MGET_BATCH_SIZE):
    """Carrega detalhes do Redis em lotes para evitar uma ida a rede por lead."""
    details = {}
    invalid_json_ids = []
    lead_ids = list(lead_ids)

    for start in range(0, len(lead_ids), batch_size):
        batch_ids = lead_ids[start : start + batch_size]
        keys = [f"{key_prefix}{lead_id}" for lead_id in batch_ids]
        raw_values = client.mget(keys)

        for lead_id, raw in zip(batch_ids, raw_values):
            if not raw:
                continue
            try:
                record = json.loads(raw)
            except (TypeError, json.JSONDecodeError):
                invalid_json_ids.append(lead_id)
                continue
            if isinstance(record, dict):
                details[lead_id] = record
            else:
                invalid_json_ids.append(lead_id)

    return details, invalid_json_ids
