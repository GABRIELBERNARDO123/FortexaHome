# Testes do backend

## Suíte unitária

No diretório `backend`, instale `requirements-test.txt` em um ambiente virtual e execute:

```sh
pytest --cov=app --cov-report=term-missing
```

Os testes em `tests/unit` não precisam de PostgreSQL. Os testes de integração ficam em `tests/integration` e são ignorados sem `--run-integration`.

## PostgreSQL isolado e RLS

Na raiz `fortexahome`, execute a suíte integrada no serviço PostgreSQL descartável do Compose:

```sh
docker compose --profile tests run --build --rm tests
```

O banco de testes usa o nome fixo `fortexahome_test`, não publica porta no host e é criado sem volume persistente. O serviço executa testes unitários, testes PostgreSQL e cobertura. A fixture exige host local (`test-db`, loopback), nome de banco exato, papéis distintos de runtime e migrations, e que a URL operacional seja idêntica a `TEST_DATABASE_URL`; também confirma que o papel operacional não tem `SUPERUSER` nem `BYPASSRLS` antes de executar `alembic upgrade head`. Os testes usam transações revertidas para isolar seus dados. Não configure as URLs de teste para apontar a outro banco.

Para executar contra um PostgreSQL de teste gerenciado localmente, configure `DATABASE_URL` e `TEST_DATABASE_URL` com a mesma conexão de runtime limitada, e `MIGRATION_DATABASE_URL` e `TEST_MIGRATION_DATABASE_URL` com a conexão de migrations. Todas as URLs precisam apontar para `fortexahome_test`. Crie previamente um papel runtime sem `SUPERUSER` e sem `BYPASSRLS`, com as grants das migrations, e não reutilize credenciais de produção.

## Proxy confiável

O Compose atribui `172.31.0.10` ao frontend Nginx e restringe a rede `fortexahome_net` a `172.31.0.0/24`; a API confia somente no IP fixo do Nginx configurado no exemplo. O Nginx sobrescreve `X-Real-IP` e `X-Forwarded-For` com `$remote_addr`. A topologia externa de produção não está descrita neste repositório. Se existir um proxy externo, configure no Nginx `set_real_ip_from` somente com os CIDRs confirmados desse proxy, `real_ip_header X-Forwarded-For` e `real_ip_recursive on`; então o Nginx pode enviar o endereço já resolvido à API. Sem essa configuração, a API verá o endereço do proxy externo e o rate limit será compartilhado por seus visitantes. Não invente ou confie em redes privadas inteiras.

## Migration corretiva de licenças

A migration `20261031_04` prende leitura e atualização por pedido tanto ao ID quanto ao provedor visível sob RLS. Um trigger permite ativação somente da licença não vinculada com contexto de código e tenant, ou revogação somente de status/data de revogação quando o pedido e o provedor correspondem. A revogação não pode mudar tenant, e-mail vinculado, produto ou pedido.

O downgrade para `20261031_03` remove o trigger e restaura as policies antigas que verificavam apenas `payment_order_id`. Isso perde o escopo por provedor e a separação entre alteração de vínculo e revogação. O teste de integração demonstra essa diferença e reaplica `head` no banco descartável; nunca use esse downgrade em produção.

## Preflight e catálogo administrativo

Os comandos administrativos usam o mesmo `Settings` e a mesma sessão SQLAlchemy da aplicação:

```sh
python -m app.cli.preflight --stage environment
python -m app.cli.preflight --stage database
python -m app.cli.preflight --stage commercial
python -m app.cli.provision_product --help
```

Os testes unitários de preflight não precisam de PostgreSQL. Os testes de catálogo e de preflight de banco são integração e usam o banco descartável do perfil `tests`:

```sh
docker compose --env-file .env.example --profile tests run --build --rm tests
```

Arquivos relevantes:

- `tests/unit/test_preflight.py` — validações de ambiente, credenciais e Hotmart.
- `tests/unit/test_product_schema.py` — validação do schema de provisionamento.
- `tests/integration/test_catalog_provisioning.py` — idempotência, atualização, RLS, permissões, dry-run e rollback.
- `tests/integration/test_preflight_database.py` — papel, head Alembic, permissões, RLS e catálogo comercial.

O procedimento operacional completo está em [production-preflight.md](production-preflight.md). Nunca use o `.env.example` como ambiente real.

## Ciclo de vida comercial e entrega

A missão 03 adicionou testes PostgreSQL reais para a máquina de estados Hotmart e o ciclo de entrega:

