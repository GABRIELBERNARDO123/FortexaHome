# Lockout progressivo por conta

## Objetivo

Complementar o rate limit distribuído com proteção específica por identidade de conta contra força bruta e credential stuffing. O mecanismo não substitui o rate limit de IP/e-mail, não desativa a conta e não revoga sessões existentes.

## Identidade e privacidade

A chave é:

```text
HMAC-SHA-256(RATE_LIMIT_HMAC_KEY, "auth.login.lockout" + "account" + normalize_email(email))
```

- O e-mail é normalizado com a rotina existente (`strip().lower()`).
- O banco armazena somente o hash de 64 caracteres.
- O namespace `auth.login.lockout` separa a finalidade do rate limit comum.
- E-mails existentes e inexistentes usam a mesma tabela, chave e resposta externa.
- Não existe endpoint público para consultar lockout.

## Persistência

Migration `20261102_16_account_lockout.py` cria `login_lockout_states`:

- `key_hash` (PK);
- `failure_count`;
- `locked_until`;
- `last_failure_at`;
- `updated_at`;
- `expires_at`, com índice.

A tabela é global, sem PII em claro e sem RLS. O papel operacional tem `SELECT`, `INSERT`, `UPDATE` e `DELETE`; o worker da outbox não tem acesso. A limpeza é probabilística e baseada em `expires_at`.

## Política

Parâmetros tipados em `Settings`:

| Variável | Padrão | Origem/premissa |
| --- | --- | --- |
| `LOGIN_LOCKOUT_ENABLED` | `true` | proteção habilitada por padrão |
| `LOGIN_LOCKOUT_FAILURE_THRESHOLD` | `5` | mesmo limiar do lockout existente do suporte |
| `LOGIN_LOCKOUT_BASE_COOLDOWN_SECONDS` | `60` | cooldown inicial conservador |
| `LOGIN_LOCKOUT_MAX_COOLDOWN_SECONDS` | `900` | teto existente do lockout do suporte: 15 min |
| `LOGIN_LOCKOUT_INACTIVITY_RESET_SECONDS` | `86400` | expiração por inatividade: 24 h |
| `LOGIN_LOCKOUT_MAX_TRACKED_FAILURES` | `32` | limita o contador e o expoente de cooldown |

Cooldown:

```text
excess = failure_count - threshold
cooldown = min(max_cooldown, base_cooldown * 2^min(excess, 10))
```

- 4 falhas: sem lockout.
- 5ª falha: 60 s.
- 6ª: 120 s; 7ª: 240 s; 8ª: 480 s; 9ª+: 900 s.
- O contador não cresce sem limite.
- Após `LOGIN_LOCKOUT_INACTIVITY_RESET_SECONDS` sem falhas, o estado expira e é limpo.
- Não há bloqueio permanente.

Os valores não estavam definidos integralmente na auditoria. Foram adotadas premissas conservadoras e configuráveis, usando o lockout do suporte como referência para limiar e teto. Nenhum limiar da Missão 07 foi alterado.

## Fluxo de login

1. Pré-checagem read-only do estado de lockout.
2. Se `locked_until > now`, retorna `429` com `Retry-After` e mensagem genérica.
3. Se não bloqueado, o usuário é localizado e os campos necessários são capturados.
4. A transação de leitura é encerrada antes da verificação Argon2.
5. Senha inválida: incremento atômico da falha em uma transação curta, auditoria e `401`; se o limiar foi atingido, `429` com `Retry-After`.
6. Senha válida: reset atômico do estado, depois emissão de sessão/cookie e auditoria.
7. E-mail inexistente: verificação dummy, mesma política de falha e mesma resposta externa.

O bloqueio não altera `users.status`, não revoga sessões e não impede outros endpoints autenticados.

## Concorrência

- A pré-checagem não mantém lock.
- Falhas e sucesso são registrados com `INSERT ... ON CONFLICT DO NOTHING` + `SELECT ... FOR UPDATE`.
- Duas falhas simultâneas são serializadas e ambas contam.
- O reset de sucesso é atômico; se uma falha concorrente ocorreu antes, o sucesso limpa o estado. Se o lock já existia antes da pré-checagem, a senha correta não ignora o cooldown.
- Não há chamada externa nem Argon2 com lock de linha.

## Falha do storage

Falhas no estado de lockout usam **fail-open** com log sanitizado: a indisponibilidade isolada da tabela não deve bloquear todos os logins. O banco principal continua sendo necessário para autenticação normal. Nenhum e-mail ou chave é registrado.

## Preflight

Em produção, `LOGIN_LOCKOUT_ENABLED` deve ser `true`. O preflight de banco confirma `login_lockout_states`, permissões do papel operacional e ausência de acesso do worker. Os ranges são validados pelo `Settings`.

## Testes

`tests/integration/test_login_lockout.py` cobre com PostgreSQL real:

- quinta falha bloqueia e retorna `429` + `Retry-After`;
- senha correta não ignora lock ativo;
- expiração automática permite novo login;
- sucesso reseta o contador;
- e-mail inexistente tem o mesmo lockout e não enumera conta;
- falhas concorrentes são contabilizadas atomicamente;
- cooldown máximo e contador limitado;
- auditoria de `LOGIN_FAILED`, `LOGIN_LOCKED` e `LOGIN_SUCCESS`.

Testes de rate limit existentes foram ajustados para não misturar lockout por identidade com o teste de limite por IP.

## Limitações

- Os limiares são premissas conservadoras, não valores empiricamente calibrados para o tráfego de produção.
- Um ataque sustentado ainda pode causar indisponibilidade temporária de login por até o cooldown máximo; não há CAPTCHA, MFA ou desafio adaptativo.
- O lockout não substitui WAF, detecção de credential stuffing ou monitoramento de fraude.
- Não há revogação de sessões por falhas de login, por decisão de segurança.
