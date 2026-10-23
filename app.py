"""
Sistema Web de Justificativas de Ponto — Backend Flask
"""

import os
import re
import json
import tempfile
import uuid
import unicodedata
from datetime import datetime, timezone, timedelta
from sqlalchemy import func
from io import BytesIO

from openpyxl import Workbook
from functools import wraps

from flask import (
    Flask, render_template, request, redirect, url_for,
    flash, jsonify, send_from_directory, session, abort, send_file
)
from flask_wtf.csrf import CSRFProtect, CSRFError
from flask_login import (
    LoginManager, login_user, logout_user,
    login_required, current_user
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload

from models import (db, Usuario, Permissao, UsuarioPermissao, Solicitacao, Colaborador, TipoJustificativa,
                    SolicitacaoParticipante, Area, Empresa, TipoOcorrencia)

# ──────────────────────────────────────────────
# Configuração
# ──────────────────────────────────────────────

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY')
if not app.config['SECRET_KEY']:
    raise RuntimeError('Defina SECRET_KEY no ambiente antes de iniciar o sistema.')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///ponto.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = os.environ.get(
    'UPLOAD_FOLDER',
    os.path.join(tempfile.gettempdir(), 'ponto-uploads')
)
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024  # 10 MB
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    SESSION_COOKIE_SECURE=os.environ.get('SESSION_COOKIE_SECURE', '').lower() == 'true',
)

csrf = CSRFProtect(app)

EXTENSOES_PERMITIDAS = {'pdf', 'png', 'jpg', 'jpeg', 'xls', 'xlsx'}
PERFIS = ('analista', 'gestor', 'dp', 'ti', 'supervisor_administrativo')
PERFIS_SOLICITANTES = ('analista', 'gestor', 'dp', 'ti')
STATUS_SUPERVISOR = ('encaminhado_supervisor', 'aprovado_supervisor', 'recusado_supervisor')

TIPOS_OCORRENCIA = (
    'Saída antecipada',
    'Sem registro de entrada',
    'Sem registro de saída',
    'Sem registro de entrada/sem registro de saída',
    'Horas extras',
    'Outros',
)

