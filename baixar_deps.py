"""
Script para baixar dependências do frontend localmente.
Execute uma vez: python baixar_deps.py

Isso permite o sistema funcionar 100% na Intranet
sem depender de CDNs externos.
"""

import os
import urllib.request
import ssl

# Ignorar verificação SSL caso a rede tenha proxy/firewall
ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DOWNLOADS = [
    {
        'url': 'https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css',
        'dest': os.path.join(BASE_DIR, 'static', 'css', 'bootstrap.min.css'),
    },
    {
        'url': 'https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js',
        'dest': os.path.join(BASE_DIR, 'static', 'js', 'bootstrap.bundle.min.js'),
    },
    {
        'url': 'https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.min.css',
        'dest': os.path.join(BASE_DIR, 'static', 'css', 'bootstrap-icons.min.css'),
    },
    {
        'url': 'https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/fonts/bootstrap-icons.woff2',
        'dest': os.path.join(BASE_DIR, 'static', 'css', 'fonts', 'bootstrap-icons.woff2'),
    },
    {
        'url': 'https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/fonts/bootstrap-icons.woff',
        'dest': os.path.join(BASE_DIR, 'static', 'css', 'fonts', 'bootstrap-icons.woff'),
    },
]


def baixar():
    print('📦 Baixando dependências do frontend...\n')

    for item in DOWNLOADS:
        dest = item['dest']
        os.makedirs(os.path.dirname(dest), exist_ok=True)

        if os.path.exists(dest):
            print(f'  ✔ Já existe: {os.path.relpath(dest, BASE_DIR)}')
            continue

        try:
            print(f'  ⬇ Baixando: {os.path.basename(dest)}...', end=' ')
            with urllib.request.urlopen(item['url'], context=ctx) as response, open(dest, 'wb') as output:
                output.write(response.read())
            size = os.path.getsize(dest)
            print(f'OK ({size:,} bytes)')
        except Exception as e:
            print(f'ERRO: {e}')
            print(f'    → Baixe manualmente: {item["url"]}')
            print(f'    → Salve em: {dest}')

    print('\n✅ Concluído! O sistema agora funciona 100% offline na Intranet.')


if __name__ == '__main__':
    baixar()
