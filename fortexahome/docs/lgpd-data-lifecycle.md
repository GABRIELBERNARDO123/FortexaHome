# Ciclo de vida de dados pessoais — LGPD

## 1. Escopo e aviso

Este documento descreve a implementação técnica do FortexaHome para solicitações de titulares e o ciclo de vida dos dados. **Não é parecer jurídico.** Fundamentos e prazos marcados como pendentes exigem validação do responsável legal, jurídico e contábil.

Referências iniciais: Lei nº 13.709/2018 (LGPD), especialmente arts. 15, 16, 18 e 19; orientações da ANPD; Resolução CD/ANPD nº 15/2024 para registros de incidentes de segurança abrangidos.

## 2. Inventário e finalidades

| Grupo | Exemplos | Tratamento |
| --- | --- | --- |
| Conta | e-mail, nome, senha (hash), tema | Anonimização/exclusão no encerramento |
| Autenticação | sessões, reset, ativação, lockout | Revogação/exclusão/expiração |
| Financeiro do cliente | lançamentos, contas, cartões, metas, orçamentos, categorias | Member: preservado no tenant compartilhado; owner único: excluído |
| Comercial | pedido, transação, produto, valor, estado, licença | Preservado com comprador anonimizado; prazo pendente |
| Operacional | outbox, idempotência, rate limit, logs, auditoria | Cancelado/higienizado/anonimizado conforme finalidade |
| Backups | cópia PostgreSQL | Retenção pendente; reaplicação de tombstone após restore |

A matriz detalhada está em [data-retention-matrix.md](data-retention-matrix.md).

## 3. Bases legais identificadas

As bases abaixo são hipóteses técnicas a validar:

- execução de contrato — conta, licença, entrega e suporte;
- cumprimento de obrigação legal/regulatória — registros comerciais, quando aplicável;
- segurança/prevenção a fraude — autenticação, rate limit, lockout, auditoria;
- exercício regular de direitos — defesa em processos e suporte.

Consentimento não é tratado como base única. A base final por categoria deve ser aprovada e registrada.

## 4. Direitos dos titulares

| Direito | Situação | Canal |
| --- | --- | --- |
| Exclusão/eliminação | Implementado para titular autenticado | Configurações → Privacidade |
| Acesso/confirmação | Exportação JSON existente + atendimento | Configurações / suporte |
| Correção | Perfil e dados financeiros editáveis | Configurações/UI |
| Anonimização | Implementada no fluxo de exclusão | Configurações/suporte |
| Bloqueio | Manual pelo suporte/SOP | Suporte |
| Portabilidade | Exportação JSON, quando aplicável | Configurações/suporte |
| Informação sobre compartilhamento | Documentação/SOP | Suporte |

Controlador, encarregado/DPO, e-mail e endereço oficial **não estão definidos no repositório** e devem ser publicados antes do lançamento.

## 5. Jornada de exclusão

1. Cliente autenticado acessa Configurações → Privacidade.
2. Informa senha atual (reautenticação) e motivo opcional.
3. Sistema cria `privacy_requests` com protocolo `PRIV-...` e evento `requested`.
4. Member: anonimização imediata dos próprios dados; tenant e dados compartilhados permanecem.
5. Owner único: encerramento do tenant, exclusão dos dados financeiros e anonimização comercial.
6. Owner com outros usuários ativos: status `awaiting_review`; nenhuma exclusão automática.
7. Suporte aprovado executa; recusa exige justificativa.
8. Sessões são revogadas e cookie limpo; login posterior falha.

Não há exclusão por ID de usuário, e-mail ou requisição anônima.

## 6. Separação exclusão × anonimização

- **Excluídos:** perfil, sessões, tokens, ativações, lockout/rate limit aplicáveis, idempotência, dados financeiros do tenant encerrado.
- **Anonimizados:** usuário (`deleted-<id>@invalid.local`, nome “Conta excluída”, senha inutilizável), comprador em pedidos, vínculo de auditoria.
- **Conservados com fundamento pendente:** pedido, evento, licença/valores comerciais, auditoria. O comprador é desvinculado; hashes pseudônimos podem permanecer.
- **Preservados em tenant compartilhado:** dados financeiros comuns, pois pertencem ao tenant/outros usuários.
- **Fora do escopo:** dados de operadores de suporte e informações de terceiros.