- `tests/integration/test_hotmart_integration.py` — atraso seguido de aprovação, atraso antigo, recuperação de licença ativada/não ativada, precedência por timestamp, eventos terminais mais novos, concorrência aprovação/reembolso/chargeback/cancelamento, cancelamento de `license_delivery`, reembolso repetido, worker reservando mensagem, worker enviando enquanto o reembolso chega, licença cancelada bloqueando ativação e isolamento de outros pedidos/reset.
- `tests/integration/test_email_outbox.py` — cancelamento escopado de `license_delivery`, preservação de `sent`, worker cancelando pedido não pago/licença ausente, worker adiando pedido pendente e acesso restrito do worker aos estados de licença/pedido.
- `tests/integration/test_postgres_rls.py` — downgrade/upgrade da migration `20261031_11`, policies de entrega, grants de coluna do worker e trigger de recuperação.
- `tests/unit/test_hotmart_payload.py` — rejeição de `creation_date` ausente.

A migration `20261031_11` altera policies/grants e o trigger `guard_license_update()`; não cria tabelas nem colunas. O teste de downgrade/upgrade usa banco descartável; nunca execute esse downgrade em produção.

## Recuperação de licença e backoffice

Adicionados testes PostgreSQL reais:

- `tests/integration/test_license_recovery.py` — compra paga não ativada, e-mail desconhecido sem enumeração, usuário existente recebendo reset de senha, pedidos terminais/suspensos, cooldown por e-mail e criação única de tenant.
- `tests/integration/test_support_backoffice.py` — login de operador, lockout, cookie separado do cliente, leitura por `support_read`, ação proibida para leitura, ação auditada/idempotente, justificativa obrigatória, pedido terminal, PII mascarada, filtros/paginação, auditoria append-only e provisionamento/desativação de operador.
- `tests/integration/test_postgres_rls.py` — downgrade/upgrade da migration `20261031_12`, tabelas/policies de suporte e preservação da migration anterior.

O backoffice não expõe payload de outbox, hashes de licença ou credenciais. O head atual é `20261104_18`. Para provisionar um operador:

```sh
python -m app.cli.provision_support_operator --email operador@example.com \
  --name "Operador" --role support_read --password-stdin --apply
```

Consulte [support-backoffice.md](support-backoffice.md).

## Domínio financeiro (Missão 05)

`tests/integration/test_financial_domain.py` cobre, via API e PostgreSQL real:

- lançamentos: CRUD, filtros, busca, paginação, resumo, valores inválidos, categoria/cartão incompatíveis;
- contas: CRUD, pagar, desfazer, recorrência e bloqueio de alteração de conta paga;
- cartões: CRUD, gasto, limite disponível e arquivamento;
- orçamentos: CRUD, duplicidade, cálculo de consumo e categoria de despesa;
- metas: CRUD, aportes, retiradas, conclusão, reabertura e histórico;
- dashboard, relatórios, CSV, exportação e atualização de conta;
- isolamento entre dois tenants via cookies/API;
- concorrência real: duas retiradas de meta não deixam saldo negativo; dois pagamentos da mesma conta geram apenas uma transação.

Cobertura backend atual: **85%**. O head vigente é `20261104_18`.

## E2E (Missão 05)

Playwright + Chromium, ambiente Compose próprio. Consulte [e2e-testing.md](e2e-testing.md).

```sh
cd frontend
npm run test:e2e
```

31 cenários cobrem cliente, ativação, recuperação, CRUD financeiro, idempotência financeira, categorias, backoffice, suporte, segurança de sessão e responsividade. Falhas geram screenshots/traces em `frontend/test-results`.


## Gestão de categorias (Missão 06)

Adicionados testes PostgreSQL/API em `tests/integration/test_financial_domain.py`:

- CRUD de categoria, duplicidade case-insensitive e edição de nome/cor/ícone;
- contagem de uso em lançamentos, contas e orçamentos;
- arquivamento/reativação de categoria personalizada e proteção de categoria padrão;
- bloqueio de exclusão de categoria em uso e de uso de categoria arquivada em novos registros;
- preservação de histórico: edição de lançamento, pagamento de conta e recorrência com categoria arquivada;
- autorização owner/member e isolamento entre tenants;
- migration `20261031_10 → head` com verificação de `categories.archived` no teste de downgrade/upgrade.

O E2E `frontend/e2e/categories-management.spec.ts` cobre criação, edição, duplicidade, arquivamento, reativação, exclusão, categoria em uso, member somente leitura e isolamento entre tenants. A responsividade da página também é verificada em `responsive.spec.ts`.

