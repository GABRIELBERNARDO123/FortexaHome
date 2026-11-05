# Matriz de retenção de dados

**Status geral:** política técnica inicial. Prazos marcados como pendentes **não** são obrigações legais confirmadas e exigem validação jurídica/contábil antes do lançamento.

## Legenda

- **Aprovado:** decisão técnica implementada no código/documentação atual.
- **Pendente de decisão:** requer validação jurídica, contábil ou operacional.
- **Não aplicável:** categoria não existe ou não é tratada pelo FortexaHome.

## Matriz

| Categoria | Finalidade | Origem | Titular | Base legal documentada | Retenção | Justificativa | Ação após finalidade | Em solicitação de exclusão | Backup | Responsável | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| E-mail, nome, senha (hash), tema/preferências | Autenticar e personalizar a conta | Cliente | Usuário | Execução de contrato (art. 7º, V) — a confirmar | Enquanto a conta existir | Necessário para acesso e segurança | Excluir/anonimizar no encerramento | Anonimizado; senha substituída por hash inutilizável | Pode reaparecer em backup antigo; reaplicar tombstone | Jurídico + Engenharia | Aprovado (técnico) |
| Sessões, tokens de reset, códigos de ativação, lockout | Segurança e autenticação | Cliente/sistema | Usuário | Execução de contrato e segurança (art. 7º, V/IX) — a confirmar | Sessão: até expirar/revogar; tokens: TTL; lockout: até expirar | Proteção contra acesso indevido | Excluir ou expirar | Sessões/reset apagados; ativações anonimizadas/expiradas; lockout removido | Reaplicar tombstone | Engenharia | Aprovado (técnico) |
| Lançamentos, contas, cartões, metas, orçamentos, categorias | Funcionalidade financeira contratada | Cliente | Usuário/tenant | Execução de contrato — a confirmar | Enquanto a conta do tenant existir | Dados inseridos pelo próprio cliente | Excluir no encerramento do tenant; preservar em tenant compartilhado | Member: preservados no tenant; owner único: excluídos | Backup antigo deve ser tratado por tombstone | Jurídico + Engenharia | Aprovado (técnico); retenção específica pendente |
| Pedido, transação, valor, produto, status, reembolso, chargeback | Prova comercial, suporte e eventual obrigação legal/regulatória | Hotmart | Comprador | Execução de contrato / obrigação legal a confirmar | **Pendente** | Necessário para suporte, contestação e conciliação | Anonimizar comprador; manter dados comerciais mínimos | E-mail, hash e customer ID anonimizados; valores/estado preservados | Reaplicar tombstone | Jurídico/Contábil | **REVISÃO JURÍDICA/CONTÁBIL NECESSÁRIA** |
| Licença e código (hash) | Controle de acesso e prevenção de reutilização | Hotmart/FortexaHome | Comprador | Execução de contrato e segurança | **Pendente** | Evitar reutilização e comprovar entrega | Cancelar e desvincular; manter hash pseudônimo enquanto necessário | Licença cancelada, revogada, tenant/e-mail desvinculados | Reaplicar tombstone | Jurídico/Engenharia | **REVISÃO JURÍDICA NECESSÁRIA** |
| Eventos de pagamento e reconciliação | Integridade e conciliação comercial | Hotmart | Comprador/tenant | Execução de contrato / obrigação legal a confirmar | **Pendente** | Auditoria de estado comercial | Manter sem PII direta | Dados de comprador nos pedidos relacionados são anonimizados | Reaplicar tombstone | Jurídico/Contábil | **REVISÃO JURÍDICA/CONTÁBIL NECESSÁRIA** |
| Outbox transacional | Entrega de e-mail | Sistema | Usuário | Execução de contrato | Até envio/cancelamento/expiração | Entrega necessária | Payload apagado após envio/cancelamento | Pendentes/processing cancelados; payload apagado; dead letters higienizadas | Backup antigo pode conter payload cifrado; reaplicar tombstone | Engenharia | Aprovado (técnico) |
| Registros de idempotência | Evitar duplicidade financeira | Sistema | Usuário | Legítimo interesse/segurança — a confirmar | 7 dias (`IDEMPOTENCY_RETENTION_HOURS=168`) | Janela de retry | Excluir expirados | Apagados para o usuário/tenant | Reaplicar tombstone | Engenharia | Aprovado (técnico) |
| Rate limit e lockout | Segurança e prevenção de abuso | Sistema | Usuário/IP | Segurança (art. 7º, IX) — a confirmar | Até expiração; limpeza periódica | Proteção contra abuso | Excluir/expirar | Hashes associados ao usuário/e-mail removidos | Reaplicar tombstone | Engenharia | Aprovado (técnico) |
| Auditoria do cliente e suporte | Segurança, suporte e comprovação | Sistema | Usuário/operador | Obrigação legal/segurança — a confirmar | **Pendente** | Investigação e defesa | Manter sem PII direta; anonymizar vínculo | `user_id` desvinculado; evento de exclusão preservado | Reaplicar tombstone | Jurídico/Segurança | **REVISÃO JURÍDICA NECESSÁRIA** |
| Logs operacionais | Diagnóstico e segurança | Sistema | Usuário/operador | Segurança/legítimo interesse — a confirmar | **Pendente** | Monitoramento e incidentes | Expurgo conforme retenção operacional | Não há PII por política; logs históricos não são alterados por conta | Retenção externa | Segurança/Operação | **REVISÃO JURÍDICA/OPERACIONAL NECESSÁRIA** |
| Backups PostgreSQL | Recuperação de desastres | Sistema | Todos | Segurança/continuidade — a confirmar | **Pendente** | Restauração e integridade | Expurgo conforme política de backup | Tombsone externo + reaplicação após restore | Backup não é alterado | Segurança/Operação | **REVISÃO JURÍDICA/OPERACIONAL NECESSÁRIA** |
| Registros de incidentes de segurança | Investigação e prestação de contas | Sistema | Titulares afetados | Obrigação regulatória (Resolução CD/ANPD nº 15/2024) | **Pelo menos 5 anos** para incidentes abrangidos | Determinação regulatória específica | Manter registro mínimo e restrito | Não usar esta retenção para logs gerais | Backup protegido | Encarregado/Segurança | Aprovado como obrigação específica; escopo a validar |
| Dados de operadores de suporte | Autenticação e auditoria do backoffice | FortexaHome | Operador | Execução de contrato/segurança — a confirmar | Enquanto o operador estiver ativo + auditoria pendente | Controle de acesso administrativo | Desativar e anonimizar conforme política de RH/segurança | Fora do escopo do titular-cliente | Reaplicar política própria | Jurídico/RH/Segurança | **REVISÃO JURÍDICA NECESSÁRIA** |

## Observações

- A LGPD não fixa prazo único de retenção. Os prazos acima não substituem análise jurídica/contábil.
- A retenção de um pedido comercial **não** autoriza conservar todos os dados financeiros domésticos do cliente.
- Hashes e HMACs são pseudonimização, não anonimização automática; o risco de reidentificação deve ser avaliado.
- A Resolução CD/ANPD nº 15/2024 é aplicável a registros de incidentes de segurança abrangidos; ela não autoriza reter todos os logs ou dados de clientes por cinco anos.
- A política final deve ser aprovada pelo responsável legal da empresa e registrada com data/versão.
