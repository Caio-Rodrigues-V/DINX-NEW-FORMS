import csv
import io
import json
import os
from threading import Thread
from html import escape

import redis
from dotenv import load_dotenv
from flask import Flask, Response, jsonify, render_template_string, request

import main as lead_sync


load_dotenv()

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
SEEN_REDIS_KEY = "dinx:seen_leads"
SENT_DETAIL_REDIS_KEY = "dinx:sent_leads"
REJECTED_REDIS_KEY = "dinx:rejected_leads"
INVALID_REDIS_KEY = "dinx:invalid_leads"
FILTERED_REDIS_KEY = "dinx:filtered_leads"
META_WEBHOOK_VERIFY_TOKEN = os.getenv("META_WEBHOOK_VERIFY_TOKEN", "")

app = Flask(__name__)


def process_webhook_lead(lead_id):
    lead_sync.process_lead_id(lead_id)


def redis_client():
    return redis.from_url(
        REDIS_URL,
        decode_responses=True,
        socket_connect_timeout=3,
        socket_timeout=3,
    )


def safe_count(client, key):
    try:
        return client.scard(key)
    except redis.RedisError:
        return 0


def first_reason(record):
    reasons = record.get("reasons") or []
    if not reasons:
        return "", ""
    reason = reasons[0] or {}
    return reason.get("field", ""), reason.get("message", "")


def load_rejected_records(limit=None):
    client = redis_client()
    records = []

    try:
        lead_ids_iter = client.sscan_iter(REJECTED_REDIS_KEY, count=200)
        lead_ids = []
        for lead_id in lead_ids_iter:
            lead_ids.append(lead_id)
            if limit and len(lead_ids) >= limit:
                break
    except redis.RedisError:
        app.logger.exception("Erro ao listar leads rejeitados no Redis")
        return []

    for lead_id in lead_ids:
        try:
            raw = client.get(f"dinx:rejected_lead:{lead_id}")
            if raw:
                record = json.loads(raw)
            else:
                record = {
                    "lead_id": lead_id,
                    "status": "",
                    "phone_digits": "",
                    "created_at": "",
                    "response": "",
                    "reasons": [{"field": "", "message": "Detalhe nao encontrado no Redis"}],
                }
        except (redis.RedisError, json.JSONDecodeError):
            app.logger.exception("Erro ao carregar lead rejeitado %s", lead_id)
            continue

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

    records.sort(key=lambda row: row.get("created_at") or "", reverse=True)
    return records[:limit] if limit else records


def load_sent_records(limit=None):
    client = redis_client()
    records = []

    try:
        lead_ids_iter = client.sscan_iter(SENT_DETAIL_REDIS_KEY, count=200)
        lead_ids = []
        for lead_id in lead_ids_iter:
            lead_ids.append(lead_id)
            if limit and len(lead_ids) >= limit:
                break
    except redis.RedisError:
        app.logger.exception("Erro ao listar leads enviados no Redis")
        return []

    for lead_id in lead_ids:
        try:
            raw = client.get(f"dinx:sent_lead:{lead_id}")
            if not raw:
                continue
            record = json.loads(raw)
        except (redis.RedisError, json.JSONDecodeError):
            app.logger.exception("Erro ao carregar lead enviado %s", lead_id)
            continue

        records.append(
            {
                "lead_id": record.get("lead_id", lead_id),
                "status": record.get("status", ""),
                "decision": record.get("decision", "accepted"),
                "phone_digits": record.get("phone_digits", ""),
                "created_at": record.get("created_at", ""),
                "response": record.get("response", ""),
            }
        )

    records.sort(key=lambda row: row.get("created_at") or "", reverse=True)
    return records[:limit] if limit else records


def masked_config():
    meta_form_id = os.getenv("META_FORM_ID", "")
    dinx_url = os.getenv("DINX_URL", "")
    interval = os.getenv("INTERVAL_MINUTES", "")
    redis_host = REDIS_URL.split("@")[-1].split("/")[0] if REDIS_URL else ""
    return {
        "meta_form_id": meta_form_id,
        "dinx_url": dinx_url,
        "interval": interval,
        "redis_host": redis_host,
    }


