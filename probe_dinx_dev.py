import argparse
import json
import os
import random
import sys
import uuid
from urllib.parse import urlparse

import requests
from dotenv import load_dotenv


DEFAULT_DEV_URL = (
    "https://bff.dev.dinx.app/"
    "site.beta_access.v1.SiteBetaAccessService/RequestPartnerBetaAccess"
)

SCENARIOS = {
    "private": {"school_type": 2, "expected_approved": True},
    "public": {"school_type": 1, "expected_approved": False},
}


def ensure_dev_url(url: str):
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != "bff.dev.dinx.app":
        raise ValueError("Teste bloqueado: somente https://bff.dev.dinx.app e permitido")


def build_payload(school_type: int) -> dict:
    suffix = uuid.uuid4().hex[:12]
    phone = f"119{random.randint(0, 99_999_999):08d}"
    return {
        "email": f"teste.automacao+{suffix}@example.com",
        "name": "Teste Automacao Dinx",
        "phone": phone,
        "children_count": 1,
        "children_between_age_tier": "between3and6",
        "device_type": "empty",
        "income_range": "notInformed",
        "origin": 1,
        "school_type": school_type,
    }


def interpret_response(status_code: int, body) -> dict:
    if status_code == 401:
        return {
            "communication_ok": False,
            "automation_result": "authentication_error",
            "detail": "x-api-key ausente ou sem permissao no ambiente Dev",
        }
    if status_code != 200:
        return {
            "communication_ok": False,
            "automation_result": "http_error",
            "detail": f"HTTP {status_code}",
        }
    if not isinstance(body, dict) or not isinstance(body.get("success"), bool):
        return {
            "communication_ok": False,
            "automation_result": "invalid_schema",
            "detail": "Resposta sem o booleano success",
        }
    if body["success"] is False:
        return {
            "communication_ok": True,
            "automation_result": "business_error",
            "detail": str(body.get("error") or body.get("message") or "Motivo nao informado"),
        }
    if not isinstance(body.get("approved"), bool):
        return {
            "communication_ok": False,
            "automation_result": "invalid_schema",
            "detail": "Resposta de sucesso sem o booleano approved",
        }
    return {
        "communication_ok": True,
        "automation_result": "approved" if body["approved"] else "pending",
        "detail": "Resposta valida",
    }


def run_scenario(name: str, url: str, api_key: str, send: bool) -> bool:
    config = SCENARIOS[name]
    payload = build_payload(config["school_type"])
    expected_result = "approved" if config["expected_approved"] else "pending"

    print(f"\nSCENARIO={name}")
    print(f"EXPECTED_AUTOMATION_RESULT={expected_result}")
    print("REQUEST=" + json.dumps(payload, ensure_ascii=False))
    if not send:
        print("DRY_RUN=true")
        return True

    response = requests.post(
        url,
        json=payload,
        headers={"Content-Type": "application/json", "x-api-key": api_key},
        timeout=20,
    )
    print(f"HTTP_STATUS={response.status_code}")
    try:
        body = response.json()
    except ValueError:
        body = None
    print("RESPONSE=" + (json.dumps(body, ensure_ascii=False) if body is not None else response.text[:1000]))

    result = interpret_response(response.status_code, body)
    print("COMMUNICATION_OK=" + str(result["communication_ok"]).lower())
    print("AUTOMATION_RESULT=" + result["automation_result"])
    print("DETAIL=" + result["detail"])

    matches = result["communication_ok"] and result["automation_result"] == expected_result
    print("MATCHES_EXPECTED_RULE=" + str(matches).lower())
    return matches


def main():
    load_dotenv()
    parser = argparse.ArgumentParser(description="Valida o retorno da API Dinx no ambiente Dev.")
    parser.add_argument("--scenario", choices=["private", "public", "both"], default="both")
    parser.add_argument("--send", action="store_true", help="Executa as chamadas; sem esta opcao faz apenas dry-run")
    args = parser.parse_args()

    url = os.getenv("DINX_DEV_URL", DEFAULT_DEV_URL)
    ensure_dev_url(url)
    api_key = os.getenv("DINX_DEV_API_KEY", "")
    if args.send and not api_key:
        raise SystemExit("DINX_DEV_API_KEY nao configurada")

    names = list(SCENARIOS) if args.scenario == "both" else [args.scenario]
    matches = [run_scenario(name, url, api_key, args.send) for name in names]
    if args.send and not all(matches):
        raise SystemExit(1)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, requests.RequestException) as error:
        print(f"PROBE_ERROR={error}", file=sys.stderr)
        raise SystemExit(2)
