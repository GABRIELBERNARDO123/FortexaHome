# FortexaHome — Auditoria de prontidão para lançamento comercial

**Data da auditoria:** 01/11/2026 · **Atualização final:** 02/11/2026  
**Repositório:** `/home/sicredi/FortexaHome/fortexahome`  
**Commit base:** `8cbd7f7` + alterações locais não commitadas  
**Modo:** auditoria inicial somente leitura + implementação local nas Missões 02–11; nenhum commit, push, deploy, acesso a VPS/banco de produção, Resend real ou Hotmart real foi realizado.  
**Restrição respeitada:** `HOTMART_ENABLED=false`; nenhum acesso a VPS, banco de produção, Resend ou Hotmart.

> Esta auditoria é técnica e baseada no código real. Onde a validação não pôde ser feita em runtime (navegador, Resend real, Hotmart real), o texto diz explicitamente “não verificado em execução”.

---

## 1. Resumo executivo

O FortexaHome é uma aplicação real, coerente e tecnicamente acima da média para um SaaS de finanças domésticas: FastAPI + PostgreSQL com RLS/FORCE RLS, React/Vite, outbox transacional criptografada, ativação de licença com confirmação de e-mail, integração Hotmart 2.0.0 idempotente e separação de papéis PostgreSQL.

O produto **evoluiu de auditoria inicial para um candidato a homologação**, mas ainda não deve ser vendido sem aceitar/fechar os P2 remanescentes e validar os serviços externos. As Missões 02–11 resolveram os P0, o caminho de catálogo/preflight, a recuperação de licença e o backoffice, a confiabilidade do domínio financeiro, a jornada E2E, a gestão de categorias, o rate limit distribuído, a reconciliação Hotmart, o lockout progressivo e o hardening de rotas legadas/logs.

Permanecem como bloqueadores de lançamento:

1. **Validação externa real** de Resend e Hotmart em homologação, com compra/webhook controlados; o código usa `HOTMART_ENABLED=false` nesta auditoria.
2. **Configuração operacional de produção** (segredos, URLs, proxy confiável e catálogo) fora do repositório; o ambiente local não substitui o preflight de produção.
3. **P2 remanescentes** de segurança, retenção/LGPD, busca/filtros e visibilidade de entrega, além de integrações externas ainda não homologadas.
4. A cobertura de componentes por página ainda é parcial; os fluxos críticos estão cobertos por integração e Playwright.

> **Atualização das Missões 02–12:** P0-01/P0-02, P1-01/P1-02/P1-03/P1-04/P1-05/P1-06/P1-07, P2-01/P2-03/P2-04/P2-05/P2-06/P2-07/P2-10 e P2-02 foram tratados. A Missão 11 desabilitou a rota legada em produção e centralizou redaction/request ID; a Missão 12 adicionou idempotência financeira transacional no PostgreSQL.

### Números da auditoria

| Métrica | Resultado |
| --- | --- |
| Funcionalidades inventariadas | 49 |
| Comprovadamente concluídas (implementação + evidência automatizada) | **22/49 = 44,9%** |
| Implementadas com lacuna de teste ou defeito conhecido | 23/49 = 46,9% |
| Ausentes | 4/49 = 8,2% |
| Prontidão funcional ponderada (`concluída=1`, `parcial=0,5`, `ausente=0`) | **68,4%** |
| Problemas P0 | **0 remanescentes (2 resolvidos na Missão 02)** |
| Problemas P1 | **0 remanescentes (7 identificados; todos corrigidos)** |
| Problemas P2 | **3 abertos/adiados (P2-09, P2-11, P2-12); P2-01/P2-02/P2-03/P2-04/P2-05/P2-06/P2-07/P2-08/P2-10 resolvidos** |
| Escopo comercial | **Produto individual:** uma licença por comprador; sem anúncio de compartilhamento familiar nesta fase |
| Problemas P3 | **6 remanescentes (8 identificados; P3-01 e P3-04 corrigidos)** |
| Testes backend no container | **325 aprovados, 0 reprovados** (129 unitários + 196 integração PostgreSQL) |
| Testes frontend | **7 component tests + 33 E2E Playwright aprovados** |
| Cobertura backend no container | **85%** |
| TypeScript | aprovado (`tsc -b`) |
| Build de produção frontend | aprovado |
| Build das imagens Docker `api` e `web` | aprovado |
| Head Alembic | `20261104_18` (head único) |

### Método do percentual

Cada uma das 49 capacidades recebeu um status:

- **Concluída**: backend + frontend + fluxo coerente + pelo menos uma evidência automatizada direta (teste unitário/integração) daquela capacidade ou de seu núcleo.
- **Parcial**: implementada, mas sem teste suficiente, sem interface, com defeito conhecido ou com dependência operacional não resolvida.
- **Ausente**: não existe no código ou existe apenas como intenção/modelo.

O percentual “comprovadamente concluídas” é `concluídas / total`. O percentual ponderado é `(concluídas × 1 + parciais × 0,5) / total`. Ele não mede esforço restante nem qualidade visual; mede evidência de conclusão. Uma tela existir não conta como conclusão.

### Limitações desta auditoria

- As Missões 05 e 06 adicionaram 28 cenários Playwright em Chromium headless. Safari/Firefox e leitores de tela reais não foram testados; a inspeção visual fina continua limitada.
- Não houve envio real pelo Resend, compra real na Hotmart, nem validação de webhook externo.
- Não houve acesso a banco de produção.
- Os testes de integração rodaram no banco descartável do perfil `tests` do Compose, conforme a documentação do projeto.
- O `.env` local foi lido apenas para conferir presença de nomes de variáveis; valores não foram expostos neste documento.

---

## 2. Arquitetura encontrada

### 2.1 Componentes

| Camada | Tecnologia | Caminho |
| --- | --- | --- |
| API | FastAPI 0.115 + SQLAlchemy 2 + Pydantic 2 | `backend/app` |
| Banco | PostgreSQL 16 com RLS/FORCE RLS, papéis separados | `backend/migrations` |
| Frontend | React 18 + Vite 6 + TypeScript | `frontend/src` |
| E-mail | Outbox transacional + worker independente + Resend | `backend/app/services/email_outbox_service.py`, `backend/app/workers/email_outbox.py` |
| Pagamento | Webhook Hotmart 2.0.0 + sandbox HMAC legado | `backend/app/integrations/payments` |
| Proxy | Nginx com CSP, proxy `/api`, fallback SPA | `frontend/nginx.conf` |
| Orquestração | Docker Compose: `db`, `migrate`, `api`, `email-worker`, `web`; perfil `tests` | `docker-compose.yml` |

### 2.2 Domínios e rotas

- **Autenticação e ativação:** `/api/v1/auth/*` (`activate`, `activate/confirm`, `activate/resend`, `login`, `logout`, `me`, `forgot-password`, `reset-password`, `change-password`, `sessions`).
- **Financeiro:** `/api/v1/transactions`, `/bills`, `/cards`, `/budgets`, `/goals`, `/categories`, `/dashboard`, `/reports`.
- **Conta:** `/api/v1/account`, `/api/v1/account/export`.
- **Licença:** `/api/v1/license`.
- **Webhooks:** `/api/v1/webhooks/hotmart`, `/api/v1/webhooks/payments/{provider}`.
- **Saúde:** `/api/v1/health`.

### 2.3 Banco, RLS e papéis

- Tabelas por tenant usam RLS e FORCE RLS (`categories`, `transactions`, `bills`, `credit_cards`, `budgets`, `goals`, `goal_movements`, `subscriptions`, `tenants`, `users`, `sessions`, `password_reset_tokens`, `audit_logs`).
- Licenças têm policies por tenant, por `license_code_hash`, por pedido/provedor e um trigger `guard_license_update()` que separa ativação de revogação e impede alteração de campos comerciais.
- `products`, `orders` e `payment_events` têm RLS; orders/events são escopados por `app.payment_provider`.
- `pending_activations` usa RLS sem tenant, alcançada por `app.pending_activation_id` ou por licença visível.
- `email_outbox` usa RLS; a API só lê metadados de ativação/reset; o worker usa `OUTBOX_DB_USER` sem herança, sem `SUPERUSER` e sem `BYPASSRLS`.
- O papel operacional é validado no startup em produção: precisa ser `APP_DB_USER`, sem `SUPERUSER`/`BYPASSRLS` (`backend/app/core/database.py:77-90`).

### 2.4 Cadeia de migrations

Ordem real verificada:

`097fe0849068` → `20261026_01` → `20261026_02` → `20261031_03` → `20261031_04` → `20261031_05` → `20261031_06` → `20261031_07` → `20261031_08` → `20261031_09` → `20261031_10` → `20261031_11` → `20261031_12` → `20261101_13` → `20261102_14` (head único).

O head vigente é `20261102_14` (rate limit distribuído); a documentação operacional deve sempre consultar `alembic heads`.

### 2.5 Modelo comercial

1. Produto interno no catálogo (`products`).
2. Compra aprovada na Hotmart gera `orders`, `payment_events` e `licenses` na mesma transação.
3. A licença é entregue por e-mail via outbox (`license_delivery`).
4. O comprador acessa `/entrar`, escolhe “Ativar licença”, informa licença, nome, e-mail e senha.
5. Um código de 6 dígitos confirma o e-mail; somente depois disso são criados tenant, usuário, categorias padrão, sessão e vínculo da licença.
6. Reembolso/cancelamento revoga a licença e as sessões; chargeback/protesto suspende.

---

## 3. Inventário das funcionalidades

Legenda: **C** = concluída com evidência automatizada; **P** = implementada com lacuna; **A** = ausente.

| # | Funcionalidade | Backend | Frontend | Evidência de teste | Status |
| --- | --- | --- | --- | --- | --- |
| 1 | Início de ativação por licença | Sim | Sim | `test_activation_flow.py:132` | **C** |
| 2 | Confirmação por código de e-mail | Sim | Sim | `test_activation_flow.py` (vários) | **C** |
| 3 | Reenvio, cooldown, expiração e limite de tentativas | Sim | Sim | `test_activation_flow.py:188-470` | **C** |
| 4 | Login | Sim | Sim | `test_activation_flow.py:955-1030` (login legado positivo/negado) | **C** |
| 5 | Persistência de sessão por cookie | Sim | Sim | `test_activation_flow.py:132` (`/auth/me` após confirmação) | **C** |
| 6 | Logout | Sim | Sim | Nenhum teste direto | **P** |
| 7 | Recuperação de senha | Sim | Sim | `test_email_outbox.py:199-310` | **C** |
| 8 | Alteração de senha e revogação de outras sessões | Sim | Sim | Nenhum teste direto | **P** |
| 9 | Listagem e revogação de sessões | Sim | Sim | Nenhum teste direto | **P** |
| 10 | Status da licença na conta | Sim | Sim | Nenhum teste direto | **P** |
| 11 | Entrega de licença por e-mail/outbox | Sim | — | `test_activation_flow.py:617`, `test_email_outbox.py:127` | **C** |
| 12 | Webhook Hotmart, idempotência e ordenação | Sim | — | `test_hotmart_payload.py`, `test_hotmart_integration.py` | **C** |
| 13 | Order Bump pela própria transação | Sim | — | `test_hotmart_integration.py:344-414` | **C** |
| 14 | Reembolso, chargeback, cancelamento e expiração | Sim | — | `test_hotmart_integration.py` (lifecycle e outbox) | **C** |
| 15 | Recuperação pós-atraso; reconciliação/protesto reversível | Sim (atraso) | — | `test_hotmart_integration.py` | **P** |
| 16 | Dashboard | Sim | Sim | Nenhum teste de domínio | **P** |
| 17 | CRUD de lançamentos | Sim | Sim | Nenhum teste de domínio | **P** |
| 18 | Filtros, pesquisa e paginação de lançamentos | Sim | Sim | Nenhum teste | **P** |
| 19 | CRUD de contas a pagar | Sim | Sim | Nenhum teste de domínio | **P** |
| 20 | Pagar/desfazer conta e lançamento automático | Sim | Sim | Nenhum teste | **P** |
| 21 | Recorrência mensal de contas | Sim | Sim | Nenhum teste | **P** |
| 22 | CRUD/arquivamento de cartões | Sim | Sim | Nenhum teste de domínio | **P** |
| 23 | Orçamentos e consumo por categoria | Sim | Sim | Nenhum teste de domínio | **P** |
| 24 | CRUD de metas | Sim | Sim | Nenhum teste de domínio | **P** |
| 25 | Movimentos de metas e histórico | Sim | Sim | Nenhum teste; corrida identificada | **P** |
| 26 | Relatórios mensais | Sim | Sim | Nenhum teste de domínio | **P** |
| 27 | Exportação CSV de lançamentos | Sim | Sim | Nenhum teste | **P** |
| 28 | Exportação JSON da conta | Sim | Sim | Nenhum teste | **P** |
| 29 | API de categorias (CRUD) | Sim | Sim | `test_financial_domain.py` (CRUD, uso, permissões, isolamento) | **C** |
| 30 | Gestão de categorias pela interface | Sim | Sim | `categories-management.spec.ts`; arquivamento/reativação | **C** |
| 31 | Configurações de conta, tema e fuso | Sim | Sim | Nenhum teste | **P** |
| 32 | Catálogo de produto para produção | Sim (CLI) | — | `test_catalog_provisioning.py` | **C** |
| 33 | Backoffice de pedidos/licenças/suporte | Sim | Sim | `test_support_backoffice.py` | **C** |
| 34 | Recuperação de licença pelo cliente e suporte | Sim | Sim | `test_license_recovery.py`, `test_support_backoffice.py` | **C** |
| 35 | Reconciliação com API Hotmart | Sim (CLI) | — | `test_hotmart_reconciliation.py`, `test_hotmart_api_client.py` | **C** |
| 36 | Exclusão de conta / apagamento LGPD | Não | Não | Nenhum | **A** |
| 37 | Compartilhamento familiar / convite de membro | Não | Não | Nenhum | **A** |
| 38 | RLS e isolamento multi-tenant | Sim | — | `test_postgres_rls.py`, `test_activation_flow.py:504` | **C** |
| 39 | Autorização owner/member | Parcial | Parcial | `test_http_security.py:42` (owner) | **P** |
| 40 | Rate limiting distribuído | Sim | — | `test_rate_limit_distributed.py`, `test_rate_limit.py` (concorrência/429) | **C** |
| 41 | CSRF, CORS e cabeçalhos de segurança | Sim | Sim | `test_http_security.py:12-23` | **C** |
| 42 | Criptografia de PII e hashes de busca | Sim | — | `test_security_basics.py:34-53`, `test_email_outbox.py:405` | **C** |
| 43 | Testes automatizados do domínio financeiro | Sim | — | `test_financial_domain.py`; cobertura backend 85% | **C** |
| 44 | Testes de frontend/componentes | — | Parcial | 7 component tests; E2E cobre telas financeiras e idempotência | **P** |
| 45 | Testes E2E da jornada | — | Sim | Playwright: 28 cenários cliente/backoffice/categorias/responsivo | **C** |
| 46 | Responsividade | — | Sim (CSS) | Não verificado em navegador | **P** |
| 47 | Acessibilidade básica | — | Parcial | Não auditada em navegador | **P** |
| 48 | Estados de loading, erro e vazio | — | Sim | Não testados | **P** |
| 49 | Ordenação em todas as listas | Parcial | Não | Nenhum | **A** |

**Contagem:** C = 22; P = 23; A = 4; total = 49.

---

## 4. Jornada completa do cliente

### 4.1 Fluxo de compra até a conta utilizável

| Etapa | O que existe | Situação |
| --- | --- | --- |
| Compra na Hotmart | Produto externo, UCODE e HOTTOK configuráveis | Implementado; `HOTMART_ENABLED=false` nesta auditoria |
| Recebimento do webhook | `/api/v1/webhooks/hotmart`, HOTTOK, JSON, limite de 256 KiB, rate limit 60/min | Implementado e testado |
| Criação de pedido/licença | Transação única com `orders`, `payment_events`, `licenses` e outbox | Implementado e testado |
| Entrega da licença | E-mail `license_delivery` criptografado na outbox, worker com retry | Implementado e testado |
| Primeiro acesso | `/entrar` com abas “Entrar” e “Ativar licença” | Implementado |
| Ativação | Código de licença + nome + e-mail + senha | Implementado e testado |
| Verificação de e-mail | Código de 6 dígitos, HMAC, expiração de 10 min, até 5 tentativas | Implementado e testado |
| Criação da conta | Tenant, usuário, categorias padrão, licença vinculada, sessão | Implementado e testado |
| Uso do produto | Dashboard, lançamentos, contas, cartões, orçamento, metas, relatórios | Implementado; CRUD e cálculos cobertos por integração/E2E |
| Logout | Revoga a sessão e limpa o cookie | Implementado; sem teste |
| Reembolso/chargeback | Revoga/suspende licença e sessões | Implementado; gaps P1-01/P1-04 |

### 4.2 Primeiro acesso e autenticação

