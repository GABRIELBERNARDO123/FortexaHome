# Rate limiting distribuído

## Objetivo

Substituir o rate limit em memória do SlowAPI por um mecanismo compartilhado entre todas as instâncias da API, mantendo os limites existentes e adicionando proteção consistente para autenticação, suporte e webhooks.

## Decisão de arquitetura

O FortexaHome não possui Redis nem API gateway compartilhado. O PostgreSQL já é uma dependência obrigatória e única entre as réplicas, por isso o rate limiter usa uma tabela própria no banco operacional:

- **storage compartilhado**: `rate_limit_buckets`;
- **algoritmo**: token bucket atômico com `SELECT ... FOR UPDATE` e transação curta;
- **relógio**: `now()` do PostgreSQL, evitando divergência de relógio entre instâncias;
- **chaves**: HMAC-SHA-256 com `RATE_LIMIT_HMAC_KEY`, nunca IP/e-mail em claro;
- **expiração**: `expires_at` com limpeza probabilística de linhas expiradas;
- **concorrência**: a linha de cada chave é bloqueada durante a leitura/atualização, portanto duas instâncias não consomem o mesmo token duas vezes;
- **reinício**: contadores permanecem no banco;
- **falha**: fail-open com log sanitizado, porque o banco já é necessário para os fluxos protegidos e uma falha isolada do limiter não deve bloquear usuários legítimos.

Redis não foi adicionado porque exigiria uma nova credencial, serviço, rede, healthcheck, persistência operacional e procedimento de produção sem necessidade comprovada nesta arquitetura. A tabela PostgreSQL resolve o escopo atual de poucos endpoints sensíveis e pode ser substituída por Redis no futuro sem alterar os decorators.

## Migration

`backend/migrations/versions/20261102_14_distributed_rate_limit.py`:

- cria `rate_limit_buckets(key_hash, tokens, updated_at, expires_at)`;
- cria índice em `expires_at`;
- concede `SELECT, INSERT, UPDATE, DELETE` somente ao papel operacional da API;
- revoga acesso do worker da outbox e de `PUBLIC`;
- não habilita RLS porque a tabela é global, não contém `tenant_id` nem dados pessoais em claro.

A migration é aditiva; o downgrade remove a tabela e deve ser usado somente em ambiente descartável.

## Algoritmo

Cada endpoint protegido informa um limite no formato `N/janela` (`5/hour`, `10/minute`, etc.). O token bucket usa:

- capacidade = `N`;
- recarga = `N / janela_em_segundos`;
- cada requisição consome 1 token;
- requisição negada não consome token, mas preserva os tokens acumulados;
- `Retry-After` = segundos até o próximo token inteiro, no mínimo 1.

Efeitos de borda:

- uma janela de `5/hour` permite um pequeno burst inicial de até 5 requisições, seguido de recarga contínua;
- não há salto de contador no fim de uma janela fixa;
- tokens não usados acumulam até a capacidade, nunca indefinidamente;
- o limite é aplicado por identidade; múltiplos identificadores no mesmo endpoint precisam ser satisfeitos simultaneamente.

## Identidade e privacidade

A chave é `HMAC(scope + tipo + valor)` com `RATE_LIMIT_HMAC_KEY`. O banco armazena somente o hash de 64 caracteres.

Identidades suportadas:

- `ip`: IP real resolvido por `client_ip()`;
- `email`: e-mail normalizado (`strip().lower()`);
- `support_operator`: UUID do operador autenticado;
- `user`, `tenant`, `session`: disponíveis para extensões futuras.

Não são usados como prova de identidade headers fornecidos livremente pelo cliente, tokens de sessão, códigos de ativação ou senhas. Nenhum e-mail, IP, token, cookie ou payload aparece em logs do limiter.

## Proxy reverso

`client_ip()` só considera `X-Real-IP`/`X-Forwarded-For` quando a conexão direta vem de `TRUSTED_PROXY_IPS`. O Nginx do Compose sobrescreve os cabeçalhos com `$remote_addr`. Sem proxy confiável configurado, o IP da conexão direta é usado; um cliente não consegue trocar o próprio IP por header para contornar o limite.

## Limites aplicados

| Endpoint | Limite | Chaves |
| --- | --- | --- |
| `POST /auth/activate` | 5/hour | IP + e-mail |
| `POST /auth/activate/confirm` | 10/minute | IP |
| `POST /auth/activate/resend` | 5/hour | IP |
| `POST /auth/recover-license` | 5/hour | IP + e-mail |
| `POST /auth/recover-license/confirm` | 10/minute | IP + e-mail |
| `POST /auth/login` | 10/minute | IP + e-mail |
| `POST /auth/forgot-password` | 5/hour | IP + e-mail |
| `POST /auth/reset-password` | 10/hour | IP |
| `POST /support/auth/login` | 10/minute | IP + e-mail |
| `POST /support/orders/{id}/recovery-instructions` | 30/hour | operador + IP |
| `POST /webhooks/hotmart` | 60/minute | IP |
| `POST /webhooks/payments/{provider}` | 120/minute | IP |

