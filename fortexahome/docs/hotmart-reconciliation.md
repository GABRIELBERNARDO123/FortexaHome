# Reconciliação Hotmart

## Escopo

A reconciliação complementa o webhook Hotmart 2.0.0. Ela consulta o estado comercial atual de transações **já conhecidas localmente** e compara com `orders`, `licenses` e entregas. O webhook continua sendo o caminho principal; a reconciliação existe para detectar notificações perdidas ou fora de ordem.

Ela não cria pedido, tenant, licença ou entrega para transação desconhecida. Não altera catálogo, preço interno, comprador ou e-mail de compra. Não reabre estados terminais.

## Documentação oficial consultada

- Autenticação: `https://developers.hotmart.com/docs/pt-BR/start/app-auth/`
- Participantes de vendas: `https://developers.hotmart.com/docs/pt-BR/v1/sales/sales-users/`
- Detalhamento de preços: `https://developers.hotmart.com/docs/pt-BR/v1/sales/sales-price-details/`
- Histórico de vendas: `https://developers.hotmart.com/docs/pt-BR/v1/sales/sales-history/`
- Paginação: `https://developers.hotmart.com/docs/pt-BR/start/pagination/`
- Rate limit: `https://developers.hotmart.com/docs/pt-BR/start/rate-limit/`
- Códigos HTTP: `https://developers.hotmart.com/docs/pt-BR/start/http-response-codes/`
- Sandbox: `https://developers.hotmart.com/docs/pt-BR/start/sandbox/`
- Webhook 2.0.0: `https://developers.hotmart.com/docs/pt-BR/2.0.0/webhook/purchase-webhook/`
- Boas práticas: `https://developers.hotmart.com/docs/pt-BR/tutorials/learn-good-usage-practices/`

## Endpoint utilizado

Somente o histórico de vendas:

```text
GET https://developers.hotmart.com/payments/api/v1/sales/history?transaction=<ID>&max_results=5
Authorization: Bearer <access_token>
```

Produção usa a URL acima. Sandbox usa `https://sandbox.hotmart.com/payments/api/v1/sales/history`.

O filtro `transaction` é obrigatório para esta integração. Isso evita varredura irrestrita e garante que a consulta não dependa do comportamento padrão que retorna apenas `APPROVED`/`COMPLETE` quando não há filtro.

Não são usados `sales/users` nem `sales/price/details`:
- `sales/users` expõe nome, e-mail, telefone, documentos e endereço, sem necessidade para confirmar o estado comercial;
- `sales/price/details` não é necessário porque o preço interno do catálogo é a fonte de verdade e a reconciliação não corrige valores.

O endpoint de histórico também retorna dados de comprador; o cliente faz parsing somente de transação, produto, status, datas comerciais e preço/ moeda do provedor. Nome, e-mail, documento, endereço e telefone não são persistidos nem registrados.

## Autenticação

OAuth 2.0 com `client_credentials`, conforme documentação:

```text
POST https://api-sec-vlc.hotmart.com/security/oauth/token
  ?grant_type=client_credentials
  &client_id=<client_id>
  &client_secret=<client_secret>
Authorization: Basic base64(client_id:client_secret)
Content-Type: application/json
```

O token fica somente em memória, com validade controlada. Uma resposta `401` invalida o token e tenta renová-lo uma vez. `403` é erro de autorização sem retry. `429` respeita `Retry-After`; `5xx`, timeout e falha de transporte usam backoff exponencial com jitter e número máximo de tentativas.

Nunca são registrados client secret, Basic token, access token, HOTTOK ou payload externo completo.

## Configuração

A reconciliação é independente de `HOTMART_ENABLED` e permanece desabilitada por padrão.

| Variável | Uso |
| --- | --- |
| `HOTMART_RECONCILIATION_ENABLED` | habilita explicitamente a feature |
| `HOTMART_RECONCILIATION_CLIENT_ID` | Client ID da credencial Developers |
| `HOTMART_RECONCILIATION_CLIENT_SECRET` | Client Secret da credencial Developers |
| `HOTMART_RECONCILIATION_ENVIRONMENT` | `production` ou `sandbox` |
| `HOTMART_RECONCILIATION_PRODUCT_ID` | ID numérico do produto na Hotmart, usado para validar o produto retornado |
| `HOTMART_RECONCILIATION_TIMEOUT_SECONDS` | timeout HTTP, 1–30 s |
| `HOTMART_RECONCILIATION_MAX_TRANSACTIONS` | lote máximo por execução, 1–100 |
| `HOTMART_RECONCILIATION_LOOKBACK_HOURS` | janela padrão de pedidos locais, 1–720 h |
| `HOTMART_RECONCILIATION_MAX_ATTEMPTS` | tentativas por chamada, 1–5 |
| `HOTMART_RECONCILIATION_BACKOFF_BASE_SECONDS` | base do backoff, 0,1–30 s |
| `HOTMART_RECONCILIATION_REQUEST_INTERVAL_SECONDS` | intervalo entre transações, 0–5 s |

