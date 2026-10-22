# Contexto do Projeto — Sistema de Justificativas de Ponto

## Objetivo

Aplicação web interna para registrar, revisar e concluir justificativas de ocorrências de ponto.

Fluxo principal:

1. Usuário autenticado cria uma solicitação.
2. Gestor do usuário analisa a solicitação.
3. Gestor aprova ou recusa.
4. DP analisa solicitações aprovadas pelo gestor.
5. DP conclui ou recusa.
6. TI administra usuários, áreas, empresas e vínculos.

## Stack

- Python
- Flask 3.1.1
- Flask-SQLAlchemy 3.1.1
- Flask-Login 0.6.3
- Flask-WTF 1.2.2
- Werkzeug 3.1.3
- SQLite por padrão
- Bootstrap local
- Jinja2

Dependências: `requirements.txt`

## Execução local

Windows:

```bat
setup_local.bat
```

O script:

- entra na pasta do projeto;
- cria `venv` se necessário;
- instala `requirements.txt` usando o Python do ambiente virtual;
- gera `SECRET_KEY` temporária para a execução local, caso não exista;
- inicializa o banco com `init_db.py`;
- prepara arquivos estáticos com `baixar_deps.py`;
- inicia `app.py`.

Execução manual:

```powershell
$env:SECRET_KEY="uma-chave-longa-e-aleatoria"
$env:FLASK_DEBUG="false"
$env:SESSION_COOKIE_SECURE="false"
.\venv\Scripts\python.exe app.py
```

Para produção, definir `SECRET_KEY` persistente e usar HTTPS com:

```powershell
$env:SESSION_COOKIE_SECURE="true"
```

## Estrutura principal

```text
app.py                    Rotas, autenticação, regras e configuração Flask
models.py                 Modelos SQLAlchemy
init_db.py                Inicialização/seeding do banco
baixar_deps.py            Preparação de dependências estáticas
setup_local.bat           Inicialização local no Windows
requirements.txt          Dependências Python
instance/ponto.db         Banco SQLite local
templates/                Páginas Jinja
templates/base.html      Layout, navegação, logout e mensagens
templates/login.html     Login
templates/admin.html     Administração TI
templates/analista.html  Painel de solicitações
 templates/gestor.html   Painel do gestor
templates/dp.html        Painel do DP
templates/solicitacao_form.html Formulário de criação/edição
static/css/               Bootstrap e estilos
static/js/app.js          Máscaras, toasts e interações
auth uploads/             Arquivos enviados em `static/uploads`
```

## Perfis

Os perfis existentes são:

- `analista`: cria e acompanha suas solicitações;
- `gestor`: analisa solicitações de subordinados;
- `dp`: analisa solicitações aprovadas pelo gestor e mantém cadastros operacionais;
- `ti`: administra usuários, áreas, empresas e vínculos.

A função `perfil_requerido()` restringe rotas por perfil. A função `ti_requerido()` restringe operações exclusivas da TI. Em acessos sem permissão, esses decorators retornam para `request.referrer` quando disponível, mantendo o usuário na página anterior; sem referer, usam o dashboard como fallback.

## Modelos de dados

### `Usuario`

Usuário autenticável. Campos importantes:

- `matricula`
- `nome`
- `email`
- `senha_hash`
- `perfil`
- `gestor_id`
- `area_id`
- `empresa_id`
- `ativo`

### `Solicitacao`

Solicitação criada pelo usuário. Campos importantes:

- `colaborador_id`: usuário que abriu a solicitação;
- `data_ocorrencia`;
- `tipo_ocorrencia`;
- `tipo_justificativa`;
- `horario_entrada`;
- `horario_saida`;
- `motivo`;
- `comprovante`;
- `status`;
- dados de análise do gestor;
- dados de análise do DP.

Status atuais:

- `pendente`
- `aprovado_gestor`
- `recusado_gestor`
- `aprovado_dp`
- `recusado_dp`

### `SolicitacaoParticipante`

Participante ou colaborador envolvido na ocorrência. Armazena nome e matrícula informados na solicitação.

### Cadastros auxiliares

- `Area`
- `Empresa`
- `Colaborador`
- `TipoJustificativa`
- `TipoOcorrencia`

