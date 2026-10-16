"""
Sistema Web de Justificativas de Ponto — Backend Flask
"""

import os
import re
import uuid
import unicodedata
from datetime import datetime, timezone
from functools import wraps

from flask import (
    Flask, render_template, request, redirect, url_for,
    flash, jsonify, send_from_directory, session
)
from flask_login import (
    LoginManager, login_user, logout_user,
    login_required, current_user
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

from models import (db, Usuario, Solicitacao, Colaborador, TipoJustificativa,
                    SolicitacaoParticipante, Area, Empresa, TipoOcorrencia)

# ──────────────────────────────────────────────
# Configuração
# ──────────────────────────────────────────────

app = Flask(__name__)
app.config['SECRET_KEY'] = 'chave-secreta-ponto-2026'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///ponto.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = os.path.join(app.root_path, 'static', 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024  # 10 MB

EXTENSOES_PERMITIDAS = {'pdf', 'png', 'jpg', 'jpeg'}
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


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(Usuario, int(user_id))


@app.context_processor
def inject_now():
    """Disponibiliza now() nos templates para o ano do footer."""
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


def perfil_requerido(*perfis):
    """Decorator para restringir acesso por perfil."""
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if current_user.perfil not in perfis:
                flash('Acesso não autorizado.', 'danger')
                return redirect(url_for('dashboard'))
            return f(*args, **kwargs)
        return wrapper
    return decorator


def carregar_cadastros():
    return (Colaborador.query.filter_by(ativo=True).order_by(Colaborador.nome).all(),
            TipoJustificativa.query.filter_by(ativo=True).order_by(TipoJustificativa.nome).all(),
            TipoOcorrencia.query.filter_by(ativo=True).order_by(TipoOcorrencia.nome).all())


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


@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Sessão encerrada com sucesso.', 'info')
    return redirect(url_for('login'))


# ──────────────────────────────────────────────
# Dashboard — redireciona por perfil
# ──────────────────────────────────────────────

@app.route('/dashboard')
@login_required
def dashboard():
    if current_user.perfil == 'ti':
        return redirect(url_for('painel_admin'))
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
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return wrapper


@app.route('/admin')
@ti_requerido
def painel_admin():
    minhas_solicitacoes = (Solicitacao.query.filter_by(colaborador_id=current_user.id)
                           .order_by(Solicitacao.criado_em.desc()).all())
    return render_template('admin.html', minhas_solicitacoes=minhas_solicitacoes,
                           usuarios=Usuario.query.order_by(Usuario.nome).all(),
                           areas=Area.query.order_by(Area.nome).all(),
                           gestores=Usuario.query.filter_by(perfil='gestor', ativo=True).order_by(Usuario.nome).all(),
                           empresas=Empresa.query.order_by(Empresa.nome).all())


def dados_usuario_validos(form, senha_obrigatoria=True):
    nome = ' '.join(form.get('nome', '').split())
    matricula = form.get('matricula', '').strip()
    email = form.get('email', '').strip().lower()
    perfil = form.get('perfil', '').strip().lower()
    senha = form.get('senha', '')
    perfis = {'analista', 'gestor', 'dp', 'ti'}
    if not nome or not matricula or not email or perfil not in perfis or (senha_obrigatoria and len(senha) < 8):
        return None
    return nome, matricula, email, perfil, senha


@app.route('/admin/usuarios', methods=['POST'])
@ti_requerido
def criar_usuario():
    dados = dados_usuario_validos(request.form)
    if not dados:
        flash('Preencha os dados corretamente. A senha deve ter pelo menos 8 caracteres.', 'danger')
        return redirect(url_for('painel_admin'))
    nome, matricula, email, perfil, senha = dados
    if Usuario.query.filter((Usuario.matricula == matricula) | (Usuario.email == email)).first():
        flash('Matrícula ou e-mail já cadastrado.', 'danger')
        return redirect(url_for('painel_admin'))
    db.session.add(Usuario(nome=nome, matricula=matricula, email=email,
                           perfil=perfil, senha_hash=generate_password_hash(senha)))
    db.session.commit()
    flash('Usuário criado.', 'success')
    return redirect(url_for('painel_admin'))


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


# ──────────────────────────────────────────────
# PAINEL DO ANALISTA
# ──────────────────────────────────────────────

PERFIS_SOLICITANTES = ('analista', 'gestor', 'dp', 'ti')


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

    # Upload de comprovante
    comprovante_nome = None
    arquivo = request.files.get('comprovante')
    if arquivo and arquivo.filename:
        if extensao_permitida(arquivo.filename):
            nome_seguro = secure_filename(arquivo.filename)
            nome_unico = f"{uuid.uuid4().hex}_{nome_seguro}"
            os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
            arquivo.save(os.path.join(app.config['UPLOAD_FOLDER'], nome_unico))
            comprovante_nome = nome_unico
        else:
            flash('Formato de arquivo não permitido. Use PDF, PNG ou JPG.', 'danger')
            return redirect(url_for('dashboard'))

    solicitacao = Solicitacao(
        colaborador_id=current_user.id,
        data_ocorrencia=data_ocorrencia,
        tipo_ocorrencia=tipo,
        tipo_justificativa=tipo_justificativa,
        horario_entrada=entrada or None,
        horario_saida=saida or None,
        motivo=motivo,
        comprovante=comprovante_nome,
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
    arquivo = request.files.get('comprovante')
    if arquivo and arquivo.filename:
        if not extensao_permitida(arquivo.filename):
            flash('Formato de arquivo não permitido. Use PDF, PNG ou JPG.', 'danger')
            return redirect(url_for('editar_solicitacao', sol_id=sol_id))
        nome_seguro = secure_filename(arquivo.filename)
        comprovante = f"{uuid.uuid4().hex}_{nome_seguro}"
        os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
        arquivo.save(os.path.join(app.config['UPLOAD_FOLDER'], comprovante))
        solicitacao.comprovante = comprovante
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

    return render_template('gestor.html', pendentes=pendentes, historico=historico,
                           minhas_solicitacoes=minhas_solicitacoes,
                           colaboradores=Colaborador.query.order_by(Colaborador.nome).all(),
                           tipos=TipoJustificativa.query.order_by(TipoJustificativa.nome).all(),
                           tipos_ocorrencia=TIPOS_OCORRENCIA)


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
    if not justificativa:
        flash('Informe o motivo da recusa.', 'danger')
        return redirect(url_for('painel_gestor'))

    sol.status = 'recusado_gestor'
    sol.gestor_id = current_user.id
    sol.gestor_parecer = justificativa
    sol.gestor_data = datetime.now(timezone.utc)
    db.session.commit()

    flash(f'Solicitação #{sol.id} recusada.', 'info')
    return redirect(url_for('painel_gestor'))


# ──────────────────────────────────────────────
# PAINEL DO DP
# ──────────────────────────────────────────────

@app.route('/dp')
@login_required
@perfil_requerido('dp')
def painel_dp():
    minhas_solicitacoes = (Solicitacao.query.filter_by(colaborador_id=current_user.id)
                           .order_by(Solicitacao.criado_em.desc()).all())
    filtro_status = request.args.get('status', 'aprovado_gestor')
    filtro_data = request.args.get('data', '')
    filtro_colaborador = request.args.get('colaborador', '')

    query = Solicitacao.query.join(Usuario, Solicitacao.colaborador_id == Usuario.id)

    if filtro_status == 'aprovado_gestor':
        query = query.filter(Solicitacao.status == 'aprovado_gestor')
    elif filtro_status == 'todos':
        pass  # sem filtro
    else:
        query = query.filter(Solicitacao.status == filtro_status)

    if filtro_data:
        try:
            data_filtro = datetime.strptime(filtro_data, '%Y-%m-%d').date()
            query = query.filter(Solicitacao.data_ocorrencia == data_filtro)
        except ValueError:
            pass

    if filtro_colaborador:
        query = query.filter(Usuario.nome.ilike(f'%{filtro_colaborador}%'))

    solicitacoes = query.order_by(Solicitacao.criado_em.desc()).all()

    return render_template('dp.html', solicitacoes=solicitacoes,
                           minhas_solicitacoes=minhas_solicitacoes,
                           filtro_status=filtro_status,
                           filtro_data=filtro_data,
                           filtro_colaborador=filtro_colaborador,
                           colaboradores=Colaborador.query.order_by(Colaborador.nome).all(),
                           tipos=TipoJustificativa.query.order_by(TipoJustificativa.nome).all(),
                           tipos_ocorrencia=TipoOcorrencia.query.order_by(TipoOcorrencia.nome).all())


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
    return redirect(url_for('painel_dp'))


@app.route('/cadastros/colaborador/<int:colaborador_id>/alternar', methods=['POST'])
@login_required
@perfil_requerido('gestor', 'dp')
def alternar_colaborador(colaborador_id):
    colaborador = db.session.get(Colaborador, colaborador_id)
    if colaborador:
        colaborador.ativo = not colaborador.ativo
        db.session.commit()
    return redirect(url_for('painel_dp'))


@app.route('/cadastros/tipo', methods=['POST'])
@login_required
@perfil_requerido('dp')
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
    return redirect(url_for('painel_dp'))


@app.route('/cadastros/ocorrencia', methods=['POST'])
@login_required
@perfil_requerido('dp')
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
    return redirect(url_for('painel_dp'))


@app.route('/cadastros/ocorrencia/<int:tipo_id>/alternar', methods=['POST'])
@login_required
@perfil_requerido('dp')
def alternar_ocorrencia(tipo_id):
    tipo = db.session.get(TipoOcorrencia, tipo_id)
    if tipo:
        tipo.ativo = not tipo.ativo
        db.session.commit()
    return redirect(url_for('painel_dp'))


@app.route('/cadastros/tipo/<int:tipo_id>/alternar', methods=['POST'])
@login_required
@perfil_requerido('dp')
def alternar_tipo(tipo_id):
    tipo = db.session.get(TipoJustificativa, tipo_id)
    if tipo:
        tipo.ativo = not tipo.ativo
        db.session.commit()
    return redirect(url_for('painel_dp'))


@app.route('/dp/aprovar/<int:sol_id>', methods=['POST'])
@login_required
@perfil_requerido('dp')
def dp_aprovar(sol_id):
    sol = db.session.get(Solicitacao, sol_id)
    if not sol or sol.status != 'aprovado_gestor':
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
    if not sol or sol.status != 'aprovado_gestor':
        flash('Solicitação não encontrada ou não está pronta para análise do DP.', 'warning')
        return redirect(url_for('painel_dp'))

    justificativa = request.form.get('justificativa', '').strip()
    if not justificativa:
        flash('Informe o motivo da recusa.', 'danger')
        return redirect(url_for('painel_dp'))

    sol.status = 'recusado_dp'
    sol.dp_id = current_user.id
    sol.dp_parecer = justificativa
    sol.dp_data = datetime.now(timezone.utc)
    db.session.commit()

    flash(f'Solicitação #{sol.id} recusada pelo DP.', 'info')
    return redirect(url_for('painel_dp'))


# ──────────────────────────────────────────────
# Rota para visualizar comprovante
# ──────────────────────────────────────────────

@app.route('/uploads/<filename>')
@login_required
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)


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
        pendentes = Solicitacao.query.filter_by(status='aprovado_gestor').count()
        return jsonify({'pendentes': pendentes})

    return jsonify({'pendentes': 0})


# ──────────────────────────────────────────────
# Inicialização
# ──────────────────────────────────────────────

with app.app_context():
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    db.create_all()


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
