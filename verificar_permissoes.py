"""Verificação do comportamento das permissões avançadas.

Roda contra um SQLite temporário.

Importante: cada requisição precisa do seu próprio app context. Manter um
`app_context()` externo aberto faz o Flask-Login reutilizar o usuário já
resolvido em `g._login_user`, e a segunda requisição "vê" o usuário errado —
isso é um artefato do harness de teste, não do aplicativo (em produção cada
requisição tem o próprio contexto).

Executar: .\\venv\\Scripts\\python.exe verificar_permissoes.py
"""
import os
import sqlite3
import sys
import tempfile

os.environ.setdefault('SECRET_KEY', 'teste-local-chave-longa')
_DB = os.path.join(tempfile.gettempdir(), 'ponto-verificacao-perm.db')
if os.path.exists(_DB):
    os.remove(_DB)
os.environ['DATABASE_URL'] = 'sqlite:///' + _DB.replace('\\', '/')

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import app as appmod  # noqa: E402
from models import Usuario, UsuarioPermissao, Solicitacao, db, Area  # noqa: E402
from werkzeug.security import generate_password_hash  # noqa: E402

app = appmod.app
app.config['TESTING'] = True
app.config['WTF_CSRF_ENABLED'] = False

ERROS = []
IDS = {}


def ok(nome, cond, extra=''):
    print(('  [OK]   ' if cond else '  [ERRO] ') + nome + (f'   -> {extra}' if extra and not cond else ''))
    if not cond:
        ERROS.append(nome)


def sql(query, params=()):
    """Lê o banco por uma conexão nova — sem o cache de sessão do SQLAlchemy."""
    con = sqlite3.connect(_DB)
    try:
        return con.execute(query, params).fetchall()
    finally:
        con.close()


def status_de(sol_id):
    return sql('SELECT status FROM solicitacoes WHERE id=?', (sol_id,))[0][0]


def perms_de(usuario_id):
    return {r[0] for r in sql(
        'SELECT permissao FROM usuario_permissoes WHERE usuario_id=?', (usuario_id,))}


def nova_solicitacao(analista_id, gestor_id, status='pendente'):
    """Cria uma solicitação em seu próprio app context."""
    with app.app_context():
        s = Solicitacao(
            colaborador_id=analista_id,
            data_ocorrencia=appmod.datetime.now().date(),
            tipo_ocorrencia='Outros', motivo='Motivo de teste', status=status,
            gestor_id=gestor_id if status != 'pendente' else None)
        db.session.add(s)
        db.session.commit()
        return s.id


def conceder(usuario_id, permissao):
    """Concede uma permissão em seu próprio app context (idempotente)."""
    with app.app_context():
        existente = UsuarioPermissao.query.filter_by(
            usuario_id=usuario_id, permissao=permissao).first()
        if not existente:
            db.session.add(UsuarioPermissao(usuario_id=usuario_id, permissao=permissao))
            db.session.commit()


def revogar(usuario_id, permissao):
    """Remove uma permissão em seu próprio app context (idempotente)."""
    with app.app_context():
        UsuarioPermissao.query.filter_by(
            usuario_id=usuario_id, permissao=permissao).delete()
        db.session.commit()


def login(cliente, usuario_id):
    with cliente.session_transaction() as s:
        s['_user_id'] = str(usuario_id)
        s['_fresh'] = True