db.init_app(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Faça login para acessar o sistema.'
login_manager.login_message_category = 'warning'


@app.errorhandler(CSRFError)
def handle_csrf_error(error):
    flash('Sessão expirada ou formulário inválido. Tente novamente.', 'danger')
    return redirect(request.referrer or url_for('login'))


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(Usuario, int(user_id))


@app.template_filter('from_json')
def from_json(value):
    try:
        return json.loads(value or '[]')
    except (TypeError, json.JSONDecodeError):
        return [value] if value else []


@app.context_processor
def inject_now():
    """Disponibiliza now() e permissões do usuário nos templates."""
    return {'now': datetime.now}


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

def extensao_permitida(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in EXTENSOES_PERMITIDAS


def nome_valido(nome):
    nome = ' '.join(nome.split())
    return bool(nome) and len(nome) <= 100 and all(
        ch.isalpha() or ch.isspace() for ch in nome
    )


def matricula_valida(matricula):
    return matricula.isdigit() and 1 <= len(matricula) <= 20


def permissao_requerida(chave):
    def decorator(f):
        @wraps(f)
        @login_required
        def wrapper(*args, **kwargs):
            if not current_user.tem_permissao(chave):
                flash('Acesso não autorizado.', 'danger')
                return redirect(request.referrer or url_for('dashboard'))
            return f(*args, **kwargs)
        return wrapper
    return decorator


def permissao_avancada(chave):
    """Verifica uma permissão avançada (aditiva).

    O perfil TI já tem acesso total. Para os demais perfis, a permissão
    precisa ter sido concedida individualmente.
    """
    return current_user.perfil == 'ti' or current_user.tem_permissao(chave)


def permissoes_avancadas_do_usuario(usuario):
    """Conjunto de permissões avançadas que um usuário possui."""
    if usuario.perfil == 'ti':
        return set(PERMISSOES_AVANCADAS)
    return {item.permissao for item in
            UsuarioPermissao.query.filter_by(usuario_id=usuario.id).all()} & set(PERMISSOES_AVANCADAS)


def perfil_requerido(*perfis):
    """Decorator para restringir acesso por perfil."""
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if current_user.perfil not in perfis:
                flash('Acesso não autorizado.', 'danger')
                return redirect(request.referrer or url_for('dashboard'))
            return f(*args, **kwargs)
        return wrapper
    return decorator


def permissao_avancada_requerida(chave):
    """Decorator para exigir uma permissão avançada além do perfil.

    Combina-se com perfil_requerido: o perfil continua sendo condição
    necessária, e a permissão avançada concede o poder extra.
    """
    def decorator(f):
        @wraps(f)
        @login_required
        def wrapper(*args, **kwargs):
            if not permissao_avancada(chave):
                flash('Acesso não autorizado.', 'danger')
                return redirect(request.referrer or url_for('dashboard'))
            return f(*args, **kwargs)
        return wrapper
    return decorator


def carregar_cadastros():
    return (Colaborador.query.filter_by(ativo=True).order_by(Colaborador.nome).all(),
            TipoJustificativa.query.filter_by(ativo=True).order_by(TipoJustificativa.nome).all(),
            TipoOcorrencia.query.filter_by(ativo=True).order_by(TipoOcorrencia.nome).all())


@app.route('/admin/vinculos')
@login_required
@perfil_requerido('dp', 'ti')
def painel_vinculos():
    return redirect(url_for('painel_admin_usuarios'))


@app.route('/admin/usuarios/<int:usuario_id>')
@login_required
@perfil_requerido('ti')
def detalhes_usuario(usuario_id):
    usuario = db.session.get(Usuario, usuario_id)
    if not usuario:
        abort(404)
    permissoes = {item.permissao for item in UsuarioPermissao.query.filter_by(usuario_id=usuario.id).all()}
    return render_template('usuario_detalhes.html', usuario=usuario,
                           permissoes=permissoes,
                           permissoes_disponiveis=PERMISSOES_DISPONIVEIS)


@app.route('/admin/usuarios/<int:usuario_id>/permissoes', methods=['GET', 'POST'])
@login_required
@perfil_requerido('ti')
def permissoes_usuario(usuario_id):
    usuario = db.session.get(Usuario, usuario_id)
    if not usuario:
        abort(404)
    if request.method == 'POST':
        dados = dados_usuario_validos(request.form, senha_obrigatoria=False)
        if not dados:
            flash('Dados inválidos.', 'danger')
            return redirect(url_for('permissoes_usuario', usuario_id=usuario.id))
        nome, matricula, email, perfil, senha = dados
        duplicado = Usuario.query.filter(Usuario.id != usuario.id, (Usuario.matricula == matricula) | (Usuario.email == email)).first()
        empresa_id = request.form.get('empresa_id', type=int)
        area_id = request.form.get('area_id', type=int)
        gestor_id = request.form.get('gestor_id', type=int)
        empresa = db.session.get(Empresa, empresa_id) if empresa_id else None
        area = db.session.get(Area, area_id) if area_id else None
        gestor = db.session.get(Usuario, gestor_id) if gestor_id else None
        if duplicado or (empresa_id and not empresa) or (area_id and (not area or (empresa and empresa not in area.empresas))) or (gestor and (gestor.id == usuario.id or gestor.perfil not in ('gestor', 'supervisor_administrativo') or not gestor.ativo)):
            flash('Dados ou vínculos inválidos.', 'danger')
            return redirect(url_for('permissoes_usuario', usuario_id=usuario.id))
        if usuario.perfil == 'ti' and perfil != 'ti' and Usuario.query.filter_by(perfil='ti', ativo=True).count() < 2:
            flash('Não é possível remover o último administrador TI ativo.', 'danger')
            return redirect(url_for('permissoes_usuario', usuario_id=usuario.id))
        usuario.nome, usuario.matricula, usuario.email, usuario.perfil = nome, matricula, email, perfil
        usuario.empresa_id, usuario.area_id, usuario.gestor_id = empresa_id, area_id, gestor_id
        usuario.ativo = request.form.get('ativo') == 'on'
        if senha:
            usuario.senha_hash = generate_password_hash(senha)
        db.session.commit()
        flash('Usuário e permissões atualizados.', 'success')
        return redirect(url_for('painel_vinculos'))
    return render_template('usuario_permissoes.html', usuario=usuario,
                           areas=Area.query.order_by(Area.nome).all(),
                           empresas=Empresa.query.filter_by(ativo=True).order_by(Empresa.nome).all(),
                           gestores=Usuario.query.filter_by(perfil='gestor', ativo=True).order_by(Usuario.nome).all())


@app.route('/supervisor-administrativo')
@login_required
@perfil_requerido('supervisor_administrativo')
def painel_supervisor():
    pendentes = (Solicitacao.query
                 .filter(Solicitacao.status == 'encaminhado_supervisor')
                 .filter(Solicitacao.supervisor_id == current_user.id)
                 .order_by(Solicitacao.criado_em.desc()).all())
    historico = (Solicitacao.query
                 .filter(Solicitacao.supervisor_id == current_user.id)
                 .filter(Solicitacao.status != 'encaminhado_supervisor')
                 .order_by(Solicitacao.atualizado_em.desc()).limit(50).all())
    return render_template('supervisor_administrativo.html', pendentes=pendentes, historico=historico,
                           pode_devolver_dp=permissao_avancada('supervisor_encaminhar_dp'))


@app.route('/configuracoes')
@login_required
@perfil_requerido('dp', 'ti')
def configuracoes():
    return render_template('configuracoes.html', areas=Area.query.order_by(Area.nome).all(), empresas=Empresa.query.order_by(Empresa.nome).all(), colaboradores=Colaborador.query.order_by(Colaborador.nome).all(), tipos=TipoJustificativa.query.order_by(TipoJustificativa.nome).all(), tipos_ocorrencia=TipoOcorrencia.query.order_by(TipoOcorrencia.nome).all())


@app.route('/organograma')
@login_required
@perfil_requerido('dp', 'ti')
def organograma():
    empresas = Empresa.query.filter_by(ativo=True).order_by(Empresa.nome).all()
    empresa_id = request.args.get('empresa_id', type=int)
    empresa = next((item for item in empresas if item.id == empresa_id), None) if empresa_id else None
    empresa = empresa or (empresas[0] if empresas else None)

    usuarios = (Usuario.query.filter_by(ativo=True)
                .options(joinedload(Usuario.empresa), joinedload(Usuario.area), joinedload(Usuario.gestor))
                .order_by(Usuario.nome).all())
    usuarios_empresa = [u for u in usuarios if empresa and u.empresa_id == empresa.id]

    areas = {}
    sem_area = []
    sem_gestor = []
    sem_empresa = [u for u in usuarios if u.empresa_id is None]
    for usuario in usuarios_empresa:
        if usuario.area is None:
            sem_area.append(usuario)
            continue
        area = areas.setdefault(usuario.area.nome, {'gestores': {}, 'usuarios': []})
        area['usuarios'].append(usuario)
        if usuario.gestor_id is None:
            sem_gestor.append(usuario)
        elif usuario.gestor is not None:
            # O gestor pode pertencer a outra empresa; o vínculo por ID continua válido.
            area['gestores'].setdefault(usuario.gestor.id, usuario.gestor)

    estrutura = []
    for nome, dados in sorted(areas.items()):
        gestores = []
        for gestor in sorted(dados['gestores'].values(), key=lambda item: item.nome):
            subordinados = [u for u in dados['usuarios'] if u.gestor_id == gestor.id and u.id != gestor.id]
            gestores.append({'usuario': gestor, 'subordinados': subordinados})
        estrutura.append({'nome': nome, 'gestores': gestores, 'usuarios': dados['usuarios']})

    return render_template('organograma.html', empresas=empresas, empresa=empresa,
                           estrutura=estrutura, sem_area=sem_area,
                           sem_gestor=sem_gestor, sem_empresa=sem_empresa)


# ──────────────────────────────────────────────
# Rotas de Autenticação
# ──────────────────────────────────────────────

@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        matricula = request.form.get('matricula', '').strip()
        senha = request.form.get('senha', '').strip()

        usuario = Usuario.query.filter_by(matricula=matricula, ativo=True).first()

        if usuario and check_password_hash(usuario.senha_hash, senha):
            login_user(usuario)
            flash(f'Bem-vindo(a), {usuario.nome}!', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Matrícula ou senha inválidos.', 'danger')

    return render_template('login.html')


@app.route('/logout', methods=['POST'])
@login_required
def logout():
    logout_user()
    flash('Sessão encerrada com sucesso.', 'info')
    return redirect(url_for('login'))


# ──────────────────────────────────────────────
# Dashboard — redireciona por perfil
# ──────────────────────────────────────────────

def tamanho_uploads():
    total = 0
    for raiz, _, arquivos in os.walk(app.config['UPLOAD_FOLDER']):
        for nome in arquivos:
            try:
                total += os.path.getsize(os.path.join(raiz, nome))
            except OSError:
                pass
    return total


@app.route('/dashboard/solicitacoes')
@login_required
def dashboard_solicitacoes():
    agora = datetime.now(timezone.utc)
    inicio_padrao = agora.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    inicio = request.args.get('inicio', '').strip()
    fim = request.args.get('fim', '').strip()
    try:
        inicio = datetime.strptime(inicio, '%Y-%m-%d').replace(tzinfo=timezone.utc) if inicio else inicio_padrao
        fim_data = datetime.strptime(fim, '%Y-%m-%d').replace(tzinfo=timezone.utc) + timedelta(days=1) if fim else agora + timedelta(days=1)
    except ValueError:
        inicio, fim_data = inicio_padrao, agora + timedelta(days=1)
    consulta = Solicitacao.query.filter(Solicitacao.criado_em >= inicio, Solicitacao.criado_em < fim_data)
    if current_user.perfil == 'gestor':
        consulta = consulta.join(Usuario, Solicitacao.colaborador_id == Usuario.id).filter(Usuario.gestor_id == current_user.id)
    elif current_user.perfil == 'analista':
        consulta = consulta.filter(Solicitacao.colaborador_id == current_user.id)
    solicitacoes = consulta.order_by(Solicitacao.atualizado_em.desc()).all()
    base_mes = Solicitacao.query.filter(Solicitacao.criado_em >= inicio, Solicitacao.criado_em < fim_data)
    por_dia = [[str(dia), total] for dia, total in db.session.query(func.date(Solicitacao.criado_em), func.count(Solicitacao.id)).filter(Solicitacao.criado_em >= inicio, Solicitacao.criado_em < fim_data).group_by(func.date(Solicitacao.criado_em)).all()]
    por_tipo = [[tipo or 'Não informado', total] for tipo, total in base_mes.with_entities(Solicitacao.tipo_ocorrencia, func.count(Solicitacao.id)).group_by(Solicitacao.tipo_ocorrencia).all()]
    return render_template('dashboard_solicitacoes.html', solicitacoes=solicitacoes[:10], por_dia=por_dia, por_tipo=por_tipo, inicio=inicio.date().isoformat(), fim=(fim_data - timedelta(days=1)).date().isoformat(),
                           total=consulta.count(), pendentes=consulta.filter_by(status='pendente').count(),
                           aprovadas=consulta.filter(Solicitacao.status.in_(['aprovado_dp', 'aprovado_supervisor'])).count(),
                           recusadas=consulta.filter(Solicitacao.status.like('recusado%')).count())


@app.route('/dashboard')
@login_required
def dashboard():
    if current_user.perfil == 'ti':
        return redirect(url_for('painel_admin'))
    if current_user.perfil == 'supervisor_administrativo':
        return redirect(url_for('painel_supervisor'))
    if current_user.perfil == 'analista':
        return redirect(url_for('painel_analista'))
    elif current_user.perfil == 'gestor':
        return redirect(url_for('painel_gestor'))
    elif current_user.perfil == 'dp':
        return redirect(url_for('painel_dp'))
    return redirect(url_for('login'))


# ──────────────────────────────────────────────
# ADMINISTRAÇÃO DE USUÁRIOS (TI)
# ──────────────────────────────────────────────


def ti_requerido(f):
    @wraps(f)
    @login_required
    def wrapper(*args, **kwargs):
        if current_user.perfil != 'ti':
            flash('Acesso não autorizado.', 'danger')
            return redirect(request.referrer or url_for('dashboard'))
        return f(*args, **kwargs)
    return wrapper


@app.route('/admin/consultas-sql', methods=['GET', 'POST'])
@ti_requerido
def consultas_sql():
    sql = ''
    colunas = []
    resultados = []
    erro = None
    if request.method == 'POST':
        sql = request.form.get('sql', '').strip()
        instrucoes = sql.rstrip(';').strip()
        primeiro = instrucoes.split(None, 1)[0].lower() if instrucoes else ''
        if not instrucoes or primeiro not in {'select', 'with'} or ';' in instrucoes:
            erro = 'Informe uma única consulta SELECT somente para leitura.'
        else:
            try:
                resultado = db.session.execute(db.text(instrucoes))
                colunas = list(resultado.keys())
                resultados = [list(linha) for linha in resultado.fetchmany(200)]
            except Exception:
                db.session.rollback()
                erro = 'Não foi possível executar a consulta.'
    return render_template('sql_admin.html', sql=sql, colunas=colunas, resultados=resultados, erro=erro)


@app.route('/admin/consultas-sql/exportar', methods=['POST'])
@ti_requerido
def exportar_consulta_sql():
    sql = request.form.get('sql', '').strip().rstrip(';').strip()
    primeiro = sql.split(None, 1)[0].lower() if sql else ''
    if not sql or primeiro not in {'select', 'with'} or ';' in sql:
        flash('Informe uma única consulta SELECT válida.', 'danger')
        return redirect(url_for('consultas_sql'))
    try:
        resultado = db.session.execute(db.text(sql))
        workbook = Workbook()
        sheet = workbook.active
        sheet.append(list(resultado.keys()))
        for linha in resultado.fetchmany(200):
            sheet.append(list(linha))
        arquivo = BytesIO()
        workbook.save(arquivo)
        arquivo.seek(0)
        return send_file(arquivo, as_attachment=True, download_name='consulta_sql.xlsx', mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    except Exception:
        db.session.rollback()
        flash('Não foi possível exportar a consulta.', 'danger')
        return redirect(url_for('consultas_sql'))


@app.route('/admin')
@login_required
def painel_admin():
    permissoes = {item.permissao for item in UsuarioPermissao.query.filter_by(usuario_id=current_user.id).all()}
    if current_user.perfil != 'ti' and 'admin_dashboard' not in permissoes:
        flash('Acesso não autorizado.', 'danger')
        return redirect(url_for('dashboard'))
    agora = datetime.now(timezone.utc)
    hoje = agora.date()
    semana = agora - timedelta(days=7)
    estatisticas = {
        'usuarios_total': Usuario.query.count(),
        'usuarios_ativos': Usuario.query.filter_by(ativo=True).count(),
        'usuarios_inativos': Usuario.query.filter_by(ativo=False).count(),
        'empresas_ativas': Empresa.query.filter_by(ativo=True).count(),
        'areas_ativas': Area.query.filter_by(ativo=True).count(),
        'solicitacoes_total': Solicitacao.query.count(),
        'solicitacoes_pendentes': Solicitacao.query.filter_by(status='pendente').count(),
        'solicitacoes_hoje': Solicitacao.query.filter(func.date(Solicitacao.criado_em) == hoje).count(),
        'solicitacoes_semana': Solicitacao.query.filter(Solicitacao.criado_em >= semana).count(),
        'storage_bytes': tamanho_uploads(),
        'sem_gestor': Usuario.query.filter_by(ativo=True, gestor_id=None).count(),
        'sem_area': Usuario.query.filter_by(ativo=True, area_id=None).count(),
    }
    return render_template('admin_dashboard.html', estatisticas=estatisticas)


PERMISSOES_DISPONIVEIS = {
    'view_organograma': ('Ver organograma', 'estrutura'), 'manage_empresas': ('Gerenciar empresas', 'estrutura'), 'manage_areas': ('Gerenciar áreas', 'estrutura'),
    'manage_users': ('Gerenciar usuários', 'usuarios'), 'reset_passwords': ('Resetar senhas', 'usuarios'), 'manage_permissions': ('Gerenciar permissões', 'usuarios'),
    'create_solicitacao': ('Criar solicitação', 'solicitacoes'), 'approve_as_gestor': ('Aprovar como gestor', 'solicitacoes'), 'approve_as_dp': ('Aprovar como DP', 'solicitacoes'),
    'view_audit_logs': ('Ver auditoria', 'relatorios'), 'export_reports': ('Exportar relatórios', 'relatorios'),
    'admin_dashboard': ('Ver dashboard administrativo', 'relatorios'),
}

# ──────────────────────────────────────────────
# Permissões avançadas (aditivas)
#
# Semântica: o perfil concede o poder padrão. Conceder uma permissão
# aqui apenas ADICIONA capacidade — nunca remove. Por isso o caso
# "gestor que só recusa" não é representável por esta lista: exigiria
# uma permissão que subtraia o poder de aprovar.
#
# Cada entrada: (rótulo, categoria, perfis que se beneficiam, descrição)
# ──────────────────────────────────────────────
PERMISSOES_AVANCADAS = {
    'gestor_encaminhar_supervisor': (
        'Gestor pode encaminhar ao supervisor', 'gestor', ('gestor',),
        'Permite ao gestor enviar a solicitação ao supervisor administrativo em vez de aprová-la.'
    ),
    'gestor_encaminhar_area': (
        'Gestor pode encaminhar para outro gestor', 'gestor', ('gestor',),
        'Permite ao gestor repassar a solicitação a um gestor de nível superior da área.'
    ),
    'dp_encaminhar_supervisor': (
        'DP pode encaminhar ao supervisor', 'dp', ('dp',),
        'Permite ao DP enviar a solicitação ao supervisor administrativo antes de concluir.'
    ),
    'dp_recusar_sem_parecer': (
        'DP pode recusar sem parecer detalhado', 'dp', ('dp',),
        'Dispensa a obrigatoriedade de justificativa na recusa do DP.'
    ),
    'gestor_recusar_sem_parecer': (
        'Gestor pode recusar sem parecer detalhado', 'gestor', ('gestor',),
        'Dispensa a obrigatoriedade de justificativa na recusa do gestor.'
    ),
    'supervisor_encaminhar_dp': (
        'Supervisor pode devolver ao DP', 'supervisor', ('supervisor_administrativo',),
        'Permite ao supervisor administrativo devolver a solicitação ao DP para novo ajuste.'
    ),
    'gestor_aprovar_sem_comprovante': (
        'Gestor pode aprovar sem comprovante', 'gestor', ('gestor',),
        'Permite aprovar solicitações sem anexo de comprovante obrigatório.'
    ),
}

# Categorias exibidas na aba de permissões avançadas.
CATEGORIAS_PERMISSOES = {
    'estrutura': 'Estrutura organizacional',
    'usuarios': 'Usuários e permissões',
    'solicitacoes': 'Solicitações e fluxos',
    'relatorios': 'Relatórios e auditoria',
    'gestor': 'Gestor — ações avançadas',
    'dp': 'DP — ações avançadas',
    'supervisor': 'Supervisor — ações avançadas',
}


@app.route('/admin/usuarios')
@ti_requerido
def painel_admin_usuarios():
    minhas_solicitacoes = (Solicitacao.query.filter_by(colaborador_id=current_user.id)
                           .order_by(Solicitacao.criado_em.desc()).all())
    usuarios = Usuario.query.order_by(Usuario.nome).all()
    return render_template('admin.html', minhas_solicitacoes=minhas_solicitacoes,
                           usuarios=[usuario for usuario in usuarios if usuario.ativo],
                           usuarios_inativos=[usuario for usuario in usuarios if not usuario.ativo],
                           areas=Area.query.order_by(Area.nome).all(),
                           gestores=Usuario.query.filter_by(perfil='gestor', ativo=True).order_by(Usuario.nome).all(),
                           empresas=Empresa.query.order_by(Empresa.nome).all(),
                           tipos=TipoJustificativa.query.order_by(TipoJustificativa.nome).all(),
                           tipos_ocorrencia=TipoOcorrencia.query.order_by(TipoOcorrencia.nome).all(),
                           permissoes_disponiveis=PERMISSOES_DISPONIVEIS)


@app.route('/admin/permissoes/<int:usuario_id>', methods=['GET', 'POST'])
@ti_requerido
def editar_permissoes(usuario_id):
    """Tela única de permissões do usuário.

    Reúne os acessos gerais (PERMISSOES_DISPONIVEIS) e as permissões
    avançadas (PERMISSOES_AVANCADAS) em um só formulário. As avançadas só
    aparecem quando o perfil do usuário é compatível com elas.
    """
    usuario = db.session.get(Usuario, usuario_id)
    if not usuario:
        abort(404)
    if request.method == 'POST':
        # Acessos gerais: substituem integralmente o conjunto anterior.
        base = set(request.form.getlist('permissoes')) & set(PERMISSOES_DISPONIVEIS)
        # Permissões avançadas: apenas as compatíveis com o perfil do usuário.
        validas = {chave for chave, dados in PERMISSOES_AVANCADAS.items()
                   if usuario.perfil in dados[2]}
        avancadas = set(request.form.getlist('permissoes_avancadas')) & validas
        # A exclusão abaixo remove todas as permissões do usuário (base e
        # avançadas); a inserção recria exatamente o conjunto marcado.
        UsuarioPermissao.query.filter_by(usuario_id=usuario.id).delete()
        db.session.add_all(UsuarioPermissao(usuario_id=usuario.id, permissao=item)
                           for item in (base | avancadas))
        db.session.commit()
        flash('Permissões atualizadas.', 'success')
        return redirect(url_for('painel_admin_usuarios'))

    permissoes = {item.permissao for item in
                   UsuarioPermissao.query.filter_by(usuario_id=usuario.id).all()}
    # Só oferece as permissões avançadas compatíveis com o perfil do usuário.
    disponiveis = {chave: dados for chave, dados in PERMISSOES_AVANCADAS.items()
                    if usuario.perfil in dados[2]}
    return render_template('usuario_permissoes.html', usuario=usuario, permissoes=permissoes,
                           permissoes_disponiveis=PERMISSOES_DISPONIVEIS,
                           permissoes_avancadas=disponiveis,
                           categorias_permissoes=CATEGORIAS_PERMISSOES,
                           areas=Area.query.order_by(Area.nome).all(),
                           empresas=Empresa.query.filter_by(ativo=True).order_by(Empresa.nome).all(),
                           gestores=Usuario.query.filter_by(perfil='gestor', ativo=True).order_by(Usuario.nome).all())


@app.route('/admin/permissoes-avancadas/<int:usuario_id>', methods=['GET', 'POST'])
@ti_requerido
def editar_permissoes_avancadas(usuario_id):
    """Redireciona para a tela unificada de permissões.

    Mantido para preservar links já existentes na interface.
    """
    return redirect(url_for('editar_permissoes', usuario_id=usuario_id))


def dados_usuario_validos(form, senha_obrigatoria=True):
    nome = ' '.join(form.get('nome', '').split())
    matricula = form.get('matricula', '').strip()
    email = form.get('email', '').strip().lower()
    perfil = form.get('perfil', '').strip().lower()
    senha = form.get('senha', '')
    perfis = set(PERFIS)
    if not nome or not matricula or not email or perfil not in perfis or (senha_obrigatoria and len(senha) < 8):
        return None
    return nome, matricula, email, perfil, senha


@app.route('/admin/usuarios', methods=['POST'])
@ti_requerido
def criar_usuario():
    dados = dados_usuario_validos(request.form)
    if not dados:
        flash('Preencha os dados corretamente. A senha deve ter pelo menos 8 caracteres.', 'danger')
        return redirect(url_for('painel_admin_usuarios'))
    nome, matricula, email, perfil, senha = dados
    if Usuario.query.filter((Usuario.matricula == matricula) | (Usuario.email == email)).first():
        flash('Matrícula ou e-mail já cadastrado.', 'danger')
        return redirect(url_for('painel_admin_usuarios'))
    db.session.add(Usuario(nome=nome, matricula=matricula, email=email,
                           perfil=perfil, senha_hash=generate_password_hash(senha)))
    db.session.commit()
    flash('Usuário criado.', 'success')
    return redirect(url_for('painel_admin_usuarios'))


@app.route('/admin/areas/<int:area_id>', methods=['POST'])
@login_required
@perfil_requerido('dp', 'ti')
def editar_area(area_id):
    area = db.session.get(Area, area_id)
    nome = ' '.join(request.form.get('nome', '').split())
    if not area or not nome or len(nome) > 100:
        flash('Nome de departamento inválido.', 'danger')
    elif Area.query.filter(Area.nome == nome, Area.id != area.id).first():
        flash('Departamento já cadastrado.', 'danger')
    else:
        area.nome = nome
        db.session.commit()
        flash('Departamento atualizado.', 'success')
    return redirect(url_for('painel_vinculos'))


@app.route('/admin/areas/<int:area_id>/empresas', methods=['POST'])
@login_required
@perfil_requerido('dp', 'ti')
def vincular_area_empresas(area_id):
    area = db.session.get(Area, area_id)
    ids = request.form.getlist('empresa_ids', type=int)
    empresas = Empresa.query.filter(Empresa.id.in_(ids), Empresa.ativo == True).all() if ids else []
    if not area or len(empresas) != len(set(ids)):
        flash('Empresas inválidas.', 'danger')
    else:
        area.empresas = empresas
        db.session.commit()
        flash('Vínculos do departamento atualizados.', 'success')
    return redirect(url_for('painel_vinculos'))


@app.route('/admin/areas', methods=['POST'])
@ti_requerido
def criar_area():
    nome = ' '.join(request.form.get('nome', '').split())
    if not nome or len(nome) > 100:
        flash('Informe um nome de área válido.', 'danger')
    elif Area.query.filter_by(nome=nome).first():
        flash('Área já cadastrada.', 'danger')
    else:
        db.session.add(Area(nome=nome))
        db.session.commit()
        flash('Área cadastrada.', 'success')
    return redirect(url_for('painel_admin'))


@app.route('/admin/usuarios/<int:usuario_id>/vinculo', methods=['POST'])
@ti_requerido
def vincular_usuario(usuario_id):
    usuario = db.session.get(Usuario, usuario_id)
    area_id = request.form.get('area_id', type=int)
    gestor_id = request.form.get('gestor_id', type=int)
    empresa_id = request.form.get('empresa_id', type=int)
    area = db.session.get(Area, area_id) if area_id else None
    gestor = db.session.get(Usuario, gestor_id) if gestor_id else None
    empresa = db.session.get(Empresa, empresa_id) if empresa_id else None
    if not usuario or (area_id and (not area or not area.ativo)) or (empresa_id and (not empresa or not empresa.ativo)):
        flash('Área ou empresa inválida.', 'danger')
    elif gestor and (gestor.perfil != 'gestor' or not gestor.ativo or gestor.id == usuario.id):
        flash('Gestor inválido.', 'danger')
    else:
        usuario.area_id = area_id or None
        usuario.empresa_id = empresa_id or None
        usuario.gestor_id = gestor_id or None
        db.session.commit()
        flash('Vínculo atualizado.', 'success')
    return redirect(url_for('painel_admin'))


@app.route('/admin/empresas/<int:empresa_id>', methods=['POST'])
@ti_requerido
def editar_empresa(empresa_id):
    empresa = db.session.get(Empresa, empresa_id)
    nome = ' '.join(request.form.get('nome', '').split())
    if not empresa or not nome or len(nome) > 120:
        flash('Nome de empresa inválido.', 'danger')
    elif Empresa.query.filter(Empresa.nome == nome, Empresa.id != empresa.id).first():
        flash('Empresa já cadastrada.', 'danger')
    else:
        empresa.nome = nome
        db.session.commit()
        flash('Empresa atualizada.', 'success')
    return redirect(url_for('painel_vinculos'))


@app.route('/admin/empresas', methods=['POST'])
@ti_requerido
def criar_empresa():
    nome = ' '.join(request.form.get('nome', '').split())
    if not nome or len(nome) > 120:
        flash('Informe um nome de empresa válido.', 'danger')
    elif Empresa.query.filter_by(nome=nome).first():
        flash('Empresa já cadastrada.', 'danger')
    else:
        db.session.add(Empresa(nome=nome))
        db.session.commit()
        flash('Empresa cadastrada.', 'success')
    return redirect(url_for('painel_admin'))


@app.route('/admin/empresas/<int:empresa_id>/alternar', methods=['POST'])
@ti_requerido
def alternar_empresa(empresa_id):
    empresa = db.session.get(Empresa, empresa_id)
    if empresa:
        empresa.ativo = not empresa.ativo
        db.session.commit()
    return redirect(url_for('painel_admin'))


@app.route('/admin/areas/<int:area_id>/alternar', methods=['POST'])
@ti_requerido
def alternar_area(area_id):
    area = db.session.get(Area, area_id)
    if area:
        area.ativo = not area.ativo
        db.session.commit()
    return redirect(url_for('painel_admin'))


@app.route('/admin/usuarios/<int:usuario_id>', methods=['POST'])
@ti_requerido
def editar_usuario(usuario_id):
    usuario = db.session.get(Usuario, usuario_id)
    dados = dados_usuario_validos(request.form, senha_obrigatoria=False)
    if not usuario or not dados:
        flash('Dados inválidos.', 'danger')
        return redirect(url_for('painel_admin'))
    nome, matricula, email, perfil, senha = dados
    duplicado = Usuario.query.filter(
        Usuario.id != usuario.id,
        (Usuario.matricula == matricula) | (Usuario.email == email)
    ).first()
    if duplicado:
        flash('Matrícula ou e-mail já cadastrado.', 'danger')
        return redirect(url_for('painel_admin'))
    usuario.nome, usuario.matricula, usuario.email, usuario.perfil = nome, matricula, email, perfil
    if senha:
        if len(senha) < 8:
            flash('A nova senha deve ter pelo menos 8 caracteres.', 'danger')
            return redirect(url_for('painel_admin'))
        usuario.senha_hash = generate_password_hash(senha)
    db.session.commit()
    flash('Usuário atualizado.', 'success')
    return redirect(url_for('painel_admin'))


@app.route('/admin/usuarios/<int:usuario_id>/alternar', methods=['POST'])
@ti_requerido
def alternar_usuario(usuario_id):
    usuario = db.session.get(Usuario, usuario_id)
    if usuario and usuario.id != current_user.id:
        usuario.ativo = not usuario.ativo
        db.session.commit()
    return redirect(url_for('painel_admin'))


@app.route('/admin/usuarios/<int:usuario_id>/excluir', methods=['POST'])
@ti_requerido
def excluir_usuario(usuario_id):
    usuario = db.session.get(Usuario, usuario_id)
    if not usuario:
        flash('Usuário não encontrado.', 'danger')
    elif usuario.id == current_user.id:
        flash('Não é possível excluir o próprio usuário.', 'danger')
    elif usuario.subordinados or Solicitacao.query.filter(
        (Solicitacao.colaborador_id == usuario.id) |
        (Solicitacao.gestor_id == usuario.id) |
        (Solicitacao.dp_id == usuario.id) |
        (Solicitacao.supervisor_id == usuario.id)
    ).first():
        flash('Usuário possui histórico ou subordinados. Desative-o em vez de excluir.', 'warning')
    else:
        try:
            db.session.delete(usuario)
            db.session.commit()
            flash('Usuário excluído permanentemente.', 'success')
        except IntegrityError:
            db.session.rollback()
            flash('Não foi possível excluir o usuário por causa de vínculos existentes.', 'danger')
    return redirect(url_for('painel_admin'))


# ──────────────────────────────────────────────
# PAINEL DO ANALISTA
# ──────────────────────────────────────────────



@app.route('/solicitacoes/nova', methods=['GET', 'POST'])
@login_required
@perfil_requerido(*PERFIS_SOLICITANTES)
def solicitacao_nova():
    if request.method == 'GET':
        _, tipos, tipos_ocorrencia = carregar_cadastros()
        return render_template('solicitacao_form.html', solicitacao=None,
                               tipos=tipos, tipos_ocorrencia=tipos_ocorrencia)
    return salvar_solicitacao()


@app.route('/analista')
@login_required
@perfil_requerido('analista')
def painel_analista():
    solicitacoes = (Solicitacao.query
                    .filter_by(colaborador_id=current_user.id)
                    .order_by(Solicitacao.criado_em.desc())
                    .all())
    colaboradores, tipos, tipos_ocorrencia = carregar_cadastros()
    return render_template('analista.html', solicitacoes=solicitacoes,
                           colaboradores=colaboradores, tipos=tipos,
                           tipos_ocorrencia=tipos_ocorrencia)


@app.route('/analista/nova', methods=['POST'])
@login_required
@perfil_requerido(*PERFIS_SOLICITANTES)
def salvar_solicitacao():
    data_str = request.form.get('data_ocorrencia')
    tipo = request.form.get('tipo_ocorrencia', '').strip()
    entrada = request.form.get('horario_entrada', '').strip()
    saida = request.form.get('horario_saida', '').strip()
    motivo = request.form.get('motivo', '').strip()
    tipo_justificativa = request.form.get('tipo_justificativa', '').strip()
    nomes = request.form.getlist('colaborador_nome[]')
    matriculas = request.form.getlist('colaborador_matricula[]')

    if not data_str or not tipo or not tipo_justificativa or not motivo or not nomes or len(nomes) != len(matriculas):
        flash('Preencha todos os campos obrigatórios.', 'danger')
        return redirect(url_for('dashboard'))

    tipo_obj = TipoJustificativa.query.filter_by(nome=tipo_justificativa, ativo=True).first()
    ocorrencia_obj = TipoOcorrencia.query.filter_by(nome=tipo, ativo=True).first()
    if not ocorrencia_obj:
        ocorrencia_obj = TipoOcorrencia.query.filter_by(nome=tipo).first()
    if not ocorrencia_obj or not ocorrencia_obj.ativo:
        flash('Tipo de ocorrência inválido.', 'danger')
        return redirect(url_for('dashboard'))
    if not tipo_obj:
        flash('Tipo de justificativa inválido.', 'danger')
        return redirect(url_for('dashboard'))

    colaboradores_solicitacao = []
    vistos = set()
    for nome, matricula in zip(nomes, matriculas):
        nome = ' '.join(nome.split())
        matricula = matricula.strip()
        if not nome_valido(nome) or not matricula_valida(matricula):
            flash('Nome deve conter apenas letras e matrícula apenas números.', 'danger')
            return redirect(url_for('dashboard'))
        if matricula in vistos:
            flash('Não repita a matrícula dos colaboradores.', 'danger')
            return redirect(url_for('dashboard'))
        vistos.add(matricula)
        # Cadastro prévio não é obrigatório nesta fase.
        colaboradores_solicitacao.append((nome, matricula))

    try:
        data_ocorrencia = datetime.strptime(data_str, '%d/%m/%Y').date()
    except ValueError:
        flash('Data inválida. Use o formato dd/mm/aaaa.', 'danger')
        return redirect(url_for('dashboard'))

    for horario in (entrada, saida):
        if horario:
            try:
                datetime.strptime(horario, '%H:%M')
            except ValueError:
                flash('Horário inválido. Use o formato 24 horas hh:mm.', 'danger')
                return redirect(url_for('dashboard'))

    if entrada and saida and entrada == saida:
        flash('Entrada e saída não podem ser iguais.', 'danger')
        return redirect(url_for('dashboard'))

    anexos = []
    for arquivo in request.files.getlist('comprovantes'):
        if not arquivo or not arquivo.filename:
            continue
        nome_seguro = secure_filename(arquivo.filename)
        if not (extensao_permitida(nome_seguro) and nome_seguro and '.' in nome_seguro):
            flash('Formato não permitido. Use PDF, PNG, JPG ou Excel.', 'danger')
            return redirect(url_for('dashboard'))
        nome_unico = f"{uuid.uuid4().hex}_{nome_seguro}"
        os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
        arquivo.save(os.path.join(app.config['UPLOAD_FOLDER'], nome_unico))
        anexos.append(nome_unico)

    solicitacao = Solicitacao(
        colaborador_id=current_user.id,
        data_ocorrencia=data_ocorrencia,
        tipo_ocorrencia=tipo,
        tipo_justificativa=tipo_justificativa,
        horario_entrada=entrada or None,
        horario_saida=saida or None,
        motivo=motivo,
        comprovante=json.dumps(anexos),
    )
    db.session.add(solicitacao)
    db.session.flush()
    for ordem, (nome, matricula) in enumerate(colaboradores_solicitacao):
        db.session.add(SolicitacaoParticipante(
            solicitacao_id=solicitacao.id,
            nome=nome,
            matricula=matricula,
            ordem=ordem,
        ))
    db.session.commit()

    flash('Solicitação enviada com sucesso!', 'success')
    return redirect(url_for('dashboard'))


@app.route('/solicitacoes/<int:sol_id>/editar', methods=['GET', 'POST'])
@login_required
@perfil_requerido(*PERFIS_SOLICITANTES)
def editar_solicitacao(sol_id):
    solicitacao = db.session.get(Solicitacao, sol_id)
    if not solicitacao or solicitacao.colaborador_id != current_user.id:
        flash('Solicitação não encontrada ou sem permissão.', 'danger')
        return redirect(url_for('dashboard'))
    if solicitacao.status != 'pendente':
        flash('Solicitações aprovadas não podem mais ser alteradas.', 'warning')
        return redirect(url_for('dashboard'))
    if request.method == 'GET':
        _, tipos, tipos_ocorrencia = carregar_cadastros()
        return render_template('solicitacao_form.html', solicitacao=solicitacao,
                               tipos=tipos, tipos_ocorrencia=tipos_ocorrencia)

    # Edição reaproveita o mesmo formato e validações da criação.
    form = request.form
    data_str = form.get('data_ocorrencia', '')
    tipo = form.get('tipo_ocorrencia', '').strip()
    tipo_justificativa = form.get('tipo_justificativa', '').strip()
    motivo = form.get('motivo', '').strip()
    entrada = form.get('horario_entrada', '').strip()
    saida = form.get('horario_saida', '').strip()
    nomes = form.getlist('colaborador_nome[]')
    matriculas = form.getlist('colaborador_matricula[]')
    try:
        data_ocorrencia = datetime.strptime(data_str, '%d/%m/%Y').date()
        if entrada:
            datetime.strptime(entrada, '%H:%M')
        if saida:
            datetime.strptime(saida, '%H:%M')
    except ValueError:
        flash('Data ou horário inválido.', 'danger')
        return redirect(url_for('editar_solicitacao', sol_id=sol_id))
    ocorrencia = TipoOcorrencia.query.filter_by(nome=tipo, ativo=True).first()
    justificativa = TipoJustificativa.query.filter_by(nome=tipo_justificativa, ativo=True).first()
    if not ocorrencia or not justificativa or not motivo or not nomes or len(nomes) != len(matriculas):
        flash('Preencha os dados corretamente.', 'danger')
        return redirect(url_for('editar_solicitacao', sol_id=sol_id))
    participantes = []
    vistos = set()
    for nome, matricula in zip(nomes, matriculas):
        nome = ' '.join(nome.split())
        matricula = matricula.strip()
        if not nome_valido(nome) or not matricula_valida(matricula) or matricula in vistos:
            flash('Nome ou matrícula inválidos, ou repetidos.', 'danger')
            return redirect(url_for('editar_solicitacao', sol_id=sol_id))
        vistos.add(matricula)
        participantes.append((nome, matricula))
    anexos = json.loads(solicitacao.comprovante or '[]')
    remover = set(request.form.getlist('remover_anexos'))
    for nome in remover:
        if nome in anexos:
            try:
                os.remove(os.path.join(app.config['UPLOAD_FOLDER'], nome))
            except OSError:
                pass
    anexos = [nome for nome in anexos if nome not in remover]
    for arquivo in request.files.getlist('comprovantes'):
        if not arquivo or not arquivo.filename:
            continue
        nome_seguro = secure_filename(arquivo.filename)
        if not extensao_permitida(nome_seguro):
            flash('Formato não permitido. Use PDF, PNG, JPG ou Excel.', 'danger')
            return redirect(url_for('editar_solicitacao', sol_id=sol_id))
        nome_unico = f"{uuid.uuid4().hex}_{nome_seguro}"
        os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
        arquivo.save(os.path.join(app.config['UPLOAD_FOLDER'], nome_unico))
        anexos.append(nome_unico)
    solicitacao.comprovante = json.dumps(anexos)
    solicitacao.data_ocorrencia = data_ocorrencia
    solicitacao.tipo_ocorrencia = tipo
    solicitacao.tipo_justificativa = tipo_justificativa
    solicitacao.horario_entrada = entrada or None
    solicitacao.horario_saida = saida or None
    solicitacao.motivo = motivo
    solicitacao.participantes.clear()
    for ordem, (nome, matricula) in enumerate(participantes):
        solicitacao.participantes.append(SolicitacaoParticipante(nome=nome, matricula=matricula, ordem=ordem))
    db.session.commit()
    flash('Solicitação atualizada.', 'success')
    return redirect(url_for('dashboard'))


# ──────────────────────────────────────────────
# PAINEL DO GESTOR
# ──────────────────────────────────────────────

@app.route('/gestor')
@login_required
@perfil_requerido('gestor')
def painel_gestor():
    minhas_solicitacoes = (Solicitacao.query.filter_by(colaborador_id=current_user.id)
                           .order_by(Solicitacao.criado_em.desc()).all())
    # Pendentes da equipe do gestor
    pendentes = (Solicitacao.query
                 .join(Usuario, Solicitacao.colaborador_id == Usuario.id)
                 .filter(Usuario.gestor_id == current_user.id)
                 .filter((Usuario.area_id == current_user.area_id) | (current_user.area_id == None))
                 .filter(Solicitacao.status == 'pendente')
                 .order_by(Solicitacao.criado_em.desc())
                 .all())

    # Histórico já analisado
    historico = (Solicitacao.query
                 .join(Usuario, Solicitacao.colaborador_id == Usuario.id)
                 .filter(Usuario.gestor_id == current_user.id)
                 .filter((Usuario.area_id == current_user.area_id) | (current_user.area_id == None))
                 .filter(Solicitacao.status != 'pendente')
                 .order_by(Solicitacao.atualizado_em.desc())
                 .limit(50)
                 .all())

    equipe = Usuario.query.filter_by(gestor_id=current_user.id, ativo=True).all()
    equipe_ids = [usuario.id for usuario in equipe]
    equipe_solicitacoes = Solicitacao.query.filter(Solicitacao.colaborador_id.in_(equipe_ids)).all() if equipe_ids else []
    estatisticas = {
        'membros': len(equipe),
        'total': len(equipe_solicitacoes),
        'pendentes': sum(s.status == 'pendente' for s in equipe_solicitacoes),
        'concluidas': sum(s.status in {'aprovado_dp', 'aprovado_supervisor'} for s in equipe_solicitacoes),
        'recusadas': sum(s.status.startswith('recusado') for s in equipe_solicitacoes),
    }
    return render_template('gestor.html', pendentes=pendentes, historico=historico,
                           estatisticas=estatisticas,
                           minhas_solicitacoes=minhas_solicitacoes,
                           colaboradores=Colaborador.query.order_by(Colaborador.nome).all(),
                           tipos=TipoJustificativa.query.order_by(TipoJustificativa.nome).all(),
                           tipos_ocorrencia=TIPOS_OCORRENCIA,
                           supervisores=Usuario.query.filter_by(
                               perfil='supervisor_administrativo', ativo=True).order_by(Usuario.nome).all(),
                           pode_encaminhar_supervisor=permissao_avancada('gestor_encaminhar_supervisor'),
                           pode_recusar_sem_parecer=permissao_avancada('gestor_recusar_sem_parecer'))


@app.route('/gestor/aprovar/<int:sol_id>', methods=['POST'])
@login_required
@perfil_requerido('gestor')
def gestor_aprovar(sol_id):
    sol = db.session.get(Solicitacao, sol_id)
    if not sol or sol.status != 'pendente':
        flash('Solicitação não encontrada ou já processada.', 'warning')
        return redirect(url_for('painel_gestor'))

    # Verificar se o colaborador é subordinado do gestor
    colab = db.session.get(Usuario, sol.colaborador_id)
    if not colab or colab.gestor_id != current_user.id:
        flash('Acesso não autorizado.', 'danger')
        return redirect(url_for('painel_gestor'))

    sol.status = 'aprovado_gestor'
    sol.gestor_id = current_user.id
    sol.gestor_parecer = 'Aprovado'
    sol.gestor_data = datetime.now(timezone.utc)
    db.session.commit()

    flash(f'Solicitação #{sol.id} aprovada com sucesso.', 'success')
    return redirect(url_for('painel_gestor'))


@app.route('/gestor/recusar/<int:sol_id>', methods=['POST'])
@login_required
@perfil_requerido('gestor')
def gestor_recusar(sol_id):
    sol = db.session.get(Solicitacao, sol_id)
    if not sol or sol.status != 'pendente':
        flash('Solicitação não encontrada ou já processada.', 'warning')
        return redirect(url_for('painel_gestor'))

    colab = db.session.get(Usuario, sol.colaborador_id)
    if not colab or colab.gestor_id != current_user.id:
        flash('Acesso não autorizado.', 'danger')
        return redirect(url_for('painel_gestor'))

    justificativa = request.form.get('justificativa', '').strip()
    if not justificativa and not permissao_avancada('gestor_recusar_sem_parecer'):
        flash('Informe o motivo da recusa.', 'danger')
        return redirect(url_for('painel_gestor'))

    sol.status = 'recusado_gestor'
    sol.gestor_id = current_user.id
    sol.gestor_parecer = justificativa or 'Recusado sem justificativa detalhada'
    sol.gestor_data = datetime.now(timezone.utc)
    db.session.commit()

    flash(f'Solicitação #{sol.id} recusada.', 'info')
    return redirect(url_for('painel_gestor'))


@app.route('/gestor/encaminhar/<int:sol_id>', methods=['POST'])
@login_required
@perfil_requerido('gestor')
@permissao_avancada_requerida('gestor_encaminhar_supervisor')
def gestor_encaminhar_supervisor(sol_id):
    """Encaminha a solicitação ao supervisor administrativo (permissão avançada)."""
    sol = db.session.get(Solicitacao, sol_id)
    if not sol or sol.status != 'pendente':
        flash('Solicitação não encontrada ou já processada.', 'warning')
        return redirect(url_for('painel_gestor'))

    colab = db.session.get(Usuario, sol.colaborador_id)
    if not colab or colab.gestor_id != current_user.id:
        flash('Acesso não autorizado.', 'danger')
        return redirect(url_for('painel_gestor'))

    supervisor_id = request.form.get('supervisor_id', type=int)
    supervisor = db.session.get(Usuario, supervisor_id) if supervisor_id else None
    if not supervisor or supervisor.perfil != 'supervisor_administrativo' or not supervisor.ativo:
        flash('Selecione um supervisor administrativo ativo.', 'danger')
        return redirect(url_for('painel_gestor'))

    sol.status = 'encaminhado_supervisor'
    sol.gestor_id = current_user.id
    sol.gestor_parecer = 'Encaminhado ao supervisor administrativo'
    sol.gestor_data = datetime.now(timezone.utc)
    sol.supervisor_id = supervisor.id
    sol.supervisor_parecer = 'Encaminhado pelo gestor'
    sol.supervisor_data = datetime.now(timezone.utc)
    db.session.commit()

    flash(f'Solicitação #{sol.id} encaminhada ao supervisor administrativo.', 'success')
    return redirect(url_for('painel_gestor'))


# ──────────────────────────────────────────────
# PAINEL DO DP
# ──────────────────────────────────────────────

@app.route('/dp/exportar')
@login_required
@perfil_requerido('dp')
def exportar_justificativas():
    status = request.args.get('status', 'aprovado_gestor')
    data_inicio = request.args.get('data_inicio', '')
    data_fim = request.args.get('data_fim', '')
    colaborador = request.args.get('colaborador', '')
    query = Solicitacao.query.join(Usuario, Solicitacao.colaborador_id == Usuario.id)
    if status == 'aprovado_gestor':
        query = query.filter(Solicitacao.status == status)
    elif status == 'aguardando_supervisor':
        query = query.filter(Solicitacao.status.in_(STATUS_SUPERVISOR))
    elif status != 'todos':
        query = query.filter(Solicitacao.status == status)
    try:
        if data_inicio:
            query = query.filter(Solicitacao.data_ocorrencia >= datetime.strptime(data_inicio, '%Y-%m-%d').date())
        if data_fim:
            query = query.filter(Solicitacao.data_ocorrencia <= datetime.strptime(data_fim, '%Y-%m-%d').date())
    except ValueError:
        flash('Período inválido.', 'danger')
        return redirect(url_for('painel_dp'))
    if colaborador:
        query = query.filter(Usuario.nome.ilike(f'%{colaborador}%'))
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(['ID', 'Solicitado por', 'Matrícula', 'Data', 'Tipo', 'Justificativa', 'Status'])
    for item in query.order_by(Solicitacao.criado_em.desc()).all():
        sheet.append([item.id, item.colaborador.nome, item.colaborador.matricula,
                      item.data_ocorrencia.strftime('%d/%m/%Y'), item.tipo_ocorrencia,
                      item.tipo_justificativa or '', item.status_label])
    arquivo = BytesIO()
    workbook.save(arquivo)
    arquivo.seek(0)
    return send_file(arquivo, as_attachment=True, download_name='justificativas.xlsx', mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


@app.route('/dp')
@login_required
@perfil_requerido('dp')
def painel_dp():
    minhas_solicitacoes = (Solicitacao.query.filter_by(colaborador_id=current_user.id)
                           .order_by(Solicitacao.criado_em.desc()).all())
    filtro_status = request.args.get('status', 'aprovado_gestor')
    filtro_data = request.args.get('data', '')
    filtro_data_inicio = request.args.get('data_inicio', '')
    filtro_data_fim = request.args.get('data_fim', '')
    filtro_colaborador = request.args.get('colaborador', '')

    supervisores = Usuario.query.filter_by(perfil='supervisor_administrativo', ativo=True).order_by(Usuario.nome).all()
    query = Solicitacao.query.join(Usuario, Solicitacao.colaborador_id == Usuario.id)

    if filtro_status == 'aprovado_gestor':
        query = query.filter(Solicitacao.status == 'aprovado_gestor')
    elif filtro_status == 'todos':
        pass  # sem filtro
    elif filtro_status == 'aguardando_supervisor':
        query = query.filter(Solicitacao.status.in_(STATUS_SUPERVISOR))
    else:
        query = query.filter(Solicitacao.status == filtro_status)

    if filtro_data:
        try:
            data_filtro = datetime.strptime(filtro_data, '%Y-%m-%d').date()
            query = query.filter(Solicitacao.data_ocorrencia == data_filtro)
        except ValueError:
            pass
    else:
        if filtro_data_inicio:
            try:
                query = query.filter(Solicitacao.data_ocorrencia >= datetime.strptime(filtro_data_inicio, '%Y-%m-%d').date())
            except ValueError:
                pass
        if filtro_data_fim:
            try:
                query = query.filter(Solicitacao.data_ocorrencia <= datetime.strptime(filtro_data_fim, '%Y-%m-%d').date())
            except ValueError:
                pass

    if filtro_colaborador:
        query = query.filter(Usuario.nome.ilike(f'%{filtro_colaborador}%'))

    solicitacoes = query.order_by(Solicitacao.criado_em.desc()).all()

    return render_template('dp.html', solicitacoes=solicitacoes,
                           minhas_solicitacoes=minhas_solicitacoes,
                           filtro_status=filtro_status,
                           filtro_data=filtro_data,
                           filtro_data_inicio=filtro_data_inicio,
                           filtro_data_fim=filtro_data_fim,
                           filtro_colaborador=filtro_colaborador,
                           colaboradores=Colaborador.query.order_by(Colaborador.nome).all(),
                           tipos=TipoJustificativa.query.order_by(TipoJustificativa.nome).all(),
                           tipos_ocorrencia=TipoOcorrencia.query.order_by(TipoOcorrencia.nome).all(),
                           supervisores=supervisores,
                           pode_encaminhar_supervisor=permissao_avancada('dp_encaminhar_supervisor'),
                           pode_recusar_sem_parecer=permissao_avancada('dp_recusar_sem_parecer'))


@app.route('/cadastros/colaborador', methods=['POST'])
@login_required
@perfil_requerido('gestor', 'dp')
def cadastrar_colaborador():
    nome = ' '.join(request.form.get('nome', '').split())
    matricula = request.form.get('matricula', '').strip()
    if not nome_valido(nome) or not matricula_valida(matricula):
        flash('Nome deve conter apenas letras e matrícula apenas números.', 'danger')
    elif Colaborador.query.filter_by(matricula=matricula).first():
        flash('Matrícula já cadastrada.', 'danger')
    else:
        db.session.add(Colaborador(nome=nome, matricula=matricula))
        db.session.commit()
        flash('Colaborador cadastrado.', 'success')
    return redirect(url_for('configuracoes'))


@app.route('/cadastros/colaborador/<int:colaborador_id>/alternar', methods=['POST'])
@login_required
@perfil_requerido('gestor', 'dp')
def alternar_colaborador(colaborador_id):
    colaborador = db.session.get(Colaborador, colaborador_id)
    if colaborador:
        colaborador.ativo = not colaborador.ativo
        db.session.commit()
    return redirect(url_for('configuracoes'))


@app.route('/cadastros/tipo', methods=['POST'])
@login_required
@perfil_requerido('dp', 'ti')
def cadastrar_tipo():
    nome = ' '.join(request.form.get('nome', '').split())
    if not nome or len(nome) > 80:
        flash('Informe um tipo válido.', 'danger')
    elif TipoJustificativa.query.filter_by(nome=nome).first():
        flash('Tipo já cadastrado.', 'danger')
    else:
        db.session.add(TipoJustificativa(nome=nome))
        db.session.commit()
        flash('Tipo de justificativa cadastrado.', 'success')
    return redirect(url_for('configuracoes'))


@app.route('/cadastros/ocorrencia', methods=['POST'])
@login_required
@perfil_requerido('dp', 'ti')
def cadastrar_ocorrencia():
    nome = ' '.join(request.form.get('nome', '').split())
    if not nome or len(nome) > 80:
        flash('Informe uma ocorrência válida.', 'danger')
    elif TipoOcorrencia.query.filter_by(nome=nome).first():
        flash('Ocorrência já cadastrada.', 'danger')
    else:
        db.session.add(TipoOcorrencia(nome=nome))
        db.session.commit()
        flash('Ocorrência cadastrada.', 'success')
    return redirect(url_for('configuracoes'))


@app.route('/cadastros/ocorrencia/<int:tipo_id>/alternar', methods=['POST'])
@login_required
@perfil_requerido('dp', 'ti')
def alternar_ocorrencia(tipo_id):
    tipo = db.session.get(TipoOcorrencia, tipo_id)
    if tipo:
        tipo.ativo = not tipo.ativo
        db.session.commit()
    return redirect(url_for('configuracoes'))


@app.route('/cadastros/tipo/<int:tipo_id>/alternar', methods=['POST'])
@login_required
@perfil_requerido('dp', 'ti')
def alternar_tipo(tipo_id):
    tipo = db.session.get(TipoJustificativa, tipo_id)
    if tipo:
        tipo.ativo = not tipo.ativo
        db.session.commit()
    return redirect(url_for('configuracoes'))


@app.route('/dp/encaminhar/<int:sol_id>', methods=['POST'])
@login_required
@perfil_requerido('dp')
@permissao_avancada_requerida('dp_encaminhar_supervisor')
def dp_encaminhar_supervisor(sol_id):
    sol = db.session.get(Solicitacao, sol_id)
    supervisor_id = request.form.get('supervisor_id', type=int)
    supervisor = db.session.get(Usuario, supervisor_id) if supervisor_id else None
    if not sol or sol.status != 'aprovado_gestor' or not supervisor or supervisor.perfil != 'supervisor_administrativo' or not supervisor.ativo:
        flash('Solicitação ou supervisor inválido.', 'danger')
        return redirect(url_for('painel_dp'))
    sol.status = 'encaminhado_supervisor'
    sol.supervisor_id = supervisor.id
    sol.supervisor_parecer = 'Encaminhado pelo DP'
    sol.supervisor_data = datetime.now(timezone.utc)
    db.session.commit()
    flash(f'Solicitação #{sol.id} encaminhada ao supervisor.', 'success')
    return redirect(url_for('painel_dp'))


@app.route('/supervisor/devolver/<int:sol_id>', methods=['POST'])
@login_required
@perfil_requerido('supervisor_administrativo')
@permissao_avancada_requerida('supervisor_encaminhar_dp')
def supervisor_devolver_dp(sol_id):
    """Devolve a solicitação ao DP para novo ajuste (permissão avançada)."""
    sol = db.session.get(Solicitacao, sol_id)
    if not sol or sol.status != 'encaminhado_supervisor' or sol.supervisor_id != current_user.id:
        flash('Solicitação não encontrada ou já processada.', 'warning')
        return redirect(url_for('painel_supervisor'))
    sol.status = 'aprovado_gestor'
    sol.supervisor_parecer = request.form.get('parecer', '').strip() or 'Devolvido ao DP para ajuste'
    sol.supervisor_data = datetime.now(timezone.utc)
    db.session.commit()
    flash(f'Solicitação #{sol.id} devolvida ao DP.', 'success')
    return redirect(url_for('painel_supervisor'))


@app.route('/supervisor/aprovar/<int:sol_id>', methods=['POST'])
@login_required
@perfil_requerido('supervisor_administrativo')
def supervisor_aprovar(sol_id):
    sol = db.session.get(Solicitacao, sol_id)
    if not sol or sol.status != 'encaminhado_supervisor' or sol.supervisor_id != current_user.id:
        flash('Solicitação não encontrada ou já processada.', 'warning')
        return redirect(url_for('painel_supervisor'))
    sol.status = 'aprovado_supervisor'
    sol.supervisor_parecer = 'Aprovado'
    sol.supervisor_data = datetime.now(timezone.utc)
    db.session.commit()
    flash(f'Solicitação #{sol.id} aprovada.', 'success')
    return redirect(url_for('painel_supervisor'))


@app.route('/supervisor/recusar/<int:sol_id>', methods=['POST'])
@login_required
@perfil_requerido('supervisor_administrativo')
def supervisor_recusar(sol_id):
    sol = db.session.get(Solicitacao, sol_id)
    justificativa = request.form.get('justificativa', '').strip()
    if not sol or sol.status != 'encaminhado_supervisor' or sol.supervisor_id != current_user.id or not justificativa:
        flash('Solicitação ou justificativa inválida.', 'danger')
        return redirect(url_for('painel_supervisor'))
    sol.status = 'recusado_supervisor'
    sol.supervisor_parecer = justificativa
    sol.supervisor_data = datetime.now(timezone.utc)
    db.session.commit()
    flash(f'Solicitação #{sol.id} recusada.', 'info')
    return redirect(url_for('painel_supervisor'))


@app.route('/dp/aprovar/<int:sol_id>', methods=['POST'])
@login_required
@perfil_requerido('dp')
def dp_aprovar(sol_id):
    sol = db.session.get(Solicitacao, sol_id)
    if not sol or sol.status not in ('aprovado_gestor', 'aprovado_supervisor'):
        flash('Solicitação não encontrada ou não está pronta para aprovação do DP.', 'warning')
        return redirect(url_for('painel_dp'))

    sol.status = 'aprovado_dp'
    sol.dp_id = current_user.id
    sol.dp_parecer = 'Ajuste realizado'
    sol.dp_data = datetime.now(timezone.utc)
    db.session.commit()

    flash(f'Solicitação #{sol.id} finalizada com sucesso.', 'success')
    return redirect(url_for('painel_dp'))


@app.route('/dp/recusar/<int:sol_id>', methods=['POST'])
@login_required
@perfil_requerido('dp')
def dp_recusar(sol_id):
    sol = db.session.get(Solicitacao, sol_id)
    if not sol or sol.status not in ('aprovado_gestor', 'aprovado_supervisor'):
        flash('Solicitação não encontrada ou não está pronta para análise do DP.', 'warning')
        return redirect(url_for('painel_dp'))

    justificativa = request.form.get('justificativa', '').strip()
    if not justificativa and not permissao_avancada('dp_recusar_sem_parecer'):
        flash('Informe o motivo da recusa.', 'danger')
        return redirect(url_for('painel_dp'))

    sol.status = 'recusado_dp'
    sol.dp_id = current_user.id
    sol.dp_parecer = justificativa or 'Recusado sem justificativa detalhada'
    sol.dp_data = datetime.now(timezone.utc)
    db.session.commit()

    flash(f'Solicitação #{sol.id} recusada pelo DP.', 'info')
    return redirect(url_for('painel_dp'))


# ──────────────────────────────────────────────
# Rota para visualizar comprovante
# ──────────────────────────────────────────────

@app.route('/uploads/<int:sol_id>')
@login_required
def uploaded_file(sol_id):
    sol = db.session.get(Solicitacao, sol_id)
    if not sol or not sol.comprovante:
        abort(404)
    if current_user.perfil == 'ti' or sol.colaborador_id == current_user.id:
        autorizado = True
    elif current_user.perfil == 'gestor':
        colaborador = db.session.get(Usuario, sol.colaborador_id)
        autorizado = colaborador is not None and colaborador.gestor_id == current_user.id
    elif current_user.perfil == 'supervisor_administrativo':
        autorizado = sol.supervisor_id == current_user.id
    else:
        autorizado = current_user.perfil == 'dp'
    if not autorizado:
        abort(404)
    response = send_from_directory(app.config['UPLOAD_FOLDER'], sol.comprovante)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Content-Disposition'] = 'inline'
    return response


# ──────────────────────────────────────────────
# API — contagem para badges (opcional)
# ──────────────────────────────────────────────

@app.route('/api/contagens')
@login_required
def api_contagens():
    if current_user.perfil == 'gestor':
        pendentes = (Solicitacao.query
                     .join(Usuario, Solicitacao.colaborador_id == Usuario.id)
                     .filter(Usuario.gestor_id == current_user.id)
                     .filter(Solicitacao.status == 'pendente')
                     .count())
        return jsonify({'pendentes': pendentes})

    elif current_user.perfil == 'dp':
        pendentes = Solicitacao.query.filter(Solicitacao.status.in_(['aprovado_gestor', 'aprovado_supervisor', 'recusado_supervisor'])).count()
        return jsonify({'pendentes': pendentes})

    elif current_user.perfil == 'supervisor_administrativo':
        pendentes = Solicitacao.query.filter_by(status='encaminhado_supervisor', supervisor_id=current_user.id).count()
        return jsonify({'pendentes': pendentes})

    return jsonify({'pendentes': 0})


# ──────────────────────────────────────────────
# Inicialização
# ──────────────────────────────────────────────

with app.app_context():
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    db.create_all()
    # Atualiza bases existentes; create_all não adiciona colunas novas.
    if db.engine.dialect.name == 'postgresql':
        db.session.execute(db.text(
            'ALTER TABLE usuarios ALTER COLUMN perfil TYPE VARCHAR(40)'
        ))
        for coluna, tipo in (
            ('supervisor_id', 'INTEGER'),
            ('supervisor_parecer', 'TEXT'),
            ('supervisor_data', 'TIMESTAMP'),
        ):
            db.session.execute(db.text(
                f'ALTER TABLE solicitacoes ADD COLUMN IF NOT EXISTS {coluna} {tipo}'
            ))
        db.session.commit()
    if os.environ.get('SEED_ADMIN_ON_START', '').lower() == 'true':
        senha = os.environ.get('ADMIN_INITIAL_PASSWORD')
        if senha:
            admin = Usuario.query.filter_by(matricula='TI001').first()
            if admin:
                admin.ativo = True
                admin.perfil = 'ti'
                admin.senha_hash = generate_password_hash(senha)
            else:
                db.session.add(Usuario(
                    matricula='TI001', nome='Administrador TI',
                    email='ti@empresa.local', perfil='ti',
                    senha_hash=generate_password_hash(senha),
                ))
            db.session.commit()


if __name__ == '__main__':
    app.run(
        host=os.environ.get('FLASK_HOST', '127.0.0.1'),
        port=int(os.environ.get('FLASK_PORT', '5000')),
        debug=os.environ.get('FLASK_DEBUG', '').lower() == 'true',
    )