O preflight de ambiente falha se a feature estiver habilitada sem credenciais, produto, slug local ou ID de produto válido. O preflight de banco verifica a tabela de observações e seus privilégios. Nenhuma credencial é impressa.

## Fluxo

1. O CLI seleciona transações locais recentes (`orders.updated_at` dentro da janela) ou uma transação explícita.
2. Antes de cada HTTP, carrega um snapshot local: `order.updated_at`, status do pedido, status da licença, existência de e-mail local e fingerprint do último `payment_event`.
3. Consulta o estado remoto **sem manter locks de banco durante o HTTP**.
4. Se o pedido local não existe, registra `local_order_missing` e não cria nada.
5. Valida produto local, produto remoto (`product_id`), UCODE quando retornado e eventuais divergências de preço/moeda do provedor. Divergência não altera estado.
6. Compara estados e decide entre consistente, corrigível ou análise manual.
7. Em `--apply`, abre uma transação, adquire o advisory lock `hotmart:transaction:<id>` (o mesmo do webhook), bloqueia o pedido com `FOR UPDATE`, recarrega snapshot/licença/evento e só aplica se o snapshot não mudou.
8. Aplica aprovação/terminal usando `apply_hotmart_approval`/`apply_hotmart_terminal` do `license_service`, as mesmas regras do webhook.
9. Registra a observação no mesmo commit da alteração comercial. Em falha, faz rollback e tenta registrar uma observação `error` sanitizada.

## Mapeamento de status

| Status remoto | Tratamento | Efeito |
| --- | --- | --- |
| `APPROVED` | seguro | pedido pendente → pago; cria/restaura licença conforme regra existente |
| `CANCELLED` | terminal seguro | pedido → cancelado; licença → cancelada; entrega cancelada |
| `EXPIRED` | terminal seguro | pedido → cancelado; licença → cancelada; entrega cancelada |
| `REFUNDED` | terminal seguro | pedido → reembolsado; licença → cancelada; entrega cancelada |
| `CHARGEBACK` | terminal seguro | pedido → chargeback; licença → suspensa; entrega cancelada |
| `PROTESTED` | terminal seguro | mesmo tratamento de chargeback |
| `COMPLETE` | informativo | não concede acesso; consistente apenas em estados já pagos |
| `PRINTED_BILLET`, `PROCESSING_TRANSACTION`, `STARTED`, `UNDER_ANALISYS`, `WAITING_PAYMENT`, `PRE_ORDER`, `OVERDUE` | informativo/temporário | sem alteração; não concede acesso |
| `BLOCKED` | manual | divergência registrada, nenhuma alteração |
| `PARTIALLY_REFUNDED` | manual | nenhuma alteração automática |
| `NO_FUNDS` | manual | nenhuma alteração automática |
| desconhecido | manual | divergência registrada, nenhuma alteração |

Estados terminais locais nunca são revertidos. `APPROVED` remoto sobre pedido terminal gera conflito manual. `PROTESTED` e `CHARGEBACK` são mapeados para `chargeback`, como no webhook atual. `PARTIALLY_REFUNDED` não é tratado como reembolso total.

## Concorrência e eventos fora de ordem

- O HTTP ocorre fora de qualquer transação de banco.
- O snapshot local é obrigatório para aplicar; se pedido, licença ou último evento mudarem durante a consulta, o resultado é `stale` e nenhuma transição é aplicada.
- Webhook e reconciliação compartilham advisory lock transacional por `provider + transaction`, além de `SELECT ... FOR UPDATE` no pedido.
- Webhook que chega depois da consulta tem precedência natural; a observação antiga é descartada.
- Duas reconciliações simultâneas: uma aplica, a outra encontra snapshot alterado e registra `stale`.
- Nenhum `payment_event` sintético é criado. A observação guarda origem `hotmart_sales_api`, `run_id`, horários, estados e resultado.
- Não há uso da hora da consulta como data de ocorrência do evento remoto. Datas de pedido/aprovação retornadas pela API são apenas registradas na observação quando existem.

## Idempotência