- **Ativação:** `AuthPage.tsx` concentra login, ativação e confirmação; o frontend não cria sessão antes da confirmação do código. O teste `AuthPage.test.tsx` comprova que “guest” permanece até `/auth/activate/confirm`.
- **E-mail:** o backend responde `202` após persistir a solicitação; não promete entrega. O frontend informa que o worker está processando o envio.
- **Senha:** mínimo de 8 caracteres no schema e no HTML; Argon2id no servidor.
- **Sessão:** cookie `fh_session` httpOnly, `SameSite=Lax`, `Secure` obrigatório em produção, token opaco com hash SHA-256 no banco.
- **Recuperação:** `forgot-password` é genérico; em `DEBUG` devolve `reset_token` para conveniência local. Em produção `DEBUG=false` é obrigatório e o token não é devolvido.
- **Logout:** funciona mesmo com licença inativa porque usa `get_auth_context_soft`.

### 4.3 Navegação e funcionalidades financeiras

Todas as rotas de `App.tsx:47-54` existem: dashboard, lançamentos, contas, cartões, orçamento, metas, relatórios e configurações.

Operações verificadas por leitura de código:

- **Lançamentos:** criar, editar, excluir, busca por descrição/observação, filtro por tipo/categoria, paginação de 100. Lançamentos gerados por conta paga são bloqueados para edição/exclusão e precisam ser tratados na conta.
- **Contas:** criar, editar, excluir, pagar, desfazer pagamento, gerar próxima recorrência. O pagamento cria uma despesa vinculada; desfazer remove a despesa.
- **Cartões:** criar, editar, arquivar (soft delete) e acompanhar limite usado/disponível no mês.
- **Orçamentos:** definir limite por categoria/mês, editar, excluir e comparar com gasto realizado.
- **Metas:** criar, editar, excluir, aportar, retirar e ver histórico; conclusão automática ao atingir o alvo.
- **Relatórios:** resumo mensal, distribuição por categoria, histórico e exportação CSV.
- **Configurações:** perfil, tema, fuso, licença, troca de senha, sessões ativas, exportação JSON/CSV e logout.

### 4.4 Estados e qualidade percebida

- **Loading:** skeletons nas listas e cards; spinner em botões.
- **Erro:** `ErrorState` com “Tentar novamente” nas principais listas; toasts para erros de ação.
- **Vazio:** estados vazios com CTA em lançamentos, contas, cartões, orçamento, metas, relatórios e dashboard.
- **Indisponibilidade da API:** `errorMessage` converte `TypeError` em mensagem de conexão; as telas exibem `ErrorState`.
- **Validação:** HTML `required/minLength`, parser de moeda BRL e mensagens de erro do backend.
- **Responsividade:** há breakpoints em 1280, 1100, 1024, 920, 720 e 480 px; sidebar vira drawer; tabelas viram cartões em 720 px; modais se aproximam do rodapé.
- **Acessibilidade:** labels associados por `useId`, foco visível, foco preso em modal, `aria-label` em ícones, `role="alert"` em erros, `aria-live` em toasts e `prefers-reduced-motion`. Gráficos e barras de progresso, porém, não têm alternativa textual (P3-06).
- **Não verificado em execução:** não houve navegador real; contraste, breakpoints e foco não foram medidos visualmente.

### 4.5 O que impede uma compra real de virar conta utilizável

1. ~~Produto interno não cadastrado em produção (P0-01) → webhook retorna `503`.~~ Resolvido na Missão 02.
2. ~~Variáveis de ambiente obrigatórias ausentes (P0-02) → migration/ativação falham.~~ Detecção implementada; o ambiente operacional ainda precisa ser preenchido.
3. ~~Licença pode não ser entregue se o e-mail ficar `dead` e não houver recuperação (P1-02).~~ Resolvido com recuperação pelo cliente/suporte; `dead` continua exigindo operação de host.
4. ~~Aprovação após atraso/protesto pode manter a licença suspensa (P1-01).~~ Resolvido para atraso; protesto/chargeback permanecem terminais.
5. ~~Reembolso pode não cancelar um e-mail de licença já enfileirado (P1-04).~~ Resolvido; inclui revalidação do worker e limitação de mensagem já aceita.
6. ~~Suporte não tem backoffice para localizar pedido/licença e reenviar/revogar (P1-07).~~ Resolvido na Missão 04.

---

## 5. Auditoria de segurança e multi-tenancy

### 5.1 Pontos fortes confirmados

| Controle | Evidência | Avaliação |
| --- | --- | --- |
| Isolamento por tenant | RLS/FORCE RLS em 19 tabelas; `test_postgres_rls.py:39-62` | Forte |
| Contexto RLS | `set_db_context()` só aceita chaves conhecidas; GUC local à transação (`core/database.py:23-66`) | Forte |
| Papel operacional | Produção exige `APP_DB_USER` sem `SUPERUSER`/`BYPASSRLS` (`core/database.py:77-90`) | Forte |
| Worker isolado | `OUTBOX_DB_USER` sem herança/grants amplos; `test_email_outbox.py:99` | Forte |
| Licenças | Policies por código/pedido/provedor + trigger de imutabilidade (`20261031_04`) | Forte |
| Senhas | Argon2id com `time_cost=3`, `memory_cost=65536`, `parallelism=4` | Forte |
| Tokens | Sessão, reset, licença e código de e-mail são hasheados/HMAC; nenhum token em claro no banco | Forte |
| PII | AES-GCM com contexto de campo; e-mail tem HMAC de busca e versão mascarada | Forte |
| Sessão | Cookie httpOnly, Secure em produção, SameSite, expiração, revogação | Forte |
| CSRF | Origem validada em métodos mutáveis; `Sec-Fetch-Site`; webhooks excluídos por terem autenticação própria | Forte |
| Cabeçalhos | CSP, X-Frame-Options, nosniff, Referrer-Policy, Permissions-Policy, HSTS em produção | Forte |
| Webhooks | HOTTOK em tempo constante, Content-Type, limite de corpo, idempotência, advisory locks | Forte |
| Rate limit e lockout | Token bucket atômico + lockout progressivo por conta, chaves HMAC, `Retry-After`, fail-open e proxies confiáveis | Forte |
| Logs | Redaction central, request ID e sanitização de exceções; sem payload/token/PII | Forte |

### 5.2 Separação entre frontend, backend e banco

- O frontend nunca decide autorização: recebe `403` quando a licença está inativa e apenas exibe o bloqueio.
- O backend valida licença em **todas** as rotas autenticadas via `get_auth_context` (`core/deps.py:38-87`).
- Operações por ID sempre filtram `tenant_id` (`transaction_service.py:101-105`, `bill_service.py:57-61`, `category_service.py:35-39`, `goal_service.py:81-85`, etc.).
- RLS é a segunda barreira; os testes cobrem troca de IDs e URLs entre tenants/provedores.
- **Risco residual:** o isolamento entre tenants agora é exercitado via API para transações, contas e metas, além de categorias/licenças/pedidos. Ainda não há caso dedicado para todos os endpoints de cartões/orçamentos/relatórios; a cobertura é substancial, mas não exaustiva.

### 5.3 Riscos e achados

- **P2-01 (resolvido para saldo):** movimentos de meta usam `FOR UPDATE` e teste concorrente; a idempotência dos POSTs foi concluída no P2-02.
- **P2-03 (resolvido):** lockout progressivo distribuído por conta, com cooldown limitado, expiração e reset em sucesso.
- **P2-04 (resolvido):** o rate limit agora usa token bucket atômico no PostgreSQL, compartilhado entre réplicas e reinícios.
- **P2-10 (resolvido):** a reconciliação Hotmart consulta somente transações locais, registra observações imutáveis e aplica apenas transições seguras; endpoints públicos e worker não foram alterados.
- **P2-05 (resolvido):** rota legada não é registrada em produção; sandbox exige flag explícita fora de produção.
- **P2-06 (resolvido):** `APP_BASE_URL` é validado como HTTPS em produção; DNS/TLS reais continuam pendentes de homologação.
- **P2-07 (resolvido):** logger central sanitiza mensagens, argumentos, headers e tracebacks; request ID correlaciona erros sem PII.
- **P3-02:** `SECRET_KEY` é exigido, mas não é usado em nenhum fluxo; isso induz o operador a acreditar que há uma camada de assinatura que não existe.

### 5.4 Dados pessoais

- E-mail e nome de usuário são cifrados; a busca usa HMAC.
- E-mail do comprador em `orders` é cifrado; hash para busca.
- Payload da outbox é cifrado e apagado após `sent`/`cancelled`; `dead` é apagado após retenção.
- Código de licença e código de verificação não são armazenados em claro.
- **Fluxo de exclusão/anonimização de conta** implementado no P2-08 (Missão 13), com reautenticação, protocolo, suporte e tombstones de backup.

---

## 6. Auditoria comercial (Hotmart e licenciamento)

### 6.1 O que está implementado

- Webhook `POST /api/v1/webhooks/hotmart` com HOTTOK, `Content-Type`, limite de 256 KiB, rate limit 60/min e retorno `503` em falha transitória para permitir retry.
- Validação de `version=2.0.0`, eventos permitidos, `id`, `creation_date`, produto, comprador e compra.
- UCODE diferente do configurado retorna `{"status":"ignored"}` sem efeitos.
- Pedido identificado pela transação própria; Order Bump usa a própria transação e não a do pai.
- Valores externos (`price`, `full_price`) são gravados apenas em `provider_*`; o acesso usa o preço interno do catálogo.
- Idempotência por evento e por transação, com advisory locks e constraints.
- Licença única por pedido; e-mail de entrega na mesma transação.
- Eventos negativos atualizam pedido/licença e revogam sessões.
- Ordenação por `creation_date` + prioridade de estado; eventos antigos não revertem estados.
- Worker com retry, backoff, jitter, lease, dead letter e recuperação manual limitada por CLI.
- Resend com `Idempotency-Key` estável por evento.

### 6.2 O que ainda impede uma compra real de gerar uma conta utilizável

> Tabela histórica da auditoria inicial. As correções posteriores (catálogo/preflight, recuperação, backoffice, cancelamento de entrega, testes e reconciliação) estão detalhadas nas seções 13–19.

| Bloqueador | Impacto |
| --- | --- |
| Produto interno não pode ser cadastrado em produção por comando/API | Toda compra retorna `503` até intervenção manual no banco |
| `.env` incompleto | Migration e ativação falham antes de qualquer venda |
| Aprovação após atraso/protesto não reativa licença | Cliente pagou e continua bloqueado |
| E-mail de licença `dead` sem recuperação pelo cliente | Cliente não consegue ativar |
| Reembolso não cancela e-mail de licença enfileirado | Cliente reembolsado recebe código de ativação |
| Sem backoffice de pedidos/licenças | Suporte não consegue reenviar, revogar ou consultar com segurança |
| Sem reconciliação Hotmart | Divergências dependem de inspeção manual do banco |

### 6.3 Política de estados: comportamento real

| Evento | Efeito no código | Avaliação |
| --- | --- | --- |
| `PURCHASE_APPROVED` | Se pedido `pending`, cria licença e entrega; se licença suspensa temporária, restaura `pending`/`active` | Recuperação implementada e testada |
| `PURCHASE_REFUNDED` | Pedido `refunded`, licença `cancelled`, sessões revogadas e entrega cancelada | Implementado com testes |
| `PURCHASE_CHARGEBACK` | Pedido `chargeback`, licença `suspended`, sessões revogadas | Sem reversão automática |
| `PURCHASE_PROTEST` | Tratado como chargeback | Sem reversão automática |
| `PURCHASE_CANCELED` / `EXPIRED` | Pedido `cancelled`, licença `cancelled` se existir | Terminal |
| `PURCHASE_DELAYED` | Pedido `pending`, licença suspensa, sessões revogadas; entrega adiada | Aprovação posterior mais nova recupera |
| `PURCHASE_COMPLETE` / `BILLET_PRINTED` | Apenas registro | Correto |

### 6.4 Reembolso, chargeback, cancelamento e suspensão

- Reembolso/chargeback/cancelamento revogam sessões imediatamente; o acesso é bloqueado no próximo request porque `get_auth_context` revalida a licença.
- Não há e-mail transacional avisando o cliente sobre reembolso/chargeback/cancelamento/suspensão.
- Não há reativação automática após resolução de chargeback/protesto.
- Não há política de retenção de dados após revogação além do que está no banco.

### 6.5 Entrega de e-mail, retry e falhas

- Outbox cifrada, claim com `SKIP LOCKED`, lease, backoff exponencial com jitter e limite de tentativas.
- `activation_verification` expirada é cancelada antes do envio.
- `password_reset` é revalidado antes do envio; token usado/expirado cancela a mensagem.
- `license_delivery` não tem revalidação de licença antes do envio; por isso um reembolso pode não impedir a entrega (P1-04).
- `requeue_dead` não permite recuperar `activation_verification` (precisa de novo código) e permite uma recuperação para `license_delivery`, mas apenas por CLI no host (P1-02/P1-07).

---

## 7. Resultado dos testes

### 7.1 Comandos executados e resultados

| Comando | Diretório | Resultado |
| --- | --- | --- |
| `npm test -- --reporter=verbose` | `frontend` | **5 aprovados**, 3 arquivos; Playwright: **28 E2E aprovados** |
| `npm run typecheck` | `frontend` | **Aprovado** (`tsc -b --pretty false`) |
| `npm run build` | `frontend` | **Aprovado**; assets Vite gerados |
| `npm run test:e2e` | `frontend` | **28 aprovados**, 0 reprovados (Playwright/Chromium) |
| `docker compose --env-file .env.example --profile tests run --build --rm tests` | raiz | **325 aprovados**, 0 reprovados; cobertura total 85% |
| `docker compose --env-file .env.example --profile tests run --rm tests pytest --collect-only -q` | raiz | 129 unitários + 196 integração = 325 |
| `docker compose --env-file .env.example --profile tests run --rm tests alembic heads` | raiz | `20261104_18 (head)` |
| `docker compose --env-file .env.example --profile tests run --rm tests alembic history` | raiz | Cadeia linear até `20261104_18` |
| `docker compose --env-file .env.example build api web` | raiz | **Aprovado** para `fortexahome-api:local` e `fortexahome-web:local` |
| `docker compose --env-file .env.example config --quiet` | raiz | Sem erros |
| `docker compose --env-file .env config --quiet` | raiz | Avisos de `OUTBOX_DB_USER` e `OUTBOX_DB_PASSWORD` não definidos |
| `python3 -m pytest` no host | `backend` | **Não executado**: host sem `fastapi`; repetido no container com sucesso |

### 7.2 Cobertura por módulo (backend)

| Módulo | Cobertura | Observação |
| --- | --- | --- |
| `activation_service.py` | 89% | Forte |
| `email_outbox_service.py` | 71% | Forte no ciclo de entrega e retry; recuperação manual parcialmente coberta |
| `license_service.py` | 83% | Boa no fluxo Hotmart, recuperação e provisionamento; sandbox sem teste |
| `auth_service.py` | 73% | Login/ativação cobertos; logout/senha/sessões não |
| `transaction_service.py` | **93%** | CRUD, filtros, resumo, arquivamento e validação cobertos |
| `bill_service.py` | **79%** | CRUD, pagamento, desfazer, recorrência e histórico arquivado cobertos |
| `card_service.py` | **84%** | CRUD, gasto, disponível e arquivamento cobertos |
| `budget_service.py` | **97%** | CRUD, cálculo de consumo e bloqueio de categoria arquivada cobertos |
| `goal_service.py` | **99%** | CRUD, movimentos, conclusão e concorrência cobertos |
| `dashboard_service.py` | **98%** | Agregações, séries e indicadores cobertos |
| `report_service.py` | **100%** | Relatório e CSV cobertos |
| `category_service.py` | **98%** | CRUD, uso, arquivamento, reativação e proteção de padrão cobertos |
| `account_service.py` | **87%** | Configurações e exportação cobertas |
| `periods.py` | **67%** | Períodos e limites cobertos |
| `core/preflight.py` | **79%** | Ambiente, banco, rate limit e comercial |
| `core/rate_limit.py` | **84%** | Token bucket, HMAC, proxy, 429/fail-open |
| `core/log_safety.py` | **94%** | Redaction, request ID, exceções e headers |
| `main.py` | **89%** | Middleware, request ID e handlers seguros |
| `endpoints/webhooks.py` | **81%** | Rota legada condicionada ao ambiente |
| `services/login_lockout_service.py` | **75%** | Lockout progressivo, concorrência, reset e fail-open |
| `auth_service.py` | **79%** | Login com lockout, Argon2 fora de locks e reset |
| `integrations/payments/hotmart_api.py` | **78%** | OAuth, retries, 401/403/429/5xx, parsing |
| `services/hotmart_reconciliation_service.py` | **77%** | Seleção, comparação, concorrência, auditoria |
| `cli/reconcile_hotmart.py` | **84%** | Dry-run/apply, limites, JSON, validação |
| `core/config.py` | **84%** | Inclui validação de `RATE_LIMIT_HMAC_KEY`/timeout |
| `core/database.py` | **90%** | Inclui reaplicação de contexto RLS após commit |
| `main.py` | **89%** | Middleware, request ID e handlers seguros |
| `cli/provision_product.py` | 82% | Novo: provisionamento administrativo |
| **Total** | **85%** | Rate limit e reconciliação cobertos; worker/CLI histórico ainda puxam para baixo |

