# Gestão de categorias

## Objetivo

Permitir que o responsável pela conta adapte as categorias financeiras à realidade da família, arquive categorias que não devem mais ser usadas e preserve o histórico de lançamentos, contas e orçamentos.

## Modelo e migrations

A tabela `categories` já existia com `tenant_id`, `name`, `kind`, `color`, `icon` e `is_system`. A migration `20261101_13_category_archive.py` adiciona:

- `archived BOOLEAN NOT NULL DEFAULT false`.

A unicidade permanece por tenant + tipo + `lower(name)`. Por isso, uma categoria arquivada ainda ocupa o nome; para reutilizá-lo, reative a categoria existente em vez de criar outra.

## Regras de negócio

- Categorias padrão (`is_system=true`) não podem ser excluídas nem arquivadas. Nome, cor e ícone continuam editáveis, preservando o comportamento anterior.
- Categoria personalizada pode ser arquivada mesmo em uso. O histórico permanece e a categoria deixa de ser oferecida para novos lançamentos, contas e orçamentos.
- Categoria personalizada só pode ser excluída quando não possui lançamentos, contas ou orçamentos vinculados.
- Categoria arquivada não pode ser escolhida em novos lançamentos, contas ou orçamentos.
- Registros existentes continuam exibindo o nome da categoria arquivada. Um lançamento antigo pode ser editado mantendo a mesma categoria arquivada; contas existentes podem ser pagas e recorrências podem continuar o histórico.
- A API retorna `usage_count` e `in_use`, calculados a partir de lançamentos, contas e orçamentos do tenant.
- O isolamento por tenant usa RLS/FORCE RLS e os serviços consultam sempre `tenant_id`.

## Relação com idempotência financeira

A criação/edição/exclusão de categorias não faz parte do escopo P2-02: não gera lançamento, pagamento ou movimentação financeira. O `category_id` participa do fingerprint das operações financeiras idempotentes; portanto, um retry do mesmo lançamento com outra categoria é tratado como reutilização indevida da chave (`409`), enquanto uma nova chave cria a operação intencional. Consulte [financial-idempotency.md](financial-idempotency.md).

## Permissões

- `owner`: listar, criar, editar, arquivar/reativar e excluir.
- `member`: listar; mutações retornam `403`.
- Qualquer categoria de outro tenant retorna `404` nas operações de leitura/alteração.

## API

- `GET /api/v1/categories?kind=income|expense&archived=true|false` — lista categorias. Sem filtro, inclui ativas e arquivadas para preservar filtros históricos.
- `POST /api/v1/categories` — cria categoria ativa.
- `PATCH /api/v1/categories/{id}` — atualiza `name`, `color`, `icon` e/ou `archived`.
- `DELETE /api/v1/categories/{id}` — exclui categoria personalizada sem uso.

Erros relevantes:

- `409` nome duplicado, categoria padrão protegida ou categoria em uso;
- `400` categoria arquivada em novo lançamento/conta/orçamento ou tipo incompatível;
- `403` mutação por member;
- `404` categoria de outro tenant/inexistente.

## Interface

A rota `/categorias` está disponível no menu principal:

- busca por nome;
- filtros por tipo (receita/despesa) e situação (ativa/arquivada);
- indicadores de uso, “Padrão” e “Arquivada”;
- criação/edição com nome, tipo, cor e ícone;
- arquivamento com confirmação; reativação;
- exclusão apenas quando o backend confirma que não há uso;
- member vê a lista em modo somente leitura.

Os formulários de lançamentos, contas e orçamentos filtram categorias arquivadas. Ao editar um registro antigo, a categoria arquivada atual é mantida como opção marcada com “(arquivada)”.

## Testes

Backend (`backend/tests/integration/test_financial_domain.py`):

- CRUD, duplicidade case-insensitive, edição de atributos;
- contagem de uso e bloqueio de exclusão;
- arquivamento/reativação e proteção das categorias padrão;
- rejeição de categoria arquivada em novos lançamentos/contas/orçamentos;
- edição de lançamento histórico com categoria arquivada;
- pagamento de conta e geração de recorrência com categoria arquivada;
- permissões owner/member;
- isolamento entre tenants.

Componente (`frontend/src/pages/CategoriesPage.test.tsx`): owner vê ações e uso; member permanece somente leitura.

E2E (`frontend/e2e/categories-management.spec.ts`):

- criação, edição, duplicidade, arquivamento, reativação e exclusão;
- categoria em uso arquivada com histórico preservado e edição permitida;
- member somente leitura e `403` na API;
- isolamento entre dois tenants;
- responsividade da página em celular.

## Operação e rollback

A migration é aditiva e segura para banco descartável/homologação. O downgrade remove apenas `categories.archived`, portanto deve ser usado somente em ambiente descartável e após confirmar que nenhuma operação depende do arquivamento. Nunca execute downgrade em produção sem backup e plano de reversão.