Respostas bloqueadas usam `HTTP 429` com `Retry-After`.

## Configuração

| Variável | Uso |
| --- | --- |
| `RATE_LIMIT_ENABLED` | liga/desliga o limiter; deve ser `true` em produção |
| `RATE_LIMIT_HMAC_KEY` | segredo dedicado para hashing das chaves; obrigatório em produção, mínimo 32 caracteres |
| `RATE_LIMIT_DB_TIMEOUT_MS` | timeout de statement/lock do limiter; padrão 1000 ms, faixa 100–5000 |

Em desenvolvimento/teste, `RATE_LIMIT_HMAC_KEY` vazia é aceita com aviso; nenhuma chave em claro é armazenada mesmo nesse caso. Em produção o preflight falha se a chave estiver ausente, curta, repetir outro segredo ou contiver placeholder.

## Falha e disponibilidade

- Erro/timeout de banco no limiter: `fail-open`, com log `Rate limiter indisponível (Tipo)` e sem dados sensíveis.
- A sessão de request é reutilizada quando disponível para evitar uma segunda conexão; o contexto RLS é reaplicado após o commit intermediário.
- Webhooks assíncronos usam sessão separada para não compartilhar sessão SQLAlchemy entre threads.
- Limpeza de chaves expiradas ocorre em ~1% das requisições, além da expiração lógica por `expires_at`.

## Testes

- `tests/unit/test_rate_limit.py`: IP confiável, parsing, HMAC, escopo, múltiplas chaves, 429/`Retry-After`, bypass desabilitado e fail-open.
- `tests/integration/test_rate_limit_distributed.py`: concorrência real (20 requisições, 5 tokens), isolamento de chaves, recarga após janela, dois clientes API compartilhando o limite e 429 real via login.
- `tests/integration/test_postgres_rls.py`: migration 14, tabela, privilégios da aplicação e ausência de acesso do worker.
- `tests/integration/test_rate_limit_route_coverage.py`: matriz de políticas por rota e `429` real de suporte/webhook com PostgreSQL.
- E2E continua com `RATE_LIMIT_ENABLED=true`; os limites atuais não interferem no fluxo normal de testes.

## Operação

1. Configurar `RATE_LIMIT_HMAC_KEY` no gerenciador de segredos antes do deploy.
2. Executar `alembic upgrade head` e `python -m app.cli.preflight --stage database`.
3. Confirmar `rate_limit_buckets` com privilégios apenas do papel operacional.
4. Monitorar logs de fail-open e latência do banco.
5. Revisar limites se houver aumento de tráfego legítimo ou mudança de topologia de proxy.

Não execute downgrade em produção sem backup e plano de reversão.

## Auditoria complementar de cobertura (Missão 07)

Esta auditoria confronta os decorators efetivamente aplicados com as rotas existentes. Nenhum limiar foi alterado. A introspecção usa o metadado `__rate_limit_policy__` exposto pelos wrappers e é validada por teste com PostgreSQL real.

### Suporte e backoffice

| Rota | Limite aplicado | Chave | Situação |
| --- | --- | --- | --- |
| `POST /api/v1/support/auth/login` | 10/minute | IP + e-mail normalizado | Coberto |
| `POST /api/v1/support/orders/{id}/recovery-instructions` | 30/hour | operador + IP | Coberto |
| `POST /api/v1/support/auth/logout` | nenhum específico | sessão de suporte | Baixo custo; autenticado |
| `GET /api/v1/support/auth/me` | nenhum específico | sessão de suporte | Baixo custo; autenticado |
| `GET /api/v1/support/dashboard` | nenhum específico | sessão + permissão `support:read` | Lacuna de limiar |
| `GET /api/v1/support/orders` | nenhum específico | sessão + `support:read` | Lacuna de limiar |
| `GET /api/v1/support/orders/{id}` | nenhum específico | sessão + `support:read` | Lacuna de limiar |
| `GET /api/v1/support/licenses` | nenhum específico | sessão + `support:read` | Lacuna de limiar |
| `GET /api/v1/support/outbox` | nenhum específico | sessão + `support:read` | Lacuna de limiar |
| `GET /api/v1/support/audit` | nenhum específico | sessão + `support:read` | Lacuna de limiar |

As rotas de leitura são autenticadas, paginadas (`page_size <= 100`) e sujeitas a RLS/permissões de suporte. Não foi definido um limiar específico para elas na arquitetura/missão; criar um valor arbitrário poderia bloquear investigações legítimas. A lacuna fica registrada para decisão de produto/operação. O login de suporte e a ação sensível de recuperação já estão cobertos.