### 7.3 O que os testes cobrem bem

- Ativação sem sessão antes da confirmação; código vinculado à ativação; cooldown; expiração; bloqueio após 5 tentativas; concorrência; atomicidade da outbox.
- RLS/FORCE RLS nas 19 tabelas; isolamento de tenant; escopo por provedor; permissões de comércio; downgrade/upgrade corretivo.
- Hotmart: payloads oficiais, idempotência, concorrência, rollback, eventos fora de ordem, order bump, preço interno vs. preço do provedor.
- Outbox: papel restrito, criptografia do payload, retry/dead/lease, cancelamento de reset, status de token, heartbeat.

### 7.4 O que ainda não tem cobertura exaustiva

- Alteração de senha e revogação de sessões pela interface ainda não têm teste E2E dedicado.
- CRUD de categorias e todas as combinações de autorização owner/member ainda não estão cobertos.
- A cobertura de componentes por página é parcial; os fluxos críticos estão cobertos por Playwright.
- Testes E2E usam Chromium headless; Safari/Firefox e leitores de tela reais não foram exercitados.
- Resend e Hotmart continuam mockados/desabilitados; nenhuma validação externa real foi feita.
- Worker da outbox e alguns caminhos de erro de CLI ainda têm cobertura baixa.

---

## 8. Problemas classificados P0–P3

### 8.1 P0 — bloqueiam o lançamento

#### P0-01 — Catálogo de produto de produção não pode ser criado por procedimento versionado

- **Status:** **RESOLVIDO na Missão 02** — comando `python -m app.cli.provision_product` com `--dry-run`/`--apply`, idempotência por slug, RLS e testes de integração. Ver seção 13.
- **Prioridade:** P0
- **Arquivo/localização:** `backend/app/services/license_service.py:417-447`; `backend/app/services/license_service.py:241-262`; `backend/scripts/seed_demo.py:12-15`; `docs/hotmart-integration.md:24-26`.
- **Comportamento observado:** o webhook resolve o produto por `HOTMART_PRODUCT_SLUG` e lança `hotmart_product_not_configured` se ele não existir ou estiver inativo, resultando em `503`. O único seed existente é o de demonstração, bloqueado em produção e dependente de `DEMO_MODE=true`.
- **Evidência:** o código acima e a ausência de qualquer endpoint/CLI de catálogo. Não há teste que crie um produto de produção.
- **Consequência para o cliente:** a primeira compra real falha; a Hotmart reenvia algumas vezes e desiste. O cliente pagou e não recebe licença.
- **Correção recomendada:** criar um comando idempotente de produção (por exemplo, `python -m app.scripts.upsert_product`) que use o papel de migrations ou `catalog_write`, receba slug/nome/preço/moeda/tipo e seja seguro para repetir; documentar o pré-requisito; adicionar um preflight no startup/webhook que diferencie “integração desabilitada” de “produto ausente” com alerta operacional.
- **Teste necessário:** teste de integração que execute o comando, publique um `PURCHASE_APPROVED` fictício e verifique `200`, pedido, licença e outbox; executar o comando duas vezes e provar idempotência.

#### P0-02 — Ambiente local/Compose incompleto para migration e ativação

- **Status:** **RESOLVIDO na Missão 02** — preflight `environment`/`database`/`commercial`, integração com `migrate`, API e worker, validação de placeholders e testes. Ver seção 13.
- **Prioridade:** P0
- **Arquivo/localização:** `.env` local (não versionado), `docker-compose.yml:67-72`, `backend/migrations/versions/20261031_06_transactional_email_outbox.py:30-31`, `backend/app/core/email_verification.py:15-18`.
- **Comportamento observado:** `docker compose --env-file .env config --quiet` emite avisos de `OUTBOX_DB_USER` e `OUTBOX_DB_PASSWORD` em branco. A migration `20261031_06` exige `OUTBOX_DB_PASSWORD`; a ativação exige `EMAIL_VERIFICATION_HMAC_KEY` com pelo menos 32 caracteres, que também não está no `.env` local. O `EMAIL_PROVIDER` local é `dev`, que não entrega e-mail real.
- **Evidência:** saída dos comandos de configuração; leitura do validador e da migration. O `.env.example` contém marcadores, mas o `.env` local não.
- **Consequência para o cliente:** um ambiente criado a partir do `.env` atual não migra e não ativa conta; em produção, esquecer essas variáveis derruba a jornada inteira.
- **Correção recomendada:** completar o ambiente com segredos reais no gerenciador apropriado (sem versionar), adicionar um script de preflight que valide a presença e o formato de todas as variáveis obrigatórias antes de `docker compose up`, e incluir isso no runbook de deploy.
- **Teste necessário:** CI que renderize o Compose com um `.env` de teste e falhe em variável obrigatória vazia; teste de integração que suba a API com todas as variáveis e conclua uma ativação.

### 8.2 P1 — impedem funcionalidade central ou prejudicam diretamente o cliente

#### P1-01 — Aprovação após atraso/protesto não reativa a licença

- **Status:** **RESOLVIDO para atraso temporário na Missão 03** — recuperação `suspended -> pending/active` com pedido `paid`, trigger da migration `20261031_11`, testes de timestamp/concorrência. Protesto/chargeback permanecem terminais por política.
- **Prioridade:** P1
- **Arquivo/localização:** `backend/app/services/license_service.py:481-507` e `backend/app/services/license_service.py:522-529`.
- **Comportamento observado:** `PURCHASE_DELAYED` grava `order.status="pending"`, suspende a licença e revoga sessões. Um `PURCHASE_APPROVED` posterior entra no ramo `order.status == "pending"`, marca o pedido como `paid`, mas, como a licença já existe, não altera seu status. A licença permanece `suspended`. O mesmo vale para reversão de `PURCHASE_PROTEST`/`PURCHASE_CHARGEBACK`, que não tem fluxo de reativação.
- **Evidência:** o código acima e a limitação assumida em `docs/hotmart-integration.md:86-88`.
- **Consequência para o cliente:** o cliente pagou, mas continua bloqueado; precisa de intervenção manual no banco.
- **Correção recomendada:** definir uma máquina de estados explícita. Em `PURCHASE_APPROVED` com pedido `pending` e licença `suspended` por atraso/protesto (não terminal), reativar a licença, limpar `revoked_at`, manter sessões encerradas (exigir novo login) e auditar. Manter irreversibilidade apenas para estados terminais definidos.
- **Teste necessário:** integração com sequência `APPROVED → DELAYED → APPROVED` (eventos com timestamps crescentes) e `DELAYED → APPROVED`; verificar licença `active` e login possível. Testar também a política para chargeback/protesto.

#### P1-02 — Sem recuperação de licença entregue por e-mail

- **Status:** **RESOLVIDO na Missão 04** — recuperação pelo cliente via e-mail de compra + código, e instruções de recuperação pelo backoffice. O código original não é revelado.
- **Prioridade:** P1
- **Arquivo/localização:** `backend/app/services/email_outbox_service.py:241-275`; `docs/email-outbox.md:21`; ausência de rota/UI de reenvio.
- **Comportamento observado:** uma mensagem `license_delivery` em `dead` só pode ser reenfileirada por CLI no host, com uma única tentativa. `activation_verification` em `dead` não pode ser reenfileirada (precisa de novo código). Não existe endpoint autenticado nem tela de suporte para reenviar a licença ao comprador.
- **Evidência:** função `requeue_dead`, documentação e ausência de rota em `backend/app/api/v1/endpoints` e de tela em `frontend/src/pages`.
- **Consequência para o cliente:** se o e-mail for recusado, cair em spam ou for digitado errado na compra, o cliente não consegue ativar e depende de suporte manual.
- **Correção recomendada:** criar fluxo autenticado de reenvio por e-mail de compra + pedido/licença, com rate limit, resposta genérica e auditoria; ou um backoffice interno protegido. Para `license_delivery` em `dead`, gerar novo evento com nova chave de idempotência somente após validar que a licença não está vinculada.
- **Teste necessário:** integração com mensagem `dead`, reenvio, verificação de nova outbox e entrega; tentativas não autorizadas e rate limit; garantir que o código não é exposto a terceiros.

#### P1-03 — Gestão de categorias existe no backend, mas não na interface

- **Status:** **RESOLVIDO na Missão 06** — página `Categorias`, CRUD completo na UI, busca/filtros, contagem de uso, arquivamento/reativação e exclusão protegida. Owner gerencia; member consulta. Categorias padrão não podem ser excluídas nem arquivadas.
- **Prioridade:** P1
- **Arquivo/localização:** `frontend/src/pages/CategoriesPage.tsx`; rota `/categorias`; `backend/app/services/category_service.py`; migration `20261101_13_category_archive.py`.
- **Comportamento anterior:** o backend tinha CRUD completo, com `require_owner`; o frontend só listava categorias para seleção. O cliente ficava limitado às 14 categorias padrão.
- **Correção implementada:** tela própria com lista, busca, filtro por tipo/situação, criação, edição, arquivamento, reativação e exclusão; `usage_count`/`in_use` derivados de lançamentos, contas e orçamentos; categorias arquivadas deixam de ser oferecidas em novos registros, mas o histórico continua visível/editável e contas existentes podem ser pagas.
- **Proteções:** arquivamento/exclusão de categoria padrão retornam `409`; exclusão de categoria em uso retorna `409`; member recebe `403` em mutações; isolamento entre tenants retorna `404`; lançamentos/contas/orçamentos novos rejeitam categoria arquivada.
- **Evidência:** `test_financial_domain.py` (CRUD, uso, permissões, isolamento, histórico, pagamento/recorrência) e `frontend/e2e/categories-management.spec.ts`.
- **Documentação:** [category-management.md](category-management.md).

#### P1-04 — Reembolso/chargeback não cancela e-mail de licença já enfileirado

- **Status:** **RESOLVIDO na Missão 03** — cancelamento transacional de `license_delivery` pendente/processing, revalidação no worker com lock e testes de corrida. Mensagem já aceita pelo provedor permanece `sent` e a licença é invalidada.
- **Prioridade:** P1
- **Arquivo/localização:** `backend/app/services/license_service.py:508-521`; `backend/app/services/email_outbox_service.py:169-238`.
- **Comportamento observado:** ao receber `PURCHASE_REFUNDED`, `PURCHASE_CHARGEBACK`, `PURCHASE_PROTEST`, `PURCHASE_CANCELED` ou `PURCHASE_EXPIRED`, o código atualiza pedido e licença, mas não cancela a mensagem `license_delivery` pendente. O worker não revalida o status da licença antes de enviar `license_delivery`.
- **Evidência:** o ramo negativo não chama nenhum cancelamento de outbox; `process_one` só revalida `password_reset`.
- **Consequência para o cliente:** um comprador reembolsado pode receber um código de ativação válido na aparência; a ativação falhará porque a licença está cancelada, gerando confusão e suporte.
- **Correção recomendada:** na mesma transação do evento negativo, cancelar `license_delivery` pendente/processing da licença; adicionar policy de cancelamento para a API; para mensagens já reivindicadas, incluir revalidação de status da licença no worker ou aceitar explicitamente a janela residual com documentação e alerta.
- **Teste necessário:** teste de integração que enfileire licença, processe reembolso antes do worker e verifique `cancelled` e nenhum envio; teste de corrida para mensagem já em `processing`.

#### P1-05 — Domínio financeiro sem testes automatizados

- **Status:** **RESOLVIDO na Missão 05** — suíte financeira PostgreSQL/API com CRUD, cálculos, filtros, relatórios, isolamento e concorrência; cobertura backend 85% após a Missão 07.
- **Prioridade:** P1
- **Arquivo/localização:** `backend/app/services/transaction_service.py`, `bill_service.py`, `card_service.py`, `budget_service.py`, `goal_service.py`, `dashboard_service.py`, `report_service.py`, `account_service.py`, `periods.py`; `backend/app/api/v1/endpoints/*`.
- **Comportamento observado:** a suíte de 98 testes não exercita CRUD financeiro. A cobertura dos serviços financeiros varia de 20% a 34%; `periods.py` tem 33%.
- **Evidência:** relatório de cobertura da execução no container (seção 7.2).
- **Consequência para o cliente:** erros de cálculo, isolamento e validação podem chegar à produção sem detecção; qualquer refatoração é arriscada.
- **Correção recomendada:** criar testes unitários e de integração por módulo, cobrindo criação/edição/exclusão, validação de categoria/cartão, pagamento/desfazer conta, recorrência idempotente, cálculo de orçamento, movimentos de meta, relatórios, CSV e autorização. Estabelecer gate de cobertura mínima (por exemplo, 80% de branch nos serviços financeiros).
- **Teste necessário:** suíte nova executada no mesmo perfil `tests`; casos de isolamento entre tenants e valores inválidos.

#### P1-06 — Sem testes de frontend das telas financeiras e sem E2E

- **Status:** **RESOLVIDO na Missão 05** — 28 cenários Playwright (cliente, financeiro, backoffice, categorias, responsividade) + 5 testes de componentes; lacuna residual de testes unitários por página.
- **Prioridade:** P1
- **Arquivo/localização:** `frontend/src/pages/AuthPage.test.tsx` (2 testes); `frontend/e2e` vazio.
- **Comportamento observado:** apenas a ativação é testada no frontend. Login/logout, redefinição, dashboard, lançamentos, contas, cartões, orçamento, metas, relatórios e configurações não têm testes. Não existe teste de navegador ponta a ponta.
- **Evidência (histórica):** antes da Missão 05 havia apenas 2 testes de componente e o diretório E2E estava vazio.
- **Consequência para o cliente:** regressões de UI e de integração frontend/backend passam despercebidas.
- **Correção recomendada:** adicionar testes de componentes com API mockada para estados de loading/erro/vazio, formulários e ações; adicionar Playwright E2E contra o Compose descartável, incluindo ativação e CRUD principal.
- **Teste necessário:** pipeline que executa Vitest + Playwright e falha em regressão.

#### P1-07 — Sem backoffice de produto, pedido e licença

- **Status:** **RESOLVIDO na Missão 04** — identidade de suporte separada, console de pedidos/licenças/outbox/auditoria e ação auditada.
- **Prioridade:** P1
- **Arquivo/localização:** ausência de endpoints/UI; `backend/app/services/license_service.py` só é acessível pelo webhook; `frontend/src/pages/SettingsPage.tsx:310-346` mostra apenas a licença do próprio usuário.
- **Comportamento observado:** não há consulta de pedido por e-mail/transação, reemissão de licença, revogação/reativação manual, nem cadastro de produto. O suporte dependeria de SQL direto.
- **Evidência:** inventário de rotas e telas.
- **Consequência para o cliente:** problemas comuns de compra não podem ser resolvidos com segurança e rastreabilidade.
- **Correção recomendada:** criar backoffice interno (host-only ou autenticação administrativa separada) para catálogo, pedidos, licenças e outbox, com auditoria e sem exposição a usuários comuns.
- **Teste necessário:** autorização (não acessível por tenant), auditoria de cada ação e idempotência de reenvio/revogação.

### 8.3 P2 — relevantes, com alternativa funcional

#### P2-01 — Corrida em movimentos de meta pode gerar saldo negativo

- **Status:** **RESOLVIDO na Missão 05** para a corrida de saldo — `goal_service.add_movement` bloqueia a meta com `FOR UPDATE`; teste concorrente comprova que duas retiradas não deixam saldo negativo. A idempotência de criação foi concluída no P2-02 (Missão 12).
- **Prioridade:** P2
- **Arquivo/localização:** `backend/app/services/goal_service.py:120-159`.
- **Comportamento observado:** o saldo é calculado antes do insert, sem lock na meta ou nos movimentos. Duas retiradas concorrentes podem validar contra o mesmo saldo e deixar o total negativo. Não há chave de idempotência para o POST.
- **Evidência:** ausência de `with_for_update` e de constraint de saldo.
- **Consequência:** progresso e valores da meta ficam incorretos.
- **Correção recomendada:** lock na meta antes de calcular, ou saldo materializado com `CHECK (saved >= 0)`, e idempotência por requisição.
- **Teste necessário:** integração concorrente com duas retiradas que, juntas, excedem o saldo.

#### P2-02 — Ausência de idempotência em criação de registros financeiros

