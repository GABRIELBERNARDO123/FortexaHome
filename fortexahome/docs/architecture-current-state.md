# FortexaHome — Arquitetura do estado atual

Referência objetiva do código existente na branch `release/fortexahome-launch`. A fonte da verdade são os arquivos citados; este documento não substitui as migrations nem os testes.

## 1. Visão geral

FortexaHome é uma aplicação de gestão financeira doméstica multi-tenant:

- `backend/app` — API FastAPI, serviços, modelos SQLAlchemy, integrações de pagamento e worker de e-mail.
- `backend/migrations` — Alembic/PostgreSQL, incluindo RLS, gatilhos e papéis.
- `frontend/src` — React + Vite + TypeScript.
- `docker-compose.yml` — PostgreSQL, migrations, API, worker de e-mail e Nginx.

O acesso comercial é vendido por licença. A compra aprovada gera licença e e-mail de entrega; o comprador ativa a licença, confirma o e-mail e recebe uma sessão.

## 2. Módulos principais

| Módulo | Caminho | Responsabilidade |
| --- | --- | --- |
| Entrada HTTP | `backend/app/main.py` | Middleware de segurança, CORS, rate limit, cabeçalhos, tratamento de erros. |
| Rotas | `backend/app/api/v1/router.py`, `backend/app/api/v1/endpoints/` | Endpoints de auth, dados financeiros, licença, webhooks. |
| Contexto RLS | `backend/app/core/database.py` | `set_db_context()` grava GUCs `app.*` na transação. |
| Configuração | `backend/app/core/config.py` | Validação de segredos, produção, Hotmart, outbox e proxy. |
| Criptografia/PII | `backend/app/core/field_encryption.py` | AES-GCM para PII, HMAC para e-mail, licença e códigos. |
| Autenticação | `backend/app/services/auth_service.py` | Login, logout, sessões, senha, reset. |
| Ativação | `backend/app/services/activation_service.py` | Desafio de ativação, código de e-mail, criação de tenant/usuário/licença. |
| Licenças/comercial | `backend/app/services/license_service.py` | Produto, pedido, licença, eventos Hotmart. |
| Outbox | `backend/app/services/email_outbox_service.py` | Enfileiramento, claim, envio, retry, cancelamento, requeue. |
| Worker | `backend/app/workers/email_outbox.py` | Loop independente com papel PostgreSQL próprio. |
| E-mail | `backend/app/services/email_service.py` | Renderização e adaptador Resend. |
| Integrações | `backend/app/integrations/payments/` | `hmac_sandbox` somente fora de produção quando habilitado, `hotmart`, contrato base. |
| Operação/preflight | `backend/app/core/preflight.py`, `backend/app/cli/` | Preflight de ambiente/banco/comercial, provisionamento idempotente do catálogo e de operadores de suporte. |
| Suporte/backoffice | `backend/app/services/support_service.py`, `backend/app/api/v1/endpoints/support.py`, `frontend/src/pages/support/` | Identidade administrativa separada, recuperação de licença e console de pedidos/licenças/outbox. |
| Qualidade/E2E | `backend/tests/`, `frontend/e2e/`, `docker-compose.e2e.yml`, `frontend/playwright.config.ts` | Suíte financeira/categorias/rate limit/reconciliação PostgreSQL/API e Playwright isolado para cliente, financeiro, categorias, backoffice e responsividade. |

## 3. Banco de dados e migrations

Ordem real (`alembic`):