@app.get("/meta-webhook")
def meta_webhook_verify():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    if mode == "subscribe" and token and token == META_WEBHOOK_VERIFY_TOKEN:
        return Response(challenge or "", status=200, mimetype="text/plain")

    return Response("Forbidden", status=403)


@app.post("/meta-webhook")
def meta_webhook_receive():
    payload = request.get_json(silent=True) or {}
    lead_ids = []

    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            if change.get("field") != "leadgen":
                continue
            value = change.get("value") or {}
            lead_id = value.get("leadgen_id") or value.get("lead_id")
            if lead_id:
                lead_ids.append(lead_id)

    for lead_id in lead_ids:
        Thread(target=process_webhook_lead, args=(lead_id,), daemon=True).start()

    return jsonify({"ok": True, "received": len(lead_ids)})


@app.get("/")
def dashboard():
    try:
        client = redis_client()
        stats = {
            "sent": safe_count(client, SEEN_REDIS_KEY),
            "rejected": safe_count(client, REJECTED_REDIS_KEY),
            "invalid": safe_count(client, INVALID_REDIS_KEY),
            "filtered": safe_count(client, FILTERED_REDIS_KEY),
        }
    except redis.RedisError:
        app.logger.exception("Erro ao carregar contadores do Redis")
        stats = {"sent": 0, "rejected": 0, "invalid": 0, "filtered": 0}

    try:
        records = load_rejected_records(limit=100)
    except Exception:
        app.logger.exception("Erro ao carregar lista de leads rejeitados")
        records = []
    try:
        sent_records = load_sent_records(limit=25)
    except Exception:
        app.logger.exception("Erro ao carregar lista de leads enviados")
        sent_records = []
    config = masked_config()

    return render_template_string(
        DASHBOARD_HTML,
        stats=stats,
        records=records,
        sent_records=sent_records,
        config=config,
        escape=escape,
    )


@app.get("/rejected.csv")
def rejected_csv():
    records = load_rejected_records()
    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=["lead_id", "status", "phone_digits", "field", "message", "created_at", "response"],
        delimiter=";",
    )
    writer.writeheader()
    writer.writerows(records)

    data = "\ufeff" + output.getvalue()
    return Response(
        data,
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=rejected_leads.csv"},
    )


@app.get("/health")
def health():
    client = redis_client()
    client.ping()
    return jsonify({"ok": True})