- **Status:** **RESOLVIDO na Missão 12** — `Idempotency-Key` transacional em PostgreSQL, tabela `idempotency_records`, replay/conflito e testes de concorrência.
- **Prioridade:** P2
- **Arquivo/localização (correção):** `backend/app/services/idempotency_service.py`; `backend/app/models/idempotency.py`; migration `20261104_17_financial_idempotency.py`; serviços/endpoints de transações, contas, metas e movimentos; frontend `api.ts`, formulários e E2E.
- **Comportamento anterior:** retry de rede ou duplo clique podia criar dois registros; a UI apenas desabilitava o botão e a API não tinha chave de idempotência.
- **Escopo protegido:** `transactions.create`, `bills.create`, `bills.pay`, `bills.unpay`, `goals.create` e `goals.movements.create`. Gasto no cartão usa `transactions.create`.
- **Garantias de domínio preservadas:** orçamento por categoria/mês e recorrência por conta-base/vencimento usam constraints únicas; pagamento de conta mantém `FOR UPDATE` e vínculo único do lançamento; metas mantêm lock de saldo.
- **Evidência:** `tests/integration/test_financial_idempotency.py` (replay, conflito, rollback, chaves diferentes, 10 requisições concorrentes, pagamento, desfazer, aporte e isolamento por tenant/usuário), `tests/unit/test_idempotency.py`, `test_postgres_rls.py` e `frontend/e2e/idempotency.spec.ts`.
- **Documentação:** [financial-idempotency.md](financial-idempotency.md).

#### P2-03 — `failed_login_count` não bloqueia a conta

- **Status:** **RESOLVIDO na Missão 09** — lockout progressivo distribuído por identidade de conta, separado do rate limit de IP/e-mail, com `Retry-After`, expiração automática e reset em login válido.
- **Prioridade:** P2
- **Arquivo/localização:** `backend/app/services/login_lockout_service.py`; `backend/app/services/auth_service.py`; migration `20261102_16_account_lockout.py`; `login_lockout_states`.
- **Comportamento anterior:** `failed_login_count` era incrementado, mas nunca consultado; o limite por IP não impedia credential stuffing distribuído.
- **Correção implementada:** HMAC do e-mail normalizado com namespace próprio; contador e `locked_until` atômicos no PostgreSQL; cooldown 60 s → 900 s; expiração por inatividade; contador limitado; `429` + `Retry-After`; mensagens genéricas para existentes e inexistentes; sem revogação de sessões ou desativação da conta.
- **Premissas:** limiar 5 e teto 15 min derivados do lockout existente do suporte; cooldown inicial 60 s e janela de 24 h centralizados em `Settings` e configuráveis.
- **Evidência:** `test_login_lockout.py` (bloqueio, expiração, reset, concorrência, e-mail inexistente, cap, auditoria), `test_postgres_rls.py` (migration 16/grants).
- **Documentação:** [account-lockout.md](account-lockout.md).

#### P2-04 — Rate limit em memória, não compartilhado entre réplicas

- **Status:** **RESOLVIDO na Missão 07** — SlowAPI removido; token bucket atômico no PostgreSQL com chaves HMAC, `Retry-After` e fail-open documentado.
- **Prioridade:** P2
- **Arquivo/localização:** `backend/app/core/rate_limit.py`; migration `20261102_14_distributed_rate_limit.py`; `rate_limit_buckets`.
- **Comportamento anterior:** `Limiter` do SlowAPI usava storage em memória; cada réplica tinha contadores independentes e reinícios zeravam limites.
- **Correção implementada:** tabela compartilhada, `SELECT ... FOR UPDATE`, relógio do banco, expiração/limpeza, HMAC para IP/e-mail/operador, limites existentes preservados e duas chaves por endpoint quando aplicável.
- **Falha:** fail-open com log sanitizado; contexto RLS é reaplicado após o commit intermediário; webhooks assíncronos usam sessão separada.
- **Evidência:** `test_rate_limit.py`, `test_rate_limit_distributed.py` (concorrência real, recarga, dois clientes API e 429), `test_postgres_rls.py` (migration/privilégios).
- **Documentação:** [distributed-rate-limiting.md](distributed-rate-limiting.md).

#### P2-05 — Rota legada `hmac_sandbox` permanece disponível em produção

- **Status:** **RESOLVIDO na Missão 11** — `PAYMENT_SANDBOX_ENABLED=false` por padrão, rejeitado em produção, router legado não registrado em produção e teste de conjunto de rotas + 404.
- **Prioridade:** P2
- **Arquivo/localização (correção):** `backend/app/api/v1/endpoints/webhooks.py:20-22`; `backend/app/api/v1/router.py:39`; `backend/app/core/config.py:84,203-205,238-239`; `backend/app/core/preflight.py:281-299`.
- **Comportamento anterior (antes da Missão 11):** `/webhooks/payments/hmac_sandbox` era sempre registrada. Em produção com `PAYMENT_WEBHOOK_SECRET` configurado (obrigatório quando Hotmart está desabilitada), ela aceitava notificações assinadas e emitia licenças usando o produto/valor do payload.
- **Evidência histórica:** código anterior e ausência de bloqueio no `Settings`.
- **Consequência anterior:** um segredo mal configurado ou vazado permitia emitir licenças fora da Hotmart.
- **Correção implementada:** rota incluída apenas com `PAYMENT_SANDBOX_ENABLED=true` e `ENV != production`; flag é false por padrão, rejeitada pelo `Settings` e pelo preflight em produção. Hotmart, ativação e serviços internos legítimos permanecem inalterados.
- **Teste de comprovação:** `tests/unit/test_sandbox_route_registration.py` verifica o conjunto de rotas em produção e exige 404 para o endpoint; configuração de produção com a flag habilitada é rejeitada.

#### P2-06 — `APP_BASE_URL` não é validado como HTTPS em produção

- **Status:** **RESOLVIDO na Missão 02** — `Settings` rejeita HTTP em produção e o preflight/testes confirmam HTTPS. Permanece a necessidade de validar DNS/TLS reais na fase de homologação.
- **Prioridade:** P2
- **Arquivo/localização:** `backend/app/core/config.py:121-175`; `backend/app/services/email_service.py:35,47`.
- **Comportamento observado:** os links de redefinição e de licença usam `APP_BASE_URL`. CORS é validado como HTTPS, mas `APP_BASE_URL` não.
- **Evidência:** validador de produção não verifica `APP_BASE_URL`.
- **Consequência:** link com token de reset pode ser enviado por HTTP.
- **Correção recomendada:** exigir `https://` em produção e domínio coerente com `CORS_ORIGINS`.
- **Teste necessário:** settings rejeitam `http://` em produção.

#### P2-07 — Logs de exceção podem expor parâmetros de banco e PII

- **Status:** **RESOLVIDO na Missão 11** — logger central com redaction recursiva, sanitização de exceções/tracebacks, request ID, headers de correlação, access log Uvicorn desativado e testes de caminhos reais de logging.
- **Prioridade:** P2
- **Arquivo/localização (correção):** `backend/app/core/log_safety.py`; `backend/app/main.py:85-104,121-165`; `backend/app/api/v1/endpoints/hotmart_webhook.py:59-67`.
- **Comportamento anterior (antes da Missão 11):** o handler global e o handler do webhook usavam `logger.exception`, que registrava a exceção completa. Erros de SQLAlchemy podiam incluir SQL e parâmetros; não havia filtro central de redaction.
- **Evidência histórica:** os caminhos de exceção não passavam por sanitização.
- **Consequência anterior:** PII ou dados de pagamento podiam aparecer nos logs.
- **Correção implementada:** `RedactingFilter` central em todos os handlers, sanitização de mensagens/argumentos/estruturas aninhadas/headers/exceções, request ID por `contextvars`, `X-Request-ID` nas respostas, erros 500 genéricos sem stack trace, SQLAlchemy/httpx/httpcore em WARNING e access log Uvicorn desativado.
- **Teste de comprovação:** `tests/unit/test_log_safety.py` e `tests/integration/test_logging_redaction.py` exercitam exceção real via TestClient, `IntegrityError`, logs capturados sem e-mail/senha/token/CPF, resposta genérica, correlação por request ID e erro de validação sem `input`.

#### P2-08 — Exclusão de conta/LGPD ausente

- **Status:** **RESOLVIDO na Missão 13** — jornada autenticada de exclusão, anonimização, suporte, auditoria, outbox/idempotência e tombstones de backup.
- **Prioridade:** P2
- **Arquivo/localização (correção):** `backend/app/services/privacy_service.py`; `backend/app/models/privacy.py`; `backend/app/api/v1/endpoints/privacy.py`; `backend/app/api/v1/endpoints/support.py`; migration `20261104_18_privacy_data_lifecycle.py`; `SettingsPage.tsx`; `SupportPrivacyPage.tsx`.
- **Comportamento anterior:** a UI orientava contato com o suporte; não havia endpoint, protocolo, SOP, retenção ou tombstone.
- **Fluxo implementado:** reautenticação por senha, protocolo, `awaiting_review` para owner com membros, execução para member/owner único, recusa/justificativa no suporte, eventos auditáveis e status consultável.
- **Dados:** member anonimiza apenas dados próprios; owner único encerra tenant, exclui dados financeiros e anonimiza comprador/licença; pedidos/eventos/auditoria são conservados sem PII direta.
- **Operação:** outbox cancelada/higienizada, idempotência apagada, lockout/rate limit removidos, tombstones para reaplicação após restore.
- **Governança:** [lgpd-data-lifecycle.md](lgpd-data-lifecycle.md), [data-subject-request-sop.md](data-subject-request-sop.md), [data-retention-matrix.md](data-retention-matrix.md).
- **Pendências:** prazos jurídicos/contábeis, controlador/encarregado/canal oficial e restore drill real.
- **Testes:** `tests/integration/test_privacy_lifecycle.py`; `test_postgres_rls.py`; `frontend/e2e/privacy-lifecycle.spec.ts`.

#### P2-09 — Papel `member` existe, mas compartilhamento familiar não é utilizável

- **Prioridade:** P2
- **Arquivo/localização:** `backend/app/core/permissions.py:7-19`; `backend/app/models/user.py:17`; ausência de convite/criação de membro.
- **Comportamento observado:** o banco e as permissões conhecem `member`, mas não há endpoint/UI para criar ou convidar um membro. A ativação sempre cria `owner`.
- **Evidência:** busca por `member` e ausência de rota de convite.
- **Consequência:** se o produto for vendido como “família”, o compartilhamento não existe; se for single-user, o modelo é enganoso.
- **Correção recomendada:** decidir o escopo. Se multi-usuário, implementar convite, aceite, papéis e limites; se não, remover o papel do discurso comercial e documentar.
- **Teste necessário:** convite e autorização owner/member, ou teste de que a funcionalidade não é anunciada.

#### P2-10 — Sem reconciliação com a Hotmart

- **Status:** **RESOLVIDO na Missão 08** — CLI operacional com dry-run padrão, cliente OAuth mockável, observações imutáveis, aplicação de transições seguras e proteção contra concorrência com o webhook.
- **Prioridade:** P2
- **Arquivo/localização:** `backend/app/cli/reconcile_hotmart.py`; `backend/app/integrations/payments/hotmart_api.py`; `backend/app/services/hotmart_reconciliation_service.py`; migration `20261102_15`.
- **Comportamento anterior:** o estado era derivado somente dos webhooks; não havia consulta à API de vendas nem detecção de divergências.
- **Correção implementada:** consulta por transação em `GET /sales/history`, validação de produto/ID, token OAuth em memória, retries com backoff, `Retry-After`, dry-run, lote limitado, snapshot antes do HTTP, advisory lock compartilhado com webhook, revalidação e observações append-only.
- **Mapeamento seguro:** `APPROVED`, `CANCELLED`, `EXPIRED`, `REFUNDED`, `CHARGEBACK` e `PROTESTED`; estados informativos não concedem acesso; `BLOCKED`, `PARTIALLY_REFUNDED`, `NO_FUNDS` e desconhecidos exigem análise manual.
- **Evidência:** `test_hotmart_api_client.py`, `test_hotmart_reconciliation.py` (concorrência PostgreSQL, stale, terminal, idempotência, dry-run, produto/status), `test_postgres_rls.py` (migration 15/grants).
- **Documentação:** [hotmart-reconciliation.md](hotmart-reconciliation.md).

#### P2-11 — Busca, filtros e ordenação incompletos nas listas

- **Status:** **PARCIAL** — lançamentos já têm busca, filtro por tipo/categoria e paginação; contas ainda não expõem busca/status na UI e ordenação por coluna continua ausente em várias listas.
- **Prioridade:** P2
- **Arquivo/localização:** `backend/app/api/v1/endpoints/bills.py:16-27` oferece `search`/`status`, mas `BillsPage.tsx:83` não os usa; não há ordenação por coluna em lançamentos/contas/cartões/metas; `ReportsPage.tsx` não ordena.
- **Comportamento observado:** o usuário depende da ordem fixa e do mês; em contas, não há busca nem filtro de status na UI.
- **Evidência:** código das páginas.
- **Consequência:** usabilidade cai com volume de dados.
- **Correção recomendada:** expor controles de busca/filtro/ordenação nas telas e usar os parâmetros existentes; adicionar `sort`/`order` no backend onde necessário.
- **Teste necessário:** testes de componente e integração de query.

#### P2-12 — Sem visibilidade de entrega de e-mail para cliente/suporte

- **Status:** **PARCIAL** — o backoffice de suporte já lista outbox e entregas por pedido/licença, sem payload. O cliente ainda não tem status genérico de entrega na conta.
- **Prioridade:** P2
- **Arquivo/localização:** `backend/app/services/email_outbox_service.py`; nenhuma rota/tela de status; `SettingsPage.tsx` mostra apenas a licença.
- **Comportamento observado:** o status `pending`/`processing`/`sent`/`dead` só é acessível por banco/CLI.
- **Evidência:** inventário de rotas e telas.
- **Consequência:** suporte não sabe se o e-mail saiu ou morreu; cliente espera sem informação.
- **Correção recomendada:** visão interna sanitizada de outbox por pedido/licença (sem payload) e, opcionalmente, status público genérico para o comprador autenticado.
- **Teste necessário:** autorização, ausência de PII na resposta e consistência com o estado real.

### 8.4 P3 — melhorias

#### P3-01 — Documentação desatualizada sobre o head Alembic

- **Status:** **RESOLVIDO** — `docs/email-outbox.md` foi atualizado para referenciar `alembic heads` e o head vigente.
- **Prioridade:** P3
- **Arquivo/localização:** `docs/email-outbox.md:79`.
- **Comportamento observado:** o texto diz head `20261031_08`; o head real é `20261031_10`.
- **Evidência:** `alembic heads`.
- **Consequência:** operador pode concluir errado o estado das migrations.
- **Correção recomendada:** atualizar o documento ou remover o número fixo, referenciando `alembic heads`.
- **Teste necessário:** lint de documentação/checagem em CI.

#### P3-02 — `SECRET_KEY` é exigido e não é usado

- **Prioridade:** P3
- **Arquivo/localização:** `backend/app/core/config.py:44,103-104`.
- **Comportamento observado:** a chave é validada e nunca consumida; não há assinatura com `itsdangerous`.
- **Evidência:** busca por `SECRET_KEY` no código.
- **Consequência:** falsa sensação de segurança e rotação desnecessária.
- **Correção recomendada:** remover a exigência ou usá-la para um fim explícito, documentando.
- **Teste necessário:** ajustar testes de settings.

#### P3-03 — Ausência de README/runbook de nível superior

- **Prioridade:** P3
- **Arquivo/localização:** raiz do repositório; `docs/` tem documentos profundos, mas não um guia de “primeiro deploy”.
- **Comportamento observado:** não há README com passos de instalação, variáveis, seed de produto, migração, testes e operação.
- **Evidência:** listagem da raiz.
- **Consequência:** onboarding operacional lento e propenso a erro.
- **Correção recomendada:** criar README com pré-requisitos, checklist de segredos, comandos e troubleshooting.
- **Teste necessário:** validar o runbook em ambiente limpo.

#### P3-04 — `.env.example` contém placeholders que passam em algumas validações

- **Status:** **RESOLVIDO** — `Settings` e o preflight rejeitam placeholders de exemplo em produção.
- **Prioridade:** P3
- **Arquivo/localização:** `.env.example:18` (`OUTBOX_DB_PASSWORD=troque_por_segredo_aleatorio_do_worker`).
- **Comportamento observado:** o placeholder tem mais de 32 caracteres e passaria na validação de produção, embora não seja um segredo real.
- **Evidência:** validador de produção.
- **Consequência:** implantação com senha conhecida e previsível.
- **Correção recomendada:** adicionar rejeição explícita de valores que comecem com `troque_` em produção, ou documentar fortemente; nunca usar `.env.example` como ambiente final.
- **Teste necessário:** settings rejeitam placeholders em produção.

#### P3-05 — Ajustes visuais menores

- **Prioridade:** P3
- **Arquivo/localização:** `frontend/src/styles.css:772-783` (`.month-nav span` sem `display:flex`/`line-height`); fontes `Avenir Next`/`Inter` referenciadas sem carregamento explícito.
- **Comportamento observado:** o texto do seletor de mês pode não ficar verticalmente centralizado em todos os navegadores; a tipografia cai para fallback em sistemas sem as fontes.
- **Evidência:** CSS.
- **Consequência:** pequena inconsistência visual.
- **Correção recomendada:** centralizar via flex e documentar/embutir as fontes.
- **Teste necessário:** inspeção visual em navegadores alvo.