- Reprocessar a mesma transação não cria pedido, licença, evento ou entrega duplicada.
- Aprovação só age em pedido pendente; terminal só age em pedido não terminal.
- Observações são imutáveis e únicas por `(run_id, provider, external_order_id)`.
- Observações de execuções diferentes são permitidas para auditoria, mas não geram efeitos comerciais duplicados.
- `payment_events` continua exclusivo do webhook; a reconciliação não inventa eventos Hotmart.

## Observações e auditoria

Tabela `hotmart_reconciliation_observations` (migration `20261102_15`):

- `run_id`, `provider`, `source` (`hotmart_sales_api`), `external_order_id`, `order_id`;
- status remoto, produto remoto, status local do pedido/licença e `local_updated_at`;
- resultado da comparação, resultado da aplicação, motivo e código de erro sanitizado;
- datas comerciais remotas quando disponíveis, `observed_at`, `processed_at` e `dry_run`.

Não há payload integral, e-mail, documento, endereço, token, segredo ou HOTTOK. O papel operacional recebe somente `SELECT`/`INSERT`; não recebe `UPDATE`/`DELETE`. O worker da outbox não tem acesso. A tabela não usa RLS porque é global e não contém dado de tenant/PII em claro; o acesso é limitado por grants.

## CLI

```sh
# Dry-run padrão: consulta, compara e registra apenas observações/auditoria
python -m app.cli.reconcile_hotmart

# Uma transação específica
python -m app.cli.reconcile_hotmart --transaction HP12345678901234 --dry-run

# Aplicação explícita
python -m app.cli.reconcile_hotmart --transaction HP12345678901234 --apply

# Lote limitado, com janela e JSON para automação
python -m app.cli.reconcile_hotmart --limit 10 --lookback-hours 24 --apply --json
```

Regras do CLI:

- `--apply` é obrigatório para qualquer transição;
- sem `--apply`, o comando é sempre dry-run;
- `--transaction` ignora a seleção por janela, mas não cria pedido local;
- `--limit` não pode exceder `HOTMART_RECONCILIATION_MAX_TRANSACTIONS`;
- `--lookback-hours` não pode exceder 720;
- três falhas consecutivas interrompem o lote;
- logs não incluem credenciais nem payload;
- código `0`: execução concluída; `1`: falha de API/aplicação ou parada antecipada; `2`: configuração/entrada inválida.

## Retentativas e falhas

- `401` renova token uma vez; se persistir, falha sem alterar estado.
- `403`, `404`, resposta malformada e status desconhecido não são interpretados como cancelamento/reembolso.
- `429`, timeout, DNS/conexão e `5xx` usam backoff com jitter e máximo de tentativas; `Retry-After` é respeitado.
- API indisponível não altera estado local.
- O lote é limitado; não há varredura de toda a história de vendas.
- Rate limit oficial: 500 chamadas/minuto por aplicação. O CLI usa lote pequeno e intervalo configurável; não usa os endpoints de participantes/preços.

## RLS e operação

- O CLI usa o papel operacional existente (`APP_DB_USER`), sem `BYPASSRLS` e sem privilégios administrativos de catálogo/worker. Ele reutiliza os serviços transacionais e o contexto RLS; não foi criado um papel com privilégios maiores.
- O worker da outbox continua sem acesso à tabela de observações.
- Nenhuma rota HTTP pública foi criada para reconciliação.
- A feature não é executada automaticamente nesta missão. O operador pode agendá-la via cron/tarefa operacional, sempre com `--apply` explícito para efeitos comerciais.
- O procedimento recomendado é: preflight → migrations → dry-run em lote pequeno → revisar observações → aplicar transação específica → dry-run de acompanhamento.

## Limitações conhecidas

- Nenhuma chamada real à Hotmart foi executada nesta missão; todos os testes usam `httpx.MockTransport`.
- O endpoint `sales/history` não expõe UCODE no contrato documentado; a validação usa o ID numérico do produto (`HOTMART_RECONCILIATION_PRODUCT_ID`) e o vínculo local ao produto. UCODE continua sendo validado pelo webhook.
- `sales/users` e `sales/price/details` não são usados; a reconciliação não corrige comprador, endereço, documento, comissão ou preço.
- Estados sem mapeamento seguro exigem análise manual e não alteram licença.
- `PARTIALLY_REFUNDED` não é reembolso total automático.
- Não há scheduler embutido; a execução periódica é responsabilidade operacional.
- O circuit breaker é um limite de três falhas consecutivas por lote, não um breaker distribuído entre processos.
