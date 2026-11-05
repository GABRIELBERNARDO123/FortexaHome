# FortexaHome — Testes E2E com Playwright

## 1. Ferramenta

- **Playwright 1.64** com Chromium headless.
- Configuração: `frontend/playwright.config.ts`.
- Testes: `frontend/e2e/*.spec.ts`.
- Helpers/fixtures: `frontend/e2e/helpers.ts`, `frontend/e2e/global-setup.ts`, `frontend/e2e/global-teardown.ts`.
- Dependência local em `frontend/package.json` (`@playwright/test`).

Não há segunda ferramenta E2E no projeto.

## 2. Ambiente isolado

O arquivo `docker-compose.e2e.yml` cria um projeto Compose próprio chamado `fortexahome_e2e`, sem reutilizar o banco/stack de desenvolvimento:

- `e2e-db`: PostgreSQL 16 descartável, sem volume, porta `127.0.0.1:5435`.
- `e2e-migrate`: executa preflight de ambiente e `alembic upgrade head`.
- `e2e-api`: API em `127.0.0.1:8011`, com env de teste e `EMAIL_PROVIDER=dev`.
- `e2e-web`: frontend Nginx em `127.0.0.1:3011`, proxy interno para `api:8000`.
- `e2e-seed`: imagem de testes; executa `python -m tests.e2e_seed`.

O projeto separado permite `down` sem afetar a stack normal. Nenhum volume persistente é usado para o E2E. Não há chamada real à Hotmart ou Resend; `HOTMART_ENABLED=false`.

Credenciais e segredos do Compose E2E são locais, descartáveis e explicitamente não produtivos.

## 3. Seed e fixtures

`backend/tests/e2e_seed.py` só executa com `ENV=test` e `E2E_SEED=1`. Ele cria:

- produto interno `fortexahome-e2e`;
- licença de ativação com desafio conhecido (`123456`);
- licença de recuperação com desafio conhecido (`654321`);
- conta owner `cliente.e2e@example.com`, member `membro.e2e@example.com` e segundo tenant owner `cliente2.e2e@example.com` para isolamento;
- pedido `TX-E2E-0001`, licença e entrega na outbox;
- pedido terminal `TX-E2E-REF-0001`;
- operadores `suporte.e2e@example.com` (`support_operator`), `leitura.e2e@example.com` e `lockout.e2e@example.com` (`support_read`); tenant dedicado de privacidade com owner/member `privacidade.owner.e2e@example.com` e `privacidade.member.e2e@example.com`.

Senhas são exclusivas do ambiente E2E e documentadas apenas para testes locais.

## 4. Execução

Na raiz:

```sh
cd frontend
npm install
npm run test:e2e
```

O `globalSetup`:

1. derruba apenas o projeto E2E (`docker compose -p fortexahome_e2e down --remove-orphans`);
2. sobe banco, migração, API e web com build;
3. executa o seed;
4. aguarda web e health da API;
5. cria storage states de cliente, member, segundo tenant e suporte.

O `globalTeardown` derruba o projeto E2E e remove os storage states locais, salvo `E2E_KEEP=1`.

Para manter o ambiente após falha e investigar:

```sh
E2E_KEEP=1 npm run test:e2e
```

Para usar um ambiente já iniciado, sem gerenciar Compose:

```sh
E2E_EXTERNAL=1 E2E_BASE_URL=http://127.0.0.1:3011 npm run test:e2e
```

## 5. Cenários cobertos

- Autenticação do cliente: rota protegida, sucesso, erro, persistência, logout.
- Ativação por e-mail com código controlado, código inválido e sucesso.
- Recuperação de licença com resposta genérica e confirmação por código.
- Transações: criar, buscar, excluir.
- Categorias: criar, editar, duplicidade, arquivar/reativar, excluir, categoria em uso, member somente leitura e isolamento entre tenants.
- Contas: criar, pagar, desfazer.
- Cartões: criar e acompanhar limite.
- Metas: criar e aportar.
- Dashboard, relatórios, download CSV e configurações.
- Backoffice: login, dashboard, pedidos, detalhe, ação com justificativa, idempotência, pedido terminal, auditoria, read-only/403, cliente/member barrados, cookie inválido, lockout.
- Idempotência financeira: retry de lançamento, pagamento e aporte com a mesma chave, conflito `409`, refresh após sucesso e nova operação com nova chave.
- Privacidade/LGPD: painel desktop/mobile, reautenticação, senha incorreta, member com exclusão imediata, owner compartilhado em análise, aprovação do suporte, sessão revogada e login posterior bloqueado.
- Responsividade: desktop, tablet, celular, menu mobile, página de categorias e ausência de scroll horizontal.
- Acessibilidade básica: labels, foco por teclado e alerta de validação.

## 6. Depuração

- Falhas geram screenshot e trace em `frontend/test-results`.
- Abrir trace:

```sh
cd frontend
npx playwright show-trace test-results/<pasta>/trace.zip
```

- Executar um arquivo/cenário:

```sh
npx playwright test e2e/financial-flows.spec.ts
npx playwright test -g "cria cartão"
```

- Rodar com interface:

```sh
npm run test:e2e:ui
```

## 7. Limpeza segura

- Teardown padrão: `docker compose -f docker-compose.e2e.yml -p fortexahome_e2e down --remove-orphans`.
- Sem `-v`; não remove volumes de outros projetos.
- `frontend/e2e/.auth/` e `frontend/test-results/` são artefatos locais e estão no `.gitignore`.
- Nunca aponte o Compose E2E para o banco de desenvolvimento/produção.

## 8. Limitações

- Apenas Chromium foi executado. A suíte atual tem 33 cenários.
- Hotmart/Resend são simulados/desabilitados.
- O ambiente E2E mantém `RATE_LIMIT_ENABLED=true`; o lockout do suporte é testado. Testes de carga e múltiplas réplicas não fazem parte.
- Testes usam um worker Playwright para evitar disputa de dados; os dados são isolados por seed, nomes únicos e um segundo tenant para validar isolamento de categorias.
- O ambiente E2E mantém `RATE_LIMIT_ENABLED=true`; o rate limit usa PostgreSQL compartilhado. O 429 e o `Retry-After` são validados por integração de backend para não interferir nos fluxos E2E normais.
- Não há teste E2E de envio real de e-mail; a outbox é inspecionada via interface/backoffice e testes de integração.

## Release candidate (Missão 14)

A suíte E2E completa do release candidate executou **33 cenários** com Chromium, incluindo financeiro, idempotência, privacidade/LGPD, ativação, recuperação, backoffice, suporte e responsividade. O ambiente permanece descartável, com `HOTMART_ENABLED=false` e `EMAIL_PROVIDER=dev`.

Consulte [release-runbook.md](release-runbook.md) e [prelaunch-checklist.md](prelaunch-checklist.md).