#### P3-06 — Gráficos e progresso sem alternativa textual

- **Prioridade:** P3
- **Arquivo/localização:** `frontend/src/components/ui.tsx:242-248`; `DashboardPage.tsx:43-69`; `ReportsPage.tsx:36-61`.
- **Comportamento observado:** barras e donut são `div`s com `aria-hidden`/`title`; não há tabela ou resumo textual equivalente.
- **Evidência:** código.
- **Consequência:** usuários de leitor de tela não acessam os dados do gráfico, embora os números principais estejam nos cards.
- **Correção recomendada:** adicionar resumo textual ou tabela oculta acessível.
- **Teste necessário:** auditoria com leitor de tela.

#### P3-07 — Paginação sem total e botão “Próxima” pode abrir página vazia

- **Prioridade:** P3
- **Arquivo/localização:** `frontend/src/pages/TransactionsPage.tsx:408-418`; `CardsPage.tsx:311-321`; `ReportsPage.tsx:275-285`.
- **Comportamento observado:** a UI mostra “Página N” sem total; “Próxima” é habilitada quando a página tem exatamente 100 itens, podendo haver uma página seguinte vazia.
- **Evidência:** código.
- **Consequência:** experiência confusa em listas grandes.
- **Correção recomendada:** retornar total/páginas ou desabilitar por `has_more`.
- **Teste necessário:** listas com 100/101 itens.

#### P3-08 — `last_seen_at` nunca é atualizado

- **Prioridade:** P3
- **Arquivo/localização:** `backend/app/models/session.py:31`; `backend/app/services/auth_service.py:323-344` lista o campo, mas não o atualiza.
- **Comportamento observado:** a tela de sessões mostra “Iniciada em” e expiração, não última atividade.
- **Evidência:** busca por `last_seen_at`.
- **Consequência:** informação de sessão menos útil.
- **Correção recomendada:** atualizar em cada request autenticado com baixa frequência (throttle) ou remover o campo da API.
- **Teste necessário:** atualização e throttle.

---

## 9. Dependências entre correções

```text
P0-02 (ambiente válido)
  └─ necessário para qualquer validação local/produção

P0-01 (catálogo de produção)
  └─ necessário para habilitar HOTMART_ENABLED=true
       └─ P1-01, P1-04, P1-07 e P2-10 estão implementados; homologação real exige compra/webhook

P1-05 (testes financeiros) e P1-06 (frontend/E2E)
  └─ P2-02 e P2-01 foram concluídos; testes financeiros e E2E protegem a regressão

P1-02 (recuperação de licença) e P2-12 (status de entrega)
  └─ backoffice já entrega visão de outbox; resta status ao cliente

P1-03 (UI de categorias) — resolvido
  └─ usa o CRUD existente; a migration 13 adiciona arquivamento

P2-03 (lockout progressivo) — resolvido
  └─ migration 16 e tabela `login_lockout_states`

P2-04 (rate limit distribuído) — resolvido
  └─ migration 14 e tabela `rate_limit_buckets`

P2-10 (reconciliação Hotmart) — resolvido
  └─ migration 15, credenciais próprias e CLI `reconcile_hotmart`

P2-08 (LGPD)
  └─ depende de inventário de dados, backups e retenção definidos

P3-01/P3-03/P3-04
  └─ documentação e hardening de configuração; podem ser feitos em paralelo
```

---

## 10. Plano de conclusão em ordem de execução

### Fase 0 — Desbloquear o ambiente (P0-02)

1. Completar os segredos reais fora do repositório: `OUTBOX_DB_USER`, `OUTBOX_DB_PASSWORD`, `EMAIL_VERIFICATION_HMAC_KEY`, `RESEND_API_KEY`, `EMAIL_FROM`, `APP_BASE_URL`, `CORS_ORIGINS`, `TRUSTED_PROXY_IPS`, `HOTMART_*`.
2. Criar preflight de configuração e rodar `docker compose config --quiet` sem avisos.
3. Rodar migration em banco descartável e uma ativação completa com provider de e-mail controlado.

### Fase 1 — Fechar o caminho comercial (P0-01, P1-01, P1-04, P1-02, P1-07)

1. Criar comando idempotente de catálogo de produção e documentar.
2. Escrever a máquina de estados Hotmart com testes de `APPROVED/DELAYED/PROTEST/CHARGEBACK/REFUNDED`.
3. Cancelar `license_delivery` em eventos negativos e revalidar antes do envio.
4. Criar fluxo de reenvio de licença e backoffice mínimo de pedidos/licenças.
5. Homologar com fixtures oficiais e uma compra de teste na Hotmart (quando a operação permitir).

### Fase 2 — Proteger o núcleo financeiro (P1-05, P1-06, P2-01, P2-02)

1. Testes de todos os serviços financeiros e endpoints.
2. Testes de componentes das páginas financeiras e E2E da jornada principal.
3. Corrigir corrida de metas e adicionar idempotência de criação (concluído na Missão 12).
4. Gate de cobertura e execução em CI.

### Fase 3 — Completar a experiência (P1-03, P2-11, P2-12)

1. ~~Tela de categorias.~~ Concluída na Missão 06.
2. Busca/filtro/ordenação nas listas.
3. Status de entrega de e-mail para suporte.

### Fase 4 — Endurecer segurança e operação (P2-03 a P2-10)

1. ~~Rate limit compartilhado.~~ Concluído na Missão 07; ~~lockout progressivo~~ concluído na Missão 09.
2. Desabilitar sandbox em produção e validar `APP_BASE_URL`.
3. Redaction de logs.
4. Processo LGPD e decisão sobre compartilhamento familiar.
5. ~~Reconciliação Hotmart.~~ Concluída na Missão 08.

### Fase 5 — Polimento (P3)

1. Atualizar documentação e criar README/runbook.
2. Ajustes visuais e acessibilidade.
3. Paginação e `last_seen_at`.

---

## 11. Critérios objetivos para considerar o produto pronto para venda

O produto só deve ser considerado pronto quando **todos** os critérios abaixo forem verdadeiros e comprováveis:

1. **Configuração**
   - `docker compose --env-file <arquivo-real> config --quiet` sem avisos de variáveis obrigatórias.
   - Preflight falha antes do deploy se qualquer segredo obrigatório estiver ausente/placeholder.
   - `HOTMART_ENABLED=true` somente após produto interno ativo e homologado.

2. **Banco**
   - `alembic heads` com head único.
   - `alembic upgrade head` em banco descartável e em staging.
   - RLS/FORCE RLS verificados para todas as tabelas por tenant.
   - Nenhum papel operacional com `SUPERUSER`/`BYPASSRLS`.

3. **Compra e licença**
   - Compra de teste na Hotmart gera pedido, licença e e-mail.
   - E-mail entregue por Resend com domínio autenticado.
   - Ativação com código de e-mail cria conta e sessão.
   - Reembolso revoga acesso em até 1 minuto e cancela e-mail pendente.
   - Chargeback/protesto suspende e existe procedimento de revisão.
   - `APPROVED` após `DELAYED` reativa acesso quando a política permitir.

4. **Testes**
   - Backend: suíte atual (98) + novos testes financeiros, com cobertura mínima acordada (recomendado ≥ 80% nos serviços financeiros).
   - Frontend: testes de todas as páginas principais e fluxos de erro/vazio.
   - E2E: compra simulada → e-mail → ativação → CRUD → reembolso.
   - Zero falhas no CI.

5. **Segurança**
   - Nenhum segredo no repositório/logs.
   - Rate limit compartilhado e lockout progressivo.
   - Sandbox desabilitado em produção.
   - Cookies `Secure`, CSP, CORS e HSTS ativos.
   - Teste de IDOR entre tenants em todos os recursos.
   - Logs sem PII/código/token.

6. **Operação**
   - Backoffice/CLI para catálogo, pedido, licença e outbox.
   - Monitoramento de outbox (`pending`, `processing`, `dead`), erros 5xx e banco.
   - Backup e restauração testados.
   - Runbook de suporte e de incidente.

7. **Comercial/LGPD**
   - Produto Hotmart e produto interno com preço/moeda coerentes.
   - Política de reembolso/chargeback/cancelamento documentada e implementada.
   - Processo de exclusão/anonimização de dados com prazo.
   - Textos de suporte e atendimento disponíveis ao comprador.

8. **Qualidade visual**
   - Revisão em desktop e mobile nos navegadores alvo.
   - Contraste, foco, navegação por teclado e leitor de tela verificados.
   - Estados de loading/erro/vazio consistentes.

---

## 12. Apêndice — evidências rápidas

- Rotas frontend: `frontend/src/App.tsx:21-57`.
- Contexto de autenticação e sessão: `frontend/src/context/AuthContext.tsx:47-172`.
- Cliente HTTP e tratamento de 401/erro: `frontend/src/lib/api.ts:15-87`.
- Middleware de segurança: `backend/app/main.py:89-141`.
- Resolução de sessão/licença: `backend/app/core/deps.py:38-95`.
- Ativação: `backend/app/services/activation_service.py:56-341`.
- Outbox: `backend/app/services/email_outbox_service.py:20-303`.
- Worker: `backend/app/workers/email_outbox.py:23-107`.
- Hotmart: `backend/app/api/v1/endpoints/hotmart_webhook.py:18-63`; `backend/app/services/license_service.py:316-443`.
- RLS: `backend/migrations/versions/20261026_01_row_level_security.py`, `20261026_02_licenses_rls.py`, `20261031_03_commerce_rls.py`, `20261031_04_license_provider_guard.py`, `20261031_05_email_activation.py`, `20261031_06_transactional_email_outbox.py`.
- Cobertura e contagem de testes: seção 7.2.

### Comandos de reprodução

```sh
# do diretório raiz
docker compose --env-file .env.example --profile tests run --build --rm tests
docker compose --env-file .env.example --profile tests run --rm tests alembic heads
docker compose --env-file .env.example build api web

# do diretório frontend
npm ci
npm test
npm run typecheck
npm run build
```

> Não execute `HOTMART_ENABLED=true`, não envie fixtures para produção e não use o `.env.example` como ambiente real.

---

## 13. Atualização pós-Missão 02 — P0-01 e P0-02

**Data da atualização:** 02/11/2026  
**Escopo:** implementação dos dois bloqueadores P0 identificados na seção 8.1. As demais prioridades (P1/P2/P3) permanecem como estavam.

### P0-01 — RESOLVIDO

- **Implementação:** `python -m app.cli.provision_product` em `backend/app/cli/provision_product.py`, usando `provision_product()` em `backend/app/services/license_service.py` e o schema `ProductProvision` em `backend/app/schemas/product.py`.
- **Segurança:** usa `set_db_context(db, catalog_write="true")` e a policy existente `products_catalog_write`; não há bypass de RLS nem concessão de privilégio novo.
- **Idempotência:** o slug é a chave estável; reexecutar com os mesmos dados retorna `unchanged` e não cria duplicata.
- **Controle:** `--dry-run` é o padrão; `--apply` é obrigatório para gravar; `--state` explícito controla ativação/desativação; produto inativo não é reativado silenciosamente.
- **Validação:** slug, nome, descrição, preço em centavos, moeda e `license_kind` são validados pelo schema existente.
- **Rollback:** conflito, permissão insuficiente e falha de commit são tratados e a transação é revertida.
- **Testes:** `tests/integration/test_catalog_provisioning.py` (9 testes), `tests/unit/test_product_schema.py` (9 casos parametrizados) e cobertura de `license_service.py` em 81%.
- **Documentação:** `docs/production-preflight.md` e `docs/hotmart-integration.md`.

### P0-02 — RESOLVIDO COMO CONTROLE DE PRONTIDÃO

- **Implementação:** `backend/app/core/preflight.py` e `backend/app/cli/preflight.py`, com estágios `environment`, `database`, `commercial` e `all`.
- **Fonte de verdade:** reutiliza `Settings`, `SessionLocal`, `alembic.ini`, policies RLS e permissões existentes; não cria cadastro/configuração paralela.
- **Integração:** o serviço `migrate` do Compose executa `preflight --stage environment` antes de `alembic upgrade head`; a API e o worker validam o ambiente no startup; o webhook continua retornando `503` sem produto.
- **Segurança:** não imprime segredos, senhas, tokens, HOTTOK, UCODE ou URLs completas; valida placeholders, finalidades distintas, HTTPS, cookies e credenciais Hotmart somente quando habilitada.
- **Testes:** `tests/unit/test_preflight.py` (19 testes), `tests/integration/test_preflight_database.py` (5 testes), `tests/unit/test_http_security.py` (startup com configuração inválida) e cobertura de `core/preflight.py` em 78%.
- **Limitação operacional:** o `.env` local real permaneceu intencionalmente inalterado, conforme as regras da missão. Ele continua incompleto (`OUTBOX_DB_USER`, `OUTBOX_DB_PASSWORD`, `EMAIL_VERIFICATION_HMAC_KEY` ausentes), e o novo preflight agora reprova esse ambiente antes das migrations, em vez de falhar tardiamente. O operador deve preencher os segredos no ambiente/secret manager.

### Evidências executadas

| Comando | Resultado |
| --- | --- |
| `docker compose --env-file .env.example --profile tests run --build --rm tests` | **141 aprovados**, 0 reprovados; cobertura 74% |
| `docker compose --env-file .env.example --profile tests run --rm tests python -m app.cli.preflight --stage environment` | **0 falhas**, 1 skip (Hotmart desabilitada) |
| `docker compose --env-file .env.example --profile tests run --rm tests python -m app.cli.preflight --stage database` | **0 falhas**; head `20261102_16`, permissões, rate limit, lockout, reconciliação e RLS confirmadas |
| Provisionamento dry-run + apply no banco descartável | Criou sem duplicar; teste de integração confirma `unchanged` na reexecução com os mesmos dados |
| `python -m app.cli.preflight --stage commercial` com produto ativo de teste | **OK** |
| `docker compose --env-file .env run --rm --no-deps api python -m app.cli.preflight --stage environment` | **1** (reprovou corretamente o `.env` local incompleto) |
| `npm test` | 2 aprovados |
| `npm run typecheck` / `npm run build` | aprovados |
| `docker compose --env-file .env.example config --quiet` | aprovado |
| `alembic heads` | `20261102_16` |
| `git diff --check` | sem erros |

### Correções incidentais

Além dos dois P0, esta missão corrigiu P3-01 (head documentado) e P3-04 (placeholders aceitos em produção), totalizando 6 P3 remanescentes.

### Observação sobre a nota de prontidão

Os números do topo deste relatório foram atualizados para refletir o catálogo de produção como concluído: **13/49 concluídas**, **26/49 parciais**, **10/49 ausentes**, prontidão ponderada **53,1%**. Os P0 remanescentes são **zero**; os bloqueadores agora são os itens P1/P2 documentados nas seções 8.2 e 8.3, especialmente a máquina de estados Hotmart, a recuperação de licença, o cancelamento de e-mail em reembolso e os testes do domínio financeiro.

---

## 14. Atualização pós-Missão 03 — P1-01 e P1-04

**Data da atualização:** 02/11/2026  
**Escopo:** ciclo de vida de licenças Hotmart e cancelamento/revalidação de entrega. P1-01 e P1-04 foram corrigidos; os demais P1/P2/P3 permanecem.

### P1-01 — RESOLVIDO para atraso temporário

- `PURCHASE_DELAYED` é o único estado temporário: pedido `pending`, licença `suspended`, sessões revogadas.
- Uma aprovação posterior mais nova/precedente restaura:
  - `pending` se a licença nunca foi ativada;
  - `active` se já foi ativada, limpando `revoked_at`.
- Sessões revogadas não são restauradas; o cliente precisa autenticar novamente.
- O trigger `guard_license_update()` foi estendido na migration `20261031_11` para permitir somente `suspended -> pending/active` com pedido `paid`, mesmo pedido e mesmo provedor.
- `PURCHASE_PROTEST`/`PURCHASE_CHARGEBACK`/`PURCHASE_REFUNDED`/`CANCELED`/`EXPIRED` continuam terminais ou bloqueantes. Aprovação antiga, duplicada ou até mais nova é registrada sem reativar acesso.
- `COMPLETE`/`BILLET_PRINTED` continuam sem conceder acesso.
- Testes cobrem atraso seguido de aprovação (licença ativada e não ativada), atraso antigo, timestamp igual, precedência, eventos terminais com aprovação mais nova, concorrência aprovação/reembolso/chargeback/cancelamento e timestamp ausente.

### P1-04 — RESOLVIDO

- Eventos terminais cancelam `license_delivery` pendente/processing na mesma transação da invalidação comercial.
- O cancelamento é escopado por `event_type='license_delivery'` e `aggregate_id` da licença; não atinge reset de senha, ativação, outros pedidos nem mensagens `sent`/`dead`.
- O payload é apagado e a linha permanece para auditoria com `last_error` (`license_revoked`/`license_suspended`).
- Mensagens `dead` de entrega também são revalidadas por `requeue_dead`, que recusa reabrir entrega de pedido reembolsado/chargeback/cancelado.
- O worker mantém a linha da outbox bloqueada com `FOR UPDATE` durante o envio e revalida:
  - pedido `paid` + licença `pending/active` → envia;
  - pedido `pending` → adia sem consumir tentativa;
  - pedido terminal, licença suspensa/cancelada/expirada/ausente → cancela sem chamar o provedor.
