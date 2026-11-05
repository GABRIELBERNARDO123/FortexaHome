# Integração Hotmart Webhook 2.0.0

## Arquitetura

O endpoint `POST /api/v1/webhooks/hotmart` recebe somente JSON da versão `2.0.0`. O adaptador Hotmart valida o cabeçalho `X-HOTMART-HOTTOK`, valida o envelope e normaliza os campos. Ele é independente do endpoint e da assinatura `hmac_sandbox`. A Hotmart não chama o Resend: a licença e o e-mail são persistidos na mesma transação, e o worker da outbox faz a entrega.

Referências oficiais: [Purchase Webhook 2.0.0](https://developers.hotmart.com/docs/pt-BR/2.0.0/webhook/purchase-webhook/) e [boas práticas de uso](https://developers.hotmart.com/docs/pt-BR/tutorials/learn-good-usage-practices/). A implementação usa `id`, `creation_date` em milissegundos, `event`, `version`, `data.product.ucode`, `data.buyer.email` quando presente, `data.purchase.transaction`, `data.purchase.price`, `data.purchase.full_price` e `data.purchase.order_bump`. Campos alheios ao processamento são ignorados; nenhum payload integral é persistido. Identificadores obrigatórios em branco são rejeitados com `400`.

## Order Bump

`data.purchase.order_bump.is_order_bump` indica que a compra é um Order Bump. `parent_purchase_transaction` aponta para a transação principal e pode vir vazio; vazio é normalizado para ausente. O pedido é sempre identificado pela transação própria `data.purchase.transaction`; `parent_purchase_transaction` nunca é usado como substituto, para não associar ou fundir compras indevidamente. Um Order Bump de outro UCODE é ignorado antes do processamento; um Order Bump do UCODE configurado é processado normalmente pela sua própria transação. O `id` do evento continua obrigatório mesmo em Order Bump e não é substituído por outro campo.

## Valores financeiros

O preço comercial do produto interno permanece a única fonte para concessão de acesso e é gravado em `orders.amount_cents`/`currency`. Os valores informados pela Hotmart são persistidos separadamente, apenas para registro: `purchase.price.value`/`currency_code` em `orders.provider_price_cents`/`provider_price_currency` e `purchase.full_price.value`/`currency_code` em `orders.provider_full_price_cents`/`provider_full_price_currency` (migration `20261031_10`). `price` é o valor da oferta; `full_price` é o total pago pelo comprador, incluindo taxas e juros, e não representa o valor líquido recebido pelo produtor. Uma divergência entre esses campos não concede nem retira acesso automaticamente; exige regra comercial explícita. Quando o webhook não traz um desses campos, o respectivo campo `provider_*` permanece nulo, e não é preenchido com o preço interno.

## Configuração

Configure no ambiente do servidor (secret manager ou arquivo de ambiente protegido, fora do repositório):

* `HOTMART_ENABLED=true` habilita o endpoint.
* `HOTMART_WEBHOOK_HOTTOK` recebe o HOTTOK criado/configurado na área de webhooks da Hotmart. O valor nunca é salvo no banco ou registrado em logs.
* `HOTMART_PRODUCT_UCODE` recebe o UCODE copiado do produto correto na Hotmart.
* `HOTMART_PRODUCT_SLUG` identifica o produto interno previamente cadastrado no catálogo FortexaHome. Seu preço e moeda internos definem o pedido; preço, nome ou moeda do webhook não concedem acesso.

Os nomes, sem valores, estão em `.env.example`. Com Hotmart habilitada, a configuração de produção rejeita HOTTOK/UCODE/slug ausentes. O produto interno precisa existir e estar ativo antes de aceitar a primeira compra. O endpoint não habilita a integração por padrão. Não envie HOTTOK ou UCODE em tickets, logs ou conversas.

O catálogo interno é provisionado por comando versionado, sem edição manual do banco:

```sh
python -m app.cli.provision_product \
  --slug <slug-interno> \
  --name "<nome comercial>" \
  --price-cents <preco-em-centavos> \
  --currency BRL \
  --license-kind lifetime \
  --state active \
  --dry-run
# revise a saída e repita com --apply
python -m app.cli.preflight --stage commercial
```

O comando é idempotente pelo slug. Um produto existente inativo não é reativado sem `--state active` explícito. Consulte [production-preflight.md](production-preflight.md) para a ordem completa de implantação, variáveis e interpretação de erros.

Com `HOTMART_ENABLED=true`, não é necessário definir `PAYMENT_WEBHOOK_SECRET` para o antigo `hmac_sandbox`; HOTTOK tem sua própria configuração e validação. Os dois protocolos permanecem independentes.

Cadastre a URL pública HTTPS `https://<dominio-api>/api/v1/webhooks/hotmart` na Hotmart, selecione Webhook 2.0.0 e os eventos listados abaixo e configure o mesmo HOTTOK. TLS precisa terminar numa infraestrutura confiável. O serviço limita o endpoint a 60 requisições por minuto por IP usando rate limit distribuído no PostgreSQL (compartilhado entre réplicas), valida `Content-Type: application/json` e limita o corpo a 256 KiB. Não há allowlist de IP inventada.

## Eventos e política comercial

A tabela abaixo é a política efetiva do código após a migration `20261031_11`.

| Evento Hotmart | Pedido | Licença existente | Entrega `license_delivery` | Natureza |
| --- | --- | --- | --- | --- |
| `PURCHASE_APPROVED` | `pending` → `paid` | inexistente: cria `pending`; `suspended` temporária: restaura `pending` (nunca ativada) ou `active` (já ativada); `cancelled`/`expired`: não reativa | mantém/permite a entrega existente; cria apenas na primeira aprovação | Concessão |
| `PURCHASE_COMPLETE` | sem concessão de acesso; registra pedido pendente se ainda não existir | não cria | sem nova entrega | Informativo |
| `PURCHASE_BILLET_PRINTED` | sem concessão de acesso; registra pedido pendente se ainda não existir | não cria | sem nova entrega | Informativo |
| `PURCHASE_DELAYED` | `paid` → `pending` quando mais novo/precedente | `pending`/`active` → `suspended`; revoga sessões | permanece na outbox; worker adia enquanto o pedido estiver pendente | Temporário |
| `PURCHASE_CANCELED` | terminal `cancelled` | `cancelled` | cancelada | Terminal |
| `PURCHASE_EXPIRED` | terminal `cancelled` | `cancelled` | cancelada | Terminal |
| `PURCHASE_REFUNDED` | terminal `refunded` | `cancelled` | cancelada | Terminal |
| `PURCHASE_CHARGEBACK` | terminal `chargeback` | `suspended` | cancelada | Terminal/bloqueante |
| `PURCHASE_PROTEST` | terminal `chargeback` | `suspended` | cancelada | Terminal/bloqueante |

### Regras de recuperação

- `PURCHASE_DELAYED` é o único estado temporário. Uma aprovação posterior, quando for mais nova ou tiver precedência maior, restaura a licença:
  - licença nunca ativada (`tenant_id` e `activated_at` nulos): volta para `pending`;
  - licença já ativada: volta para `active`, com `revoked_at` limpo.
- Sessões revogadas durante o atraso **não** são restauradas; o cliente precisa entrar novamente.
- A recuperação só é permitida pelo trigger `guard_license_update()` enquanto o pedido estiver `paid`, no mesmo pedido e provedor. O serviço faz `flush()` do pedido antes de atualizar a licença.
- Estados terminais (`refunded`, `chargeback`, `cancelled`) são irreversíveis automaticamente. Uma aprovação antiga, duplicada ou até mais nova é registrada em `payment_events`, mas não reativa o acesso.
- `PURCHASE_PROTEST` continua mapeado para `chargeback` e não é revertido automaticamente. O adaptador aceita somente os eventos oficiais listados em `HotmartWebhookPayload`; não existe evento de reversão de protesto suportado nesta versão.
- `PURCHASE_COMPLETE` e `PURCHASE_BILLET_PRINTED` nunca criam licença nem concedem acesso.

### Entrega de licença e concorrência

- Em eventos terminais, a mesma transação que invalida a licença cancela `license_delivery` pendente/processing do agregado daquela licença. Mensagens `sent` não são alteradas.
- Em `PURCHASE_DELAYED`, a entrega não é cancelada; o worker a mantém pendente e verifica novamente mais tarde.
- Antes de enviar `license_delivery`, o worker:
  1. mantém a linha da outbox bloqueada com `FOR UPDATE` durante a chamada ao provedor;
  2. lê somente `status`/`order_id` da licença e `status` do pedido, por policies/grants estreitos da migration `20261031_11`;
  3. envia apenas com pedido `paid` e licença `pending`/`active`;
  4. adia com pedido `pending` (atraso), sem consumir tentativa;
  5. cancela quando o pedido/licença está terminal, suspenso, expirado ou ausente.
- Se o provedor já aceitou a mensagem antes do reembolso/chargeback, ela não pode ser recolhida. O backend invalida a licença e a ativação é bloqueada; o registro da outbox permanece `sent` para auditoria. Essa é uma limitação inerente ao provedor.

## Idempotência e transação

O provedor é fixado pelo adaptador como `hotmart`. A unicidade persistente existente de `payment_events(provider, external_event_id)` deduplica eventos; `orders(provider, external_order_id)` associa eventos diferentes à mesma transação; `licenses.order_id` permite no máximo uma licença por pedido. Advisory locks transacionais no PostgreSQL serializam concorrência pelo ID de evento e pela transação, além dessas constraints. A migration `20261031_09` persiste horário do provedor e prioridade para comparação de eventos.

Pedido, atualização de estado, licença, evento financeiro/inbox e e-mail de entrega criptografado são confirmados no mesmo commit. Qualquer erro reverte a transação. O serviço reutiliza `issue_license()` e `enqueue_email()`; não chama o Resend. O comprador recebe a licença pelo e-mail da outbox e acessa a página existente em `/entrar` para ativá-la. Se perdeu o e-mail, pode usar **Recuperar acesso**: informe o e-mail da compra, receba um código de ativação no e-mail original e confirme sem conhecer o código da licença. Se a conta já existe, o fluxo encaminha para redefinição de senha. Detalhes em [support-backoffice.md](support-backoffice.md).

O suporte pode consultar pedidos/licenças/outbox e solicitar instruções de recuperação com justificativa auditada; não pode alterar valores nem reativar licença. O endpoint responde sucesso somente depois do commit. Duplicatas válidas e produtos não configurados retornam `200` sem repetir efeitos; erro de autenticação retorna `401`, tipo de conteúdo incorreto `415`, payload inválido `400`, corpo grande `413`, configuração ausente `503` e falha transitória de persistência `503` para permitir nova entrega. A Hotmart informa que posts com erro são reenviados automaticamente até cinco vezes ou até uma resposta positiva; o histórico permite reenvio manual e mantém eventos por até 60 dias. Após corrigir a causa, confira também se a configuração do webhook continua ativa. Veja [a orientação de suporte Hotmart sobre tentativas e histórico](https://suportehotmart.zendesk.com/hc/pt-br/articles/360001491352-Como-configurar-a-API-do-meu-produto-usando-o-Webhook-Postback). O código não armazena conteúdo integral do webhook; guarda apenas hash, IDs, tipo, data e vínculo normalizado ao pedido. Dados pessoais necessários ficam cifrados/hashados como no fluxo comercial existente.

## RLS e papéis

O processamento usa o papel operacional atual sem `SUPERUSER` ou `BYPASSRLS`, contexto de provedor fixado em `hotmart` e o `payment_order_id` existente para as operações da licença. Não há policy nova, bypass de RLS ou concessão de papel. A tabela de eventos continua com RLS/FORCE RLS e a policy por provedor. O contexto GUC é escopo funcional das policies, não uma barreira contra SQL arbitrário com as credenciais da aplicação.

## Diagnóstico

Logs indicam apenas falha genérica do evento Hotmart ou produto não configurado; não incluem HOTTOK, payload, comprador, documento, licença ou dados de pagamento. Consulte os logs da API e o estado de `payment_events`/`orders` com acesso administrativo de banco. `payload_hash` serve para correlação de integridade, não para reconstrução do evento. Uma falha `503` pode ser reenviada pela Hotmart; a mesma notificação é segura por idempotência.

## Testes e implantação

Os fixtures usam dados inteiramente fictícios em `backend/tests/unit/test_hotmart_payload.py`; os testes PostgreSQL cobrem emissão, idempotência, concorrência, rollback e evento fora de ordem. Use somente o perfil descartável:

```sh
docker compose --profile tests up -d test-db
docker compose --profile tests run --build --rm tests
docker compose --profile tests down
```

Para enviar manualmente um fixture fictício a uma API local já iniciada e configurada com o UCODE e produto de teste correspondentes:

```sh
curl --request POST \
  --url http://localhost:8010/api/v1/webhooks/hotmart \
  --header "X-HOTMART-HOTTOK: ${HOTMART_WEBHOOK_HOTTOK:?configure um HOTTOK somente local}" \
  --header 'Content-Type: application/json' \
  --data-binary @backend/tests/fixtures/hotmart/purchase_approved_v2.json
```

O JSON usa UCODE, transação e comprador de teste sem valor comercial; configure esse UCODE fictício somente no ambiente de desenvolvimento. Não envie o fixture a um endpoint de produção.

Em ambiente real, inclua a migration no processo padrão de migrations e configure as quatro variáveis na infraestrutura de segredos antes de definir `HOTMART_ENABLED=true`. Execute `python -m app.cli.preflight --stage environment`, as migrations, `python -m app.cli.preflight --stage database`, o provisionamento do produto com `--apply` e `python -m app.cli.preflight --stage commercial`. Só então habilite a integração. Depois, use uma notificação de teste documentada pela Hotmart/homologação, nunca uma compra real para validar o deploy. Não execute testes contra o serviço `db` ou o banco comercial.

## Reconciliação

A Missão 11 adicionou logging seguro: falhas do webhook registram tipo/categoria e request ID, sem HOTTOK, payload, comprador ou resposta completa. A Missão 08 adicionou uma CLI operacional de reconciliação, independente deste endpoint público. Ela consulta somente `GET /sales/history?transaction=...` para pedidos locais conhecidos, compara o estado remoto com `orders`/`licenses` e aplica apenas transições seguras usando as mesmas regras de aprovação/terminal. O dry-run é o padrão, o webhook continua sendo o caminho principal e nenhuma transação desconhecida cria pedido, licença ou entrega. Detalhes em [hotmart-reconciliation.md](hotmart-reconciliation.md).

## Limitações

O estado em produção continua sendo derivado prioritariamente dos webhooks autenticados e dos timestamps que eles fornecem; a reconciliação é complementar e não substitui a homologação real. Eventos terminais e de protesto/chargeback nunca reativam automaticamente uma licença; isso requer revisão. `PURCHASE_DELAYED` é temporário e uma aprovação posterior mais nova recupera a licença, mas não restaura sessões revogadas. O UCODE deve ser fornecido pelo operador no ambiente. A entrega de e-mail continua assíncrona pela outbox; um webhook confirmado não significa entrega imediata do e-mail. Uma mensagem já aceita pelo provedor não pode ser recolhida, mesmo que o reembolso chegue depois; nesse caso a licença é invalidada e a ativação é bloqueada. Os valores `provider_*` registram o que o webhook informou e não substituem conciliação financeira com a Hotmart.
