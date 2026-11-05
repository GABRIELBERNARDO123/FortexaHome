# Checklist pré-lançamento — FortexaHome

> Nenhum item abaixo autoriza deploy. O lançamento comercial só ocorre após todos os bloqueadores aprovados, release implantado de forma controlada e decisão formal.

## A. Produto e escopo comercial

- [ ] Produto apresentado como **individual**: uma licença por comprador, um usuário por licença.
- [ ] Não há anúncio de compartilhamento familiar/multi-usuário.
- [ ] P2-09 mantido como funcionalidade futura.
- [ ] P2-11/P2-12 avaliados como não bloqueadores da jornada essencial.
- [ ] Limitações de busca/filtros e status de entrega ao cliente comunicadas ao suporte.

## B. Bloqueadores técnicos já implementados

- [ ] P2-05: rota `hmac_sandbox` ausente em produção; sandbox rejeitado pelo `Settings`/preflight; Hotmart independente.
- [ ] P2-06: `APP_BASE_URL` HTTPS, cookies Secure, CORS HTTPS e proxy confiável validados.
- [ ] P2-07: redaction, request ID, erros sem stack trace, SQLAlchemy sem parâmetros sensíveis.
- [ ] P2-02: idempotência financeira, concorrência, replay e conflito `409` comprovados.
- [ ] P2-08: exclusão/reautenticação/anonimização, outbox, idempotência, owner/member, SOP, tombstones e matriz de retenção implementados.
- [ ] Migrations no head `20261104_18`.
- [ ] Suíte backend, frontend e E2E verdes no release candidate.

## C. Governança LGPD (responsável legal)

- [ ] Controlador dos dados definido.
- [ ] Encarregado/DPO ou canal de contato definido.
- [ ] Canal oficial de atendimento ao titular publicado.
- [ ] Prazo de resposta definido.
- [ ] Base legal por categoria aprovada.
- [ ] Retenção de pedidos/registros comerciais aprovada.
- [ ] Retenção de logs aprovada.
- [ ] Retenção de backups aprovada.
- [ ] Contratos/subprocessadores Hotmart/Resend revisados.
- [ ] Transferências internacionais avaliadas.
- [ ] Procedimento de incidentes aprovado e registros da Resolução CD/ANPD nº 15/2024 definidos.
- [ ] Matriz de retenção formalmente aprovada com data/versão.

## D. Backup e restore

- [ ] Backup pré-release executado e checksum validado.
- [ ] Restore drill real em ambiente isolado aprovado.
- [ ] RLS/roles/grants verificados no restore.
- [ ] Tombstones exportados antes do restore e reaplicados após.
- [ ] Dados excluídos não reapareceram.
- [ ] RPO/RTO aprovados.
- [ ] Frequência/retenção de backup aprovadas.
- [ ] Procedimento de descarte de backup definido.

## E. Integrações externas

- [ ] Resend: domínio verificado, chave de produção, envio controlado, ativação, recuperação, outbox e retry.
- [ ] Hotmart: OAuth, produto, UCODE, webhook, HOTTOK, aprovação, reenvio, reembolso, chargeback e reconciliação.
- [ ] DNS/TLS do domínio validados.
- [ ] Cookies Secure/CORS/proxy confiável validados em staging prod-like.
- [ ] Alertas/monitoramento e on-call definidos.
- [ ] Carga/múltiplas réplicas avaliadas conforme arquitetura.
- [ ] Nenhuma credencial real inserida em logs, tickets ou repositório.

## F. Release e implantação

- [ ] Release candidate identificado por SHA256.
- [ ] Manifesto confere.
- [ ] `.env` e segredos não estão no pacote.
- [ ] Compose de produção revisado (Traefik, rede, portas, healthchecks).
- [ ] Backup pré-release realizado.
- [ ] Preflight environment/database/commercial aprovados.
- [ ] Migrations aplicadas no banco correto.
- [ ] Builds reproduzíveis e digests registrados.
- [ ] API, worker e web saudáveis.
- [ ] Smoke tests aprovados.
- [ ] Rollback ensaiado.
- [ ] Critérios de interrupção comunicados.

## G. Critérios de interrupção

Interromper o lançamento se qualquer item abaixo ocorrer:

- [ ] preflight `FAIL`;
- [ ] migration divergente/erro;
- [ ] backup/restore não comprovado;
- [ ] RLS/roles/permissões divergentes;
- [ ] PII/segredo em log;
- [ ] worker sem heartbeat ou com privilégio indevido;
- [ ] erro 5xx anormal;
- [ ] integração externa não homologada;
- [ ] governança LGPD não aprovada;
- [ ] Traefik/outras stacks afetados;
- [ ] rollback indisponível.

## H. Decisão final

- [ ] Responsável técnico aprovou o release candidate.
- [ ] Responsável legal aprovou governança/retensão.
- [ ] Operação aprovou backup/restore/monitoramento.
- [ ] Data e responsável pela decisão registrados.
- [ ] Lançamento autorizado formalmente.
