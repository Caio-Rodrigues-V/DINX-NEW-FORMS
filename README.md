
Worker para importar leads do novo formulario Meta para a API Dinx, com regras de elegibilidade, DE/PARA de campos, limpeza de telefone, controle anti-duplicidade e dashboard operacional.

## Processos

O `Procfile` define dois processos:

```text
web: gunicorn app:app --bind 0.0.0.0:$PORT
worker: python main.py
```

- `web`: dashboard para acompanhar enviados, rejeitados e baixar CSV.
- `worker`: consulta o formulario Meta e envia novos leads para a Dinx.

O worker aguarda `SEND_DELAY_SECONDS` entre tentativas de envio para evitar rate limit e sobrecarga da API Dinx.

## Variaveis

Configure no Railway:

```text
META_PAGE_TOKEN
META_PAGE_ID
META_FORM_ID=1696556268158303
META_WEBHOOK_VERIFY_TOKEN
DINX_URL=https://bff.prd.dinx.app/site.beta_access.v1.SiteBetaAccessService/RequestPartnerBetaAccess
DINX_API_KEY
INTERVAL_MINUTES=30
SEND_DELAY_SECONDS=4
REDIS_URL
SAVE_REJECTED_FILE=0
SKIP_INVALID_LEADS=1
```

## Tempo real via Webhook Meta

O `SEND_DELAY_SECONDS` nao deixa a integracao em tempo real; ele controla apenas a pausa entre o envio de um lead e outro depois que o worker ja encontrou leads novos.

Para entrada em tempo real, o projeto tambem expoe um webhook:

```text
GET /meta-webhook
POST /meta-webhook
```

- `GET /meta-webhook`: usado pela Meta para validar o endpoint com `hub.challenge`.
- `POST /meta-webhook`: recebe eventos `leadgen`, busca o lead completo pelo `leadgen_id`, aplica o mesmo DE/PARA do worker e envia para a Dinx.

Configure no Meta Developers a URL publica:

```text
https://SEU_DOMINIO/meta-webhook
```

O token de verificacao configurado na Meta deve ser o mesmo valor de:

```text
META_WEBHOOK_VERIFY_TOKEN
```

O worker por polling pode continuar ativo como fallback. Nesse caso, `INTERVAL_MINUTES=1` funciona como uma rede de seguranca caso algum evento de webhook falhe.

## Nova regra de negocio

Idade dos filhos:

```text
De 3 a 6 anos -> segue para a pergunta de escola
De 7 a 12 anos -> segue para a pergunta de escola
Ambas as idades -> segue para a pergunta de escola
Nao tenho filho(a) -> encerra o formulario e nao envia para a Dinx
```

Escola:

```text
Escola particular -> school_type 2; resposta de download do app
Escola publica -> school_type 1; resposta de lista de espera
Nao tenho filho(a) -> nao envia para a Dinx
```

Para os dois tipos de escola, a renda e enviada como nao informada:

```text
income_range -> notInformed
```

O integrador registra a decisao devolvida pela API:

```text
success=true, approved=true -> approved
success=true, approved=false -> pending
success=false -> business_error
```

As telas finais e a navegacao condicional devem ser configuradas no formulario da Meta. O formulario tambem deve incluir a opcao `Nao tenho filho(a)` e manter desabilitado o preenchimento automatico dos dados de contato.

## Regras de DE/PARA

Idade:

```text
de_3_a_6_anos -> between3and6
de_7_a_12_anos -> between7and12
ambas_as_idades -> both
```

Telefone:

```text
p:+5511999999999 -> 11999999999
9333105273 -> 93933105273
```

Telefones brasileiros com 10 digitos recebem o nono digito apos o DDD para permitir a entrada no backoffice.

Origem:

```text
origin -> 1 (Meta)
```

Quantidade de filhos:

```text
ambas_as_idades -> children_count 2
```

## Redis

Chaves usadas:

```text
dinx:seen_leads
dinx:sent_leads
dinx:sent_lead:{lead_id}
dinx:rejected_leads
dinx:rejected_lead:{lead_id}
dinx:invalid_leads
dinx:filtered_leads
dinx:filtered_lead:{lead_id}
```

Leads com sucesso entram em `dinx:seen_leads` e os detalhes da resposta da Dinx ficam em `dinx:sent_leads` / `dinx:sent_lead:{lead_id}`. Rejeicoes ficam em `dinx:rejected_leads` e detalhes em `dinx:rejected_lead:{lead_id}`. Rejeicoes `400` tambem entram em `dinx:invalid_leads`.

Leads que responderam `Nao tenho filho(a)` entram apenas em `dinx:filtered_leads`, para auditoria e anti-reprocessamento. Eles nao sao enviados nem gravados no backoffice da Dinx.

Por padrao, `SKIP_INVALID_LEADS=1`, entao leads marcados como invalidos nao sao reenviados em ciclos futuros. Se precisar reprocessar invalidos depois de ajustar a normalizacao, use `SKIP_INVALID_LEADS=0` temporariamente.

## Dashboard

Rotas:

```text
GET /
GET /rejected.csv
GET /health
```

## Validacao da API Dev

O probe usa dados ficticios, bloqueia qualquer host diferente de `bff.dev.dinx.app` e compara os retornos esperados para escola particular e publica.

Configure a chave Dev apenas no ambiente local:

```text
DINX_DEV_API_KEY=chave-fornecida-pela-Dinx
```

Visualize os payloads sem enviar:

```bash
python probe_dinx_dev.py
```

Execute os dois cenarios no ambiente Dev:

```bash
python probe_dinx_dev.py --send
```

Tambem e possivel executar apenas `--scenario private` ou `--scenario public`. O comando nunca aceita a URL de producao.

## Exportacao Local

Para exportar rejeitados do Redis para CSV:

```bash
python export_rejected_leads.py
```
