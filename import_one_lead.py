import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

from inspect_meta import load_env

try:
    import redis
except ImportError:
    redis = None


CHILDREN_AGE_MAP = {
    "de_3_a_6_anos": "between3and6",
    "de_7_a_12_anos": "between7and12",
    "ambas_as_idades": "both",
}

SCHOOL_MAP = {
    "escola_pública": 1,
    "escola_particular": 2,
}

INCOME_MAP = {
    "abaixo_de_r$_3.600,00": "under2k",
    "acima_de_r$_3.600,00/mês": "between4kAnd12k",
}


def normalize_phone(raw_phone):
    digits = "".join(char for char in str(raw_phone or "") if char.isdigit())
    if digits.startswith("55") and len(digits) >= 12:
        digits = digits[2:]
    if len(digits) == 10:
        digits = digits[:2] + "9" + digits[2:]
    return digits


def graph_get(path, params):
    query = urllib.parse.urlencode(params)
    url = f"https://graph.facebook.com/v25.0/{path}?{query}"
    with urllib.request.urlopen(url, timeout=25) as response:
        return json.loads(response.read().decode("utf-8"))


def post_json(url, payload, api_key=None):
    body = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["x-api-key"] = api_key

    request = urllib.request.Request(
        url,
        data=body,
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=25) as response:
        return response.status, response.read().decode("utf-8")


def fields_by_name(raw_lead):
    return {
        item.get("name"): (item.get("values") or [""])[0]
        for item in raw_lead.get("field_data", [])
    }


def parse_payload(raw_lead):
    fields = fields_by_name(raw_lead)

    age = fields.get("qual_é_a_idade_do_seu_filho?_", "").strip()
    school = fields.get("seu(s)_filho(s)_estuda(m)_em_qual_tipo_de_escola?", "").strip()
    income = fields.get(
        "em_qual_faixa_se_encaixa_aproximadamente_a_renda_familiar_mensal_da_sua_casa?__(é_confidencial_e_ajuda_a_personalizar_sua_experiência)",
        "",
    ).strip()

    children_count = 2 if age == "ambas_as_idades" else 1

    return {
        "email": fields.get("email", ""),
        "name": fields.get("full_name", fields.get("name", "")),
        "phone": normalize_phone(fields.get("phone_number", fields.get("phone", ""))),
        "children_count": children_count,
        "children_between_age_tier": CHILDREN_AGE_MAP.get(age, "none"),
        "device_type": "empty",
        "income_range": INCOME_MAP.get(income, "notInformed"),
        "origin": "META",
        "school_type": SCHOOL_MAP.get(school, 1),
    }


def masked_payload(payload):
    masked = dict(payload)
    if masked.get("email"):
        masked["email"] = "<email>"
    if masked.get("phone"):
        masked["phone"] = f"<phone digits={len(masked['phone'])} start={masked['phone'][:4]}>"
    if masked.get("name"):
        masked["name"] = "<name>"
    return masked


def extract_rejection_reason(response_text):
    try:
        data = json.loads(response_text)
    except (TypeError, json.JSONDecodeError):
        return []

    reasons = []
    for detail in data.get("details", []):
        debug = detail.get("debug") or {}
        field = debug.get("field")
        message = debug.get("message")
        if field or message:
            reasons.append({"field": field, "message": message})
    return reasons


def save_rejected_lead(lead_id, payload, status, response_text):
    record = {
        "lead_id": lead_id,
        "status": status,
        "response": response_text[:1000] if response_text else "",
        "reasons": extract_rejection_reason(response_text),
        "phone_digits": payload.get("phone", ""),
        "payload": masked_payload(payload),
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    record_json = json.dumps(record, ensure_ascii=False)
    redis_url = os.getenv("REDIS_URL")

    if redis and redis_url:
        client = redis.from_url(redis_url, decode_responses=True)
        client.sadd("dinx:rejected_leads", lead_id)
        client.set(f"dinx:rejected_lead:{lead_id}", record_json)
        if status == 400:
            client.sadd("dinx:invalid_leads", lead_id)

    if os.getenv("SAVE_REJECTED_FILE", "0") == "1" or not (redis and redis_url):
        rejected_file = os.getenv("REJECTED_LEADS_FILE", "rejected_leads.jsonl")
        with open(rejected_file, "a", encoding="utf-8") as file:
            file.write(record_json + "\n")


def main():
    env = load_env()
    env.update({key: value for key, value in os.environ.items() if value})

    token = env.get("META_PAGE_TOKEN")
    form_id = env.get("META_FORM_ID", "1696556268158303")
    dinx_url = env.get(
        "DINX_URL",
        "https://bff.prd.dinx.app/site.beta_access.v1.SiteBetaAccessService/RequestPartnerBetaAccess",
    )
    dinx_api_key = env.get("DINX_API_KEY")
    send = env.get("SEND_TO_DINX") == "1"
    lead_id = env.get("META_LEAD_ID")
    lead_offset = int(env.get("META_LEAD_OFFSET", 0))

    if not token:
        raise SystemExit("Missing META_PAGE_TOKEN")

    if lead_id:
        response = graph_get(
            lead_id,
            {"access_token": token, "fields": "id,created_time,field_data"},
        )
        lead = response
    else:
        response = graph_get(
            f"{form_id}/leads",
            {
                "access_token": token,
                "fields": "id,created_time,field_data",
                "limit": lead_offset + 1,
            },
        )
        leads = response.get("data", [])
        if len(leads) <= lead_offset:
            raise SystemExit("No leads found")
        lead = leads[lead_offset]

    payload = parse_payload(lead)
    print("lead_id:", lead.get("id"))
    print("created_time:", lead.get("created_time"))
    print("send_to_dinx:", send)
    print("payload_masked:")
    print(json.dumps(masked_payload(payload), ensure_ascii=False, indent=2))

    if send:
        try:
            status, body = post_json(dinx_url, payload, dinx_api_key)
            print("dinx_status:", status)
            print("dinx_body:", body[:1000])
            try:
                parsed_body = json.loads(body)
            except json.JSONDecodeError:
                parsed_body = {}
            if parsed_body.get("success") is False:
                save_rejected_lead(lead.get("id"), payload, "business_error", body)
                raise SystemExit(1)
        except urllib.error.HTTPError as error:
            body = error.read().decode("utf-8")
            save_rejected_lead(lead.get("id"), payload, error.code, body)
            print("dinx_status:", error.code)
            print("dinx_body:", body[:1000])
            raise SystemExit(1)
        except Exception as error:
            save_rejected_lead(lead.get("id"), payload, "request_error", str(error))
            raise


if __name__ == "__main__":
    main()
