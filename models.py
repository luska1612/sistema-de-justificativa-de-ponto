"""Modelos do Banco de Dados — Sistema de Justificativas de Ponto."""

from datetime import datetime, timezone
from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy


db = SQLAlchemy()

area_empresas = db.Table(
    'area_empresas',
    db.Column('area_id', db.Integer, db.ForeignKey('areas.id'), primary_key=True),
    db.Column('empresa_id', db.Integer, db.ForeignKey('empresas.id'), primary_key=True),
)

solicitacao_colaboradores = db.Table(
    'solicitacao_colaboradores',
    db.Column('solicitacao_id', db.Integer, db.ForeignKey('solicitacoes.id'), primary_key=True),
    db.Column('colaborador_id', db.Integer, db.ForeignKey('colaboradores.id'), primary_key=True),
)


class Empresa(db.Model):
    __tablename__ = 'empresas'
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(120), unique=True, nullable=False)
    ativo = db.Column(db.Boolean, default=True, nullable=False)
    areas = db.relationship('Area', secondary='area_empresas', back_populates='empresas')


class TipoOcorrencia(db.Model):
    __tablename__ = 'tipos_ocorrencia'
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(80), unique=True, nullable=False)
    ativo = db.Column(db.Boolean, default=True, nullable=False)


class Area(db.Model):
    __tablename__ = 'areas'
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), unique=True, nullable=False)
    ativo = db.Column(db.Boolean, default=True, nullable=False)
    empresas = db.relationship('Empresa', secondary='area_empresas', back_populates='areas')


class Usuario(UserMixin, db.Model):
    __tablename__ = 'usuarios'
    id = db.Column(db.Integer, primary_key=True)
    matricula = db.Column(db.String(20), unique=True, nullable=False)
    nome = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    senha_hash = db.Column(db.String(256), nullable=False)
    perfil = db.Column(db.String(40), nullable=False)
    gestor_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=True)
    area_id = db.Column(db.Integer, db.ForeignKey('areas.id'), nullable=True)
    empresa_id = db.Column(db.Integer, db.ForeignKey('empresas.id'), nullable=True)
    ativo = db.Column(db.Boolean, default=True)
    criado_em = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    gestor = db.relationship('Usuario', remote_side=[id], backref='subordinados')
    area = db.relationship('Area', backref='usuarios')
    empresa = db.relationship('Empresa', backref='usuarios')
    solicitacoes = db.relationship('Solicitacao', backref='colaborador',
                                   foreign_keys='Solicitacao.colaborador_id', lazy='dynamic')

    def tem_permissao(self, chave):
        if self.perfil == 'ti':
            return True
        return UsuarioPermissao.query.filter_by(usuario_id=self.id, permissao=chave).first() is not None


class Permissao(db.Model):
    __tablename__ = 'permissoes'
    id = db.Column(db.Integer, primary_key=True)
    chave = db.Column(db.String(80), unique=True, nullable=False)
    nome = db.Column(db.String(120), nullable=False)
    categoria = db.Column(db.String(40), nullable=False)
    ativo = db.Column(db.Boolean, default=True, nullable=False)


class UsuarioPermissao(db.Model):
    __tablename__ = 'usuario_permissoes'
    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)
    permissao = db.Column(db.String(80), nullable=False)
    __table_args__ = (db.UniqueConstraint('usuario_id', 'permissao'),)


# Mantém compatibilidade com a tabela existente durante a migração para Permissao.



class Colaborador(db.Model):
    __tablename__ = 'colaboradores'
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    matricula = db.Column(db.String(20), unique=True, nullable=False)
    ativo = db.Column(db.Boolean, default=True, nullable=False)
    criado_em = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


class TipoJustificativa(db.Model):
    __tablename__ = 'tipos_justificativa'
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(80), unique=True, nullable=False)
    ativo = db.Column(db.Boolean, default=True, nullable=False)
    criado_em = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


class SolicitacaoParticipante(db.Model):
    __tablename__ = 'solicitacao_participantes'
    id = db.Column(db.Integer, primary_key=True)
    solicitacao_id = db.Column(db.Integer, db.ForeignKey('solicitacoes.id'), nullable=False)
    nome = db.Column(db.String(100), nullable=False)
    matricula = db.Column(db.String(20), nullable=False)
    ordem = db.Column(db.Integer, nullable=False, default=0)
    criado_em = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


class Solicitacao(db.Model):
    __tablename__ = 'solicitacoes'
    id = db.Column(db.Integer, primary_key=True)
    # Usuário analista que abriu a solicitação; não é o colaborador justificado.
    colaborador_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)
    colaboradores = db.relationship('Colaborador', secondary=solicitacao_colaboradores,
                                    backref=db.backref('solicitacoes', lazy='dynamic'))
    participantes = db.relationship('SolicitacaoParticipante', backref='solicitacao',
                                    cascade='all, delete-orphan', order_by='SolicitacaoParticipante.ordem')
    data_ocorrencia = db.Column(db.Date, nullable=False)
    tipo_ocorrencia = db.Column(db.String(80), nullable=False)
    tipo_justificativa = db.Column(db.String(80), nullable=True)
    horario_entrada = db.Column(db.String(5), nullable=True)
    horario_saida = db.Column(db.String(5), nullable=True)
    motivo = db.Column(db.Text, nullable=False)
    comprovante = db.Column(db.Text, nullable=True)  # JSON com nomes dos anexos
    status = db.Column(db.String(30), default='pendente')
    gestor_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=True)
    gestor_parecer = db.Column(db.Text, nullable=True)
    gestor_data = db.Column(db.DateTime, nullable=True)
    dp_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=True)
    dp_parecer = db.Column(db.Text, nullable=True)
    dp_data = db.Column(db.DateTime, nullable=True)
    supervisor_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=True)
    supervisor_parecer = db.Column(db.Text, nullable=True)
    supervisor_data = db.Column(db.DateTime, nullable=True)
    criado_em = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    atualizado_em = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc),
                               onupdate=lambda: datetime.now(timezone.utc))
    gestor_resp = db.relationship('Usuario', foreign_keys=[gestor_id])
    dp_resp = db.relationship('Usuario', foreign_keys=[dp_id])
    supervisor_resp = db.relationship('Usuario', foreign_keys=[supervisor_id])

    @property
    def colaboradores_exibicao(self):
        if self.participantes:
            return self.participantes
        return self.colaboradores or ([self.colaborador] if self.colaborador else [])

    STATUS_LABELS = {
        'pendente': 'Pendente',
        'aprovado_gestor': 'Aprovado pelo Gestor',
        'recusado_gestor': 'Recusado pelo Gestor',
        'encaminhado_supervisor': 'Aguardando supervisor administrativo',
        'aprovado_supervisor': 'Aprovado pelo supervisor',
        'recusado_supervisor': 'Recusado pelo supervisor',
        'aprovado_dp': 'Concluído',
        'recusado_dp': 'Recusado pelo DP',
    }
    STATUS_COLORS = {
        'pendente': 'warning',
        'aprovado_gestor': 'info',
        'recusado_gestor': 'danger',
        'encaminhado_supervisor': 'warning',
        'aprovado_supervisor': 'info',
        'recusado_supervisor': 'danger',
        'aprovado_dp': 'success',
        'recusado_dp': 'danger',
    }

    @property
    def status_label(self):
        return self.STATUS_LABELS.get(self.status, self.status)

    @property
    def status_cor(self):
        return self.STATUS_COLORS.get(self.status, 'secondary')