- O worker recebeu apenas leitura de `licenses(status, order_id)` e `orders(id, provider, status)` por policies/grants da migration `20261031_11`; não recebeu PII, `code_hash`, permissões amplas, `SUPERUSER` ou `BYPASSRLS`.
- Se o provedor já aceitou a mensagem, ela não pode ser recolhida: permanece `sent`, a licença é invalidada e a ativação é bloqueada. O teste de corrida valida esse comportamento.

### Migration

- **Nova migration:** `20261031_11_delivery_lifecycle.py` (down_revision `20261031_10`).
- **Mudanças:** policies de cancelamento/consulta de `license_delivery`, policies/grants de colunas para o worker ler estado de licença/pedido e substituição do trigger `guard_license_update()` para recuperação temporária.
- **Sem** novas tabelas, colunas ou estados comerciais.
- **Upgrade/downgrade/upgrade** exercitados no teste de integração `test_z_corrective_migration_downgrade_and_reupgrade` em banco descartável.
- O head vigente passa a ser `20261031_11`.

### Evidências executadas

| Comando | Resultado |
| --- | --- |
| `docker compose --env-file .env.example --profile tests run --build --rm tests` | **171 aprovados**, 0 reprovados; cobertura 74% |
| `pytest --collect-only -q` no container | 64 unitários + 107 integração = 171 |
| `test_hotmart_integration.py` | ciclo de vida, concorrência, entrega, worker e ativação bloqueada |
| `test_email_outbox.py` | cancelamento escopado, payload, worker cancelando/adindo e isolamento |
| `test_postgres_rls.py` | policies, grants de coluna, trigger e downgrade/upgrade da migration 11 |
| `alembic heads` | `20261031_11` |
| `git diff --check` | sem erros |
| `python -m compileall` | aprovado |

### Observação sobre a nota de prontidão

Os números do topo foram atualizados: **14/49 concluídas (28,6%)**, **26/49 parciais**, **9/49 ausentes**, prontidão ponderada **55,1%**. P0 remanescentes: **0**. P1 remanescentes: **5**. A reconciliação Hotmart foi implementada na Missão 08; a reversão automática de protesto/chargeback continua ausente por política comercial intencional.


---

## 15. Atualização pós-Missão 04 — P1-02 e P1-07

**Data da atualização:** 02/11/2026  
**Escopo:** recuperação de licença pelo cliente/suporte e backoffice administrativo separado.

### P1-02 — RESOLVIDO

- O cliente recupera acesso sem conhecer o código original:
  - `POST /auth/recover-license` localiza compra paga por hash do e-mail e cria/reutiliza `PendingActivation`;
  - o código de 6 dígitos é enviado pela outbox existente;
  - `POST /auth/recover-license/confirm` recebe e-mail + código e reutiliza `confirm_activation`.
- Resposta genérica para e-mails conhecidos/desconhecidos; sem `activation_id` retornado.
- Se a conta já existe, dispara `password_reset` com cooldown; nenhum segundo tenant é criado.
- Pedidos terminais/suspensos são recusados.
- O suporte pode solicitar instruções de recuperação com justificativa; não recebe o código.
- Testes de estados, cooldown, estados terminais, usuário existente e criação única de tenant.

### P1-07 — RESOLVIDO

- Identidade administrativa separada: `support_operators`, `support_sessions`, `support_audit_logs`.
- Papéis `support_read` e `support_operator`; sem transformar `owner` em admin global.
- Login próprio, Argon2id, lockout, cookie separado, rate limit e provisionamento por CLI no host.
- Console `/backoffice` com dashboard, pedidos, detalhe, licenças, outbox e auditoria.
- Ações sensíveis exigem justificativa e geram auditoria append-only.
- Proibido alterar valores, marcar pedido como pago, reverter chargeback/protesto, reativar licença ou expor payload/hashes.
- Envio de instruções de recuperação é idempotente por licença/hora; dead letters continuam exigindo operação de host.
- RLS/policies restritas; worker sem acesso às tabelas administrativas.

### Migration

- `20261031_12_support_backoffice.py` (down_revision `20261031_11`).
- Novas tabelas, policies/grants, policies de leitura administrativa, recuperação por e-mail e evento `license_recovery_instructions`.
- Sem alteração destrutiva em registros comerciais; downgrade preserva o constraint amplo da outbox para não perder mensagens de recuperação.
- Head vigente: `20261031_12`.

### Evidências

| Comando | Resultado |
| --- | --- |
| Backend completo no container | **194 aprovados**, 0 reprovados (64 unitários + 130 integração) |
| Cobertura backend | **74%** |
| Frontend | 5 testes aprovados; TypeScript e build Vite aprovados |
| `test_license_recovery.py` | recuperação, enumeração, cooldown, terminal, usuário existente |
| `test_support_backoffice.py` | auth, lockout, permissões, ações, auditoria, PII mascarada, filtros |
| `test_postgres_rls.py` | migration 12, policies e downgrade/upgrade |
| Docker Compose / build API+web / Alembic / compile / diff-check | aprovados |

### Nota final

Métricas atualizadas: **16/49 concluídas (32,7%)**, **26/49 parciais**, **7/49 ausentes**, prontidão ponderada **59,2%**. P1 remanescentes: **3** (categorias, testes financeiros e testes frontend/E2E). O produto comercial agora cobre recuperação e operação de suporte, mas ainda não deve ser vendido sem fechar os P1 restantes e validar Resend/Hotmart em homologação.


---

## 16. Atualização pós-Missão 05 — P1-05 e P1-06

**Data da atualização:** 02/11/2026  
**Escopo:** confiabilidade do domínio financeiro, testes de frontend e E2E reais.

### P1-05 — RESOLVIDO

- Criada `backend/tests/integration/test_financial_domain.py` com PostgreSQL/API reais.
- Cobertura:
  - CRUD de lançamentos, filtros, busca, paginação, resumo, validação de valor/categoria/cartão;
  - contas: criação, pagamento, desfazer, recorrência, restrições de conta paga;
  - cartões: criação, gasto, limite disponível e arquivamento;
  - orçamentos: criação, duplicidade, cálculo de gasto/disponível/percentual e validação de categoria;
  - metas: aportes, retiradas, conclusão, reabertura, histórico e limite de retirada;
  - dashboard, relatórios, CSV, exportação e atualização de conta;
  - isolamento entre dois tenants via API;
  - concorrência real de retiradas de meta e pagamento de conta.
- Correções de consistência:
  - `goal_service.add_movement` passou a bloquear a meta com `FOR UPDATE`, impedindo saldo negativo em corrida;
  - `bill_service.get_bill` passou a bloquear a conta, impedindo pagamento duplicado concorrente.
- Cobertura backend subiu de **74% para 84%**; serviços financeiros principais entre 70% e 100%.

### P1-06 — RESOLVIDO

- Playwright 1.64 com Chromium, configurado em `frontend/playwright.config.ts`.
- Infraestrutura isolada `docker-compose.e2e.yml`:
  - projeto Compose próprio `fortexahome_e2e`;
  - PostgreSQL descartável, API, web e seed próprios;
  - portas 5435/8011/3011;
  - `EMAIL_PROVIDER=dev`, `HOTMART_ENABLED=false`, sem Resend/Hotmart reais;
  - seed em `backend/tests/e2e_seed.py` com pedidos, licenças, ativação, recuperação, cliente, member e operadores de suporte.
- 23 cenários E2E aprovados:
  - autenticação do cliente, rota protegida, erro, persistência e logout;
  - ativação com código controlado e recuperação de licença;
  - CRUD de lançamento, conta/pagamento/desfazer, cartão, meta/aporte, dashboard, relatório/CSV e configurações;
  - login do suporte, dashboard, busca/detalhe de pedido, ação auditada, duplicidade, pedido terminal, read-only/403, cliente/member barrados, cookie inválido, lockout;
  - desktop/tablet/mobile, menu mobile e ausência de scroll horizontal;
  - labels acessíveis, foco por teclado e alerta de validação.
- 5 testes de componentes (ativação, login do backoffice, AuthPage e categorias) e typecheck/build Vite aprovados.
- Evidências de falha configuradas: screenshot e trace em `frontend/test-results`.

### Resultados reais

| Verificação | Resultado |
| --- | --- |
| Backend completo | **204 aprovados**, 0 reprovados (64 unitários + 140 integração) |
| Cobertura backend | **84%** |
| Frontend (Vitest) | **5 aprovados** |
| E2E Playwright | **23 aprovados**, 0 reprovados |
| TypeScript / build Vite | aprovados |
| Docker Compose E2E | aprovado |
| Alembic heads | `20261031_12` |
| Compilação Python / `git diff --check` | aprovados |

### Limitações

- E2E usou Chromium headless; não houve teste em Safari/Firefox nesta missão.
- Resend e Hotmart foram simulados/desabilitados; validação externa continua pendente.
- Rate limit de login foi exercitado no lockout do suporte; testes de carga/distribuídos não fazem parte desta missão.
- `frontend/test-results` e `frontend/e2e/.auth` são artefatos locais e não devem ser versionados.
- A cobertura de componentes por página ainda é parcial; os fluxos críticos estão cobertos por E2E.

### Nota final

Métricas atualizadas: **18/49 concluídas (36,7%)**, **26/49 parciais**, **5/49 ausentes**, prontidão ponderada **63,3%**. P1 remanescente: **1** (P1-03, gestão de categorias na interface). O produto agora tem confiabilidade financeira e jornadas críticas comprovadas em navegador, restando categorias/UX e validações externas de produção.


---

## 17. Atualização pós-Missão 06 — P1-03

**Data da atualização:** 02/11/2026  
**Escopo:** gestão de categorias na interface, arquivamento e preservação de histórico.

### P1-03 — RESOLVIDO

- Nova página `/categorias` com lista, busca, filtros por tipo/situação, criação, edição, arquivamento, reativação e exclusão.
- Owner gerencia; member consulta em modo somente leitura e recebe `403` nas mutações.
- Categorias padrão não podem ser excluídas nem arquivadas.
- Categorias personalizadas podem ser arquivadas sem perder o histórico; a exclusão permanece bloqueada quando há lançamentos, contas ou orçamentos vinculados.
- A API expõe `archived`, `usage_count` e `in_use`; categorias arquivadas deixam de ser oferecidas em novos registros, mas continuam visíveis no histórico e em filtros.
- Lançamentos antigos podem ser editados mantendo a categoria arquivada; contas existentes podem ser pagas e gerar recorrência com essa categoria.
- Migration aditiva `20261101_13_category_archive.py` adiciona `categories.archived`.
- Documentação: [category-management.md](category-management.md).

### Evidências

| Verificação | Resultado |
| --- | --- |
| Backend completo no container | **206 aprovados**, 0 reprovados (64 unitários + 142 integração) |
| Cobertura backend | **86%** |
| `category_service.py` | **98%** |
| Frontend (Vitest) | **5 aprovados** |
| E2E Playwright | **28 aprovados**, 0 reprovados |
| TypeScript / build Vite | aprovados |
| Alembic heads | `20261101_13` |
| Migração downgrade/upgrade 10 → head | aprovada em banco descartável, incluindo coluna `archived` |

### Métricas finais

- **20/49 concluídas (40,8%)**, **24/49 parciais**, **5/49 ausentes**.
- Prontidão funcional ponderada: **65,3%**.
- P0: **0**; P1: **0**; P2: **12**; P3: **6**.
- Head Alembic: `20261101_13`.

### Limitações e restrições

- Validação E2E apenas em Chromium headless; Safari/Firefox e leitores de tela reais não foram exercitados.
- Resend e Hotmart continuam simulados/desabilitados; nenhuma compra ou envio real foi feito.
- Nenhum acesso a VPS, banco de produção, `.env` de produção, Hotmart ou Resend real; nenhum commit, push ou deploy foi realizado.
- P2/P3 remanescentes continuam exigindo decisão de produto e homologação externa antes da venda.


---

## 18. Atualização pós-Missão 07 — P2-04

**Data da atualização:** 02/11/2026  
**Escopo:** rate limit distribuído, identidade, proxy, privacidade e resposta a abuso.

### P2-04 — RESOLVIDO

- SlowAPI e storage em memória removidos.
- Token bucket atômico no PostgreSQL (`rate_limit_buckets`) compartilhado entre réplicas e reinícios.
- `SELECT ... FOR UPDATE` evita corrida; o relógio vem do PostgreSQL.
- Chaves HMAC-SHA-256 com `RATE_LIMIT_HMAC_KEY`; IP, e-mail normalizado, operador, usuário, tenant e sessão suportados.
- Limites existentes preservados; login/ativação/recuperação usam IP + e-mail; recuperação pelo suporte usa operador + IP.
- `HTTP 429` com `Retry-After`; expiração automática e limpeza probabilística de chaves.
- Fail-open sanitizado quando o limiter (não o banco principal) falha; contexto RLS é reaplicado após commit intermediário.
- Proxy reverso continua aceitando cabeçalhos somente de `TRUSTED_PROXY_IPS`; Nginx sobrescreve `X-Real-IP`/`X-Forwarded-For`.
- Preflight valida `RATE_LIMIT_HMAC_KEY`, `RATE_LIMIT_DB_TIMEOUT_MS` e privilégios da tabela; worker não recebe acesso.
- Migration aditiva `20261102_14`; documentação em [distributed-rate-limiting.md](distributed-rate-limiting.md).

### Evidências

| Verificação | Resultado |
| --- | --- |
| Backend completo no container | **217 aprovados**, 0 reprovados (71 unitários + 146 integração) |
| Cobertura backend | **85%** |
| `core/rate_limit.py` | **82%** |
| Frontend (Vitest) | **5 aprovados** |
| E2E Playwright | **28 aprovados**, 0 reprovados |
| TypeScript / build Vite | aprovados |
| Alembic heads | `20261102_14` |
| Concorrência real | 20 requisições / 5 tokens: exatamente 5 permitidas |
| Dois clientes API | compartilham o mesmo limite e recebem 429 com `Retry-After` |
| Migration downgrade/upgrade 10 → head | aprovada, incluindo tabela e privilégios |
| Compose / builds / Python compile / diff-check | aprovados |

### Métricas finais

- **21/49 concluídas (42,9%)**, **23/49 parciais**, **5/49 ausentes**.
- Prontidão funcional ponderada: **66,3%**.
- P0: **0**; P1: **0**; P2: **11**; P3: **6**.
- Head Alembic: `20261102_14`.

### Limitações

- Sem Redis/API gateway; a decisão usa PostgreSQL porque ele já é dependência obrigatória. Se o volume crescer, a substituição por Redis pode preservar os decorators e as chaves.
- Rate limit não substitui o lockout progressivo por conta (P2-03), resolvido posteriormente na Missão 09.
- E2E continua em Chromium headless; Resend/Hotmart reais não foram usados.
- Nenhum acesso a VPS, banco de produção, `.env` de produção, Hotmart/Resend real; nenhum commit, push ou deploy.


---

## 19. Atualização pós-Missão 08 — P2-10

**Data da atualização:** 02/11/2026  
**Escopo:** reconciliação Hotmart, consistência comercial, concorrência, auditoria e operação segura.

### P2-10 — RESOLVIDO

- Cliente OAuth 2.0 para a API oficial de vendas, com token apenas em memória, renovação em `401`, backoff/jitter, `Retry-After`, timeout e limite de tentativas.
- Consulta somente `GET /sales/history?transaction=...`, suficiente para o estado comercial e com menor exposição de PII que os endpoints de participantes/preços.
- Nenhuma criação de pedido, tenant, licença ou entrega para transação desconhecida.
- Comparação conservadora de status; terminais nunca são revertidos; estados sem mapeamento seguro geram observação manual.
- Aplicação por `apply_hotmart_approval`/`apply_hotmart_terminal`, compartilhados com o webhook.
- Snapshot local antes do HTTP, advisory lock por transação, `FOR UPDATE`, revalidação e descarte de observação desatualizada.
- Reprocessamento idempotente; `payment_events` continua exclusivo do webhook e não recebe eventos sintéticos.
- Tabela append-only `hotmart_reconciliation_observations` com `run_id`, origem, estados, resultados, motivos e horários; sem PII/payload/tokens.
- CLI `python -m app.cli.reconcile_hotmart` com dry-run padrão, `--apply` explícito, transação específica, janela, limite, JSON e códigos de saída.
- Preflight valida credenciais, produto, ranges e privilégios; worker não acessa a tabela de observações.
- Nenhuma chamada real à Hotmart, nenhum `HOTMART_ENABLED=true`, nenhuma alteração em produto/preço/licença manual.

### Evidências