1. `097fe0849068_initial_schema.py` — schema inicial (tenants, usuários, finanças, produtos, pedidos, licenças, sessões, reset).
2. `20261026_01_row_level_security.py` — RLS/FORCE RLS nas tabelas por tenant.
3. `20261026_02_licenses_rls.py` — RLS específica de licenças.
4. `20261031_03_commerce_rls.py` — RLS de `products`, `orders`, `payment_events`, escopo por provedor.
5. `20261031_04_license_provider_guard.py` — policies por pedido/provedor e trigger `guard_license_update()`.
6. `20261031_05_email_activation.py` — `pending_activations` e fluxo de ativação por código.
7. `20261031_06_transactional_email_outbox.py` — `email_outbox` cifrada, papel `OUTBOX_DB_USER`, policies e grants.
8. `20261031_07_outbox_audit_reset_lifecycle.py` — auditoria/requeue e validação de reset antes do envio.
9. `20261031_08_outbox_reset_cancel_visibility.py` — metadados mínimos de reset visíveis à aplicação.
10. `20261031_09_hotmart_event_ordering.py` — `provider_event_created_at` e `state_priority` em `payment_events`.
11. `20261031_10_hotmart_financial_values.py` — valores financeiros do provedor separados do preço interno em `orders`.
12. `20261031_11_delivery_lifecycle.py` — recuperação temporária de licença suspensa, leitura restrita de estado pelo worker e cancelamento escopado de `license_delivery`.
13. `20261031_12_support_backoffice.py` — operadores/sessões/auditoria de suporte, policies administrativas e evento `license_recovery_instructions`.
14. `20261101_13_category_archive.py` — `categories.archived`, permitindo arquivar categorias personalizadas sem perder o histórico.
15. `20261102_14_distributed_rate_limit.py` — `rate_limit_buckets` para token bucket atômico compartilhado entre instâncias; grants somente para o papel operacional.
16. `20261102_15_hotmart_reconciliation.py` — `hotmart_reconciliation_observations`, tabela append-only de reconciliação comercial com grants de `SELECT`/`INSERT` para a API.
17. `20261102_16_account_lockout.py` — `login_lockout_states`, lockout progressivo distribuído por identidade de conta, com grants de leitura/escrita para a API e sem acesso do worker.
18. `20261104_17_financial_idempotency.py` — `idempotency_records`, idempotência transacional por tenant/usuário/operação, RLS/FORCE RLS, replay/conflito e retenção configurável.
19. `20261104_18_privacy_data_lifecycle.py` — `privacy_requests`, `privacy_request_events` e `data_deletion_tombstones`; exclusão/anonimização, suporte, tombstones e políticas de privacidade. Head atual.

Modelos relevantes: `backend/app/models/product.py`, `order.py`, `payment_event.py`, `license.py`, `email_outbox.py`, `pending_activation.py`, `rate_limit.py`, `hotmart_reconciliation.py`, `login_lockout.py`, `idempotency.py`, `privacy.py`, `tenant.py`, `user.py`, `session.py`, `password_reset.py`, `audit_log.py`.

## 4. Segurança, RLS e papéis

- Tabelas financeiras por tenant usam RLS/FORCE RLS e exigem `app.tenant_id` (migration `20261026_01`).
- `products` permite leitura ampla e escrita apenas com `app.catalog_write=true`.
- `orders` e `payment_events` são visíveis apenas ao provedor em `app.payment_provider`.
- Licenças de pedido exigem `app.payment_order_id`; consulta por código exige `app.license_code_hash`; o trigger `guard_license_update()` separa ativação de revogação e impede alteração de campos comerciais.
- O papel operacional (`APP_DB_USER`) não pode ter `SUPERUSER`/`BYPASSRLS` em produção (`check_database()` em `core/database.py`).
- O worker usa `OUTBOX_DB_USER` isolado, sem herança nem grants amplos (migration `20261031_06`). A migration `20261031_11` concede apenas leitura de `licenses(status, order_id)` e `orders(id, provider, status)` para validar a entrega de licença.
- `set_db_context()` só aceita chaves conhecidas; os GUCs são locais à transação.
- Cabeçalhos de segurança, request ID, bloqueio de origem cruzada para métodos mutáveis e handlers de erro ficam em `main.py`. Logging seguro centralizado em `core/log_safety.py`; consulte [security-logging.md](security-logging.md). Operações financeiras de criação/execução aceitam `Idempotency-Key` e persistem `idempotency_records` na mesma transação do efeito; consulte [financial-idempotency.md](financial-idempotency.md). Solicitações LGPD usam `/api/v1/privacy/*`, backoffice `/api/v1/support/privacy/*` e tabelas com FORCE RLS; consulte [lgpd-data-lifecycle.md](lgpd-data-lifecycle.md), [data-subject-request-sop.md](data-subject-request-sop.md) e [data-retention-matrix.md](data-retention-matrix.md). Rate limit usa token bucket atômico em `rate_limit_buckets` (`core/rate_limit.py`), sem storage em memória; chaves são HMAC-SHA-256 com `RATE_LIMIT_HMAC_KEY`, e proxies confiáveis vêm de `TRUSTED_PROXY_IPS`. O lockout progressivo por conta usa `login_lockout_states` e a rotina `services/login_lockout_service.py`, separado do rate limit HTTP. Consulte [account-lockout.md](account-lockout.md).

