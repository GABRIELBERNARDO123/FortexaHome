# Outbox transacional de e-mails

## Fluxo e estados

Ativação/verificação, redefinição de senha e entrega de licença são registradas na tabela `email_outbox` dentro da mesma transação PostgreSQL que cria/atualiza o desafio, token, licença, pedido e evento de pagamento correspondente. A API não chama Resend. Só responde após o commit; `202` confirma persistência da solicitação, não entrega da mensagem.

Estados:

- `pending`: aguardando `next_attempt_at`.
- `processing`: reivindicada por um worker até `lease_until`.
- `sent`: o adaptador confirmou a aceitação; em produção é a resposta de sucesso do Resend, enquanto o sink `dev` apenas simula aceitação e descarta a mensagem. O payload cifrado é apagado.
- `dead`: erro permanente ou limite de tentativas; payload permanece cifrado durante a janela operacional de recuperação.
- `cancelled`: evento obsoleto/expirado; payload apagado.

O worker reivindica em lotes com `SELECT ... FOR UPDATE SKIP LOCKED`, incrementa tentativas e grava lease na mesma transação. Depois do commit da reivindicação, descriptografa o payload, confere expiração e, para redefinição de senha, consulta sob RLS apenas `id`, `used_at` e `expires_at` do token associado antes de enviar. O papel worker não pode ler o hash nem outros dados da tabela de tokens. Um lease expirado permite reprocessar uma mensagem abandonada. O worker não inicia FastAPI nem outro servidor HTTP; encerra ao receber SIGTERM/SIGINT e mensagens reivindicadas ficam recuperáveis após o lease.

## Cancelamento e revalidação de `license_delivery`

A migration `20261031_11` adiciona policies estreitas para o ciclo de vida da entrega de licença. A migration `20261031_12` acrescenta `license_recovery_instructions`, usado pelo backoffice para enviar orientações de recuperação sem revelar o código da licença:

- a API operacional pode ler/cancelar apenas `license_delivery` do `aggregate_id` igual à licença atual em `app.outbox_license_id`; não vê payload;
- o worker pode ler somente `licenses(status, order_id)` e `orders(id, provider, status)`, por `app.outbox_license_id`/`app.outbox_order_id`; não lê PII, código de licença ou e-mail do comprador.

Quando um evento Hotmart terminal (`REFUNDED`, `CHARGEBACK`, `PROTEST`, `CANCELED`, `EXPIRED`) invalida a licença, a mesma transação cancela `license_delivery` pendente ou `processing` daquele agregado. `sent` e `dead` não são alterados. O cancelamento limpa o payload, zera claim/lease e grava `last_error` (`license_revoked`/`license_suspended`), preservando a linha para auditoria.

`PURCHASE_DELAYED` é temporário: a mensagem permanece na outbox e o worker a adia (`last_error=license_pending`) sem consumir tentativa. Uma aprovação posterior recupera a licença e a mensagem volta a ser elegível. `requeue_dead` também revalida licença/pedido e recusa reabrir uma entrega que não seja mais entregável.

Antes de enviar, o worker mantém a linha da outbox bloqueada com `FOR UPDATE` e revalida licença/pedido:

- pedido `paid` + licença `pending`/`active`: envia;
- pedido `pending`: adia;
- pedido terminal, licença `cancelled`/`expired`/`suspended`, licença/pedido ausente: cancela sem chamar o provedor.

O lock permanece durante a chamada ao provedor. Se um reembolso concorrente ganhar o lock antes, a mensagem já estará `cancelled` e não é enviada. Se o worker ganhar o lock e o provedor aceitar a mensagem, o reembolso espera e depois invalida a licença; a mensagem permanece `sent` e não pode ser recolhida. A ativação é bloqueada pela licença inválida. Essa é a limitação de entrega já aceita pelo provedor, não uma reabertura de mensagem cancelada.

## Conteúdo, privacidade e retenção