def main():
    # ─── Cria os usuários ───
    with app.app_context():
        db.create_all()
        area = Area(nome='Area Teste')
        db.session.add(area)
        db.session.commit()

        def novo(nome, perfil, email, matricula):
            u = Usuario(nome=nome, matricula=matricula, email=email, perfil=perfil,
                        senha_hash=generate_password_hash('senha12345'),
                        area_id=area.id, ativo=True)
            db.session.add(u)
            db.session.commit()
            IDS[perfil] = u.id
            return u

        novo('TI', 'ti', 'ti@t.local', '900')
        novo('Supervisor', 'supervisor_administrativo', 'sup@t.local', '901')
        novo('Gestor', 'gestor', 'gestor@t.local', '902')
        novo('DP', 'dp', 'dp@t.local', '903')
        novo('Analista', 'analista', 'ana@t.local', '904')
        # vincula o analista ao gestor
        u = db.session.get(Usuario, IDS['analista'])
        u.gestor_id = IDS['gestor']
        db.session.commit()

    ti_id, sup_id = IDS['ti'], IDS['supervisor_administrativo']
    gestor_id, dp_id = IDS['gestor'], IDS['dp']
    analista_id = IDS['analista']

    def cliente_para(usuario_id):
        c = app.test_client()
        login(c, usuario_id)
        return c

    print('\n== 1. Painel do gestor SEM permissao avançada ==')
    s1 = nova_solicitacao(analista_id, gestor_id, 'pendente')
    gc = cliente_para(gestor_id)
    html = gc.get('/gestor').get_data(as_text=True)
    ok('Painel do gestor carrega', 'Motivo de teste' in html)
    ok('Botao Encaminhar ausente', 'gestor/encaminhar' not in html)

    print('\n== 2. TI concede permissões na tela unificada ==')
    tc = cliente_para(ti_id)
    r = tc.get(f'/admin/permissoes/{gestor_id}')
    ok('Tela unificada retorna 200', r.status_code == 200, str(r.status_code))
    html = r.get_data(as_text=True)
    ok('Formulário único (uma tag form)', html.count('<form method="POST">') == 1,
       str(html.count('<form method="POST">')))
    ok('Acessos gerais presentes (12)',
       html.count('name="permissoes" ') == 12, str(html.count('name="permissoes" ')))
    ok('Ações avançadas presentes (4)',
       html.count('name="permissoes_avancadas"') == 4,
       str(html.count('name="permissoes_avancadas"')))
    ok('CSRF presente', 'csrf_token' in html)

    # Salva base e avançadas no mesmo POST
    r = tc.post(f'/admin/permissoes/{gestor_id}',
                data={'permissoes': ['view_organograma', 'export_reports'],
                      'permissoes_avancadas': ['gestor_encaminhar_supervisor',
                                               'gestor_recusar_sem_parecer']},
                follow_redirects=True)
    ok('POST unificado retorna 200', r.status_code == 200, str(r.status_code))
    salvo = perms_de(gestor_id)
    ok('Acesso geral salvo', 'view_organograma' in salvo, str(salvo))
    ok('Permissão avançada salva', 'gestor_encaminhar_supervisor' in salvo, str(salvo))
    ok('Ambas as listas no mesmo POST',
       'export_reports' in salvo and 'gestor_recusar_sem_parecer' in salvo, str(salvo))

    print('\n== 3. Painel do gestor COM a permissão ==')
    html = gc.get('/gestor').get_data(as_text=True)
    ok('Botao Encaminhar aparece', 'gestor/encaminhar' in html)
    ok('Modal renderizado', 'encaminharModal' in html)
    ok('Select de supervisores presente', 'name="supervisor_id"' in html)

    print('\n== 4. Gestor encaminha ao supervisor ==')
    r = gc.post(f'/gestor/encaminhar/{s1}', data={'supervisor_id': sup_id},
                follow_redirects=True)
    ok('Status virou encaminhado_supervisor',
       status_de(s1) == 'encaminhado_supervisor', status_de(s1))
    linha = sql('SELECT supervisor_id, gestor_parecer FROM solicitacoes WHERE id=?', (s1,))[0]
    ok('Supervisor vinculado', linha[0] == sup_id, str(linha[0]))
    ok('Parecer do gestor registrado', 'Encaminhado' in (linha[1] or ''), str(linha[1]))

    print('\n== 5. Supervisor recebe e devolve ao DP ==')
    sc = cliente_para(sup_id)
    html = sc.get('/supervisor-administrativo').get_data(as_text=True)
    ok('Supervisor ve a solicitação', 'Motivo de teste' in html)
    ok('Botao Devolver ausente sem permissao', 'supervisor/devolver' not in html)

    conceder(sup_id, 'supervisor_encaminhar_dp')
    html = sc.get('/supervisor-administrativo').get_data(as_text=True)
    ok('Botao Devolver aparece com permissao', 'supervisor/devolver' in html)
    r = sc.post(f'/supervisor/devolver/{s1}', data={}, follow_redirects=True)
    ok('Solicitacao devolvida ao DP', status_de(s1) == 'aprovado_gestor', status_de(s1))

    print('\n== 6. DP: encaminhar e recusar sem parecer ==')
    dc = cliente_para(dp_id)
    # Garante que o DP começa sem as permissões avançadas desta seção.
    revogar(dp_id, 'dp_encaminhar_supervisor')
    revogar(dp_id, 'dp_recusar_sem_parecer')
    html = dc.get('/dp').get_data(as_text=True)
    ok('Botao Encaminhar do DP ausente', 'dpEncaminhar' not in html)
    s2 = nova_solicitacao(analista_id, gestor_id, 'aprovado_gestor')
    r = dc.post(f'/dp/encaminhar/{s2}', data={'supervisor_id': sup_id},
                follow_redirects=True)
    ok('Encaminhamento do DP bloqueado sem permissao',
       status_de(s2) == 'aprovado_gestor', status_de(s2))

    conceder(dp_id, 'dp_encaminhar_supervisor')
    html = dc.get('/dp').get_data(as_text=True)
    ok('Botao Encaminhar do DP aparece', 'dpEncaminhar' in html)
    r = dc.post(f'/dp/encaminhar/{s2}', data={'supervisor_id': sup_id},
                follow_redirects=True)
    ok('DP encaminhou ao supervisor',
       status_de(s2) == 'encaminhado_supervisor', status_de(s2))

    s3 = nova_solicitacao(analista_id, gestor_id, 'aprovado_gestor')
    r = dc.post(f'/dp/recusar/{s3}', data={'justificativa': ''}, follow_redirects=True)
    ok('Recusa do DP sem justificativa bloqueada sem permissao',
       status_de(s3) == 'aprovado_gestor', status_de(s3))

    conceder(dp_id, 'dp_recusar_sem_parecer')
    r = dc.post(f'/dp/recusar/{s3}', data={'justificativa': ''}, follow_redirects=True)
    ok('Recusa do DP sem justificativa aceita com permissao',
       status_de(s3) == 'recusado_dp', status_de(s3))

    print('\n== 7. Gestor: recusar sem parecer ==')
    # A seção 2 concedeu essa permissão via POST unificado — revoga para
    # testar o cenário "sem a permissão" e depois concede de novo.
    revogar(gestor_id, 'gestor_recusar_sem_parecer')
    s4 = nova_solicitacao(analista_id, gestor_id, 'pendente')
    r = gc.post(f'/gestor/recusar/{s4}', data={'justificativa': ''}, follow_redirects=True)
    ok('Recusa sem justificativa bloqueada sem permissao',
       status_de(s4) == 'pendente', status_de(s4))
    conceder(gestor_id, 'gestor_recusar_sem_parecer')
    r = gc.post(f'/gestor/recusar/{s4}', data={'justificativa': ''}, follow_redirects=True)
    ok('Recusa sem justificativa aceita com permissao',
       status_de(s4) == 'recusado_gestor', status_de(s4))

    print('\n== 8. Fluxos originais continuam funcionando ==')
    s5 = nova_solicitacao(analista_id, gestor_id, 'pendente')
    r = gc.post(f'/gestor/aprovar/{s5}', data={}, follow_redirects=True)
    ok('Gestor aprova normalmente', status_de(s5) == 'aprovado_gestor', status_de(s5))
    s6 = nova_solicitacao(analista_id, gestor_id, 'aprovado_gestor')
    r = dc.post(f'/dp/aprovar/{s6}', data={}, follow_redirects=True)
    ok('DP aprova normalmente', status_de(s6) == 'aprovado_dp', status_de(s6))
    s7 = nova_solicitacao(analista_id, gestor_id, 'pendente')
    r = gc.post(f'/gestor/recusar/{s7}', data={'justificativa': 'motivo'}, follow_redirects=True)
    ok('Gestor recusa com justificativa normalmente',
       status_de(s7) == 'recusado_gestor', status_de(s7))

    print('\n== 9. Isolamento de perfil ==')
    s8 = nova_solicitacao(analista_id, gestor_id, 'pendente')
    r = dc.post(f'/gestor/encaminhar/{s8}', data={'supervisor_id': sup_id},
                follow_redirects=True)
    ok('DP nao acessa rota de gestor', status_de(s8) == 'pendente', status_de(s8))
    s9 = nova_solicitacao(analista_id, gestor_id, 'aprovado_gestor')
    r = gc.post(f'/dp/aprovar/{s9}', data={}, follow_redirects=True)
    ok('Gestor nao acessa rota de DP', status_de(s9) == 'aprovado_gestor', status_de(s9))
    anon = app.test_client()
    r = anon.get('/gestor')
    ok('Anonimo nao acessa o painel do gestor',
       r.status_code in (301, 302, 303, 401, 403), str(r.status_code))
    anon2 = app.test_client()
    r = anon2.post('/gestor/encaminhar/1', data={}, follow_redirects=False)
    ok('Anonimo nao aciona rota de encaminhamento',
       r.status_code in (301, 302, 303, 401, 403), str(r.status_code))

    print('\n== 10. Permissoes de perfil incompativel sao ignoradas ==')
    tc.post(f'/admin/permissoes/{gestor_id}',
            data={'permissoes': [], 'permissoes_avancadas': ['dp_encaminhar_supervisor',
                                                            'permissao_inexistente']},
            follow_redirects=True)
    salvo = perms_de(gestor_id)
    ok('Permissao de DP recusada para gestor',
       'dp_encaminhar_supervisor' not in salvo, str(salvo))
    ok('Permissao inexistente recusada',
       'permissao_inexistente' not in salvo, str(salvo))

    print('\n== 11. Rota antiga de avancadas redireciona para a unificada ==')
    r = tc.get(f'/admin/permissoes-avancadas/{gestor_id}', follow_redirects=True)
    ok('Redireciona e renderiza a tela unificada', r.status_code == 200, str(r.status_code))
    ok('Chegou em /admin/permissoes/', r.request.path.endswith(f'/admin/permissoes/{gestor_id}'),
       r.request.path)
    html = r.get_data(as_text=True)
    ok('Tela unificada tem as duas seções',
       'name="permissoes" ' in html and 'name="permissoes_avancadas"' in html)

    print('\n== 12. Perfil sem acoes avancadas mostra aviso ==')
    r = tc.get(f'/admin/permissoes/{analista_id}')
    html = r.get_data(as_text=True)
    ok('Analista sem acoes avancadas', r.status_code == 200, str(r.status_code))
    ok('Mostra aviso de perfil incompativel',
       'Nenhuma ação avançada se aplica' in html)
    ok('Nenhum checkbox avancado para analista',
       'name="permissoes_avancadas"' not in html)
    ok('Acessos gerais seguem disponiveis',
       html.count('name="permissoes" ') == 12, str(html.count('name="permissoes" ')))

    print('\n' + '=' * 60)
    if ERROS:
        print(f'FALHOU: {len(ERROS)} verificacao(oes)')
        for e in ERROS:
            print('  -', e)
        return 1
    print('TODAS AS VERIFICACOES PASSARAM')
    return 0


if __name__ == '__main__':
    sys.exit(main())
