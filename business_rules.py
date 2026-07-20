import re
import unicodedata


META_ORIGIN = 1
INCOME_NOT_INFORMED = "notInformed"

ELIGIBLE_AGE_TIERS = {"between3and6", "between7and12", "both"}

CHILDREN_AGE_MAP = {
    "de_3_a_6_anos": "between3and6",
    "entre_3_e_6_anos": "between3and6",
    "sim_entre_3_e_6_anos": "between3and6",
    "de_7_a_12_anos": "between7and12",
    "entre_7_e_12_anos": "between7and12",
    "sim_entre_7_e_12_anos": "between7and12",
    "ambas_as_idades": "both",
    "ambos": "both",
    "sim_ambos": "both",
}

SCHOOL_MAP = {
    "escola_publica": 1,
    "publica": 1,
    "escola_particular": 2,
    "privada": 2,
    "particular": 2,
}

NO_CHILDREN_CHOICES = {
    "nao_tenho_filho",
    "nao_tenho_filho_a",
    "nao_tenho_filhos",
    "nenhum",
    "nenhuma",
}


def normalize_choice(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def map_age_tier(raw_value: str):
    return CHILDREN_AGE_MAP.get(normalize_choice(raw_value))


def map_school_type(raw_value: str):
    return SCHOOL_MAP.get(normalize_choice(raw_value))


def no_children_selected(age_raw: str, school_raw: str = "") -> bool:
    return any(
        normalize_choice(value) in NO_CHILDREN_CHOICES
        for value in (age_raw, school_raw)
        if value
    )


def children_count_for_tier(age_tier: str) -> int:
    if age_tier == "both":
        return 2
    if age_tier in ELIGIBLE_AGE_TIERS:
        return 1
    return 0


def terminal_business_error(message: str) -> bool:
    normalized = normalize_choice(message)
    terminal_markers = (
        "solicitacao_aprovada",
        "solicitacao_rejeitada",
        "solicitacao_expirada",
        "acesso_ativo_ao_aplicativo",
    )
    return any(marker in normalized for marker in terminal_markers)