O JSON contendo destinatário e variáveis de template é cifrado por AES-GCM pela função `encrypt_text` existente, com chave `PII_ENCRYPTION_KEY` e contexto de campo específico. Códigos, tokens, endereços e códigos de licença não são gravados em claro. Logs contêm apenas contagens de estados e categorias de falha sanitizadas; o logger central remove destinatários, códigos, tokens, payloads e segredos antes da emissão (Missão 11). O Resend recebe o conteúdo necessário para envio, mas ele não é incluído nos logs da aplicação.

Sucesso, cancelamento e expiração eliminam o payload. Falhas transitórias e mensagens `dead` preservam o payload cifrado; para `dead`, o worker o apaga após `OUTBOX_DEAD_PAYLOAD_RETENTION_DAYS` (padrão 30 dias). Linhas sem payload permanecem para auditoria operacional; definir limpeza periódica das linhas conforme política local. A recuperação é explícita e só pode ser iniciada por quem tem autorização administrativa no host para executar comandos Docker: `docker compose exec email-worker python -m app.workers.email_outbox --requeue-dead UUID`. Não existe endpoint público para re-enfileirar mensagens. A auditoria grava o UUID da mensagem na própria linha, a data e o principal PostgreSQL autenticado (`OUTBOX_DB_USER`); esse principal identifica o serviço worker, não a pessoa que usou Docker. A identidade humana depende dos controles e logs de acesso ao host/Docker. A operação preserva a chave de idempotência e o contador acumulado, concede apenas um orçamento adicional de `OUTBOX_MAX_ATTEMPTS` e só pode ser feita uma vez por evento. Tokens expirados ou já usados são recusados; mensagens de ativação `dead` não são re-enfileiradas, pois a recuperação deve gerar um novo código. Após a retenção, payload ausente também impede a recuperação. Mensagens `dead` não são reenviadas automaticamente. Uma reexecução manual pode duplicar se o provedor já tiver aceitado a mensagem fora da janela de idempotência; confira o painel do Resend antes de recuperar quando o resultado for incerto.

## Retentativas e semântica de entrega

Falhas transitórias (rede, timeout, HTTP 408/425/429 e 5xx) usam backoff exponencial com jitter, limitado por `OUTBOX_RETRY_MAX_SECONDS`. Do Resend, 409 `concurrent_idempotent_requests` é transitório; 409 `invalid_idempotent_request` (mesma chave com payload diferente) é permanente e vai para `dead`. Outros 409 sem código reconhecido também são tratados como permanentes. `OUTBOX_MAX_ATTEMPTS` limita retries; o worker nunca deixa uma mensagem indefinidamente em `processing`.