| Verificação | Resultado |
| --- | --- |
| Backend completo no container | **287 aprovados**, 0 reprovados (111 unitários + 176 integração) |
| Cobertura backend | **85%** |
| `hotmart_api.py` | **78%** |
| `hotmart_reconciliation_service.py` | **79%** |
| `reconcile_hotmart.py` | **84%** |
| Frontend (Vitest) | **5 aprovados** |
| E2E Playwright | **28 aprovados**, 0 reprovados |
| TypeScript / build Vite | aprovados |
| Alembic heads | `20261102_15` |
| Concorrência PostgreSQL | duas reconciliações concorrentes, webhook vs reconciliação, terminal vs aprovação e stale |
| Dry-run | nenhuma alteração comercial; observações registradas |
| Migration downgrade/upgrade 10 → head | aprovada, incluindo tabela e privilégios append-only |
| Compose / builds / Python compile / diff-check | aprovados |

### Métricas finais

- **22/49 concluídas (44,9%)**, **23/49 parciais**, **4/49 ausentes**.
- Prontidão funcional ponderada: **68,4%**.
- P0: **0**; P1: **0**; P2: **10**; P3: **6**.
- Head Alembic: `20261102_15`.

### Limitações

- Todos os testes usam HTTP mockado; Hotmart real não foi consultada.
- `sales/history` não expõe UCODE no contrato documentado; a validação usa `product.id` configurado e o vínculo local ao produto.
- `PARTIALLY_REFUNDED`, `BLOCKED`, `NO_FUNDS` e status desconhecidos exigem análise manual.
- A CLI usa o papel operacional existente, sem `BYPASSRLS`; não há scheduler embutido nem circuit breaker distribuído.
- Nenhum acesso a VPS, banco de produção, `.env` de produção, Hotmart/Resend real; nenhum commit, push ou deploy.


---

## 20. Auditoria complementar dos limites P2-04

**Data:** 02/11/2026  
**Escopo:** grupos previstos nas seções 4.2+ da Missão 07, que não chegaram no texto original: suporte/backoffice, webhook Hotmart e operações financeiras.

### Resultado

- Nenhum limiar existente foi alterado.
- A matriz efetiva de rotas foi tornada explícita via metadado `__rate_limit_policy__` nos decorators.
- `tests/integration/test_rate_limit_route_coverage.py` valida a matriz e faz 429 real com PostgreSQL no login de suporte e no webhook Hotmart.

### Cobertura encontrada

| Grupo | Limite distribuído | Chave | Política de falha | Falso bloqueio |
| --- | --- | --- | --- | --- |
| Login de suporte | 10/minute | IP + e-mail | fail-open | NAT compartilhado; mitigado por e-mail |
| Recuperação de suporte | 30/hour | operador + IP | fail-open | operador/legítimo em muitos IPs tem bucket próprio |
| Webhook Hotmart | 60/minute | IP | fail-open | egress compartilhado da Hotmart pode gerar 429; retry oficial trata |
| Webhook sandbox | 120/minute | IP | fail-open | mesmo risco de IP compartilhado |
| Operações financeiras | nenhum | — | — | sem limiar definido; nenhum falso bloqueio introduzido |

### Rotas sem cobertura específica

- Suporte: dashboard, pedidos, detalhe, licenças, outbox e auditoria; logout/me de suporte.
- Financeiro: transações, contas, cartões, orçamentos, metas, relatórios, CSV e export JSON.
- Conta: leitura, atualização, exportação.
- Autenticação: logout, me, sessões, troca de senha (as rotas de login/ativação/recuperação/reset já têm limites).

Essas rotas são autenticadas e tenant/support-scoped, com paginação e RLS. Não havia limiar disponível para derivar um valor seguro; nenhum valor foi inventado. O gap fica registrado, com prioridade para exportações e operações financeiras de escrita quando produto/operação definirem o limite por sessão/tenant.

### Conclusão

P2-04 permanece **RESOLVIDO**: o storage distribuído, as políticas existentes e o comportamento de falha foram auditados. A lacuna restante é de **definição de limiares adicionais**, não de implementação do mecanismo distribuído. Métricas gerais permanecem **22/49 concluídas**, **23/49 parciais**, **4/49 ausentes**, prontidão **68,4%**, P2 **10** naquele momento (P2 **9** após a Missão 09).


---

## 21. Atualização pós-Missão 09 — P2-03

**Data:** 02/11/2026  
**Escopo:** lockout progressivo por identidade de conta, concorrência, anti-enumeração e proteção contra DoS de conta.

### P2-03 — RESOLVIDO

- Nova tabela `login_lockout_states` e migration `20261102_16`.
- Chave HMAC do e-mail normalizado sob namespace `auth.login.lockout`; nenhum e-mail em claro.
- Contador e `locked_until` atômicos com `INSERT ... ON CONFLICT` + `SELECT ... FOR UPDATE`.
- Cooldown progressivo 60 s → 900 s, com teto, expiração por inatividade de 24 h e contador limitado.
- Pré-checagem read-only; Argon2 executado fora de locks de linha.
- Falhas incrementam a identidade; sucesso reseta; lock ativo retorna `429` + `Retry-After`.
- E-mails existentes e inexistentes usam a mesma tabela, mensagem e comportamento.
- Nenhuma desativação de conta ou revogação de sessão por falha de login.
- Fail-open sanitizado para indisponibilidade isolada do lockout.
- Rate limit de IP e IP+e-mail da Missão 07 permanece inalterado.
- Nova configuração tipada; preflight de produção exige `LOGIN_LOCKOUT_ENABLED=true`.
- Documentação: [account-lockout.md](account-lockout.md).

### Evidências

| Verificação | Resultado |
| --- | --- |
| Backend completo no container | **287 aprovados**, 0 reprovados (111 unitários + 176 integração) |
| Cobertura backend | **85%** |
| `login_lockout_service.py` | **75%** |
| `auth_service.py` | **79%** |
| Frontend (Vitest) | **5 aprovados** |
| E2E Playwright | **28 aprovados**, 0 reprovados |
| TypeScript / build Vite | aprovados |
| Alembic heads | `20261102_16` |
| Concorrência PostgreSQL | 10 falhas simultâneas contabilizadas; lock ativo e contador limitado |
| Anti-enumeração | e-mail inexistente recebe o mesmo lockout/429 |
| Migration downgrade/upgrade 10 → head | aprovada, incluindo tabela e privilégios |

### Métricas finais

- **22/49 concluídas (44,9%)**, **23/49 parciais**, **4/49 ausentes**.
- Prontidão funcional ponderada: **68,4%**.
- P0: **0**; P1: **0**; P2: **9**; P3: **6**.
- Head Alembic: `20261102_16`.

### Limitações

- Limiares são premissas conservadoras configuráveis, não calibração empírica de produção.
- Ataque sustentado ainda pode causar indisponibilidade temporária de login de até 15 min; não há CAPTCHA/MFA.
- Nenhum acesso a VPS, banco de produção, `.env` de produção, Hotmart/Resend real; nenhum commit, push ou deploy.

---

## 22. Auditoria consolidada dos P2 e plano de lançamento

**Data:** 02/11/2026  
**Escopo:** avaliação final dos nove P2 listados na auditoria (P2-01 a P2-12, excluindo os já resolvidos P2-03, P2-04 e P2-10), sem implementação nesta missão.

### 22.1 Reclassificação dos nove itens

A lista de nove itens incluía dois já resolvidos por missões anteriores:

- **P2-01** — corrida de saldo em metas resolvida na Missão 05 com `FOR UPDATE` e teste concorrente. A idempotência de criação foi concluída no P2-02.
- **P2-06** — `APP_BASE_URL` HTTPS em produção validado no `Settings`/preflight desde a Missão 02.

Na Missão 10, os sete P2 abertos eram **P2-02, P2-05, P2-07, P2-08, P2-09, P2-11 e P2-12**. P2-05/P2-07 foram resolvidos na Missão 11; P2-02 na Missão 12; P2-08 na Missão 13; restam **P2-09, P2-11 e P2-12**.

### 22.2 Matriz detalhada

| Código | Definição original | Objetivo | Estado comprovado | Arquivos/funcionalidades | Dependências | Risco se não concluir | Primeira venda | Esforço | Testes necessários |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **P2-01** | Corrida em movimentos de meta pode gerar saldo negativo. | Evitar saldo negativo e estado inconsistente. | **Resolvido para saldo** na Missão 05. `add_movement` usa `FOR UPDATE`; teste concorrente confirma 201/400 e saldo 20. | `goal_service.py`; `test_financial_domain.py`. | Nenhuma. | Baixo residual: idempotência de POST tratada no P2-02. | Não bloqueia. | Pequeno (resolvido). | Teste de concorrência já existente; teste de retry fica em P2-02. |
| **P2-02** | Ausência de idempotência em criação de registros financeiros. | Evitar duplicação por retry/duplo clique. | **Resolvido na Missão 12.** `Idempotency-Key` com escopo tenant/usuário/operação, fingerprint, constraint única, replay e conflito `409`. | `idempotency_service.py`; migration `20261104_17`; transações/contas/metas/movimentos; frontend/E2E. | PostgreSQL único da aplicação; retenção configurável. | Residual: clientes que omitem a chave mantêm comportamento legado; limpeza operacional. | **Não bloqueia mais.** | Médio (resolvido). | Mesma chave/payload → um efeito; mesma chave/outro payload → `409`; chaves diferentes → dois efeitos; concorrência com 10 clientes; rollback; isolamento por tenant/usuário. |
| **P2-05** | Rota legada `hmac_sandbox` permanece disponível em produção. | Remover caminho alternativo de emissão de licença fora da Hotmart. | **Resolvido na Missão 11.** Rota não é registrada em produção; `PAYMENT_SANDBOX_ENABLED` é false por padrão e rejeitado em produção. | `webhooks.py`; `hmac_sandbox.py`; `license_service.py`; config/preflight; teste HTTP. | Configuração de produção e compatibilidade de desenvolvimento/teste. | Residual: logs de infraestrutura externa. | **Não bloqueia mais.** | Pequeno (resolvido). | Produção → 404; dev/test → comportamento controlado; preflight; teste de autenticação. |
| **P2-06** | `APP_BASE_URL` não validado como HTTPS em produção. | Evitar links de reset/licença em HTTP. | **Resolvido** na Missão 02. `Settings` valida HTTPS; preflight/teste confirmam. | `config.py`; `preflight.py`; `test_preflight.py`. | DNS/TLS reais ainda pendentes. | Link inseguro se configuração contornar validação; risco residual operacional. | Não bloqueia código; TLS real é fase externa. | Pequeno (resolvido). | Teste de settings; validação HTTPS real em staging. |
| **P2-07** | Logs de exceção podem expor parâmetros de banco e PII. | Evitar vazamento de PII/financeiro em logs. | **Resolvido na Missão 11.** Logger central, redaction recursiva, exceções sanitizadas, request ID e access log Uvicorn desativado. | `main.py`; `hotmart_webhook.py`; logging da aplicação. | Padrão de log sanitizado, request ID, teste de exceção sensível. | Residual: retenção de logs/backups e logs de infraestrutura externa. | **Não bloqueia mais.** | Pequeno/médio (resolvido). | Exceção com string sensível → log não contém segredo/PII; request ID correlaciona; logs de webhook/worker sanitizados. |
| **P2-08** | Exclusão de conta/LGPD ausente. | Atender exclusão/anonimização e retenção. | **Resolvido na Missão 13.** Fluxo autenticado, reautenticação, anonimização, revisão de owner/member, SOP, retenção documentada, outbox/idempotência e tombstones. | `privacy_service.py`; migration `20261104_18`; endpoints/UI de privacidade e suporte; docs LGPD/SOP/matriz. | Aprovação jurídica/contábil, controlador/encarregado, restore drill real. | Residual: prazos legais pendentes e logs/backups externos. | **Não bloqueia código; governança legal ainda necessária antes da venda.** | Grande (resolvido tecnicamente). | Reautenticação, member/owner, owner compartilhado, exclusão/anonimização, outbox, idempotência, RLS, tombstone/restore simulado, E2E e mobile. |
| **P2-09** | Papel `member` existe, mas compartilhamento familiar não é utilizável. | Decidir single-user × família e implementar convite ou remover promessa. | **Aberto por decisão de produto (Missão 14).** Produto será individual nesta fase; suporte técnico a owner/member permanece, sem convite e sem anúncio familiar. | `permissions.py`; `user.py`; ausência de endpoints/UI; marketing. | Decisão futura de produto; e-mail/outbox; papéis. | Se anunciado como família sem convite, promessa inconsistente. | **Não bloqueia**, desde que não seja anunciado como multi-usuário. | Médio/grande. | Futuro: convite/aceite, isolamento e revogação; nesta fase, revisão da comunicação comercial. |
| **P2-11** | Busca, filtros e ordenação incompletos nas listas. | Melhorar usabilidade com volume. | **Adiado na Missão 14.** Lançamentos têm busca/tipo/categoria; contas não expõem busca/status; ordenação por coluna ausente em várias telas. Não é bloqueador da jornada essencial. | `BillsPage.tsx`; `TransactionsPage.tsx`; listas/backends de contas/cartões/metas/relatórios. | Frontend + parâmetros de query/sort. | Usabilidade cai com muitos registros; não compromete integridade. | **Pode entrar após o lançamento.** | Médio. | Componente/integração de busca, filtro, ordenação e paginação. |
| **P2-12** | Sem visibilidade de entrega de e-mail para cliente/suporte. | Dar transparência operacional sem payload. | **Adiado na Missão 14.** Backoffice lista outbox/entregas por pedido/licença e permite recuperação; cliente não vê status genérico. Suporte cobre a lacuna. | `support_service.py`; `SupportOutboxPage`; `SupportOrderDetailPage`; `SettingsPage.tsx`; outbox. | Outbox existente, autorização, UI do cliente. | Suporte já consegue diagnosticar; cliente espera sem informação e abre suporte. | **Pode entrar após o lançamento** (suporte já tem visão). | Pequeno/médio. | Autorização, ausência de payload/PII, status coerente, estados pending/sent/dead. |

### 22.3 Matriz de risco

| Classificação | Itens | Justificativa |
| --- | --- | --- |
| **Bloqueador real restante** | Validações externas (Resend, Hotmart, DNS/TLS, backup real, worker, monitoramento) e aprovação jurídica da retenção | P2-08 foi implementado; prazos jurídicos/contábeis e restore real seguem pendentes. |
| **Necessário antes da primeira venda** | Aprovação jurídica/contábil da matriz de retenção; controlador/encarregado e canal oficial; restore drill real | P2-08 implementou o fluxo e o SOP; a governança legal ainda depende do responsável da empresa. |
| **Pode entrar após o lançamento** | P2-09, P2-11, P2-12 | Não comprometem autenticação, licença, cobrança ou integridade financeira. P2-09 exige não anunciar compartilhamento familiar até implementar; P2-12 já tem mitigação no suporte. |
| **Melhoria futura** | — | Os P3 permanecem separados; não foram promovidos a P2. |
| **Resolvidos** | P2-01, P2-02, P2-03, P2-04, P2-05, P2-06, P2-07, P2-08, P2-10 | Evidência em código/testes; P2-08 fecha exclusão/anonimização, SOP e tombstones. |

### 22.4 Dependências externas ainda não comprovadas

| Item | Estado real | O que falta |
| --- | --- | --- |
| Resend | Mock/dev e testes do adaptador; nenhum envio real. | Domínio verificado, SPF/DKIM/DMARC, envio controlado, bounce/complaint, limites e logs do provedor. |
| OAuth Hotmart | `httpx.MockTransport`; nenhuma credencial real. | Credencial sandbox, obtenção/renovação de token, quotas e erros reais. |
| Webhook Hotmart | Fixtures e testes locais; `HOTMART_ENABLED=false`. | Webhook 2.0.0 real/sandbox, HOTTOK, ordem/retry, payload oficial e idempotência externa. |
| Reconciliação Hotmart | Mock e PostgreSQL descartável. | `sales/history` real/sandbox, product ID correto, dry-run/apply controlado e divergências reais. |
| DNS/domínio | Não comprovado no repositório. | Registro, propagação, domínio de e-mail e domínio da API. |
| HTTPS/certificado | Não validado em produção. | Certificado válido, renovação, HSTS, redirect HTTP→HTTPS e TLS do proxy. |
| Cookies/sessão em produção | E2E usa `Secure=false` local. | `Secure`, `SameSite`, domínio, CSRF e comportamento real em HTTPS. |
| Backup/restauração | Não há evidência de rotina/teste. | Política, criptografia, RPO/RTO, restore drill e retenção. |
| Migrations em produção | Testadas apenas em banco descartável. | Ensaio em staging prod-like, backup prévio, janela e rollback. |
| Worker da Outbox | Testado em dev/descartável. | Worker real, Resend real, dead letter, requeue e alertas. |
| Monitoramento/alertas | Sem evidência de stack/alertas. | Métricas, logs, uptime, erros 5xx, outbox/backlog, lockout/rate limit e on-call. |
| Carga e disponibilidade | Sem teste de carga distribuída. | Carga em múltiplas réplicas, proxy, DB pool, rate limit/lockout e recuperação. |

### 22.5 Plano de lançamento