Resultado na Missão 06: **206 testes backend aprovados**, cobertura **86%**, **5 testes de componentes** e **28 E2E Playwright aprovados**. Head Alembic daquela missão: `20261101_13`.


## Rate limit distribuído (Missão 07)

Testes unitários (`tests/unit/test_rate_limit.py`):

- IP real e rejeição de cabeçalhos forjados fora de proxies confiáveis;
- parsing de limites, HMAC com escopo/tipo e ausência de identificador em claro;
- combinação de IP + e-mail normalizado;
- 429 com `Retry-After`, bypass quando desabilitado e fail-open quando o storage falha.

Testes de integração PostgreSQL (`tests/integration/test_rate_limit_distributed.py`):

- 20 requisições concorrentes contra 5 tokens: exatamente 5 permitidas;
- isolamento entre chaves/escorpos e recarga após a janela;
- dois clientes API compartilhando o mesmo limite;
- login real retornando 429 com `Retry-After`;
- contexto RLS preservado após o commit intermediário do limiter (coberto pelos fluxos de suporte).

`tests/integration/test_postgres_rls.py` valida as migrations de rate limit/reconciliação, as tabelas, os privilégios do papel operacional e a ausência de acesso do worker. `tests/integration/test_rate_limit_route_coverage.py` valida a matriz de políticas e 429 real de suporte/webhook com PostgreSQL.

Resultado na Missão 07: **217 testes backend aprovados** (71 unitários + 146 integração), cobertura **85%**; `core/rate_limit.py` com **82%**. Head Alembic daquela missão: `20261102_14`.


## Reconciliação Hotmart (Missão 08)

Testes unitários (`tests/unit/test_hotmart_api_client.py`, `tests/unit/test_reconcile_hotmart_cli.py`):

- OAuth: token cacheado, renovação em 401, 403 não recuperável, credenciais ausentes, URL de sandbox/produção;
- HTTP: timeout, 429 com `Retry-After`, 5xx, backoff/limite, resposta malformada, transação inexistente e estados conflitantes;
- parsing mínimo de `sales/history` (produto, status, datas e preço), sem persistir comprador;
- decisões conservadoras para APPROVED, terminais, informativos, BLOCKED, PARTIALLY_REFUNDED, NO_FUNDS e desconhecidos;
- CLI: dry-run padrão, `--apply`, limites, JSON, feature desabilitada e credenciais ausentes.

Testes de integração PostgreSQL (`tests/integration/test_hotmart_reconciliation.py`):

- aprovação perdida cria licença/entrega a partir de pedido local;
- aprovação restaura licença temporariamente suspensa;
- reembolso/chargeback/protesto/cancelamento/expirado aplicam transição terminal e cancelam entrega;
- terminal local não é reaberto por aprovação remota;
- dry-run não altera estado comercial;
- pedido local inexistente nunca é criado;
- produto divergente exige análise manual;
- erro de API não altera estado;
- reprocessamento idempotente não duplica licença/entrega;
- observação stale não sobrescreve webhook mais novo;
- duas reconciliações concorrentes produzem um único efeito comercial;
- migration 15 e privilégios append-only/worker sem acesso.

Resultado na Missão 08/complemento: **281 testes backend aprovados** (110 unitários + 171 integração), cobertura **85%**; `hotmart_api.py` **78%**, `hotmart_reconciliation_service.py` **79%**, `reconcile_hotmart.py` **84%**. Head Alembic daquela missão: `20261102_15`.


## Lockout progressivo por conta (Missão 09)

Testes PostgreSQL reais em `tests/integration/test_login_lockout.py`:

- quinta falha bloqueia a conta e retorna 429 com `Retry-After`;
- senha correta não ignora lockout ativo;
- expiração automática permite novo login;
- login válido reseta contador e lock;
- e-mail inexistente recebe o mesmo lockout, sem enumeração;
- dez falhas concorrentes são contabilizadas atomicamente;
- cooldown máximo e contador limitado;
- auditoria `LOGIN_FAILED`, `LOGIN_LOCKED` e `LOGIN_SUCCESS`;
- HMAC sem e-mail em claro.

O teste existente de rate limit por IP foi ajustado para usar e-mails distintos por tentativa, mantendo a verificação do bucket de IP sem misturar o lockout por identidade.

Resultado atual: **301 testes backend aprovados** (122 unitários + 179 integração), cobertura **85%**; `login_lockout_service.py` **75%**, `auth_service.py` **79%**. Head Alembic: `20261102_16`.