Pseudonimização (hash/HMAC) não é tratada como anonimização automática.

## 7. Owner, member e tenant

- Member não exclui o tenant; apenas seus dados pessoais.
- Owner com outros usuários ativos não é executado automaticamente.
- Owner único encerra o tenant, revoga licença, exclui dados financeiros e anonimiza registros comerciais.
- Não há transferência silenciosa de ownership nesta versão.
- A licença é cancelada/revogada; não é reutilizada para reativar a conta.

## 8. Dados comerciais e financeiros

- Pedidos e eventos são preservados sem e-mail/hash/customer ID do comprador.
- Licença cancelada, desvinculada do tenant e com `bound_email_hash` limpo; `code_hash` permanece pseudônimo para impedir reutilização.
- Valores, status e datas comerciais permanecem para conciliação/defesa, com prazo pendente de revisão jurídica/contábil.
- Registros financeiros domésticos do cliente não são tratados como obrigação fiscal automática da FortexaHome.

## 9. Outbox

No encerramento:

- mensagens `pending`/`processing` são canceladas e o payload é apagado;
- mensagens `dead`/`cancelled` têm payload apagado;
- o worker não recebe privilégio novo;
- entregas já `sent` não podem ser recolhidas, mas não mantêm payload;
- licença cancelada impede nova entrega de licença.

## 10. Idempotência

- Registros do usuário/tenant são apagados na exclusão.
- Replays antigos não recuperam dados pessoais porque o usuário não autentica mais e os registros são removidos.
- A limpeza de expirados continua compatível (`IDEMPOTENCY_RETENTION_HOURS`).

## 11. Logs e auditoria

- Logs da aplicação não devem conter PII/segredos (ver [security-logging.md](security-logging.md)).
- A exclusão não reescreve logs históricos; a retenção de logs é operacional/jurídica pendente.
- `audit_logs` e `support_audit_logs` são preservados sem vínculo direto de usuário; o evento de exclusão e o protocolo servem como evidência.
- Operações do suporte exigem justificativa e são append-only.

## 12. Backups e restauração

Não há prazo legal de backup definido neste repositório. Estratégia técnica:

1. Antes de restore, exportar `data_deletion_tombstones` da base atual.
2. Guardar o arquivo em local restrito e auditável.
3. Restaurar a cópia em ambiente isolado.
4. Reaplicar cada tombstone (`tenant_id`, `user_id`, `scope`) com o serviço de privacidade.
5. Verificar contas/tenants afetados e só então liberar o ambiente.

O tombstone contém apenas IDs internos, escopo e data; não contém e-mail/PII em claro. A restauração completa real deve ser executada em ambiente descartável e registrada antes do lançamento. O procedimento local não altera backups reais.

## 13. RLS e segurança

- `privacy_requests`, `privacy_request_events` e `data_deletion_tombstones` usam RLS/FORCE RLS e policy por `app.tenant_id`.
- Suporte acessa via `app.support_operator_id`, com papéis `support_read`/`support_operator`.
- Worker da outbox não acessa as novas tabelas.
- Operações privilegiadas de restore/exportação ficam fora da API.
- Não há SUPERUSER/BYPASSRLS para a API.

## 14. Subprocessadores

Identificados no fluxo atual: Hotmart (compra/pagamento) e Resend (entrega de e-mail). Contratos, transferências internacionais e informações de compartilhamento precisam ser validados e publicados pelo responsável legal.

## 15. Pendências jurídicas/contábeis

- Bases legais por categoria.
- Prazo de retenção de pedidos, eventos, licenças, auditoria, logs e backups.
- Definição de controlador, encarregado/DPO e canal oficial.
- Política de incidentes e aplicação da Resolução CD/ANPD nº 15/2024.
- Processo de portabilidade e informações sobre compartilhamento.
- Aprovação formal da matriz de retenção.

## 16. Limitações técnicas

- Não há restore real executado na VPS/produção; a reaplicação de tombstone foi testada em PostgreSQL descartável por simulação.
- Dados já entregues a terceiros (e-mail/Resend, Hotmart) dependem dos controles do provedor.
- Logs de infraestrutura (Docker/proxy/PostgreSQL) exigem configuração de retenção no host.
- A licença mantém `code_hash` pseudônimo para segurança/comercial; revisão jurídica deve avaliar prazo.
