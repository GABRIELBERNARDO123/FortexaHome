# Matriz de validação externa

> Nenhum resultado abaixo deve ser interpretado como integração real já validada. “Mock/local” não substitui homologação externa.

## Legenda

- **Local:** testado no repositório/PostgreSQL descartável.
- **Mock:** provider simulado.
- **Descartável:** Compose/E2E isolado.
- **Externo pendente:** requer ambiente/credencial real de homologação.
- **Bloqueador:** impede primeira venda até conclusão.

## Resend

| Item | Estado atual | Evidência | Pendência | Bloqueador? |
| --- | --- | --- | --- | --- |
| Domínio verificado | Externo pendente | Não há domínio real no repositório | Verificar SPF/DKIM/DMARC no Resend | Sim |
| Chave de produção | Externo pendente | Apenas placeholders/teste | Configurar no gerenciador de segredos | Sim |
| Envio de validação | Mock/local | `email_service` testado com provider dev/mock | Enviar e-mail controlado em homologação | Sim |
| Ativação | Local/descartável | Testes de ativação/outbox | Validar entrega real | Sim |
| Recuperação de senha | Local/descartável | Testes de reset/outbox | Validar entrega real | Sim |
| Recuperação de licença | Local/descartável | Testes de suporte/recovery | Validar entrega real | Sim |
| Outbox/retry/cancelamento | Local/descartável | Testes de worker/outbox/privacidade | Validar com provedor real e idempotência | Sim |
| Falha/retry do provedor | Mock | Testes de erro transitório/permanente | Validar códigos reais do Resend | Sim |

## Hotmart

| Item | Estado atual | Evidência | Pendência | Bloqueador? |
| --- | --- | --- | --- | --- |
| OAuth | Mock | `test_hotmart_api_client.py` com MockTransport | Token real em homologação | Sim |
| Produto cadastrado | Local/CLI | `provision_product` | Criar produto real sandbox/produção | Sim |
| UCODE | Local/config | Preflight/config | Configurar UCODE correto | Sim |
| Webhook | Mock/local | `test_hotmart_integration.py` | Webhook oficial Hotmart 2.0.0 | Sim |
| HOTTOK | Local/config | Autenticação mock/teste | Configurar HOTTOK real | Sim |
| Aprovação | Mock/local | Fluxo `PURCHASE_APPROVED` | Compra/homologação real | Sim |
| Reenvio | Mock/local | Testes de idempotência/eventos | Reenvio real da Hotmart | Sim |
| Reembolso | Mock/local | `PURCHASE_REFUNDED`/cancelamento outbox | Reembolso real controlado | Sim |
| Chargeback | Mock/local | Transições terminais/proteção | Evento real/controlado | Sim |
| Reconciliação | Mock/local | CLI/dry-run e testes | `sales/history` real/sandbox | Sim |

## Infraestrutura

| Item | Estado atual | Evidência | Pendência | Bloqueador? |
| --- | --- | --- | --- | --- |
| DNS | Externo pendente | Não configurado no repositório | Apontar domínio aprovado | Sim |
| TLS | Externo pendente | `APP_BASE_URL` HTTPS validado no código | Certificado/renovação reais | Sim |
| Cookies Secure | Local/config | Settings/testes | Validar em staging HTTPS | Sim |
| CORS | Local/config | Settings/testes | Validar domínio real | Sim |
| Proxy confiável | Local/config | `TRUSTED_PROXY_IPS`/Nginx | Confirmar topologia Traefik | Sim |
| Banco | Local/descartável | PostgreSQL real em testes | Homologação com backup/HA | Sim |
| Worker | Local/descartável | Startup/check/heartbeat/processamento executados | Validar na VPS com serviço real | Sim |
| Backup | Local/descartável | Drill com dump/restore 2,12 s | Backup real da VPS + storage protegido | Sim |
| Restauração | Simulada | Restore descartável + tombstones | Restore drill real com backup de produção | Sim |
| Logs | Local | Redaction/testes | Centralização/alerta/retention no host | Sim |
| Alertas | Externo pendente | Não implementado no repo | Definir stack/on-call | Sim |
| Carga | Não executado | — | Teste de carga/múltiplas réplicas | Avaliar |
| Múltiplas réplicas | Não executado | Arquitetura usa PostgreSQL compartilhado | Validar se exigido pelo tráfego | Avaliar |

## Critérios para liberar a primeira venda

1. Todos os itens “Sim” acima com evidência de homologação.
2. Backup/restore real aprovado.
3. Governança LGPD aprovada.
4. Release candidate implantado em staging prod-like com smoke tests verdes.
5. Decisão formal registrada.
