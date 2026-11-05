# FortexaHome — Preflight de produção e provisionamento do catálogo

Este documento descreve os comandos administrativos introduzidos para eliminar os bloqueadores P0-01 e P0-02 da auditoria de prontidão.

Os comandos usam a mesma configuração (`app.core.config.Settings`), a mesma sessão SQLAlchemy (`app.core.database.SessionLocal`) e as mesmas policies RLS do restante da aplicação. Nenhum comando cria tabelas, campos, papéis ou permissões novas.

## 1. Ordem correta de execução

```text
1. Preparar variáveis de ambiente e segredos reais
2. python -m app.cli.preflight --stage environment
3. alembic upgrade head
4. python -m app.cli.preflight --stage database
5. python -m app.cli.provision_product ... --dry-run
6. python -m app.cli.provision_product ... --apply
7. python -m app.cli.preflight --stage commercial   # quando HOTMART_ENABLED=true
8. Iniciar API e worker
```

O `migrate` do Docker Compose executa o preflight de ambiente automaticamente antes de `alembic upgrade head`.

## 2. Preflight de ambiente

Executa antes das migrations. Valida a configuração sem imprimir valores secretos.

```sh
python -m app.cli.preflight --stage environment
```

No container:

```sh
docker compose run --rm --no-deps api python -m app.cli.preflight --stage environment
```

### O que é verificado

- `ENV` reconhecido (`development`, `test` ou `production`).
- Validação estrutural do `Settings` existente.
- Tamanho de `SECRET_KEY`, `PII_LOOKUP_KEY`, `LICENSE_HMAC_KEY`, `EMAIL_VERIFICATION_HMAC_KEY` e `RATE_LIMIT_HMAC_KEY` (produção).
- `PII_ENCRYPTION_KEY` como base64 de 32 bytes.
- Drivers PostgreSQL de `DATABASE_URL` e `MIGRATION_DATABASE_URL`.
- `APP_DB_USER`, `OUTBOX_DB_USER` e `OUTBOX_DB_PASSWORD`.
- Separação entre o papel operacional, o papel do worker e o papel de migrations.
- Senhas do worker e de migrations diferentes da senha da URL operacional.
- Finalidades distintas dos segredos em produção.
- Placeholders de exemplo em produção.
- `EMAIL_PROVIDER`, `RESEND_API_KEY`, `EMAIL_FROM`.
- `APP_BASE_URL`, `CORS_ORIGINS`, `TRUSTED_PROXY_IPS`.
- `SESSION_COOKIE_SECURE`, `SESSION_COOKIE_SAMESITE`.
- `RATE_LIMIT_ENABLED` e `RATE_LIMIT_DB_TIMEOUT_MS`.
- `PAYMENT_SANDBOX_ENABLED=false` e `LOG_LEVEL` diferente de DEBUG em produção.
- `LOGIN_LOCKOUT_ENABLED`, limiar, cooldowns, janela de inatividade e limite de falhas rastreadas.
- `RATE_LIMIT_HMAC_KEY` dedicada, com pelo menos 32 caracteres em produção; ela também fornece o namespace HMAC do lockout de conta.
- Credenciais Hotmart somente quando `HOTMART_ENABLED=true`.
- Reconciliação Hotmart: feature flag, Client ID/Secret, ambiente, product ID, ranges de timeout/lote/janela/tentativas/backoff/intervalo e placeholders.

### Exit codes

- `0`: nenhuma falha. Avisos não bloqueiam, salvo com `--strict`.
- `1`: falha de configuração, de conexão ou de catálogo.
- `2`: entrada inválida do comando de catálogo ou conflito de slug.
- `3`: falha de banco/permissão no comando de catálogo.

Use `--strict` para transformar avisos em falha.

Nunca são impressos `SECRET_KEY`, chaves HMAC, `RESEND_API_KEY`, senhas, tokens, HOTTOK, UCODE ou URLs completas de conexão.

## 3. Preflight de banco

Executa depois das migrations. Usa a conexão operacional (`DATABASE_URL`).

```sh
python -m app.cli.preflight --stage database
```

### O que é verificado

