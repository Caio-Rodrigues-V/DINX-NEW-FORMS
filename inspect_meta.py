import json
import os
import urllib.error
import urllib.parse
import urllib.request


def load_env(path=".env"):
    env = {}
    if not os.path.exists(path):
        return env

    with open(path, encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
                value = value[1:-1]
            env[key.strip()] = value
    return env


def graph_get(path, params):
    query = urllib.parse.urlencode(params)
    url = f"https://graph.facebook.com/v25.0/{path}?{query}"
    with urllib.request.urlopen(url, timeout=25) as response:
        return json.loads(response.read().decode("utf-8"))


def mask_value(name, value):
    if value is None:
        return None

    text = str(value)
    low_name = name.lower()
    if "email" in low_name:
        return "<email>"
    if "phone" in low_name or "telefone" in low_name or "whatsapp" in low_name:
        digits = "".join(char for char in text if char.isdigit())
        return f"<phone digits={len(digits)} sample_start={digits[:4]}>"
    if len(text) > 80:
        return text[:77] + "..."
    return text


def main():
    env = load_env()
    env.update({key: value for key, value in os.environ.items() if value})
    token = env.get("META_PAGE_TOKEN")
    page_id = env.get("META_PAGE_ID")
    form_id = env.get("META_FORM_ID")

    print("META_PAGE_TOKEN present:", bool(token))
    print("META_PAGE_ID present:", bool(page_id))
    print("META_FORM_ID present:", bool(form_id))
    if not token:
        raise SystemExit("Missing META_PAGE_TOKEN in .env")

    if form_id:
        inspect_forms = [{"id": form_id, "name": "<direct form id>"}]
    elif page_id:
        try:
            forms_response = graph_get(
                f"{page_id}/leadgen_forms",
                {
                    "access_token": token,
                    "fields": "id,name,questions",
                    "limit": 25,
                },
            )
        except urllib.error.HTTPError as error:
            print("Meta API error:", error.code)
            print(error.read().decode("utf-8")[:4000])
            raise SystemExit(1)

        inspect_forms = forms_response.get("data", [])
    else:
        raise SystemExit("Missing META_PAGE_ID or META_FORM_ID in .env")

    forms = inspect_forms
    print("forms_found:", len(forms))

    for form in forms:
        print("\nFORM")
        print("id:", form.get("id"))
        print("name:", form.get("name"))
        questions = form.get("questions")
        if questions is None:
            try:
                form_details = graph_get(
                    form.get("id"),
                    {
                        "access_token": token,
                        "fields": "id,name,questions",
                    },
                )
                print("name:", form_details.get("name", form.get("name")))
                questions = form_details.get("questions") or []
            except urllib.error.HTTPError as error:
                print("form_details_error:", error.code)
                print(error.read().decode("utf-8")[:2000])
                questions = []
        print("questions_found:", len(questions))
        for question in questions:
            print(
                "-",
                {
                    "key": question.get("key"),
                    "label": question.get("label"),
                    "type": question.get("type"),
                    "options": question.get("options"),
                },
            )

        leads_response = graph_get(
            f"{form.get('id')}/leads",
            {
                "access_token": token,
                "fields": "id,created_time,field_data",
                "limit": 3,
            },
        )
        leads = leads_response.get("data", [])
        print("sample_leads_found:", len(leads))
        for lead in leads:
            print("lead_id:", lead.get("id"), "created_time:", lead.get("created_time"))
            for item in lead.get("field_data", []):
                values = item.get("values") or []
                masked_values = [mask_value(item.get("name", ""), value) for value in values]
                print("  field:", item.get("name"), "values:", masked_values)


if __name__ == "__main__":
    main()