## 5. Ativação e autenticação

Arquivo central: `backend/app/services/activation_service.py`.

1. `POST /api/v1/auth/activate` inicia o desafio com licença, nome, e-mail e senha.
2. `validate_license_for_activation()` valida hash, estado, expiração e e-mail vinculado.
3. `PendingActivation` guarda dados cifrados, hash da senha, expiração e contador de tentativas.
4. A outbox recebe `activation_verification` com código de 6 dígitos; o código é hasheado com HMAC e o identificador do desafio.
5. `POST /auth/activate/confirm` bloqueia licença e ativação, confere código, cria tenant/usuário/categorias, vincula a licença, cria sessão e registra auditoria.
6. A licença só pode ser vinculada a um tenant; o e-mail é verificado no mesmo ato.
7. `resend_activation()` impõe intervalo de 60 s, invalida envios anteriores e gera novo código; tentativas são limitadas a 5.

Senha: `auth_service.forgot_password()` cria token de reset e enfileira `password_reset`; `reset_password()` valida token, expiração e uso, revoga sessões e altera a senha. O worker revalida o token antes de enviar, cancelando mensagens obsoletas.

Endpoints em `backend/app/api/v1/endpoints/auth.py`; cookies em `backend/app/api/v1/cookies.py`.

O login do cliente tem rate limit distribuído por IP e IP+e-mail e lockout progressivo por identidade de conta. A verificação Argon2 ocorre fora de locks de linha; falhas são contabilizadas atomicamente em `login_lockout_states`, e o sucesso reseta o estado. O lockout retorna `429` com `Retry-After` durante cooldown e não altera o status da conta nem revoga sessões. Detalhes em [account-lockout.md](account-lockout.md).

## 6. Outbox transacional

Arquivo central: `backend/app/services/email_outbox_service.py`.

- `enqueue_email()` cifra o payload e grava `pending` na mesma transação comercial.
- Estados: `pending`, `processing`, `sent`, `dead`, `cancelled`.
- `claim_batch()` usa `FOR UPDATE SKIP LOCKED`, calcula lease, incrementa tentativas, expira pendentes, limpa payloads antigos e marca leases esgotados como `dead`.
- `process_one()` reivindica por worker, renderiza e chama o Resend apenas pelo `email_service`; retries usam backoff exponencial com jitter; falhas permanentes viram `dead`.
- `cancel_activation_emails()` invalida códigos antigos de ativação.
- `requeue_dead()` permite uma recuperação manual limitada e não reenvia ativação sem novo código.
- `run_batch()` e `app/workers/email_outbox.py` executam o loop, heartbeat e `--check`.
- Healthcheck do Compose valida identidade do worker e leitura da outbox.

Consumidores: ativação, redefinição de senha e entrega de licença após compra.

## 7. Fluxo comercial e Hotmart

Arquivos: `backend/app/api/v1/endpoints/hotmart_webhook.py`, `backend/app/integrations/payments/hotmart.py`, `backend/app/services/license_service.py`.

Caminho de um webhook Hotmart:

1. `POST /api/v1/webhooks/hotmart` valida configuração, HOTTOK, `Content-Type: application/json` e limite de 256 KiB.
2. `parse_payload()` valida `version=2.0.0`, evento permitido, `id`, `creation_date`, produto, comprador opcional e compra.
3. Produto com UCODE diferente do configurado retorna `{"status": "ignored"}`.
4. `process_hotmart_event()` fixa `app.payment_provider=hotmart`, toma advisory locks por `id` e por `purchase.transaction`, deduplica `payment_events(provider, external_event_id)` e localiza/cria o pedido por `orders(provider, external_order_id)`.
5. `PURCHASE_APPROVED` valida e-mail, grava dados do comprador, mantém `amount_cents`/`currency` do catálogo interno e persiste `purchase.price`/`full_price` apenas nos campos `provider_*`, emite a licença e enfileira o e-mail. Se o pedido estava `pending` por `PURCHASE_DELAYED`, restaura a licença para `pending`/`active` e mantém a entrega existente. Se o pedido já está em estado terminal, apenas registra o evento.
6. Eventos terminais/bloqueantes atualizam pedido, licença e sessões e cancelam `license_delivery` pendente/processing na mesma transação; `PURCHASE_DELAYED` suspende temporariamente e o worker adia a entrega. A política está em `docs/hotmart-integration.md`.
7. `payment_events` registra `provider_event_created_at` e `state_priority`; eventos antigos não revertem estados.
8. Commit único confirma pedido, licença, evento, cancelamento/entrega da outbox e sessões. O endpoint só responde sucesso depois do commit.

O identificador próprio da compra (`purchase.transaction`) é sempre a chave do pedido. `order_bump.parent_purchase_transaction` é apenas informativo: nunca substitui a transação própria, e `parent` vazio é tratado como ausente. Um Order Bump de outro UCODE é ignorado no endpoint; um Order Bump do UCODE configurado é processado pela sua própria transação.

## 8. Frontend

- `frontend/src/App.tsx` define rotas: `/entrar`, `/redefinir-senha` e área autenticada (dashboard, lançamentos, contas, cartões, orçamento, metas, relatórios, categorias, configurações).
- `AuthPage.tsx` concentra login, ativação de licença e confirmação de código; `ResetPasswordPage.tsx` trata redefinição.
- `context/AuthContext.tsx` chama a API, mantém sessão e expõe `activate`, `confirmActivation`, `resendActivation`.
- `lib/api.ts` centraliza chamadas; `components/ProtectedRoute.tsx` protege a área autenticada.
- Build: `npm run build`; testes: `npm test` (Vitest, configuração em `vite.config.ts`).
- Categorias: `/categorias` permite que o owner crie, edite, arquive, reative e exclua categorias sem uso; members consultam em modo somente leitura. Categorias padrão não podem ser excluídas/arquivadas, e categorias arquivadas deixam de aparecer em novos lançamentos, contas e orçamentos sem apagar o histórico.
- Backoffice separado: `/backoffice/login`, `/backoffice`, pedidos, licenças, outbox e auditoria, com `SupportAuthContext` e cookie próprio.

## 8.1 Reconciliação Hotmart

- `app/integrations/payments/hotmart_api.py` — OAuth 2.0, token em memória, retries, tratamento de 401/403/404/429/5xx, timeout e parsing mínimo de `sales/history`.
- `app/services/hotmart_reconciliation_service.py` — seleção de transações locais, snapshot antes do HTTP, comparação conservadora de status, aplicação por serviços compartilhados e observações append-only.
- `app/cli/reconcile_hotmart.py` — dry-run padrão, `--apply` explícito, transação específica, janela, limite, JSON e códigos de saída.
- `hotmart_reconciliation_observations` — `run_id`, origem `hotmart_sales_api`, transação, estados, resultado, motivo, horários e `dry_run`; sem PII/payload.
- Concorrência: advisory lock por transação compartilhado com webhook, `FOR UPDATE`, revalidação de snapshot e descarte de observação stale.
- O endpoint público de webhook e o worker da outbox não foram alterados para executar reconciliação.

## 9. Docker e execução

Serviços do `docker-compose.yml`: `db`, `migrate`, `api`, `email-worker`, `web`, além do perfil `tests` (`test-db`, `tests`).

