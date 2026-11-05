# FortexaHome — Recuperação de licença e backoffice de suporte

## 1. Arquitetura administrativa

O FortexaHome não reutiliza `owner`/`member` como administradores globais. O suporte possui identidade e sessão próprias:

- `support_operators` — operador com e-mail cifrado, hash de busca, nome cifrado, senha Argon2id, papel, estado, lockout e auditoria de último acesso.
- `support_sessions` — sessões opacas com token hash, expiração, revogação e operador.
- `support_audit_logs` — trilha append-only de operações sensíveis, com operador, operação, pedido/licença/outbox, justificativa, resultado e data.
- Cookie `fh_support_session`, separado do cookie de cliente `fh_session`, restrito a `/api/v1/support`.
- Rotas de suporte: `/api/v1/support/*`; interface em `/backoffice`.

O backoffice é global por desenho operacional, mas só lê pedidos, licenças, eventos e metadados de outbox. Ele não lê usuários/tenants completos, não altera valores, não marca compra como paga e não reativa licença revogada.

## 2. Papéis e permissões

| Papel | Permissões | Pode |
| --- | --- | --- |
| `support_read` | `support:read` | Consultar dashboard, pedidos, detalhes, licenças, outbox e auditoria. |
| `support_operator` | `support:read`, `support:act` | Tudo de leitura e solicitar instruções de recuperação. |

Não existe papel administrativo global, `is_admin` de frontend, e-mail hardcoded, senha fixa ou token eterno. O papel worker da outbox não recebe acesso às tabelas administrativas.

## 3. Provisionamento de operador

O provisionamento é feito por CLI no host, usando o mesmo `SessionLocal` e RLS:

```sh
python -m app.cli.provision_support_operator \
  --email operador@exemplo.com \
  --name "Operador de Suporte" \
  --role support_read \
  --password-stdin \
  --dry-run
# revise e efetive
python -m app.cli.provision_support_operator \
  --email operador@exemplo.com \
  --name "Operador de Suporte" \
  --role support_read \
  --password-stdin \
  --apply
```

- Senha mínima de 12 caracteres, lida de `stdin`.
- Reexecução é idempotente pelo hash do e-mail.
- Para desativar: `--state disabled --apply`.
- Para reativar: `--state active --apply`.
- Um operador desativado não consegue autenticar.
- Não há autopromoção pela interface. A rotação de senha também é feita por CLI.

## 4. Autenticação e proteção

- Login em `POST /api/v1/support/auth/login`, limitado por IP + e-mail, com Argon2id e lockout após falhas. O login do cliente usa um lockout progressivo distribuído separado; consulte [account-lockout.md](account-lockout.md).
- Sessão em cookie httpOnly/Secure em produção/SameSite, com expiração própria.
- Logout em `POST /api/v1/support/auth/logout`.
- `GET /api/v1/support/auth/me` retorna operador e permissões.
- Rotas administrativas exigem cookie de suporte; cookie de cliente não serve.
- Toda autorização é validada no backend; o frontend só oculta ações não permitidas.
- CSRF/origem usam o middleware global existente; não há endpoint administrativo público.

## 5. Recuperação de licença pelo cliente

A recuperação não revela o código original. O código é armazenado como HMAC e não pode ser revertido.

Fluxo:

1. Cliente acessa `/entrar`, aba **Recuperar acesso**.
2. Informa nome, e-mail da compra e senha.
3. `POST /api/v1/auth/recover-license` responde sempre com mensagem genérica.
4. Se o e-mail já pertence a uma conta, o backend enfileira `password_reset` (com cooldown por e-mail).
5. Se há compra paga com licença ainda não vinculada, o backend cria/reutiliza uma ativação pendente e enfileira `activation_verification`.
6. O cliente confirma com `POST /api/v1/auth/recover-license/confirm` usando e-mail + código de 6 dígitos.
7. A confirmação reutiliza `confirm_activation`: cria tenant/usuário, vincula a licença e cria sessão.
8. Se a licença já estiver vinculada, nenhum segundo tenant é criado; a recuperação é encaminhada para senha.

Garantias:

- Resposta genérica para e-mail conhecido/desconhecido.
- Sem `activation_id` na resposta, reduzindo enumeração.
- Cooldown por hash normalizado de e-mail e por licença.
- Rate limit por IP nos endpoints.
- Código de 6 dígitos, HMAC vinculado à ativação, expiração de 10 minutos e limite de tentativas.
- Pedidos `refunded`, `chargeback`, `cancelled`, `pending` ou licenças suspensas/canceladas/expiradas não geram recuperação.
- Outbox transacional existente; nenhum segundo worker ou provedor de e-mail.
- Auditoria com evento e identificador interno da licença, sem código, token ou PII.

## 6. Backoffice

### Rotas

- `/backoffice/login`
- `/backoffice` — dashboard operacional.
- `/backoffice/pedidos` — busca/filtros por transação, estado e licença.
- `/backoffice/pedidos/:id` — detalhe, eventos, licença e entregas.
- `/backoffice/licencas` — licenças mascaradas.
- `/backoffice/outbox` — metadados de entrega.
- `/backoffice/auditoria` — trilha append-only.

### Operações permitidas

