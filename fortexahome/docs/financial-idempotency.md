# Idempotência financeira

## Objetivo

Impedir que retries, duplo clique, timeout após commit, perda de resposta ou concorrência entre instâncias criem mais de um efeito financeiro para a mesma operação lógica.

A API continua sendo a autoridade final. O frontend envia `Idempotency-Key`, mas a garantia é transacional no PostgreSQL.

## Contrato HTTP

Header:

```http
Idempotency-Key: <identificador opaco>
```

Regras:

- 1 a 128 caracteres;
- charset `[A-Za-z0-9._:-]`;
- não contém e-mail, CPF, token, senha ou qualquer dado pessoal;
- é gerado pelo cliente para uma operação lógica;
- deve ser reutilizado em retries da mesma operação;
- deve ser novo para uma nova operação intencional;
- não autentica nem autoriza a requisição;
- não permite acesso a resultados de outro usuário ou tenant.

O backend rejeita chave inválida com `400`. A chave é opcional por compatibilidade com clientes legados; quando ausente, o comportamento anterior é mantido. O frontend comercial sempre envia a chave nas operações abrangidas.

## Escopo

A unicidade é:

```text
(tenant_id, user_id, operation, key_hash)
```

Consequências:

- dois tenants podem usar a mesma chave sem compartilhar resultados;
- owner e member do mesmo tenant têm escopos separados;
- a mesma chave pode ser usada em operações diferentes;
- a chave bruta não é armazenada; é gravado apenas SHA-256 (`key_hash`);
- a autorização é reavaliada em cada requisição antes de recuperar o resultado.

Operações abrangidas:

| Operação | Escopo adicional | Efeito protegido |
| --- | --- | --- |
| `transactions.create` | payload do lançamento | lançamento novo, inclusive gasto no cartão |
| `bills.create` | payload da conta | nova obrigação financeira |
| `bills.pay` | `bill_id` | pagamento + lançamento vinculado |
| `bills.unpay` | `bill_id` | remoção do lançamento e reabertura |
| `goals.create` | payload da meta | nova meta |
| `goals.movements.create` | `goal_id` + payload | aporte/retirada e saldo da meta |

Não abrangidas por chave:

- edição e exclusão de recursos: operações de atualização não criam efeitos duplicados e já são protegidas por estado/locks;
- criação de orçamento: a constraint `uq_budgets_tenant_category_month` garante um único orçamento por categoria/mês; concorrência retorna `409`;
- recorrência de conta: a constraint `uq_bills_parent_due` garante uma única ocorrência por conta-base e vencimento; concorrência retorna a ocorrência existente;
- criação de cartão, categoria e conta do tenant: não geram lançamento financeiro;
- pagamentos Hotmart/outbox: possuem idempotência de domínio própria (evento/provider e chave da outbox).

## Fingerprint

O fingerprint é SHA-256 de um JSON canônico dos campos que alteram o efeito financeiro:

- valores normalizados (`Decimal` sem notação científica);
- datas em ISO;
- UUIDs em texto;
- chaves de objeto ordenadas;
- listas na ordem original.

Não entram no fingerprint: `Request ID`, cabeçalhos de observabilidade, cookies, IP ou user-agent.

Mesma chave + mesmo fingerprint: retorna o resultado anterior sem executar novamente.
Mesma chave + fingerprint diferente: `409 Conflict`, sem alteração financeira.
Chaves diferentes + mesmo payload: duas operações legítimas, salvo regra de domínio específica.

## Persistência e atomicidade

Tabela `idempotency_records` (migration `20261104_17_financial_idempotency.py`):

- `tenant_id`, `user_id`, `operation`, `key_hash`, `fingerprint`;
- `status` (`processing`/`completed`);
- `resource_type`, `resource_id`;
- `response_payload` (JSON operacional necessário para replay);
- `created_at`, `completed_at`, `expires_at`.

Garantias:

1. O registro idempotente é inserido com `INSERT ... ON CONFLICT DO NOTHING` na mesma transação do efeito financeiro.
2. O efeito e o registro são confirmados no mesmo `COMMIT`.
3. Falha antes do commit faz rollback dos dois; não fica estado `processing` permanente.
4. Concorrência é resolvida pela constraint única e por lock de linha; a segunda transação aguarda e recupera o resultado.
5. `processing` nunca é commitado pelo fluxo normal; se aparecer, a API responde conflito em vez de executar de novo.

Cenários:

- **commit + resposta perdida:** retry encontra o registro concluído e devolve o mesmo resultado;
- **falha antes do commit:** retry insere novamente e executa;
- **duas requisições simultâneas:** o PostgreSQL serializa; apenas uma executa;
- **chave com outro payload:** `409`, sem efeito;
- **chave nova com payload igual:** novo efeito intencional.

## Retenção e limpeza

Configuração:

```env
IDEMPOTENCY_RETENTION_HOURS=168
```

Padrão: **7 dias** (1 a 720 horas). Justificativa: cobre retries de rede, sessões interrompidas, falhas de proxy e recuperação manual sem manter a tabela indefinidamente.

A expiração remove apenas a memória de idempotência; nunca apaga nem reverte o lançamento, conta, meta ou movimento. Após a expiração, a mesma chave pode iniciar nova operação, mas as regras de domínio continuam valendo (por exemplo, uma conta já paga não pode ser paga de novo).

Limpeza operacional:

```sql
DELETE FROM idempotency_records WHERE expires_at < now();
```

Deve ser executada por rotina de manutenção com papel privilegiado, fora da API, preferencialmente após backup e monitorando o crescimento da tabela. A API mantém `DELETE` no próprio escopo para futura limpeza por tenant, mas não executa expurgo automático destrutivo.

## RLS e segurança

- `ENABLE ROW LEVEL SECURITY` + `FORCE ROW LEVEL SECURITY`;
- policy `tenant_isolation` por `app.tenant_id`;
- API tem `SELECT, INSERT, UPDATE, DELETE`; worker da outbox não tem acesso;
- a consulta de replay inclui `tenant_id`, `user_id`, `operation` e `key_hash`;
- a chave bruta não aparece em logs, tabela, auditoria ou resposta;
- conflito é registrado apenas como erro HTTP sanitizado;
- não há privilégio `SUPERUSER` ou `BYPASSRLS`.

## Frontend

`frontend/src/lib/api.ts` fornece `newIdempotencyKey()` e `idempotencyHeaders()`.

Comportamento:

- cada nova operação de criação gera uma chave;
- após falha/retry, a mesma chave é reutilizada;
- após sucesso, a chave é descartada;
- pagar/desfazer pagamento mantêm uma chave pendente por conta e ação;
- aporte/retirada mantêm uma chave por abertura do formulário;
- conflito `409` é exibido pela mensagem segura da API;
- o botão desabilitado continua sendo apenas UX, não a garantia.

Refresh/fechamento da página descarta a chave em memória. A API continua impedindo duplicação somente quando a mesma chave é reenviada; após refresh, um novo envio é uma nova operação lógica. O E2E valida refresh após sucesso e ausência de duplicidade na interface.

## Testes

- `tests/unit/test_idempotency.py`: validação de chave e fingerprint canônico.
- `tests/integration/test_financial_idempotency.py`: replay, conflito, rollback, chaves diferentes, concorrência com 10 clientes, pagamento, desfazer, aporte, isolamento por tenant/usuário, orçamento e recorrência.
- `tests/integration/test_postgres_rls.py`: migration, RLS, privilégios da API e ausência de acesso do worker.
- `frontend/src/test/idempotency.test.ts`: geração/envio da chave.
- `frontend/e2e/idempotency.spec.ts`: retry de lançamento, pagamento, aporte, conflito, refresh e nova operação com nova chave.

## Limitações

- A política sem chave mantém compatibilidade legada; clientes que omitirem o header não recebem a garantia.
- A chave em memória não sobrevive a refresh; ver comportamento documentado acima.
- Limpeza automática da tabela não está agendada no repositório; é uma tarefa operacional.
- O `response_payload` é o contrato público da operação, não um payload pessoal bruto.
- A garantia depende do PostgreSQL único da aplicação; múltiplas bases independentes exigiriam coordenação externa.