O adaptador HTTP envia `Idempotency-Key` estável por evento e cada retry usa a mesma chave e payload. A [documentação oficial do Resend](https://resend.com/changelog/idempotency-keys) informa retenção de chaves por 24 horas. Dentro da janela, 409 `concurrent_idempotent_requests` pode ser tentado novamente com a mesma chave; 409 `invalid_idempotent_request` indica payload diferente e não é repetido. Depois de 24 horas, o Resend pode não reconhecer a chave antiga, portanto um retry pode enviar novamente. Idempotência reduz duplicatas, mas não garante entrega exatamente uma vez: se o provedor aceitar o e-mail e o processo cair antes de gravar `sent`, um retry após a janela pode duplicar. Também não é possível recolher uma mensagem cujo envio já começou quando um evento é substituído; eventos ainda na fila/lease são cancelados e rechecados antes do envio.

Para ativações, reenvio, substituição e confirmação cancelam os eventos anteriores na mesma transação que altera o desafio. O worker também verifica `expires_at` antes do envio; códigos expirados ou substituídos não saem da fila quando a obsolescência já foi persistida antes da chamada ao provedor.

## PostgreSQL, RLS e papéis

A migration `20261031_06` habilita e força RLS em `email_outbox`. O papel operacional pode inserir mensagens e cancelar somente mensagens de verificação vinculadas ao UUID indicado no contexto de ativação; só recebe leitura de metadados necessários a esse `UPDATE`, nunca do payload. O papel `OUTBOX_DB_USER` recebe `SELECT`/`UPDATE` apenas em `email_outbox`, sem `SUPERUSER`, `BYPASSRLS`, `INHERIT`, ou grants nas tabelas de contas, licenças, pedidos e pagamentos. A criação/ajuste do papel requer que o usuário de migrations possa criar roles e conceder privilégios.

O worker lê payload cifrado e precisa de `PII_ENCRYPTION_KEY` para descriptografá-lo, mas não acessa as tabelas comerciais. O papel de worker usa o mesmo host/banco configurado em `DATABASE_URL`, com usuário e senha próprios (`OUTBOX_DB_USER` e `OUTBOX_DB_PASSWORD`). A separação de identidade reduz privilégios, mas não torna o GUC uma barreira contra SQL arbitrário executado com as credenciais operacionais.

## Configuração e operação

Configure no ambiente:

- `EMAIL_PROVIDER=resend`, `RESEND_API_KEY` e `EMAIL_FROM` de domínio verificado em produção.
- `OUTBOX_DB_USER` e `OUTBOX_DB_PASSWORD`, credenciais exclusivas do worker; em produção use ao menos 32 caracteres aleatórios em formato hex/base64url, para que a URL PostgreSQL do Compose não precise de senha em claro com escape manual.
- `OUTBOX_POLL_SECONDS` (padrão 2), `OUTBOX_BATCH_SIZE` (10), `OUTBOX_LEASE_SECONDS` (60), `OUTBOX_MAX_ATTEMPTS` (8), `OUTBOX_RETRY_BASE_SECONDS` (5), `OUTBOX_RETRY_MAX_SECONDS` (900), `OUTBOX_DEAD_PAYLOAD_RETENTION_DAYS` (30) e `OUTBOX_STATUS_LOG_SECONDS` (60).
- `PII_ENCRYPTION_KEY` compartilhada com a API, usada para cifrar e ler payloads.

`OUTBOX_DB_PASSWORD` precisa ser configurada também quando a migration é executada, pois ela cria ou reconcilia o papel do worker. O `.env.example` contém apenas marcadores; não use esse arquivo como fonte de credenciais reais.

Após preencher o ambiente operacional conforme os procedimentos locais, os comandos são:

```sh
docker compose run --rm migrate
docker compose up -d email-worker
docker compose ps email-worker
docker compose logs --tail=100 email-worker
docker compose stop email-worker
EVENT_UUID="00000000-0000-0000-0000-000000000000" # substitua pelo UUID revisado
docker compose exec email-worker python -m app.workers.email_outbox --requeue-dead "$EVENT_UUID"
```

Para validar o Compose e construir sem iniciar os serviços operacionais, use o perfil descartável de testes:

```sh
docker compose --env-file .env.example --profile tests build tests
docker compose --env-file .env.example --profile tests run --build --rm tests
```

O healthcheck executa `python -m app.workers.email_outbox --check`, verifica identidade/acesso ao banco e exige heartbeat atualizado do loop principal (janela máxima de 3 minutos). `restart: unless-stopped` reinicia o container se o processo terminar. A cada `OUTBOX_STATUS_LOG_SECONDS` (padrão 60), logs agregados informam pendentes, processing, leases vencidos, dead, idade da pendente mais antiga e falhas recentes do provedor. Encaminhe esses logs para alertas operacionais de worker unhealthy, fila/idade crescentes, leases vencidos ou dead/falhas recorrentes. Os logs não contêm payload, destinatário, código, token ou credencial. O worker não oferece interface de monitoramento HTTP.

## Testes e migrações

Os testes de isolamento, transações e locks usam PostgreSQL real isolado e os papéis de teste não privilegiados definidos pelo perfil `tests` do Compose. Não use SQLite para validar RLS, leases ou `SKIP LOCKED`.

```sh
docker compose --env-file .env.example --profile tests run --build --rm tests
docker compose --env-file .env.example --profile tests run --rm tests alembic heads
docker compose --env-file .env.example --profile tests build tests
```

Consulte o head atual com `alembic heads`; a cadeia vigente termina em `20261102_16` nesta revisão. Downgrade dessas migrations remove campos de auditoria e as políticas de cancelamento/consulta de status; o downgrade de `20261031_06` também remove todos os registros e o papel dedicado, portanto qualquer downgrade é apenas para banco descartável e não deve ser executado em produção.