## Hardening de rotas legadas e logs (Missão 11)

- `tests/unit/test_sandbox_route_registration.py`: conjunto de rotas em produção, ausência de `hmac_sandbox` e resposta 404.
- `tests/unit/test_log_safety.py`: redaction textual/recursiva, valores entre aspas com espaços, headers `Authorization`/`Cookie`, exceções, request ID e isolamento entre threads.
- `tests/integration/test_logging_redaction.py`: exceção real via TestClient, `IntegrityError`, logs capturados sem PII/segredo, resposta genérica, correlação por request ID e erro de validação.
- `tests/unit/test_preflight.py`: rejeição de sandbox/log DEBUG em produção.

Resultado atual: **301 testes backend aprovados**, cobertura **85%**; `core/log_safety.py` **94%** e `main.py` **89%**. Head Alembic: `20261102_16`.

## Idempotência financeira (Missão 12)

Testes adicionados:

- `tests/unit/test_idempotency.py` — validação de `Idempotency-Key` e fingerprint canônico.
- `tests/integration/test_financial_idempotency.py` — replay, conflito `409`, rollback antes do commit, chaves diferentes, chaves iguais em tenants/usuários diferentes, 10 requisições concorrentes em pagamento e aporte, pagamento/desfazer, orçamento e recorrência.
- `tests/integration/test_postgres_rls.py` — migration `20261104_17`, tabela `idempotency_records`, FORCE RLS, DML da API e ausência de acesso do worker.
- `frontend/src/test/idempotency.test.ts` — geração e envio da chave.
- `frontend/e2e/idempotency.spec.ts` — retry de lançamento, pagamento e aporte, conflito, refresh e nova operação com nova chave.

Resultado atual: **319 testes backend aprovados** (129 unitários + 190 integração), cobertura **85%**; `idempotency_service.py` **83%**, `models/idempotency.py` **100%**. Frontend: **7 testes**; E2E: **31 aprovados**. Head Alembic: `20261104_17`.

Consulte [financial-idempotency.md](financial-idempotency.md).

## Privacidade, exclusão e retenção (Missão 13)

Testes adicionados:

- `tests/integration/test_privacy_lifecycle.py` — member anonimizado sem apagar finanças do tenant; owner único com exclusão financeira e anonimização comercial; owner compartilhado em `awaiting_review`; aprovação/rejeição do suporte; outbox cancelada; idempotência/lockout removidos; isolamento entre tenants; cancelamento; reaplicação de tombstone após restore simulado.
- `tests/integration/test_postgres_rls.py` — migration `20261104_18`, tabelas `privacy_requests`, `privacy_request_events` e `data_deletion_tombstones`, FORCE RLS, políticas e worker sem acesso.
- `tests/integration/test_rate_limit_route_coverage.py` — política da rota `POST /privacy/requests`.
- `frontend/e2e/privacy-lifecycle.spec.ts` — privacidade no desktop/mobile, senha incorreta, member com exclusão, owner compartilhado, aprovação do suporte, sessão revogada e login posterior bloqueado.

Resultado atual: **325 testes backend aprovados** (129 unitários + 196 integração), cobertura **85%**. Frontend: **7 testes**; E2E: **33 aprovados**. Head Alembic: `20261104_18`.

Consulte [lgpd-data-lifecycle.md](lgpd-data-lifecycle.md), [data-subject-request-sop.md](data-subject-request-sop.md) e [data-retention-matrix.md](data-retention-matrix.md).

## Preparação de release (Missão 14)

Regressão final do release candidate:

- Backend: **325 aprovados**, cobertura **85%**.
- Frontend: **7 testes**, TypeScript e build Vite aprovados.
- E2E: **33 aprovados**.
- Alembic head: `20261104_18`.
- Preflight environment: `OK=25 WARN=0 FAIL=0 SKIP=2`.
- Preflight database: `OK=8 WARN=0 FAIL=0 SKIP=0`.
- Preflight commercial: `OK=0 WARN=0 FAIL=0 SKIP=1` (Hotmart desabilitada).
- Worker: startup, heartbeat, `--check`, processamento em provider dev e shutdown gracioso.
- Backup/restore: drill em PostgreSQL descartável, restore em 2,12 s, RLS/roles/migrations verificados e tombstone pós-cópia reaplicado.

Consulte [release-runbook.md](release-runbook.md), [backup-restore-runbook.md](backup-restore-runbook.md), [prelaunch-checklist.md](prelaunch-checklist.md) e [external-validation-matrix.md](external-validation-matrix.md).
