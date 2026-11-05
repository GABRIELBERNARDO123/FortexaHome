# Runbook de backup e restauração

> Procedimento preparado e testado apenas em ambiente descartável. Nenhum backup real da VPS foi acessado, alterado ou apagado.

## 1. Escopo

- Backup lógico PostgreSQL (`pg_dump -Fc`).
- Restauração em banco descartável.
- Reaplicação de tombstones de exclusão pós-backup.
- Verificação de migrations, RLS e permissões.

## 2. Drill executado (04/11/2026)

| Item | Resultado |
| --- | --- |
| Origem | banco descartável `fortexahome_test` |
| Formato | `pg_dump -Fc` |
| Tamanho | ~4,6 MB |
| SHA256 do dump | `cc73d6d50d813755ca88a1c7bb65377eb35334a3a9db4fd54575429929ebfacb` |
| Checksum no container e no host | conferiu |
| Banco de restauração | `fortexahome_restore_drill` (descartável) |
| Tempo de restore | **2,12 s** |
| Tabelas restauradas | 30 |
| Alembic restaurado | `20261104_18` |
| Migrations pendentes no restore | nenhuma |
| RLS/FORCE RLS | confirmado em `users`, `transactions`, `privacy_requests`, `data_deletion_tombstones`, `idempotency_records` |
| Roles | existentes no cluster; grants necessários reaplicados ao papel operacional |
| Consulta autenticada | `test_runtime` com `app.tenant_id` consultou 1 usuário permitido |
| Tombstone pós-cópia | reaplicado com `privacy_service.reapply_tombstone` |
| Usuário após reapply | `status=disabled`, hash de e-mail alterado |
| Banco descartável | removido após o drill |

**Limitações:** o dump usado é do banco de testes, contendo dados de testes anteriores; não é um backup de produção. O drill não testou PITR/WAL, criptografia de backup, storage externo ou restore de backup real da VPS.

## 3. Procedimento de backup

1. Confirmar janela e responsável.
2. Verificar espaço livre.
3. Executar `pg_dump -Fc` com usuário de backup/migração autorizado.
4. Calcular SHA256.
5. Guardar dump e checksum em locais separados e protegidos.
6. Registrar data, banco, versão Alembic, tamanho e checksum.
7. Validar restauração em ambiente isolado periodicamente.

Exemplo:

```sh
pg_dump -Fc -U <usuario> -d <banco> -f /backups/fortexahome_<timestamp>.dump
sha256sum /backups/fortexahome_<timestamp>.dump > /backups/fortexahome_<timestamp>.sha256
```

## 4. Procedimento de restauração descartável

```sh
createdb -U <migracao> fortexahome_restore_drill
pg_restore -U <migracao> -d fortexahome_restore_drill --no-owner --no-privileges <dump>
# reaplicar grants necessários ao papel operacional
psql -U <migracao> -d fortexahome_restore_drill -c "GRANT USAGE ON SCHEMA public TO <app>; GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO <app>; GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO <app>;"
```

Em banco gerenciado, usar ferramenta equivalente e validar roles/ACL.

## 5. Verificações obrigatórias

- checksum do dump;
- versão Alembic;
- tabelas/índices;
- RLS/FORCE RLS nas tabelas sensíveis;
- roles sem SUPERUSER/BYPASSRLS;
- grants da API e restrição do worker;
- consulta autenticada com `app.tenant_id`;
- ausência de PII em logs do drill;
- reaplicação de tombstones exportados antes do restore.

## 6. Reaplicação de tombstones

1. Antes do restore, exportar `data_deletion_tombstones` da base atual para local protegido.
2. Após restaurar o backup, reaplicar cada tombstone pelo serviço de privacidade.
3. Verificar usuários/tenants afetados.
4. Só liberar o ambiente após a verificação.

Tombstones contêm apenas IDs internos e escopo, não PII em claro.

## 7. RPO/RTO

**Não aprovados como compromisso operacional.** Proposta para validação:

- RPO desejado: **a definir** (depende de frequência/PITR oferecidos).
- RTO desejado: **a definir** (depende de storage, tamanho e equipe).
- Frequência recomendada: backup lógico diário + retenção/PITR conforme capacidade; validar com responsável.
- Retenção: **pendente de decisão jurídica/operacional**.
- Restore: trimestral ou antes de migrations críticas.

Não comunicar RPO/RTO a clientes antes de aprovação formal.

## 8. Incidentes e falhas

- Falha de checksum: não usar o dump; repetir backup.
- Falha de restore: registrar erro, não liberar ambiente.
- Migration divergente: não aplicar em produção; investigar.
- RLS/ACL ausente: corrigir grants/policies e repetir validação.
- Tombstone não reaplicado: bloquear liberação do ambiente.

## 9. Critérios de interrupção

Interromper release/restore se checksum, RLS, roles, migrations ou tombstone não forem confirmados.