- API: `http://127.0.0.1:8010`.
- Web: `http://127.0.0.1:3010`.
- Banco local: `127.0.0.1:5433`.
- Migrations: `alembic upgrade head` dentro de `backend`; o serviço `migrate` do Compose executa o preflight de ambiente antes.
- Testes backend: `pytest` (unitários) e `pytest --run-integration` (PostgreSQL descartável).
- E2E: `cd frontend && npm run test:e2e` (Playwright + `docker-compose.e2e.yml`, projeto isolado).
- Rate limit: tabela compartilhada no PostgreSQL; não há serviço Redis adicional. Consulte [distributed-rate-limiting.md](distributed-rate-limiting.md).
- Reconciliação Hotmart: CLI `python -m app.cli.reconcile_hotmart`, cliente OAuth e observações append-only. Não há rota HTTP pública nem uso do worker da outbox. Consulte [hotmart-reconciliation.md](hotmart-reconciliation.md).
- Catálogo de produção: `python -m app.cli.provision_product` (idempotente por slug, dry-run por padrão).
- Preflight: `python -m app.cli.preflight --stage environment|database|commercial|all`.
- Operador de suporte: `python -m app.cli.provision_support_operator` (host, com `--password-stdin` e `--apply`).

Variáveis necessárias (somente nomes): `DATABASE_URL`, `MIGRATION_DATABASE_URL`, `APP_DB_USER`, `OUTBOX_DB_USER`, `OUTBOX_DB_PASSWORD`, `SECRET_KEY`, `PII_ENCRYPTION_KEY`, `PII_LOOKUP_KEY`, `LICENSE_HMAC_KEY`, `EMAIL_VERIFICATION_HMAC_KEY`, `EMAIL_PROVIDER`, `RESEND_API_KEY`, `EMAIL_FROM`, `APP_BASE_URL`, `CORS_ORIGINS`, `TRUSTED_PROXY_IPS`, `HOTMART_ENABLED`, `HOTMART_WEBHOOK_HOTTOK`, `HOTMART_PRODUCT_UCODE`, `HOTMART_PRODUCT_SLUG`, `PAYMENT_WEBHOOK_SECRET`, `PAYMENT_SANDBOX_ENABLED`, `IDEMPOTENCY_RETENTION_HOURS`.

## 10. Testes e pendências operacionais

- Unitários: `backend/tests/unit`.
- Integração PostgreSQL/RLS: `backend/tests/integration`.
- Fixtures Hotmart oficiais fictícias: `backend/tests/fixtures/hotmart`.
- Documentos específicos: `docs/email-activation.md`, `docs/email-outbox.md`, `docs/hotmart-integration.md`, `docs/testing.md`, `docs/support-backoffice.md`.
- Pendências humanas: HOTTOK real, UCODE, produto interno ativo com slug/preço aprovado (executar o provisionamento versionado), operadores de suporte provisionados por CLI, URL do webhook na Hotmart, domínio Resend autenticado, segredos de produção, deploy e teste externo.
- Pré-requisitos operacionais: `docs/production-preflight.md` descreve a ordem de preflight, provisionamento, migrations e habilitação da Hotmart.
- Limitação conhecida: estados terminais e protesto/chargeback não são reativados automaticamente. `PURCHASE_DELAYED` é temporário e recuperável por aprovação posterior mais nova. Divergências financeiras reportadas pelo provedor são registradas, mas não alteram acesso. Mensagens de licença já aceitas pelo provedor não podem ser recolhidas.

## Atualização pós-Missão 14 — release candidate

- Branch: `release/fortexahome-launch`.
- Commit base: `8cbd7f70bdb834ec7dc2c5bfa364ce3c10715331`.
- Head Alembic: `20261104_18`.
- Release candidate: `fortexahome-1.0.0-rc.1-20261104.tar.gz` + checksum + manifesto.
- O Compose de produção da VPS deve ser revisado contra o Compose atual; o repositório não contém labels Traefik de produção.
- Runbooks: [release-runbook.md](release-runbook.md), [backup-restore-runbook.md](backup-restore-runbook.md), [prelaunch-checklist.md](prelaunch-checklist.md) e [external-validation-matrix.md](external-validation-matrix.md).
