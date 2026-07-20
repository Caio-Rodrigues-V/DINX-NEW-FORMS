import os
import time
import json
import logging
import requests
import schedule
import redis
from dotenv import load_dotenv

load_dotenv()

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("leads.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)

# ── Config via .env ───────────────────────────────────────────────────────────
META_PAGE_TOKEN  = os.getenv("META_PAGE_TOKEN")
META_PAGE_ID     = os.getenv("META_PAGE_ID")
META_FORM_ID     = os.getenv("META_FORM_ID")
DINX_URL         = os.getenv("DINX_URL", "https://bff.prd.dinx.app/site.beta_access.v1.SiteBetaAccessService/RequestPartnerBetaAccess")
DINX_API_KEY     = os.getenv("DINX_API_KEY")
INTERVAL_MINUTES = int(os.getenv("INTERVAL_MINUTES", 30))
SEND_DELAY_SECONDS = int(os.getenv("SEND_DELAY_SECONDS", 4))
REDIS_URL        = os.getenv("REDIS_URL", "redis://localhost:6379")
REDIS_KEY        = "dinx:seen_leads"
SENT_DETAIL_REDIS_KEY = "dinx:sent_leads"
REJECTED_REDIS_KEY = "dinx:rejected_leads"
INVALID_REDIS_KEY = "dinx:invalid_leads"
REJECTED_LEADS_FILE = os.getenv("REJECTED_LEADS_FILE", "rejected_leads.jsonl")
SAVE_REJECTED_FILE = os.getenv("SAVE_REJECTED_FILE", "0") == "1"
SKIP_INVALID_LEADS = os.getenv("SKIP_INVALID_LEADS", "1") == "1"

AGE_FIELD = "qual_é_a_idade_do_seu_filho?_"
SCHOOL_FIELD = "seu(s)_filho(s)_estuda(m)_em_qual_tipo_de_escola?"
INCOME_FIELD = "em_qual_faixa_se_encaixa_aproximadamente_a_renda_familiar_mensal_da_sua_casa?__(é_confidencial_e_ajuda_a_personalizar_sua_experiência)"

# ── Redis ─────────────────────────────────────────────────────────────────────
redis_client = redis.from_url(REDIS_URL, decode_responses=True)

def is_seen(lead_id: str) -> bool:
    return redis_client.sismember(REDIS_KEY, lead_id)

def mark_seen(lead_id: str):
    redis_client.sadd(REDIS_KEY, lead_id)

def save_sent_lead(lead_id: str, lead: dict, status, response_text: str):
    record = {
        "lead_id": lead_id,
        "status": status,
        "response": response_text[:1000] if response_text else "",
        "phone_digits": lead.get("phone", ""),
        "payload": mask_payload(lead),
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    record_json = json.dumps(record, ensure_ascii=False)
    redis_client.sadd(SENT_DETAIL_REDIS_KEY, lead_id)
    redis_client.set(f"dinx:sent_lead:{lead_id}", record_json)

def is_invalid(lead_id: str) -> bool:
    return redis_client.sismember(INVALID_REDIS_KEY, lead_id)

def mark_invalid(lead_id: str):
    redis_client.sadd(INVALID_REDIS_KEY, lead_id)

def normalize_phone(raw_phone: str) -> str:
    digits = "".join(c for c in str(raw_phone or "") if c.isdigit())

    # Meta exports Brazilian phones as p:+55DDDN...; Dinx expects only DDD + number.
    if digits.startswith("55") and len(digits) >= 12:
        digits = digits[2:]

    # If a Brazilian mobile arrives without the ninth digit, complete it.
    if len(digits) == 10:
        digits = digits[:2] + "9" + digits[2:]

    return digits

def mask_payload(payload: dict) -> dict:
    masked = dict(payload)
    if masked.get("email"):
        masked["email"] = "<email>"
    if masked.get("name"):
        masked["name"] = "<name>"
    if masked.get("phone"):
        phone = str(masked["phone"])
        masked["phone"] = f"<phone digits={len(phone)} start={phone[:4]}>"
    return masked

def map_value(mapping: dict, raw_value: str, default, field_name: str):
    if raw_value in mapping:
        return mapping[raw_value]

    log.warning("Valor sem DE/PARA em %s: %r. Usando default: %r", field_name, raw_value, default)
    return default

def first_field(fields: dict, names: list[str], default: str = "") -> str:
    for name in names:
        value = fields.get(name)
        if value:
            return str(value)
    return default

def find_field_by_key(fields: dict, keys: list[str], default: str = "") -> str:
    normalized_keys = [key.lower() for key in keys]
    for name, value in fields.items():
        if not value:
            continue
        normalized_name = str(name).lower()
        if any(key in normalized_name for key in normalized_keys):
            return str(value)
    return default

def extract_rejection_reason(response_text: str) -> list:
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

def save_rejected_lead(lead_id: str, lead: dict, status, response_text: str):
    record = {
        "lead_id": lead_id,
        "status": status,
        "response": response_text[:1000] if response_text else "",
        "reasons": extract_rejection_reason(response_text),
        "phone_digits": lead.get("phone", ""),
        "payload": mask_payload(lead),
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    record_json = json.dumps(record, ensure_ascii=False)
    redis_client.sadd(REJECTED_REDIS_KEY, lead_id)
    redis_client.set(f"dinx:rejected_lead:{lead_id}", record_json)

    if SAVE_REJECTED_FILE:
        with open(REJECTED_LEADS_FILE, "a", encoding="utf-8") as file:
            file.write(record_json + "\n")

# ── Mapeamento Meta → Dinx ────────────────────────────────────────────────────
# ATENÇÃO: ajuste as chaves conforme os valores reais retornados pelo formulário Meta
CHILDREN_AGE_MAP = {
    "de_3_a_6_anos":          "between3and6",
    "entre 3 e 6 anos":       "between3and6",
    "sim, entre 3 e 6 anos":  "between3and6",
    "de_7_a_12_anos":         "between7and12",
    "entre 7 e 12 anos":      "between7and12",
    "sim, entre 7 e 12 anos": "between7and12",
    "ambas_as_idades":        "both",
    "ambos":                  "both",
    "sim, ambos":             "both",
    "nenhum":                 "none",
    "não tenho filhos":       "none",
}

INCOME_MAP = {
    "acima_de_r$_3.600,00/mês": "between4kAnd12k",
    "abaixo_de_r$_3.600,00":    "under2k",
    "acima de 25k":       "over25k",
    "acima de r$25.000":  "over25k",
    "entre 12k e 25k":    "between12kAnd25k",
    "entre 4k e 12k":     "between4kAnd12k",
    "entre 2k e 4k":      "between2kAnd4k",
    "abaixo de 2k":       "under2k",
    "não informado":      "notInformed",
}

DEVICE_MAP = {
    "ios":      "ios",
    "iphone":   "ios",
    "android":  "android",
    "outro":    "other",
    "other":    "other",
}

SCHOOL_MAP = {
    "escola_pública":  1,
    "escola_publica":  1,
    "escola_particular": 2,
    "pública":  1,
    "publica":  1,
    "privada":  2,
    "particular": 2,
}

# ── Meta API ──────────────────────────────────────────────────────────────────
def fetch_form_ids() -> list:
    """Lista todos os formulários de lead da Page."""
    if META_FORM_ID:
        return [META_FORM_ID]

    url = f"https://graph.facebook.com/v25.0/{META_PAGE_ID}/leadgen_forms"
    params = {"access_token": META_PAGE_TOKEN, "fields": "id,name", "limit": 100}
    try:
        r = requests.get(url, params=params, timeout=15)
        r.raise_for_status()
        forms = r.json().get("data", [])
        log.info(f"📋 {len(forms)} formulário(s) encontrado(s)")
        return [f["id"] for f in forms]
    except requests.RequestException as e:
        status = e.response.status_code if e.response is not None else "request_error"
        body = e.response.text[:500] if e.response is not None else str(e)
        log.error("Erro ao buscar formularios Meta. status=%s body=%s", status, body)
        return []

def fetch_leads(form_id: str) -> list:
    """Busca leads de um formulário."""
    url = f"https://graph.facebook.com/v25.0/{form_id}/leads"
    params = {
        "access_token": META_PAGE_TOKEN,
        "fields": "id,created_time,field_data",
        "limit": 100,
    }
    try:
        r = requests.get(url, params=params, timeout=15)
        r.raise_for_status()
        return r.json().get("data", [])
    except requests.RequestException as e:
        status = e.response.status_code if e.response is not None else "request_error"
        body = e.response.text[:500] if e.response is not None else str(e)
        log.error("Erro ao buscar leads Meta. form_id=%s status=%s body=%s", form_id, status, body)
        return []

# ── Parse lead ────────────────────────────────────────────────────────────────
def fetch_lead(lead_id: str) -> dict | None:
    url = f"https://graph.facebook.com/v25.0/{lead_id}"
    params = {
        "access_token": META_PAGE_TOKEN,
        "fields": "id,created_time,field_data",
    }
    try:
        r = requests.get(url, params=params, timeout=15)
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:
        status = e.response.status_code if e.response is not None else "request_error"
        body = e.response.text[:500] if e.response is not None else str(e)
        log.error("Erro ao buscar lead Meta. lead_id=%s status=%s body=%s", lead_id, status, body)
        return None

def parse_lead(raw: dict) -> dict:
    """Converte lead da Meta para payload da Dinx."""
    fields = {
        item["name"]: item["values"][0] if item["values"] else ""
        for item in raw.get("field_data", [])
    }

    # Log dos campos brutos para debug/ajuste do mapeamento
    log.debug(f"Campos brutos: {fields}")

    name = first_field(
        fields,
        [
            "full_name",
            "name",
            "nome",
            "nome_completo",
            "nome completo",
            "qual_é_o_seu_nome?",
            "qual_e_o_seu_nome?",
            "qual_é_o_seu_nome_completo?",
            "qual_e_o_seu_nome_completo?",
        ],
    )
    if not name:
        name = find_field_by_key(fields, ["nome", "name"])
    email = fields.get("email", "")
    phone = first_field(
        fields,
        [
            "phone_number",
            "phone",
            "telefone",
            "celular",
            "whatsapp",
            "número_de_telefone",
            "numero_de_telefone",
            "número_de_celular",
            "numero_de_celular",
        ],
    )
    if not phone:
        phone = find_field_by_key(fields, ["phone", "telefone", "celular", "whatsapp"])
    phone = normalize_phone(phone)

    children_age_raw = fields.get(AGE_FIELD, fields.get("idade_dos_filhos", "")).lower().strip()
    income_raw       = fields.get(INCOME_FIELD, fields.get("renda", "")).lower().strip()
    device_raw       = fields.get("tipo_de_device", fields.get("device_type", "")).lower().strip()
    school_raw       = fields.get(SCHOOL_FIELD, fields.get("tipo_de_escola", "")).lower().strip()
    children_count   = int(fields.get("filhos", fields.get("children_count", 1 if children_age_raw else 0)) or 0)
    if children_age_raw == "ambas_as_idades":
        children_count = max(children_count, 2)

    return {
        "name":                      name,
        "email":                     email,
        "phone":                     phone,
        "children_count":            children_count,
        "children_between_age_tier": map_value(CHILDREN_AGE_MAP, children_age_raw, "none", "children_between_age_tier"),
        "income_range":              map_value(INCOME_MAP, income_raw, "notInformed", "income_range"),
        "device_type":               map_value(DEVICE_MAP, device_raw, "empty", "device_type") if device_raw else "empty",
        "school_type":               map_value(SCHOOL_MAP, school_raw, 1, "school_type"),
        "origin":                    "META",
    }

# ── Dinx API ──────────────────────────────────────────────────────────────────
def send_to_dinx(lead: dict, lead_id: str) -> bool:
    local_errors = []
    if len(str(lead.get("name") or "").strip()) < 3:
        local_errors.append({"field": "name", "message": "Nome ausente ou menor que 3 caracteres"})
    if len(str(lead.get("phone") or "")) < 10:
        local_errors.append({"field": "phone", "message": "Telefone ausente ou incompleto"})
    if local_errors:
        response_text = json.dumps(
            {
                "code": "local_validation",
                "message": "Lead nao enviado para Dinx por dados obrigatorios invalidos",
                "details": [
                    {"debug": error}
                    for error in local_errors
                ],
            },
            ensure_ascii=False,
        )
        save_rejected_lead(lead_id, lead, "local_validation", response_text)
        mark_invalid(lead_id)
        log.warning("Lead %s barrado por validacao local: %s | payload=%s", lead_id, local_errors, mask_payload(lead))
        return False

    try:
        headers = {"Content-Type": "application/json"}
        if DINX_API_KEY:
            headers["x-api-key"] = DINX_API_KEY

        r = requests.post(
            DINX_URL,
            json=lead,
            headers=headers,
            timeout=15,
        )
        if r.status_code in (200, 201):
            try:
                body = r.json()
            except ValueError:
                body = {}

            if body.get("success") is False:
                save_rejected_lead(lead_id, lead, "business_error", r.text)
                log.warning(
                    "Dinx retornou erro de negocio para lead %s: %s | payload=%s",
                    lead_id,
                    r.text[:500],
                    mask_payload(lead),
                )
                return False

            save_sent_lead(lead_id, lead, r.status_code, r.text)
            log.info("✅ Lead %s enviado → Dinx | response=%s", lead_id, r.text[:500])
            return True
        else:
            save_rejected_lead(lead_id, lead, r.status_code, r.text)
            if r.status_code == 400:
                mark_invalid(lead_id)
            log.warning(
                "Dinx rejeitou lead %s com status %s: %s | payload=%s",
                lead_id,
                r.status_code,
                r.text[:500],
                mask_payload(lead),
            )
            return False
    except requests.RequestException as e:
        save_rejected_lead(lead_id, lead, "request_error", str(e))
        log.exception("Erro ao enviar lead %s para Dinx | payload=%s", lead_id, mask_payload(lead))
        return False

# ── Ciclo principal ───────────────────────────────────────────────────────────
def process_raw_lead(raw: dict) -> bool:
    lead_id = raw.get("id")
    if not lead_id:
        log.warning("Lead sem ID recebido da Meta: %s", raw)
        return False

    if is_seen(lead_id):
        log.info("Lead %s ignorado: ja enviado", lead_id)
        return False
    if SKIP_INVALID_LEADS and is_invalid(lead_id):
        log.info("Lead %s ignorado: ja marcado como invalido", lead_id)
        return False

    lead = parse_lead(raw)
    ok = send_to_dinx(lead, lead_id)
    if ok:
        mark_seen(lead_id)
    return ok

def process_lead_id(lead_id: str) -> bool:
    raw = fetch_lead(lead_id)
    if not raw:
        return False
    return process_raw_lead(raw)

def verificar_leads():
    log.info("🔄 Verificando novos leads...")
    novos = 0

    for form_id in fetch_form_ids():
        for raw in fetch_leads(form_id):
            ok = process_raw_lead(raw)
            if ok:
                novos += 1

            if SEND_DELAY_SECONDS > 0:
                log.info("Aguardando %s segundo(s) antes do proximo lead", SEND_DELAY_SECONDS)
                time.sleep(SEND_DELAY_SECONDS)

    log.info("💤 Nenhum lead novo." if novos == 0 else f"📬 {novos} lead(s) processado(s).")

# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    log.info(f"🚀 Dinx Leads Sync — verificando a cada {INTERVAL_MINUTES} min")

    verificar_leads()
    schedule.every(INTERVAL_MINUTES).minutes.do(verificar_leads)

    while True:
        schedule.run_pending()
        time.sleep(10)
