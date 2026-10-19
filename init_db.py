"""
Script para inicializar o banco de dados com usuários de demonstração.
Execute uma vez: python init_db.py
"""

from app import app, db
from models import (Usuario, Colaborador, TipoJustificativa, TipoOcorrencia,
                    Solicitacao, solicitacao_colaboradores, Area, Empresa)
import sqlite3
import os
from werkzeug.security import generate_password_hash


def criar_usuario_ti():
    senha = os.environ.get('ADMIN_INITIAL_PASSWORD')
    if not senha:
        raise RuntimeError('Defina ADMIN_INITIAL_PASSWORD antes de inicializar o banco.')
    ti = Usuario.query.filter_by(matricula='TI001').first()
    if ti:
        ti.senha_hash = generate_password_hash(senha)
        ti.ativo = True
    else:
        db.session.add(Usuario(
            matricula='TI001', nome='Administrador TI',
            email='ti@empresa.local', perfil='ti',
            senha_hash=generate_password_hash(senha),
        ))
    db.session.commit()



# Senha inicial vem exclusivamente da variável ADMIN_INITIAL_PASSWORD.


def criar_dados_iniciais():
    with app.app_context():
        db.create_all()
        # Migração idempotente para bases anteriores ao cadastro de áreas.
        colunas_usuario = {coluna['name'] for coluna in db.session.execute(db.text('PRAGMA table_info(usuarios)')).mappings()}
        if 'area_id' not in colunas_usuario:
            db.session.execute(db.text('ALTER TABLE usuarios ADD COLUMN area_id INTEGER'))
            db.session.commit()
        if 'empresa_id' not in colunas_usuario:
            db.session.execute(db.text('ALTER TABLE usuarios ADD COLUMN empresa_id INTEGER'))
            db.session.commit()
        for nome_empresa in ('Maity - Agrícola', 'Maity - Bioenergia'):
            if not Empresa.query.filter_by(nome=nome_empresa).first():
                db.session.add(Empresa(nome=nome_empresa))
        ocorrencias_iniciais = ['Saída antecipada', 'Sem registro de entrada', 'Sem registro de saída', 'Sem registro de entrada/sem registro de saída', 'Horas extras', 'Outros']
        for nome_ocorrencia in ocorrencias_iniciais:
            if not TipoOcorrencia.query.filter_by(nome=nome_ocorrencia).first():
                db.session.add(TipoOcorrencia(nome=nome_ocorrencia))
        db.session.commit()
        if not Usuario.query.filter_by(matricula='TI001').first():
            criar_usuario_ti()
        # Compatibilidade com bancos SQLite criados antes da coluna separada.
        colunas = {coluna['name'] for coluna in db.session.execute(db.text('PRAGMA table_info(solicitacoes)')).mappings()}
        if 'tipo_justificativa' not in colunas:
            db.session.execute(db.text('ALTER TABLE solicitacoes ADD COLUMN tipo_justificativa VARCHAR(80)'))
            db.session.commit()
        # Colunas do fluxo opcional de aprovação pelo supervisor administrativo.
        for nome_coluna, definicao in (
            ('supervisor_id', 'INTEGER'),
            ('supervisor_parecer', 'TEXT'),
            ('supervisor_data', 'DATETIME'),
        ):
            if nome_coluna not in colunas:
                db.session.execute(db.text(f'ALTER TABLE solicitacoes ADD COLUMN {nome_coluna} {definicao}'))
        db.session.commit()
        tipos_iniciais = ['Sem registro de entrada', 'Sem registro de saída', 'Atraso', 'Saída antecipada', 'Horas Extras', 'Horário excedido', 'Outros']
        for nome_tipo in tipos_iniciais:
            if not TipoJustificativa.query.filter_by(nome=nome_tipo).first():
                db.session.add(TipoJustificativa(nome=nome_tipo))
        db.session.commit()

        # Verificar se já existem usuários
        if Usuario.query.first():
            for usuario in Usuario.query.filter_by(perfil='analista').all():
                if not Colaborador.query.filter_by(matricula=usuario.matricula).first():
                    db.session.add(Colaborador(nome=usuario.nome, matricula=usuario.matricula))
            db.session.commit()
            print('⚠  Banco já possui dados. Cadastros novos sincronizados.')
            return

        # ── Gestor ──
        gestor = Usuario(
            matricula='G001',
            nome='Carlos Mendes',
            email='carlos.mendes@empresa.com',
            senha_hash=generate_password_hash('123456'),
            perfil='gestor',
        )
        db.session.add(gestor)
        db.session.flush()  # obter o ID do gestor

        # ── Analistas (subordinados ao gestor) ──
        analistas = [
            Usuario(
                matricula='A001',
                nome='Ana Silva',
                email='ana.silva@empresa.com',
                senha_hash=generate_password_hash('123456'),
                perfil='analista',
                gestor_id=gestor.id,
            ),
            Usuario(
                matricula='A002',
                nome='Bruno Costa',
                email='bruno.costa@empresa.com',
                senha_hash=generate_password_hash('123456'),
                perfil='analista',
                gestor_id=gestor.id,
            ),
            Usuario(
                matricula='A003',
                nome='Daniela Rocha',
                email='daniela.rocha@empresa.com',
                senha_hash=generate_password_hash('123456'),
                perfil='analista',
                gestor_id=gestor.id,
            ),
        ]
        db.session.add_all(analistas)

        # ── DP ──
        dp = Usuario(
            matricula='DP01',
            nome='Fernanda Lima',
            email='fernanda.lima@empresa.com',
            senha_hash=generate_password_hash('123456'),
            perfil='dp',
        )
        db.session.add(dp)
        db.session.flush()

        # Colaboradores selecionáveis no formulário de justificativa.
        for analista in analistas:
            colaborador = Colaborador.query.filter_by(matricula=analista.matricula).first()
            if not colaborador:
                colaborador = Colaborador(nome=analista.nome, matricula=analista.matricula)
                db.session.add(colaborador)
            db.session.flush()

        db.session.commit()
        print('✅ Dados iniciais criados com sucesso!')
        print()
        print('╔══════════════════════════════════════════════════════╗')
        print('║          USUÁRIOS DE DEMONSTRAÇÃO                   ║')
        print('╠══════════════════════════════════════════════════════╣')
        print('║  Perfil     │ Matrícula │ Nome              │ Senha ║')
        print('╠═════════════╪═══════════╪═══════════════════╪═══════╣')
        print('║  Analista   │ A001      │ Ana Silva         │123456 ║')
        print('║  Analista   │ A002      │ Bruno Costa       │123456 ║')
        print('║  Analista   │ A003      │ Daniela Rocha     │123456 ║')
        print('║  Gestor     │ G001      │ Carlos Mendes     │123456 ║')
        print('║  DP         │ DP01      │ Fernanda Lima     │123456 ║')
        print('╚══════════════════════════════════════════════════════╝')


if __name__ == '__main__':
    criar_dados_iniciais()
