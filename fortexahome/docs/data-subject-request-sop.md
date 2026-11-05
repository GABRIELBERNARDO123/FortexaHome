# SOP — Solicitações de titulares de dados

**Público:** suporte, segurança e responsável legal.  
**Escopo:** exclusão, anonimização, acesso, correção, bloqueio, portabilidade e informações sobre compartilhamento.  
**Aviso:** este SOP não substitui parecer jurídico. Prazos legais e bases de retenção pendentes estão na [matriz de retenção](data-retention-matrix.md).

## 1. Recebimento

Canais aceitos:

- solicitação autenticada em Configurações → Privacidade;
- pedido encaminhado ao suporte por canal oficial (a definir antes do lançamento);
- solicitação do encarregado/DPO (identidade e contato **pendentes de definição**).

Registre protocolo, data, tipo de direito e forma de verificação. Não registre documentos pessoais completos em tickets, logs ou campos livres.

## 2. Verificação de identidade e propriedade

1. Confirme que a solicitação veio de sessão autenticada e licença ativa.
2. Para exclusão, exija reautenticação com senha atual.
3. Nunca aceite apenas um ID de usuário, e-mail ou protocolo como prova de propriedade.
4. Se a solicitação chegou por canal externo, use o e-mail já cadastrado e um desafio de verificação; não envie dados para endereço não verificado.
5. Em caso de dúvida sobre identidade, suspenda e escale; não execute exclusão.

## 3. Classificação do direito

| Direito | Tratamento inicial |
| --- | --- |
| Exclusão/eliminação | Fluxo de exclusão com análise de owner/member/tenant |
| Anonimização | Avaliar se o dado pode ser anonimizado sem perder finalidade legítima |
| Acesso/confirmação | Exportação JSON existente + revisão humana |
| Correção | Perfil/configurações; dados financeiros editáveis pelo cliente |
| Bloqueio | Suspender uso enquanto a análise estiver pendente |
| Portabilidade | Exportação JSON, quando aplicável; avaliar formato |
| Compartilhamento | Consultar [lifecycle](lgpd-data-lifecycle.md) e subprocessadores |

## 4. Vínculos com tenant

Antes de aprovar:

1. Identifique se o titular é owner ou member.
2. Verifique se há outros usuários ativos no tenant.
3. Verifique pedidos, licenças, assinaturas e outbox.
4. Member: somente dados pessoais próprios; não apague o tenant.
5. Owner com outros usuários: **não execute automaticamente**; encaminhe para análise. Não transfira ownership silenciosamente.

## 5. Classificação dos dados

Use a [matriz de retenção](data-retention-matrix.md):

- excluível;
- anonimizável;
- conservável com fundamento documentado;
- pendente de decisão;
- fora do escopo.

Não apague pedidos, eventos ou licenças sem avaliar obrigação comercial/legal.

## 6. Análise de retenção

1. Confirme se existe fundamento documentado para conservar.
2. Se o prazo estiver pendente, registre `REVISÃO JURÍDICA/CONTÁBIL NECESSÁRIA` e limite o acesso ao mínimo.
3. Em tenant compartilhado, dados financeiros comuns podem permanecer para os demais usuários.
4. Nunca use dado preservado para reativar conta, marketing ou finalidade incompatível.

## 7. Aprovação ou recusa

- Aprovação exige justificativa mínima de 10 caracteres e perfil `support_operator`.
- Recusa exige justificativa, fundamento e comunicação ao titular.
- O sistema bloqueia aprovação de owner com outros usuários ativos.
- Ações são auditadas em `support_audit_logs` e `privacy_request_events`.

## 8. Execução

1. Cliente owner único/member: execução transacional pelo serviço de privacidade.
2. Owner compartilhado: aguardar desvinculação/remoção dos demais usuários ou decisão jurídica.
3. A execução:
   - revoga sessões;
   - anonimiza perfil;
   - apaga/anonimiza tokens e ativações;
   - cancela/higieniza outbox;
   - apaga idempotência;
   - remove lockout/rate limit aplicáveis;
   - no tenant único, exclui dados financeiros e anonimiza dados comerciais;
   - grava tombstone de exclusão.
4. Falha antes do commit reverte a transação; não fica status `processing`.

## 9. Revisão do resultado

Verifique:

- protocolo com status `completed`;
- sessões revogadas e login bloqueado;
- ausência de PII no perfil ativo;
- pedidos/licenças preservados apenas com dados anonimizados;
- outbox pendente cancelada;
- tombstone criado;
- dados de outros tenants intactos.

## 10. Comunicação ao titular

- Informe protocolo, data, resultado e escopo.
- Explique dados conservados e fundamento, quando houver.
- Não envie cópia de dados de terceiros.
- Para direitos ainda não automatizados, informe o canal e o prazo operacional definido pelo responsável legal.

## 11. Evidências

Preserve:

- `privacy_requests`;
- `privacy_request_events`;
- `support_audit_logs`;
- `data_deletion_tombstones`;
- resultado da revisão.

Não copie PII para tickets, planilhas ou chats.

## 12. Dados de terceiros

Se o pedido afetar outro usuário/tenant:

- não revele dados do terceiro;
- não apague registros compartilhados sem análise;
- escale para o responsável legal/segurança.

## 13. Escalonamento

Escale para decisão jurídica/contábil quando:

- houver pedido, licença ou evento comercial a conservar;
- o titular for owner com outros membros;
- houver incidente de segurança;
- houver dúvida sobre base legal, prazo ou identidade;
- o pedido envolver portabilidade ou compartilhamento com terceiros.

## 14. Backups e restauração

Antes de restore:

1. Exporte `data_deletion_tombstones` da base atual.
2. Preserve o arquivo em local restrito.
3. Restaure a cópia em ambiente isolado.
4. Reaplique os tombstones com o procedimento técnico documentado em [lgpd-data-lifecycle.md](lgpd-data-lifecycle.md).
5. Verifique contas afetadas e só então libere o ambiente.

Nunca altere/apague backup real nesta operação.

## 15. Pendências antes do lançamento

- Definir controlador, encarregado/DPO, canal oficial e prazo de resposta.
- Aprovar a matriz de retenção (jurídico/contábil).
- Definir retenção de logs, backups e registros de incidentes.
- Formalizar subprocessadores e contratos.