DASHBOARD_HTML = """
<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Dinx Leads Sync</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f6f7f9;
      --panel: #ffffff;
      --text: #1d2433;
      --muted: #667085;
      --line: #d9dee8;
      --accent: #0f766e;
      --danger: #b42318;
      --warn: #b54708;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: var(--bg);
      color: var(--text);
      font-size: 14px;
    }
    header {
      background: var(--panel);
      border-bottom: 1px solid var(--line);
      padding: 18px 28px;
      display: flex;
      justify-content: space-between;
      gap: 16px;
      align-items: center;
    }
    h1 { margin: 0; font-size: 20px; font-weight: 700; letter-spacing: 0; }
    main { padding: 24px 28px 40px; max-width: 1280px; margin: 0 auto; }
    .muted { color: var(--muted); }
    .grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin-bottom: 20px; }
    .stat {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 16px;
    }
    .stat span { color: var(--muted); display: block; margin-bottom: 8px; }
    .stat strong { font-size: 28px; line-height: 1; }
    .toolbar {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
      margin: 18px 0 10px;
    }
    a.button {
      background: var(--accent);
      color: white;
      text-decoration: none;
      border-radius: 6px;
      padding: 9px 12px;
      font-weight: 600;
      white-space: nowrap;
    }
    .config {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px 16px;
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 12px;
      margin-bottom: 20px;
    }
    .config b { display: block; margin-bottom: 4px; }
    .config span {
      color: var(--muted);
      overflow-wrap: anywhere;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      overflow: hidden;
    }
    th, td {
      text-align: left;
      padding: 11px 12px;
      border-bottom: 1px solid var(--line);
      vertical-align: top;
    }
    th {
      font-size: 12px;
      text-transform: uppercase;
      color: var(--muted);
      background: #fbfcfe;
    }
    tr:last-child td { border-bottom: 0; }
    .badge {
      display: inline-block;
      border-radius: 999px;
      padding: 3px 8px;
      background: #fff4ed;
      color: var(--warn);
      font-weight: 700;
      font-size: 12px;
    }
    .phone { font-variant-numeric: tabular-nums; }
    .empty {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 28px;
      text-align: center;
      color: var(--muted);
    }
    @media (max-width: 860px) {
      header { align-items: flex-start; flex-direction: column; }
      main { padding: 18px 14px 32px; }
      .grid, .config { grid-template-columns: 1fr; }
      .toolbar { align-items: flex-start; flex-direction: column; }
      table { display: block; overflow-x: auto; white-space: nowrap; }
    }
  </style>
</head>
<body>
  <header>
    <div>
      <h1>Dinx Leads Sync</h1>
      <div class="muted">Monitoramento de importacao e rejeicoes</div>
    </div>
    <a class="button" href="/rejected.csv">Baixar rejeitados CSV</a>
  </header>
  <main>
    <section class="grid" aria-label="Resumo">
      <div class="stat"><span>Enviados</span><strong>{{ stats.sent }}</strong></div>
      <div class="stat"><span>Rejeitados</span><strong>{{ stats.rejected }}</strong></div>
      <div class="stat"><span>Invalidos</span><strong>{{ stats.invalid }}</strong></div>
      <div class="stat"><span>Filtrados pela regra</span><strong>{{ stats.filtered }}</strong></div>
    </section>

    <section class="config" aria-label="Configuracao">
      <div><b>Form V5</b><span>{{ config.meta_form_id or "nao definido" }}</span></div>
      <div><b>Dinx URL</b><span>{{ config.dinx_url or "nao definido" }}</span></div>
      <div><b>Intervalo</b><span>{{ config.interval or "nao definido" }} min</span></div>
      <div><b>Redis</b><span>{{ config.redis_host or "nao definido" }}</span></div>
    </section>

    <div class="toolbar">
      <h2 style="margin:0;font-size:18px;">Ultimos enviados aceitos pela API</h2>
      <div class="muted">Mostrando ate 25 registros</div>
    </div>

    {% if sent_records %}
    <table>
      <thead>
        <tr>
          <th>Lead ID</th>
          <th>Status HTTP</th>
          <th>Decisao</th>
          <th>Telefone</th>
          <th>Data</th>
          <th>Resposta Dinx</th>
        </tr>
      </thead>
      <tbody>
        {% for record in sent_records %}
        <tr>
          <td>{{ record.lead_id }}</td>
          <td><span class="badge">{{ record.status }}</span></td>
          <td><span class="badge">{{ record.decision }}</span></td>
          <td>{{ record.phone_digits }}</td>
          <td>{{ record.created_at }}</td>
          <td>{{ escape(record.response) }}</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
    {% else %}
    <div class="empty">Nenhum envio aceito registrado ainda.</div>
    {% endif %}

    <div class="toolbar">
      <h2 style="margin:0;font-size:18px;">Ultimos rejeitados</h2>
      <div class="muted">Mostrando ate 100 registros</div>
    </div>

    {% if records %}
    <table>
      <thead>
        <tr>
          <th>Lead ID</th>
          <th>Status</th>
          <th>Telefone</th>
          <th>Campo</th>
          <th>Motivo</th>
          <th>Data</th>
        </tr>
      </thead>
      <tbody>
      {% for row in records %}
        <tr>
          <td>{{ row.lead_id }}</td>
          <td><span class="badge">{{ row.status }}</span></td>
          <td class="phone">{{ row.phone_digits }}</td>
          <td>{{ row.field }}</td>
          <td>{{ row.message }}</td>
          <td>{{ row.created_at }}</td>
        </tr>
      {% endfor %}
      </tbody>
    </table>
    {% else %}
      <div class="empty">Nenhum lead rejeitado registrado no Redis.</div>
    {% endif %}
  </main>
</body>
</html>
"""


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