### Webhook Hotmart

| Rota | Limite aplicado | Chave | Situação |
| --- | --- | --- | --- |
| `POST /api/v1/webhooks/hotmart` | 60/minute | IP real | Coberto |
| `POST /api/v1/webhooks/payments/{provider}` | 120/minute | IP real | Coberto |

Controles complementares:
- HOTTOK validado em tempo constante no webhook Hotmart;
- `payment_events(provider, external_event_id)` deduplica reenvios;
- advisory locks por evento/transação serializam concorrência;
- corpo limitado a 256 KiB e `Content-Type` validado;
- respostas `503` permitem retry legítimo pela Hotmart;
- nenhuma chamada externa é feita pelo endpoint.

Risco de falso bloqueio: a Hotmart pode enviar eventos de vários pedidos a partir de infraestrutura compartilhada. O limite de 60/min por IP é o valor existente e foi preservado. Picos acima disso podem gerar `429`; a Hotmart trata `429` como falha temporária e reenvia. Duplicatas dentro do limite são baratas e idempotentes, mas ainda passam pelo limiter antes da deduplicação.

### Operações financeiras e conta

| Rota | Limite aplicado | Situação |
| --- | --- | --- |
| `GET/POST/PATCH/DELETE /api/v1/transactions` e `/summary` | nenhum específico | Lacuna de limiar |
| `GET/POST/PATCH/DELETE /api/v1/bills` e `/pay`, `/unpay`, `/recurrence` | nenhum específico | Lacuna de limiar |
| `GET/POST/PATCH/DELETE /api/v1/cards` | nenhum específico | Lacuna de limiar |
| `GET/POST/PATCH/DELETE /api/v1/budgets` | nenhum específico | Lacuna de limiar |
| `GET/POST/PATCH/DELETE /api/v1/goals` e movimentos | nenhum específico | Lacuna de limiar |
| `GET /api/v1/reports/summary`, `/monthly`, `/transactions.csv` | nenhum específico | Lacuna de limiar |
| `GET /api/v1/account/export` | nenhum específico | Lacuna de limiar |

Essas rotas exigem sessão válida, licença ativa, contexto de tenant e RLS. Escritas têm validações de domínio e constraints; listagens têm paginação máxima de 100; exportações são autenticadas e tenant-scoped. Não existe limiar definido nas seções disponíveis da missão nem nos controles anteriores para operações financeiras. Para não bloquear usuários legítimos com um valor inventado, nenhum limite específico foi adicionado. **Gap documentado:** exportações CSV/JSON e operações de escrita são os candidatos prioritários a um limite por sessão/tenant, mas o valor precisa ser definido por produto/capacidade antes de implementação.

### Falha e falso bloqueio

- Falha do storage: **fail-open** com log sanitizado. O banco já é necessário para as operações protegidas; uma falha isolada do limiter não deve bloquear o fluxo.
- Contexto RLS: reaplicado após o commit intermediário do limiter.
- Falso bloqueio: NAT/proxy compartilhado pode fazer vários usuários dividirem o mesmo IP. Login/ativação usam também e-mail; recuperação de suporte usa operador + IP. Webhooks permanecem somente por IP, conforme o valor existente.
- Não há limite específico para operações financeiras, portanto não há falso bloqueio introduzido nelas nesta auditoria.

### Regressão adicionada

- `tests/integration/test_rate_limit_route_coverage.py`:
  - introspecção da matriz exata de políticas por rota;
  - login de suporte com PostgreSQL real: 10 tentativas e `429` + `Retry-After`;
  - webhook Hotmart com PostgreSQL real: rajada até `429` + `Retry-After`;
  - confirmação de que os limites e chaves existentes não foram alterados.
- Testes genéricos de concorrência, expiração, dois clientes e fail-open permanecem em `test_rate_limit_distributed.py`.

## Lockout progressivo por conta (Missão 09)

O rate limit HTTP continua separado do lockout por identidade. A Missão 09 adicionou:

- tabela `login_lockout_states` (migration `20261102_16`);
- chave HMAC de e-mail normalizado sob namespace `auth.login.lockout`;
- contador de falhas e `locked_until` atômicos no PostgreSQL;
- cooldown progressivo de 60 s até 900 s, com expiração por inatividade;
- reset em login válido e `429` + `Retry-After` durante bloqueio ativo;
- fail-open para indisponibilidade isolada do lockout.

As dimensões permanecem independentes:

| Dimensão | Onde | Não substitui |
| --- | --- | --- |
| IP | rate limit distribuído | lockout por conta |
| IP + e-mail | rate limit distribuído | lockout por conta |
| Conta | `login_lockout_states` | rate limit por IP |

Detalhes completos em [account-lockout.md](account-lockout.md).
