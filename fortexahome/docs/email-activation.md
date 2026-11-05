# Ativação com confirmação de e-mail

## Fluxo

`POST /api/v1/auth/activate` valida a licença e grava uma ativação pendente. A senha é guardada apenas como Argon2id; e-mail e nome ficam cifrados; o endereço também tem um HMAC de busca. A resposta contém um identificador UUID opaco, endereço mascarado e os prazos do desafio, nunca o código.

`POST /api/v1/auth/activate/resend` solicita outro código para o mesmo identificador. O backend aplica intervalo de 60 segundos, gera um código novo e invalida o anterior. `POST /api/v1/auth/activate/confirm` consome o código e, em uma transação PostgreSQL, revalida a licença e o endereço, cria tenant, usuário, categorias, sessão e auditoria, vincula a licença e marca `email_verified_at`. A sessão só é enviada no cookie após o commit.

As pendências usam RLS FORCE sem `tenant_id`: antes da ativação não existe tenant. A linha é alcançada pelo hash/licença visível na solicitação inicial e pelo UUID opaco nas etapas posteriores. O papel operacional não possui `DELETE` para esta tabela. O bloqueio da licença e a unicidade parcial de uma pendência aberta serializam ativações concorrentes.

## Configuração

Defina `EMAIL_VERIFICATION_HMAC_KEY` como uma chave aleatória própria, com pelo menos 32 caracteres. Não reutilize chaves de sessão, busca de PII ou licença. Em produção, o sistema exige essa chave, `EMAIL_PROVIDER=resend`, `RESEND_API_KEY` e `EMAIL_FROM` com domínio público adequado. Os valores de produção devem ser colocados no gerenciador de segredos do ambiente; este repositório contém apenas um marcador no `.env.example`.

Em desenvolvimento, `EMAIL_PROVIDER=dev` usa o sink local sem envio externo e sem registrar conteúdo no log. Os testes substituem o adaptador por um sink controlado. Para validar entrega real, configure um provedor de desenvolvimento apropriado; `dev` não entrega mensagens. Esse provedor é rejeitado em produção.

## Envio e recuperação

O pedido de envio e a ativação pendente são gravados juntos na outbox transacional descrita em [email-outbox.md](email-outbox.md). A API retorna `202` depois do commit; isso confirma que o pedido ficou persistido, não que o provedor aceitou ou entregou o e-mail. O worker tenta o envio e recupera mensagens após falha ou reinício. A confirmação segue exigindo o código válido e nenhuma sessão é criada antes dela.

## Migration e validação

A migration `20261031_05` cria a tabela protegida e preenche `email_verified_at` para usuários legados que ainda não tinham o valor, usando `created_at` para preservar o login deles. Ela precisa ser executada pelo papel dedicado de migrations, separado do papel operacional e com autoridade suficiente para fazer esse backfill sob FORCE RLS. A API nunca deve usar o papel de migrations.

Execute os testes integrados apenas com o banco descartável do Compose:

```sh
docker compose --profile tests run --build --rm tests
docker compose --profile tests run --rm tests alembic heads
npm --prefix frontend test
npm --prefix frontend run typecheck
npm --prefix frontend run build
```

Não execute downgrade em produção. O downgrade de `20261031_05` remove a tabela de pendências e seus desafios. Voltar até `20261031_03` também remove a proteção comercial adicionada por `20261031_04` para consultas e atualizações de licenças vinculadas a pedido/provedor. Os testes registram essas perdas e reexecutam upgrade somente em `fortexahome_test` descartável.

## Recuperação de licença sem revelar o código

O código original da licença é armazenado apenas como HMAC e `last4`; não é possível recuperá-lo. Para o comprador que perdeu o e-mail, existe o fluxo de recuperação:

1. `POST /auth/recover-license` recebe nome, e-mail da compra e senha.
2. Se o e-mail já pertence a uma conta, o backend dispara `password_reset` com cooldown por e-mail.
3. Se há compra paga com licença não vinculada, o backend localiza a licença pelo hash do e-mail de compra e cria/reutiliza uma `PendingActivation`, sem expor `activation_id` na resposta.
4. O e-mail `activation_verification` é enfileirado na outbox existente.
5. `POST /auth/recover-license/confirm` recebe e-mail + código de 6 dígitos e reutiliza `confirm_activation`, criando tenant/usuário e vinculando a licença uma única vez.

A resposta é sempre genérica para evitar enumeração. Pedidos terminais ou suspensos, licença já vinculada a outra conta e códigos inválidos não criam uma segunda ativação/tenant. O limite por IP e o cooldown por hash normalizado/e-mail se aplicam. O suporte pode solicitar instruções de recuperação pelo backoffice; consulte [support-backoffice.md](support-backoffice.md).
