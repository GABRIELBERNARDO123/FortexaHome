# Runbook de release e implantação

> **Não executar na VPS nesta missão.** Este documento prepara a futura implantação controlada. Nenhum comando abaixo foi executado em produção.

## 1. Release candidate

| Item | Valor |
| --- | --- |
| Branch | `release/fortexahome-launch` |
| Commit base | `8cbd7f7` |
| Migration final | `20261104_18_privacy_data_lifecycle.py` |
| Alembic head | `20261104_18` |
| Pacote | `fortexahome-1.0.0-rc.1-20261104.tar.gz` |
| Domínio | definido no gerenciador de ambiente/Traefik; não fixado no repositório |

O Compose do repositório é de desenvolvimento/E2E e **não deve ser copiado sem revisão** para produção. O Compose de release deve ser comparado com o atual e adaptado aos caminhos, redes e labels Traefik da VPS.

## 2. Arquitetura de destino (verificar antes de usar)

- diretório da aplicação: `/docker/fortexahome` (confirmar existência);
- releases: `/docker/releases/fortexahome` (confirmar);
- PostgreSQL existente (não criar outro cluster sem decisão operacional);
- rede Docker `fortexahome_net`;
- Traefik existente (não derrubar nem recriar);
- API, frontend e worker da outbox;
- volume de dados PostgreSQL preservado.

Não assumir que o Compose da release anterior está atualizado. Comparar serviços, variáveis, labels, portas e healthchecks.

## 3. Preparação da VPS

1. Confirmar acesso administrativo e janela de manutenção.
2. Registrar versão atual, containers e imagens em execução.
3. Verificar espaço livre para imagens, release e backup.
4. Verificar se Traefik e demais stacks estão saudáveis.
5. Não remover volumes, redes compartilhadas ou containers alheios.
6. Conferir relógio/NTP e DNS.

## 4. Backup obrigatório

Antes de qualquer migration:

```sh
pg_dump -Fc -U <usuario_migracao> -d <banco> -f /caminho/backup_pre_release.dump
sha256sum /caminho/backup_pre_release.dump
```

- Guardar checksum separado.
- Validar restauração em ambiente isolado antes do deploy.
- Não sobrescrever backups anteriores.
- Seguir [backup-restore-runbook.md](backup-restore-runbook.md).

## 5. Preparação do release

```sh
# Exemplo de destino; confirmar caminhos reais antes de executar.
mkdir -p /docker/releases/fortexahome
cd /docker/releases/fortexahome
# Copiar o pacote por canal administrativo seguro.
sha256sum -c fortexahome-1.0.0-rc.1-20261104.tar.gz.sha256
tar -xzf fortexahome-1.0.0-rc.1-20261104.tar.gz
```

Verificar:

- `.env` **não** está no pacote;
- migrations presentes;
- documentação operacional presente;
- manifesto/checksum conferem;
- permissões de arquivos e diretórios.

## 6. Configuração

Configurar no gerenciador de segredos do host, nunca no pacote:

- `ENV=production`;
- `DEBUG=false`;
- `SESSION_COOKIE_SECURE=true`;
- `APP_BASE_URL` HTTPS;
- `CORS_ORIGINS` HTTPS;
- `TRUSTED_PROXY_IPS` compatível com Traefik;
- `SECRET_KEY`, `PII_ENCRYPTION_KEY`, `PII_LOOKUP_KEY`, `LICENSE_HMAC_KEY`, `EMAIL_VERIFICATION_HMAC_KEY`, `RATE_LIMIT_HMAC_KEY`, `OUTBOX_DB_PASSWORD`;
- `EMAIL_PROVIDER=resend` e `RESEND_API_KEY` somente quando homologado;
- `HOTMART_ENABLED=false` até a validação comercial;
- `HOTMART_*` e `HOTMART_RECONCILIATION_*` somente após aprovação;
- `IDEMPOTENCY_RETENTION_HOURS=168` (ou valor aprovado).

Não colocar segredos em tickets, logs, manifesto ou pacote.

## 7. Preflight e migrations

```sh
cd /docker/fortexahome
docker compose run --rm api python -m app.cli.preflight --stage environment
docker compose run --rm api alembic upgrade head
docker compose run --rm api python -m app.cli.preflight --stage database
docker compose run --rm api python -m app.cli.preflight --stage commercial
```

Critérios:

- environment sem `FAIL`;
- banco no head `20261104_18`;
- banco e catálogo aprovados;
- `commercial` pode retornar `SKIP` enquanto Hotmart estiver desabilitada;
- qualquer `FAIL` interrompe o release.

## 8. Build e implantação controlada

1. Construir imagens a partir do release candidate.
2. Registrar IDs/digests das imagens.
3. Subir API e worker primeiro, depois web, sem remover volumes.
4. Não recriar Traefik nem outras stacks.
5. Acompanhar logs de startup e preflight.
6. Validar healthchecks:
   - API: `/api/v1/health`;
   - worker: `python -m app.workers.email_outbox --check`;
   - web: HTTP local/health.

## 9. Smoke tests

- página pública e login;
- cookies Secure/HttpOnly e CORS;
- ativação/recuperação em ambiente controlado;
- health da API;
- leitura autenticada de dados;
- backoffice sem acesso de cliente;
- worker iniciado, heartbeat e sem erro de identidade;
- outbox sem backlog anormal;
- logs sem PII/segredo;
- `X-Request-ID` presente;
- idempotência de uma operação de teste;
- privacidade: painel visível; não executar exclusão de cliente real no smoke.

## 10. Monitoramento

Acompanhar por pelo menos 48 h antes de vendas:

- erros 5xx e exceções;
- latência e disponibilidade;
- outbox/backlog/dead letters;
- lockout/rate limit;
- ativação, entrega e suporte;
- reconciliação Hotmart (quando habilitada);
- espaço em disco e backups.

## 11. Rollback

### Aplicação

- Voltar para a imagem/release anterior identificada.
- Manter o banco e volumes.
- Não remover migrations aplicadas sem plano.
- Reverter tráfego no Traefik para a versão anterior.

### Banco

- Migrations são forward-only.
- Se houver incompatibilidade, restaurar o backup pré-release em ambiente isolado, validar e seguir o procedimento aprovado.
- Não executar downgrade em produção sem backup verificado e decisão formal.

## 12. Critérios de interrupção

Interromper o release se:

- preflight `FAIL`;
- migration divergente do head;
- restore drill não aprovado;
- healthcheck falhar;
- logs contiverem PII/segredo;
- worker não iniciar ou não tiver heartbeat;
- erro 5xx anormal;
- backup não estiver validado;
- Traefik/outras stacks forem afetados;
- qualquer bloqueador da [checklist](prelaunch-checklist.md) estiver aberto.

## 13. Pós-release

- Registrar horário, imagens, migration, operador e resultado.
- Preservar logs/evidências.
- Confirmar que backups continuam.
- Só habilitar `HOTMART_ENABLED=true` após validação externa e decisão formal.
