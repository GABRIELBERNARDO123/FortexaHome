# Logging seguro e proteção de dados

## Objetivo

Impedir que logs, exceções, tracebacks e respostas HTTP exponham PII, dados financeiros, credenciais ou segredos, preservando correlação e diagnóstico operacional.

## Política

Logs operacionais podem conter:

- timestamp, nível, módulo/logger;
- `request_id`;
- método HTTP, caminho sem query string, status e duração;
- tipo de exceção, código PostgreSQL (`pgcode`) e frames de código (arquivo/linha/função);
- contadores, estados resumidos e códigos internos não sensíveis;
- identificadores internos não sensíveis.

Não devem conter:

- senhas, hashes de senha, cookies, session IDs;
- access/refresh tokens, códigos de ativação, tokens de reset, OAuth tokens;
- HOTTOK, HMAC, API keys, client secrets, segredos de configuração;
- e-mails completos, telefones, CPF/documentos, endereços, nomes completos de compradores;
- payloads completos de pagamento, conteúdo descriptografado da outbox, códigos completos de licença;
- SQL com parâmetros sensíveis, URLs de conexão, headers `Authorization`/`Cookie`/`Set-Cookie`.

## Implementação central

`backend/app/core/log_safety.py` fornece:

- `RedactingFilter` instalado nos handlers de aplicação/Uvicorn;
- redaction recursiva de dicionários, listas, tuplas e bytes;
- redaction por nome de campo (case/underscore/hyphen-insensitive);
- redaction textual de e-mails, tokens Bearer/Basic, query strings sensíveis, CPF, licença `FH-...`, JWT, hashes longos, credenciais em URL e headers;
- sanitização de `exc_info`: o traceback é substituído por tipo da exceção + `pgcode` + frames `arquivo:linha em função`, sem mensagem original nem linhas de código-fonte;
- `request_id` via `contextvars`, sem estado global compartilhado entre threads/tarefas.

`configure_logging(service)` é usado pela API e pelo worker. Além disso, o bootstrap é instalado no import de configuração para cobrir falhas de startup antes do logger principal existir.

## Request ID

- Aceita `X-Request-ID` do cliente somente se tiver 1–64 caracteres e casar com `[A-Za-z0-9._:-]`.
- Caso inválido/ausente, gera UUID.
- O ID é colocado em `request.state` e em `ContextVar`.
- É devolvido em `X-Request-ID` em respostas normais e também no handler global de erro.
- Erros de validação e 500 incluem `request_id` no JSON.
- O ID não contém PII e não permite injeção de linha de log.

## Exceções e respostas

- O handler global registra apenas tipo, método, caminho e frames seguros; o cliente recebe mensagem genérica + `request_id`.
- `HTTPException` e validações de domínio mantêm seus contratos e mensagens seguras.
- `RequestValidationError` não inclui o campo `input` na resposta.
- Nenhum stack trace é enviado ao cliente.
- `DEBUG=false` e `LOG_LEVEL != DEBUG` são exigidos em produção.

## SQLAlchemy/PostgreSQL

- `create_engine` não usa `echo=true`.
- Loggers `sqlalchemy.engine`, `sqlalchemy.pool`, `httpx` e `httpcore` são fixados em WARNING.
- Exceções `IntegrityError`/`SQLAlchemyError` têm apenas tipo e `pgcode` registrados; SQL e parâmetros não são emitidos.
- A migration/testes de banco continuam usando logs próprios de CLI, sem dados sensíveis.

## Logs HTTP e provedores

- O Uvicorn é iniciado com `--no-access-log`; o middleware da aplicação registra método, caminho sem query, status duração e request ID.
- Hotmart: logs de falha registram tipo/categoria, nunca HOTTOK, payload, comprador ou resposta completa.
- Resend/worker: logs de contadores/estado; nenhum destinatário, corpo, token ou API key.
- Outbox: payload descriptografado não é registrado; apenas estados, contadores e categorias sanitizadas.

## Redaction em profundidade

São redigidos campos cujos nomes contenham variações de:

`password`, `passwd`, `senha`, `secret`, `segredo`, `token`, `authorization`, `cookie`, `email`, `e-mail`, `cpf`, `cnpj`, `document`, `documento`, `license_code`, `hmac`, `hottok`, `api_key`, `client_secret`, `card_number`, `cvv`, `pan`, `phone`, `telefone`, `address`, `endereco`, `buyer_name`, `customer_name`, `username`, `full_name`, `code`, `codigo`.

A redaction textual também cobre valores que aparecem em mensagens/URLs, mas a regra principal continua sendo **não logar payloads, headers ou respostas externas brutas**.

## Configuração e preflight

- `PAYMENT_SANDBOX_ENABLED=false` por padrão; em produção o `Settings` rejeita `true`.
- A rota legada só é registrada quando explicitamente habilitada fora de produção.
- `LOG_LEVEL=DEBUG` é rejeitado em produção.
- `DEBUG=true` continua rejeitado em produção.
- O preflight não imprime valores de segredos.

## Testes

- `tests/unit/test_log_safety.py`: redaction textual/recursiva, exceções, headers, request ID, isolamento entre threads.
- `tests/unit/test_sandbox_route_registration.py`: conjunto de rotas em produção e 404 para `hmac_sandbox`.
- `tests/integration/test_logging_redaction.py`: exceção real via TestClient, `IntegrityError`, logs capturados, resposta genérica, request ID e validação.
- `tests/unit/test_preflight.py`: rejeição de sandbox/log DEBUG em produção.
- Testes HTTP existentes continuam cobrindo autenticação, CSRF e webhooks.

## Limitações

- A redaction textual é uma barreira adicional, não uma garantia absoluta para formatos desconhecidos; logs não devem receber payloads brutos.
- A política de retenção de logs/backups ainda precisa ser definida operacionalmente.
- Logs de infraestrutura fora da aplicação (Docker daemon, proxy, PostgreSQL) devem ser configurados e revisados no host.
- Nenhum teste usa Hotmart/Resend reais; validação externa permanece pendente.

## Privacidade e exclusão de dados

- Solicitações LGPD registram apenas protocolo, tipo, status, escopo, datas, contadores e códigos operacionais.
- Senha de reautenticação, e-mail, nome, tokens, payloads e justificativas completas não são enviados a logs.
- Eventos de privacy request (`privacy_request_events`) e auditoria de suporte não contêm PII em claro; o protocolo é o identificador de correlação.
- Erros de exclusão e conflitos de owner compartilhado são retornados com mensagem segura e `request_id`.
- A exclusão não reescreve logs históricos; a retenção de logs/backups externos é uma decisão operacional/jurídica pendente, distinta dos registros de incidentes da Resolução CD/ANPD nº 15/2024.