#### Fase 1 — Conclusão dos bloqueadores
- ~~P2-05: rota legada desabilitada/404 em produção e teste.~~ Concluído na Missão 11.
- ~~P2-07: redaction de logs e request ID; teste de exceção com dado sensível.~~ Concluído na Missão 11.
- ~~P2-02: idempotência de criação financeira com escopo por tenant/operação e testes de retry/concorrência.~~ Concluído na Missão 12.
- ~~P2-08: implementar exclusão/anonimização ou publicar SOP manual com prazo, retenção e evidências.~~ Concluído na Missão 13 (governança jurídica final pendente).
- **Aceite:** todos os testes de regressão verdes; preflight completo; nenhuma rota legada ativa; nenhum log com PII/segredo; retry idempotente comprovado; SOP aprovado.

#### Fase 2 — Validação de segurança
- Revisar RLS/papéis em ambiente prod-like; testar owner/member, suporte, worker e migrations.
- Validar lockout/rate limit distribuídos, cookies Secure, CSRF, CSP/HSTS e redaction.
- Rodar dependency/security scan, rotação de segredos e revisão de permissões.
- **Aceite:** zero P0/P1 de segurança; nenhum achado crítico aberto; testes de autorização e isolamento aprovados.

#### Fase 3 — Preparação de release
- Staging com domínio/TLS, segredos reais de homologação, catálogo interno e produto Hotmart sandbox.
- Configurar Resend de homologação, worker, monitoramento, alertas e runbooks.
- **Aceite:** `preflight environment/database/commercial` aprovados; migrations no head; build reproduzível; runbook de incidente/rollback aprovado.

#### Fase 4 — Backup e implantação controlada
- Backup completo pré-migration e teste de restauração em ambiente isolado.
- Aplicar migrations em staging prod-like e depois produção sem tráfego de vendas.
- Subir API/worker/web com healthchecks; validar logs e métricas.
- **Aceite:** restore comprovado; RPO/RTO definidos; rollback ensaiado; healthchecks verdes; nenhum erro 5xx anormal.

#### Fase 5 — Validação de produção sem vendas
- Criar tenant/licença interna controlada ou usar sandbox; validar login, cookies, ativação, e-mail controlado, outbox, suporte e reconciliação dry-run.
- Verificar CSRF, sessão, RLS, rate limit, lockout e backup.
- **Aceite:** jornada completa sem compra real; nenhum PII em logs; worker entrega e-mail de teste; reconciliação dry-run sem divergência inesperada.

#### Fase 6 — Teste comercial controlado
- Executar compra Hotmart sandbox ou transação real de baixo valor com reembolso planejado.
- Validar webhook, pedido, licença, e-mail, ativação, recuperação, reembolso/chargeback, outbox e suporte.
- **Aceite:** uma compra gera exatamente um pedido/licença/entrega; reembolso revoga acesso; reconciliação confirma estado; suporte localiza e recupera acesso; nenhum efeito duplicado.

#### Fase 7 — Liberação das vendas
- Habilitar `HOTMART_ENABLED=true` somente após fases 1–6.
- Monitorar 48 h: erros, outbox, ativação, lockout, suporte, reconciliação e backlog.
- **Aceite:** zero incidentes críticos; alertas operacionais; suporte com SLA; rollback disponível; decisão formal de liberação registrada.

### 22.6 Próxima missão recomendada

**Missão 14 — P2-09 ou P2-11/P2-12**, conforme decisão de produto. Antes da venda, concluir aprovação jurídica/contábil da retenção, definição de controlador/encarregado/canal e restore drill real. P2-09/P2-11/P2-12 podem ficar para depois do lançamento, com a comunicação comercial ajustada.

### 22.7 Conclusão

O produto está tecnicamente próximo de homologação. P2-02/P2-05/P2-07/P2-08 foram fechados; ainda não está pronto para cobrança real enquanto a governança jurídica da retenção, o restore drill real e as validações externas de Resend, Hotmart, TLS/DNS, worker e monitoramento não forem executadas. Testes locais verdes não substituem essas evidências.


---

## 23. Atualização pós-Missão 11 — P2-05 e P2-07

**Data:** 04/11/2026  
**Escopo:** desativação da rota sandbox em produção, redaction central, request ID e tratamento seguro de exceções.

### P2-05 — RESOLVIDO

- `PAYMENT_SANDBOX_ENABLED=false` por padrão.
- Produção rejeita `PAYMENT_SANDBOX_ENABLED=true` no `Settings`/preflight.
- Router legado só é incluído quando a flag está habilitada e o ambiente não é produção.
- Teste em subprocesso com `ENV=production` confirma que `/api/v1/webhooks/payments/hmac_sandbox` não está no conjunto de rotas e responde `404`.
- Webhook Hotmart, ativação e serviços internos legítimos permanecem funcionais.
- Nenhum pedido/licença/tenant é criado pela rota ausente.

### P2-07 — RESOLVIDO

- Logger central `app/core/log_safety.py` com redaction recursiva e textual.
- Campos sensíveis (senha, token, cookie, Authorization, e-mail, CPF/documento, licença, HMAC, HOTTOK, API key, client secret, code, etc.) redigidos por nome e por padrão textual.
- `exc_info` substituído por tipo + `pgcode` + frames `arquivo:linha em função`, sem mensagem original nem linhas de código-fonte.
- Request ID via `contextvars`, validação de formato e `X-Request-ID` em respostas/erros.
- Handlers global/validação retornam mensagem genérica + `request_id`, sem stack trace.
- Uvicorn iniciado com `--no-access-log`; log de acesso próprio sem query string.
- SQLAlchemy/PostgreSQL/httpx/httpcore em WARNING; `echo` não habilitado.
- Hotmart/outbox/worker registram tipo/categoria/contadores, nunca payload, token ou PII.
- Testes exercitam exceção real via TestClient, `IntegrityError`, logs capturados, redaction aninhada, headers sensíveis, request ID e isolamento entre threads.

### Evidências

| Verificação | Resultado |
| --- | --- |
| Backend completo no container | **301 aprovados**, 0 reprovados (122 unitários + 179 integração) |
| Cobertura backend | **85%** |
| `core/log_safety.py` | **94%** |
| `main.py` | **89%** |
| Frontend (Vitest) | **5 aprovados** |
| E2E Playwright | **28 aprovados**, 0 reprovados |
| TypeScript / build Vite | aprovados |
| Alembic heads | `20261102_16` |
| Rotas em produção | `/webhooks/payments/hmac_sandbox` ausente; Hotmart presente |
| Teste de exceção real | resposta genérica, `X-Request-ID`, logs sem e-mail/senha/token/CPF |
| SQLAlchemy | SQL/parâmetros não aparecem nos logs |
| Python compile / diff-check / Compose / builds | aprovados |

### Métricas finais

- **22/49 concluídas (44,9%)**, **23/49 parciais**, **4/49 ausentes**.
- Prontidão ponderada: **68,4%**.
- P0: **0**; P1: **0**; P2: **3** (P2-09, P2-11, P2-12); P3: **6**.
- Head Alembic: `20261102_16`.

### Limitações

- A política de retenção de logs/backups ainda depende de definição operacional.
- Logs de Docker/proxy/PostgreSQL fora da aplicação precisam de revisão no host.
- Nenhuma integração Hotmart/Resend real foi executada.
- Nenhum acesso a VPS, produção, `.env` de produção; nenhum commit, push ou deploy.

---

## 24. Atualização pós-Missão 12 — P2-02

**Data:** 04/11/2026  
**Escopo:** idempotência de criação e execução financeira com `Idempotency-Key` transacional no PostgreSQL.

### P2-02 — RESOLVIDO

- Tabela `idempotency_records` e migration `20261104_17_financial_idempotency.py` após o antigo head `20261102_16`.
- Escopo único por `(tenant_id, user_id, operation, key_hash)`.
- Fingerprint canônico dos campos que alteram o efeito financeiro.
- Replay para mesma chave/fingerprint; `409` para mesma chave com parâmetros diferentes.
- Registro idempotente e efeito financeiro confirmados na mesma transação; rollback remove ambos.
- Concorrência resolvida por unique constraint e lock de linha, sem `processing` permanente.
- Operações cobertas: transações (incluindo gasto no cartão), contas, pagamento, desfazer pagamento, metas e movimentos.
- Orçamento e recorrência continuam protegidos por constraints de domínio, com concorrência tratada sem duplicação.
- Frontend gera e reutiliza chaves em retries, sem depender somente do botão desabilitado.
- RLS/FORCE RLS; API com DML; worker da outbox sem acesso.

### Evidências

| Verificação | Resultado |
| --- | --- |
| Backend completo no container | **319 aprovados**, 0 reprovados (129 unitários + 190 integração) |
| Cobertura backend | **85%** |
| `idempotency_service.py` | **83%** |
| `models/idempotency.py` | **100%** |
| Frontend (Vitest) | **7 aprovados** |
| E2E Playwright | **31 aprovados**, 0 reprovados |
| TypeScript / build Vite | aprovados |
| Alembic heads | `20261104_17` |
| Migração/RLS | idempotency table, FORCE RLS, privilégios da API e worker sem SELECT |
| Concorrência | 10 pagamentos e 10 aportes com a mesma chave → 1 efeito |
| Isolamento | mesma chave em tenants e usuários diferentes → resultados separados |
| Conflito | mesma chave com payload diferente → `409`, sem alteração |

### Métricas finais

- **P2 abertos:** P2-08, P2-09, P2-11, P2-12.
- **Resolvidos:** P2-01, P2-02, P2-03, P2-04, P2-05, P2-06, P2-07, P2-10.
- Head Alembic: `20261104_17`.
- Cobertura: **85%**; testes backend: **319**; componentes: **7**; E2E: **31**.

### Limitações

- `Idempotency-Key` é opcional por compatibilidade; clientes que não enviam mantêm o comportamento legado.
- A chave do frontend é em memória; refresh após sucesso não duplica, mas refresh antes do reenvio perde a correlação.
- A limpeza de registros expirados é operacional e deve ser agendada no host.
- Não houve acesso a VPS, produção, `.env` de produção, Hotmart/Resend reais; nenhum commit, push ou deploy.

---

## 25. Atualização pós-Missão 13 — P2-08

**Data:** 04/11/2026  
**Escopo:** LGPD, exclusão/anonimização, retenção, suporte, outbox/idempotência, RLS, tombstones e documentação de governança.

### P2-08 — RESOLVIDO tecnicamente

- `privacy_requests`, `privacy_request_events` e `data_deletion_tombstones`, migration `20261104_18`.
- Solicitação autenticada em Configurações → Privacidade com reautenticação por senha, protocolo `PRIV-...` e status.
- Member: anonimização dos dados pessoais próprios; dados financeiros compartilhados do tenant preservados.
- Owner com outros usuários ativos: `awaiting_review`; suporte decide com justificativa; aprovação automática bloqueada.
- Owner único: encerramento do tenant, exclusão de dados financeiros, cancelamento de licença, anonimização de comprador/pedido e manutenção de registros comerciais mínimos.
- Outbox pendente/processing cancelada e payload apagado; dead/cancelled higienizadas.
- Idempotência apagada; lockout/rate limit aplicáveis removidos.
- Sessões revogadas, cookie limpo e login posterior bloqueado.
- Tombstones sem PII em claro para reaplicação após restauração de backup.
- RLS/FORCE RLS; suporte com políticas próprias; worker sem acesso.
- SOP e matriz de retenção publicados, com prazos indefinidos marcados para revisão jurídica/contábil.

### Evidências

| Verificação | Resultado |
| --- | --- |
| Backend completo no container | **325 aprovados**, 0 reprovados (129 unitários + 196 integração) |
| Cobertura backend | **85%** |
| Frontend (Vitest) | **7 aprovados** |
| E2E Playwright | **33 aprovados**, 0 reprovados |
| TypeScript / build Vite | aprovados |
| Alembic heads | `20261104_18` |
| Migração/RLS | 3 tabelas com FORCE RLS, políticas de suporte, worker sem acesso |
| Member | dados próprios anonimizados; tenant e finanças compartilhadas preservados |
| Owner único | finanças excluídas; pedido/licença anonimizados/cancelados; login bloqueado |
| Owner compartilhado | `awaiting_review`; aprovação bloqueada enquanto houver membro ativo |
| Outbox | payload cancelado/limpo; worker não reenvia |
| Idempotência | registros do titular removidos |
| Backup/reapply | tombstone inserido e reaplicação testada em PostgreSQL descartável por simulação |
| E2E | privacidade desktop/mobile, reautenticação, erro de senha, aprovação do suporte e sessão revogada |

### Métricas finais

- **P2 abertos:** P2-09, P2-11, P2-12.
- **Resolvidos:** P2-01, P2-02, P2-03, P2-04, P2-05, P2-06, P2-07, P2-08, P2-10.
- Head Alembic: `20261104_18`.
- Cobertura: **85%**; testes backend: **325**; componentes: **7**; E2E: **33**.

### Governança pendente (não é bug de código)

- Aprovar a matriz de retenção com jurídico/contábil.
- Definir controlador, encarregado/DPO, canal oficial e prazo de resposta.
- Definir retenção de logs, backups e registros de incidentes.
- Executar restore drill real em ambiente isolado com reaplicação de tombstones.
- Avaliar contrato/subprocessadores Hotmart/Resend e transferências internacionais.

### Limitações

- Não houve acesso a VPS, produção, `.env` de produção, Hotmart/Resend reais, backup real, commit, push ou deploy.
- O restore drill foi simulado logicamente em PostgreSQL descartável, não executado sobre uma cópia de backup real.
- A licença mantém hash pseudônimo de código para segurança/comercial; prazo jurídico pendente.

---

## 26. Atualização pós-Missão 14 — release candidate e pré-produção

**Data:** 04/11/2026  
**Escopo:** preparação do release candidate, regressão completa, backup/restore drill, worker, preflights, runbooks e matriz de validação externa. **Sem deploy.**

### Decisão de produto

- FortexaHome será apresentado como **produto individual** nesta fase.
- Não haverá convite familiar nem anúncio de compartilhamento.
- P2-09 permanece funcionalidade futura; o suporte técnico a owner/member existente não foi removido.
- P2-11 e P2-12 permanecem adiados e não bloqueiam a jornada essencial de compra, ativação, uso e suporte.

### Release candidate

| Item | Valor |
| --- | --- |
| Branch | `release/fortexahome-launch` |
| Commit base | `8cbd7f70bdb834ec7dc2c5bfa364ce3c10715331` |
| Migration final | `20261104_18_privacy_data_lifecycle.py` |
| Alembic head | `20261104_18` |
| Pacote | `fortexahome-1.0.0-rc.1-20261104.tar.gz` |
| Checksum | arquivo `.sha256` ao lado do pacote |
| Manifesto | `fortexahome-1.0.0-rc.1-20261104.manifest.txt` |
| Testes backend | **325 aprovados**, cobertura **85%** |
| Frontend | **7 testes**, TypeScript e build aprovados |
| E2E | **33 aprovados** |

### Evidências executadas

- Backend completo no container com PostgreSQL real.
- Frontend Vitest, TypeScript e build Vite.
- Playwright completo.
- Compilação Python, `git diff --check`, Compose padrão e E2E, build API/web.
- Preflight environment: `OK=25 WARN=0 FAIL=0 SKIP=2`.
- Preflight database: `OK=8 WARN=0 FAIL=0 SKIP=0`.
- Preflight commercial: `OK=0 WARN=0 FAIL=0 SKIP=1` (Hotmart desabilitada).
- Worker: inicialização, `--check`, heartbeat, processamento de 1 mensagem em provider dev, shutdown gracioso com exit 0.
- Backup/restore drill: dump `pg_dump -Fc`, SHA256 conferido, restore em banco descartável em **2,12 s**, 30 tabelas, head 18, RLS confirmada, grants reaplicados, tombstone pós-cópia reaplicado, usuário anonimizado, banco descartável removido.

### Bloqueadores reais restantes

1. Homologação Resend (domínio, chave, envio, ativação, recuperação, outbox/retry).
2. Homologação Hotmart (OAuth, produto, UCODE, HOTTOK, webhook, reembolso, chargeback, reconciliação).
3. DNS/TLS/cookies Secure/CORS/proxy em staging prod-like.
4. Backup/restore real da VPS com storage protegido e RPO/RTO aprovados.
5. Governança LGPD: controlador, encarregado/canal, prazos, bases legais, retenção de logs/backups e subprocessadores.
6. Monitoramento/alertas/on-call e carga/múltiplas réplicas, conforme arquitetura.

### Documentação criada

- [release-runbook.md](release-runbook.md)
- [backup-restore-runbook.md](backup-restore-runbook.md)
- [prelaunch-checklist.md](prelaunch-checklist.md)
- [external-validation-matrix.md](external-validation-matrix.md)

### Conclusão

Existe um release candidate reproduzível, íntegro e empacotado para validação em staging. **O FortexaHome não está pronto para venda apenas por ter gerado o pacote.** A liberação depende das validações externas, aprovação de governança e implantação controlada posterior.