- Conectividade com o banco.
- Banco e papel utilizados.
- Ausência de `SUPERUSER` e `BYPASSRLS` no papel operacional (falha em produção; aviso fora dela).
- Revisão atual do Alembic em relação ao head único.
- Permissões operacionais mínimas em catálogo, licenças, pedidos, eventos, categorias, usuários, sessões, outbox, `rate_limit_buckets` (SELECT/INSERT/UPDATE/DELETE), `hotmart_reconciliation_observations` (SELECT/INSERT) e `login_lockout_states` (SELECT/INSERT/UPDATE/DELETE).
- `ROW LEVEL SECURITY` e `FORCE ROW LEVEL SECURITY` em `products`.
- Existência e privilégios de `rate_limit_buckets`; o worker da outbox não possui acesso.
- Existência de `hotmart_reconciliation_observations`, ausência de UPDATE/DELETE para o papel operacional e ausência de acesso do worker.
- Existência de `login_lockout_states` e ausência de acesso do worker ao estado de lockout.
- Existência da policy `products_catalog_write`.

## 4. Preflight comercial

Executa depois do provisionamento do produto e antes de habilitar a Hotmart ou a reconciliação.

```sh
python -m app.cli.preflight --stage commercial
```

Com `HOTMART_ENABLED=false` e `HOTMART_RECONCILIATION_ENABLED=false`, o estágio retorna `SKIP` e não exige credenciais nem catálogo. Se qualquer uma das features estiver habilitada, o produto interno e o slug precisam existir/estar ativos.

Com `HOTMART_ENABLED=true`, o estágio falha se:

- `HOTMART_PRODUCT_SLUG` estiver vazio;
- o produto interno não existir;
- o produto existir, mas estiver inativo.

O slug configurado é sempre comparado ao catálogo interno pelo valor exato.

## 5. Provisionamento idempotente do catálogo

O comando usa `slug` como chave estável. Ele cria ou atualiza o produto sem duplicar linhas.

### Simulação (padrão)

```sh
python -m app.cli.provision_product \
  --slug fortexahome-lifetime \
  --name "FortexaHome — Licença vitalícia" \
  --price-cents 19990 \
  --currency BRL \
  --license-kind lifetime \
  --description "Gestão financeira doméstica" \
  --state active \
  --dry-run
```

Sem `--apply`, nenhuma alteração é gravada. `--dry-run` pode ser omitido; o comportamento continua sendo simulação.

### Efetivação

```sh
python -m app.cli.provision_product \
  --slug fortexahome-lifetime \
  --name "FortexaHome — Licença vitalícia" \
  --price-cents 19990 \
  --currency BRL \
  --license-kind lifetime \
  --description "Gestão financeira doméstica" \
  --state active \
  --apply
```

### Regras

- `--slug`: identificador estável, minúsculo, com letras, números e hífens.
- `--name`: nome comercial existente no modelo, obrigatório.
- `--price-cents`: inteiro em centavos, maior ou igual a zero.
- `--currency`: três letras maiúsculas (ex.: `BRL`).
- `--license-kind`: `lifetime` ou `subscription`, conforme o modelo.
- `--description`: opcional; quando omitida em uma atualização, a descrição existente é preservada.
- `--state`: opcional. Em um produto novo, o padrão é ativo. Em um produto existente, o estado só muda quando `--state` é informado; um produto inativo não é reativado silenciosamente.
- `--apply`: confirmação explícita para gravar.
- Executar duas vezes com os mesmos dados resulta em `unchanged`.
- O comando usa `app.catalog_write=true` e a policy `products_catalog_write`; não executa SQL ignorando RLS.
- O papel operacional já possui `SELECT`, `INSERT` e `UPDATE` em `products` pela migration `20261031_03`. Nenhum privilégio novo é concedido ao papel da API ou ao worker.
- A transação é revertida em caso de conflito, falha de permissão ou erro de commit.

### Saída esperada

```text
DRY-RUN: produto seria criado: slug=fortexahome-lifetime ...
Campos alterados: slug, name, description, price_cents, currency, license_kind, active
Nenhuma alteração foi gravada. Revise e repita com --apply para efetivar.
```

```text
Produto criado: slug=fortexahome-lifetime ...
```

```text
Produto já está no estado desejado: slug=fortexahome-lifetime ...
```

## 6. Verificação posterior