- Consultar pedidos por transação/produto/estado.
- Consultar estado da licença, ativação, tenant e entregas.
- Consultar eventos comerciais e histórico de tentativas.
- Consultar outbox por estado/tipo/transação.
- Solicitar instruções de recuperação ao comprador, com justificativa obrigatória.
- Consultar auditoria.

### Operações proibidas

- Alterar valor, moeda ou produto de uma compra.
- Marcar compra como paga manualmente.
- Reverter chargeback/protesto/reembolso.
- Reativar licença revogada sem evento comercial válido.
- Ver payload criptografado/descriptografado, hash de licença, HMAC, tokens ou senha.
- Consultar usuários/tenants fora do necessário.
- Requeue genérico de outbox pela interface.
- Editar ou apagar auditoria.

Mensagens `dead` aparecem com erro sanitizado e exigem recuperação manual pelo procedimento de host já documentado em `docs/email-outbox.md`.

## 7. Ação de instruções de recuperação

`POST /api/v1/support/orders/{order_id}/recovery-instructions`

- Exige `support:act`.
- Exige justificativa de 10 a 500 caracteres.
- Só aceita pedido existente, não terminal e com licença entregável.
- Enfileira `license_recovery_instructions` na outbox, sem revelar código/token.
- Idempotência por licença/hora; segunda solicitação na mesma hora retorna `409`.
- Envia ao e-mail de compra original, descriptografado apenas no servidor.
- Registra auditoria de sucesso, recusa ou duplicidade.
- Se a outbox estiver `dead`, a interface orienta o procedimento de host; não há requeue genérico.

## 8. Auditoria

Toda ação sensível registra:

- operador (`operator_id` e e-mail mascarado em `details`);
- operação;
- pedido/licença/mensagem quando aplicável;
- justificativa;
- resultado (`success`, `rejected_terminal`, `rejected_license`, `rejected_email`, `rejected_duplicate`);
- data/hora.

A tabela `support_audit_logs` é append-only: o papel operacional recebe apenas `SELECT` e `INSERT`. `UPDATE`/`DELETE` são negados e testados.

## 9. RLS e isolamento

- `support_operators`, `support_sessions` e `support_audit_logs` usam RLS/FORCE RLS.
- Operador só vê a própria sessão/registro; login vê apenas o e-mail hash correspondente.
- Contextos `app.support_operator_id`, `app.support_session_token_hash`, `app.support_login_email_hash` e `app.support_provisioning` são locais à transação.
- O suporte tem policies de leitura explícitas em `orders`, `payment_events`, `licenses` e metadados de `email_outbox`.
- O worker não recebe grants nas tabelas administrativas.
- Recuperação do cliente usa policies por hash de e-mail para pedidos e pendências.
- Nenhum `BYPASSRLS`, superuser ou compartilhamento de credencial do PostgreSQL é usado.

## 10. Limitações conhecidas

- O código original da licença não é recuperável; a recuperação usa código de ativação enviado ao e-mail de compra.
- Se o comprador perdeu acesso ao e-mail original, o suporte só pode orientar; não há alteração de e-mail.
- A interface não faz requeue de mensagens `dead`; isso continua sendo operação de host.
- Não há reconciliação com API Hotmart nem reversão automática de protesto/chargeback.
- O provisionamento/rotação de senha de operador é feito por CLI, não pela interface; a identidade humana dessa operação depende da auditoria de acesso ao host.
- Se o mesmo e-mail tiver várias compras não ativadas, a recuperação seleciona a compra mais recente; as demais podem ser tratadas pelo suporte.
- Rate limit de identificador é aplicado no fluxo de ativação/recuperação; o limite HTTP agora é distribuído no PostgreSQL e o login/ações de suporte usam IP + e-mail ou operador + IP (Missão 07).
- Logs do backoffice e da outbox são sanitizados por `core/log_safety.py`; payloads, PII, tokens e segredos não são registrados (Missão 11).
- A interface administrativa não foi testada em navegador real nesta missão; typecheck/build e testes de backend cobrem o contrato.

## 11. Privacidade e solicitações de titulares (Missão 13)

O backoffice possui a rota `/backoffice/privacidade`, apoiada por:

- `GET /api/v1/support/privacy/requests`
- `GET /api/v1/support/privacy/requests/{id}`
- `POST /api/v1/support/privacy/requests/{id}/approve`
- `POST /api/v1/support/privacy/requests/{id}/reject`

Controles:

- `support_read`: lista e consulta protocolo, status, escopo, retenção e histórico de eventos, com dados minimizados.
- `support_operator`: aprova ou rejeita com justificativa obrigatória de 10 a 500 caracteres.
- Aprovar executa exclusão/anonimização somente conforme a política; owner com outros usuários ativos retorna `409`.
- A rejeição não apaga dados e exige justificativa.
- Toda ação gera `privacy_request_events` e `support_audit_logs` com operador mascarado, protocolo, data e resultado.
- O suporte não recebe `SUPERUSER`/`BYPASSRLS`; usa policies por `app.support_operator_id`.
- O worker da outbox não acessa `privacy_requests`, eventos ou tombstones.

O procedimento completo está em [data-subject-request-sop.md](data-subject-request-sop.md); a política de dados está em [lgpd-data-lifecycle.md](lgpd-data-lifecycle.md) e [data-retention-matrix.md](data-retention-matrix.md).
