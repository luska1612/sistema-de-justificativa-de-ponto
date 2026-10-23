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

## Permissões

Os perfis existentes são:

- `analista`: cria e acompanha suas solicitações;
- `gestor`: analisa solicitações de subordinados;
- `dp`: analisa solicitações aprovadas pelo gestor e mantém cadastros operacionais;
- `ti`: administra usuários, áreas, empresas e vínculos;
- `supervisor_administrativo`: analisa solicitações encaminhadas pelo DP.

A função `perfil_requerido()` restringe rotas por perfil. A função `ti_requerido()` restringe operações exclusivas da TI. Em acessos sem permissão, esses decorators retornam para `request.referrer` quando disponível, mantendo o usuário na página anterior; sem referer, usam o dashboard como fallback.

### Permissões individuais

`UsuarioPermissao` guarda as permissões individuais de cada usuário. A função `tem_permissao()` do modelo verifica a concede; o perfil `ti` sempre tem acesso total.

Rotas:

- `GET|POST /admin/usuarios/<id>/permissoes`: **tela única** de permissões do usuário;
- `GET|POST /admin/permissoes-avancadas/<id>`: redireciona para a tela única (mantido para preservar links antigos).

A tela única tem **um só formulário** com duas seções:

- **Acessos gerais** — as permissões de `PERMISSOES_DISPONIVEIS`, agrupadas por categoria;
- **Ações avançadas** — as permissões de `PERMISSOES_AVANCADAS` compatíveis com o perfil do usuário.

Ao salvar, a rota apaga todas as permissões do usuário e recria exatamente o conjunto marcado nas duas listas. Permissões avançadas incompatíveis com o perfil e chaves desconhecidas são descartadas.

### Permissões avançadas (aditivas)

Definidas em `PERMISSOES_AVANCADAS` (`app.py`). Cada entrada é um tupla:
`(rótulo, categoria, perfis que se beneficiam, descrição)`.

Semântica **aditiva**: o perfil já concede o poder padrão; conceder uma permissão avançada apenas **soma** capacidade — nunca remove. Por isso o caso "gestor que só recusa" não é representável nessa lista: exigiria uma permissão que subtraia o poder de aprovar.

Permissões disponíveis:

| Chave | Perfis | Efeito |
| --- | --- | --- |
| `gestor_encaminhar_supervisor` | gestor | Gestor encaminha a solicitação ao supervisor administrativo |
| `gestor_encaminhar_area` | gestor | Gestor repassa a outro gestor de nível superior |
| `gestor_recusar_sem_parecer` | gestor | Recusa do gestor sem justificativa obrigatória |
| `gestor_aprovar_sem_comprovante` | gestor | Aprovar sem anexo obrigatório |
| `dp_encaminhar_supervisor` | dp | DP encaminha ao supervisor antes de concluir |
| `dp_recusar_sem_parecer` | dp | Recusa do DP sem justificativa obrigatória |
| `supervisor_encaminhar_dp` | supervisor | Supervisor devolve a solicitação ao DP |

Ao salvar, a rota **descarta** permissões avançadas cujo perfil não se aplica ao usuário, e ignora chaves desconhecidas.

Decorators e helpers:

- `permissao_avancada(chave)`: verificação booleana; `ti` sempre verdadeiro;
- `permissao_avancada_requerida(chave)`: decorator para rotas; combina-se com `perfil_requerido`, que continua sendo condição necessária;
- `permissoes_avancadas_do_usuario(usuario)`: conjunto de permissões avançadas do usuário.

Rotas protegidas:

- `POST /gestor/encaminhar/<id>`: gestor encaminha ao supervisor;
- `POST /dp/encaminhar/<id>`: DP encaminha ao supervisor;
- `POST /supervisor/devolver/<id>`: supervisor devolve ao DP.

Status reutilizados: `encaminhado_supervisor`, `aprovado_supervisor`, `recusado_supervisor`. Não há status novo para o encaminhamento feito pelo gestor.

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
- rotas `/admin/usuarios`, `/admin/areas`, `/admin/empresas`: gerenciam cadastros e vínculos;
- `GET|POST /admin/permissoes/<id>`: tela unificada de permissões do usuário.

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

## Verificação automatizada

```powershell
.\venv\Scripts\python.exe verificar_permissoes.py
```

Script de verificação das permissões avançadas. Roda contra um SQLite temporário
(`%TEMP%\ponto-verificacao-perm.db`) e **não toca no banco real do projeto**.

Cuidado ao escrever novos testes com `app.test_client()`: **cada requisição
precisa do seu próprio app context**. Manter um `app_context()` externo aberto
faz o Flask-Login reutilizar o usuário já resolvido em `g._login_user`, e a
requisição seguinte acaba "vendo" o usuário da requisição anterior. É um
artefato do harness de teste — em produção cada requisição tem o próprio
contexto. No script, as escritas no banco são feitas em blocos
`with app.app_context():` separados, e a leitura do estado usa uma conexão
SQLite nova (`sql()`) para não depender do cache de sessão do SQLAlchemy.