```sh
python -m app.cli.preflight --stage database
python -m app.cli.preflight --stage commercial
python -m app.cli.preflight --stage all
```

O estágio `all` executa ambiente, banco e comercial na ordem lógica. Ele não substitui a ordem de implantação: ambiente deve ser aprovado antes das migrations; banco e comercial depois.

## 7. Desenvolvimento, testes e produção

| Item | development/test | production |
| --- | --- | --- |
| `ENV` | `development` ou `test` | `production` |
| `DEBUG` | permitido | obrigatoriamente `false` |
| `SESSION_COOKIE_SECURE` | pode ser `false` | obrigatoriamente `true` |
| `SESSION_COOKIE_SAMESITE` | `lax`, `strict` ou `none` | `lax` ou `strict` |
| `EMAIL_PROVIDER` | `dev` ou `resend` | obrigatoriamente `resend` |
| `APP_BASE_URL` | HTTP permitido | HTTPS obrigatório |
| Placeholders | permitidos para desenvolvimento | proibidos |
| `HOTMART_ENABLED` | pode permanecer `false` | somente após provisionar o produto e aprovar o preflight comercial |
| Credenciais Hotmart | não exigidas com a integração desabilitada | exigidas com a integração habilitada |
| Reconciliação Hotmart | desabilitada por padrão | somente com credenciais próprias, product ID e `--apply` explícito |
| Lockout progressivo | habilitado por padrão | obrigatório em produção, com parâmetros revisados |
| Sandbox HMAC | desabilitado por padrão | proibido em produção |
| Logs | redaction central | `DEBUG` proibido; retenção a definir |
| Privacidade/LGPD | fluxo e SOP disponíveis | canal/encarregado, matriz de retenção e restore drill aprovados antes da venda |

Em `test`, o banco é descartável (`fortexahome_test`) e os papéis são os definidos no perfil `tests` do Compose. Nunca use essas credenciais fora do ambiente de teste.

## 8. Integração com API, worker e migrations

- **Migrations:** o serviço `migrate` do Compose executa `python -m app.cli.preflight --stage environment` antes de `alembic upgrade head`. Assim, uma migration não começa com configuração incompleta.
- **API:** no startup, o preflight de ambiente é executado. Em produção, falhas impedem a inicialização; em desenvolvimento/teste, avisos e falhas são registrados para diagnóstico.
- **Worker:** valida `OUTBOX_DB_USER`, `OUTBOX_DB_PASSWORD`, separação de papéis e credencial de e-mail antes de abrir a conexão. O `check_worker` continua validando a identidade real no PostgreSQL.
- **Rate limit:** usa PostgreSQL compartilhado; configurar `RATE_LIMIT_HMAC_KEY` e executar a migration 14 antes de iniciar múltiplas réplicas. Consulte [distributed-rate-limiting.md](distributed-rate-limiting.md).
- **Sandbox HMAC:** `PAYMENT_SANDBOX_ENABLED` deve ser false em produção; a rota legada não é registrada.
- **Logs:** manter `LOG_LEVEL=INFO`/superior, redaction ativa e acesso a logs restrito. Consulte [security-logging.md](security-logging.md).
- **Reconciliação Hotmart:** permanece desabilitada por padrão; configurar credenciais/IDs próprios e validar `--dry-run` antes de `--apply`. O preflight não faz chamadas externas. Consulte [hotmart-reconciliation.md](hotmart-reconciliation.md).
- **Lockout de conta:** manter `LOGIN_LOCKOUT_ENABLED=true` em produção e revisar os parâmetros tipados antes do deploy. Consulte [account-lockout.md](account-lockout.md).
- **Webhook Hotmart:** continua retornando `503` se o produto interno não estiver configurado. O preflight comercial é o gate operacional para habilitar a integração.
- **Privacidade/LGPD:** o fluxo `/api/v1/privacy/*` e o backoffice `/api/v1/support/privacy/*` são funcionais, mas o lançamento exige aprovação jurídica/contábil da [matriz de retenção](data-retention-matrix.md), definição de controlador/encarregado/canal e restore drill real com reaplicação de tombstones. Consulte [data-subject-request-sop.md](data-subject-request-sop.md).

## 8.1 Operador de suporte

O provisionamento do backoffice é feito no host, com senha lida de `stdin` e confirmação explícita:

```sh
python -m app.cli.provision_support_operator   --email operador@example.com   --name "Operador de Suporte"   --role support_read   --password-stdin   --dry-run
python -m app.cli.provision_support_operator   --email operador@example.com   --name "Operador de Suporte"   --role support_read   --password-stdin   --apply
```

Use `--state disabled --apply` para revogar o acesso. O backoffice usa cookie separado e não transforma `owner` em administrador global. Consulte [support-backoffice.md](support-backoffice.md).

## 9. Interpretação de erros comuns

| Mensagem | Significado | Ação |
| --- | --- | --- |
| `OUTBOX_DB_PASSWORD não pode ser vazia` | worker/migration sem credencial dedicada | definir a senha no gerenciador de segredos |
| `EMAIL_VERIFICATION_HMAC_KEY deve ter pelo menos 32 caracteres` | ativação não conseguiria gerar códigos | gerar uma chave dedicada |
| `placeholders de exemplo detectados` | valor de exemplo usado em produção | substituir por segredo real |
| `APP_BASE_URL deve usar HTTPS em produção` | link de reset/licença inseguro | corrigir a URL pública |
| `migrations ainda não foram aplicadas` | banco fora do head | executar `alembic upgrade head` |
| `produto interno não encontrado` | slug da Hotmart sem produto | executar `provision_product --apply` |
| `produto interno encontrado, mas está inativo` | produto cadastrado porém desativado | executar `provision_product --state active --apply` |
| `o papel do banco não pode gravar o catálogo` | conexão sem permissão/policy | usar a conexão operacional correta e conferir migrations |
| `slug já existe no catálogo` | conflito de unicidade em provisionamento concorrente | revisar o produto existente e repetir a simulação |

## 9.1 Testes E2E

O E2E não faz parte do preflight de produção e não deve ser executado contra o banco comercial. Use o projeto Compose descartável:

```sh
cd frontend
npm run test:e2e
```

Consulte [e2e-testing.md](e2e-testing.md). O ambiente usa `EMAIL_PROVIDER=dev`, `HOTMART_ENABLED=false` e banco próprio sem volume.

## 10. Procedimento seguro para o operador

1. Não use `.env.example` como ambiente real.
2. Coloque segredos no gerenciador do ambiente, nunca em arquivo versionado.
3. Rode o preflight de ambiente e corrija todas as falhas.
4. Rode as migrations no banco correto.
5. Rode o preflight de banco.
6. Faça o provisionamento com `--dry-run`, revise a saída e só então use `--apply`.
7. Rode o preflight comercial.
8. Só depois habilite `HOTMART_ENABLED=true`.
9. Não envie HOTTOK, UCODE, senhas ou chaves em tickets ou logs.
10. Não execute downgrade em produção.

## 11. Release candidate e pré-produção (Missão 14)

- Release candidate `fortexahome-1.0.0-rc.1-20261104.tar.gz`, head `20261104_18`.
- O pacote inclui código, migrations e documentação; não inclui `.env`, segredos, dependências instaladas, caches, logs, bancos ou backups.
- O preflight de release deve ser executado antes das migrations e antes de habilitar Hotmart.
- Consulte [release-runbook.md](release-runbook.md), [backup-restore-runbook.md](backup-restore-runbook.md), [prelaunch-checklist.md](prelaunch-checklist.md) e [external-validation-matrix.md](external-validation-matrix.md).
- Backup/restore drill foi executado em ambiente descartável; restore real da VPS continua obrigatório antes da venda.

## 12. Checklist de privacidade antes da venda

1. Aprovar a [matriz de retenção](data-retention-matrix.md) com jurídico/contábil.
2. Definir e publicar controlador, encarregado/DPO e canal oficial de solicitações.
3. Revisar contratos/subprocessadores Hotmart e Resend e transferências internacionais.
4. Definir retenção operacional de logs e backups, separando registros de incidentes de segurança.
5. Executar restore drill real em ambiente isolado, exportar tombstones antes do restore e reaplicá-los.
6. Treinar suporte no [SOP](data-subject-request-sop.md) e validar perfis `support_read`/`support_operator`.
7. Não habilitar vendas com pendências legais marcadas como `REVISÃO JURÍDICA/CONTÁBIL NECESSÁRIA`.