## Segurança já implementada

- `SECRET_KEY` não fica mais hardcoded em `app.py`; vem de variável de ambiente.
- Debug fica desativado por padrão.
- Host padrão local: `127.0.0.1`.
- Cookies de sessão usam `HttpOnly` e `SameSite=Lax`.
- CSRF habilitado por `Flask-WTF`.
- Formulários POST possuem token CSRF.
- Logout usa POST, não GET.
- Falhas CSRF exibem mensagem segura.
- Uploads recebem nome sanitizado com UUID.
- Limite global de upload: 10 MB.
- A rota de comprovantes recebe o ID da solicitação, não um nome arbitrário.
- Comprovantes têm controle de acesso para solicitante, gestor autorizado, DP e TI.
- Resposta de arquivo inclui `X-Content-Type-Options: nosniff`.
- Debug não deve ser ativado em produção.

## Rotas importantes

### Autenticação

- `GET /`: redireciona para login ou dashboard;
- `GET|POST /login`: autentica usuário;
- `POST /logout`: encerra sessão;
- `GET /dashboard`: redireciona conforme perfil.

### Solicitações

- `GET|POST /solicitacoes/nova`: formulário de nova solicitação;
- `POST /analista/nova`: salva solicitação;
- `GET|POST /solicitacoes/<id>/editar`: edita solicitação própria pendente;
- `GET /uploads/<sol_id>`: acessa comprovante após autorização.

### Gestor

- `GET /gestor`: painel;
- `POST /gestor/aprovar/<id>`: aprova;
- `POST /gestor/recusar/<id>`: recusa.

### DP

- `GET /dp`: painel e filtros;
- `POST /dp/aprovar/<id>`: conclui;
- `POST /dp/recusar/<id>`: recusa;
- rotas `/cadastros/...`: gerenciam colaboradores, tipos e ocorrências.

### TI

- `GET /admin`: painel administrativo, sem os cards de status do sistema e armazenamento de comprovantes;
- rotas `/admin/usuarios`, `/admin/areas`, `/admin/empresas`: gerenciam cadastros e vínculos.

## Regras para futuras alterações

1. Não inserir segredos no código, templates ou Git.
2. Toda rota que altera dados deve usar POST e proteção CSRF.
3. Toda rota protegida deve usar `login_required` e validação de perfil.
4. Não confiar em IDs, nomes de arquivos ou permissões vindos do cliente.
5. Validar dados também no servidor; atributos HTML são apenas complemento.
6. Nunca liberar arquivos enviados diretamente sem verificar autorização.
7. Não usar `debug=True` em ambiente exposto.
8. Preservar mensagens de erro genéricas em login e autorização.
9. Preferir reutilizar helpers existentes em `app.py` antes de duplicar validações.
10. Alterações de modelo exigem migração ou procedimento explícito de atualização do banco.

## Pontos ainda recomendados

- Validar MIME e assinatura real dos arquivos enviados.
- Adicionar rate limiting no login.
- Adicionar testes automatizados com Flask test client.
- Adicionar migrations com Flask-Migrate.
- Substituir SQLite por PostgreSQL em produção.
- Centralizar validações duplicadas de criação/edição de solicitação.
- Adicionar limites server-side para textos.
- Adicionar logging e auditoria.
- Revisar autorização de escopo do DP e do gestor.
- Remover ou migrar o relacionamento legado entre `Solicitacao` e `Colaborador`.
- Corrigir/padronizar HTML dos templates antes de novas funcionalidades.

## Como uma IA deve trabalhar neste projeto

Antes de editar:

1. Ler `app.py`, `models.py` e os templates envolvidos.
2. Identificar o perfil e o fluxo afetados.
3. Verificar se a mudança altera autenticação, autorização, CSRF, uploads ou persistência.
4. Fazer a menor alteração compatível com o código existente.
5. Não adicionar dependências sem necessidade.

Depois de editar:

1. Verificar sintaxe Python.
2. Testar a rota alterada com ambiente configurado.
3. Confirmar que todos os formulários POST continuam contendo CSRF.
4. Confirmar que permissões continuam restritivas.
5. Informar claramente testes executados e limitações.
