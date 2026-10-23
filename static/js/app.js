/**
 * Sistema de Justificativas de Ponto — JavaScript
 */

document.addEventListener('DOMContentLoaded', () => {
    const layout = document.querySelector('.app-layout');
    const toggle = document.querySelector('#sidebar-toggle');
    if (layout && toggle) {
        const key = 'ponto-sidebar-collapsed';
        layout.classList.add('sidebar-collapsed');
        toggle.addEventListener('click', () => {
            layout.classList.toggle('sidebar-open');
        });
        document.querySelectorAll('.app-sidebar a').forEach(link => link.addEventListener('click', () => {
            layout.classList.remove('sidebar-open');
        }));
    }

    document.querySelectorAll('input[name="horario_entrada"], input[name="horario_saida"]').forEach(input => {
        input.addEventListener('input', event => {
            const digits = event.target.value.replace(/\D/g, '').slice(0, 4);
            event.target.value = digits.length > 2 ? `${digits.slice(0, 2)}:${digits.slice(2)}` : digits;
        });
    });

    document.querySelectorAll('input[name="data_ocorrencia"]').forEach(input => {
        input.addEventListener('input', event => {
            const digits = event.target.value.replace(/\D/g, '').slice(0, 8);
            event.target.value = digits.length > 4 ? `${digits.slice(0, 2)}/${digits.slice(2, 4)}/${digits.slice(4)}`
                : digits.length > 2 ? `${digits.slice(0, 2)}/${digits.slice(2)}` : digits;
        });
    });

    const dataOcorrencia = document.querySelector('input[name="data_ocorrencia"]');
    if (dataOcorrencia) {
        dataOcorrencia.addEventListener('input', event => {
            const digits = event.target.value.replace(/\D/g, '').slice(0, 8);
            event.target.value = digits.length > 4 ? `${digits.slice(0, 2)}/${digits.slice(2, 4)}/${digits.slice(4)}`
                : digits.length > 2 ? `${digits.slice(0, 2)}/${digits.slice(2)}` : digits;
        });
    }

    // ─── Auto-inicializar Toasts do Bootstrap ───
    const toastEls = document.querySelectorAll('.toast');
    toastEls.forEach(el => {
        const toast = bootstrap.Toast.getOrCreateInstance(el, { delay: 4000 });
        toast.show();
    });

    // ─── Confirmação de ações críticas (Aprovar/Recusar) ───
    document.querySelectorAll('form[action*="/aprovar/"]').forEach(form => {
        form.addEventListener('submit', (e) => {
            if (!confirm('Confirma a aprovação desta solicitação?')) {
                e.preventDefault();
            }
        });
    });

    // ─── Limpar formulário do modal ao fechar ───
    document.querySelectorAll('.modal').forEach(modal => {
        modal.addEventListener('hidden.bs.modal', () => {
            const form = modal.querySelector('form');
            if (form && form.querySelector('textarea[name="justificativa"]')) {
                form.reset();
            }
        });
    });

    // ─── Validação visual nos campos obrigatórios ───
    document.querySelectorAll('form').forEach(form => {
        form.addEventListener('submit', () => {
            form.classList.add('was-validated');
        });
    });

    const lista = document.querySelector('#colaboradores-lista');
    const adicionar = document.querySelector('#adicionar-colaborador');
    if (lista && adicionar) {
        const atualizar = () => {
            const linhas = lista.querySelectorAll('.colaborador-linha');
            linhas.forEach((linha, i) => {
                const remover = linha.querySelector('.remover-colaborador');
                if (remover) remover.disabled = i === 0;
            });
        };
        adicionar.addEventListener('click', event => {
            event.preventDefault();
            const original = lista.querySelector('.colaborador-linha');
            if (!original) return;
            const linha = original.cloneNode(true);
            linha.querySelectorAll('input').forEach(input => input.value = '');
            lista.appendChild(linha);
            atualizar();
            linha.querySelector('input')?.focus();
        });
        lista.addEventListener('click', event => {
            const remover = event.target.closest('.remover-colaborador');
            if (remover) {
                event.preventDefault();
                remover.closest('.colaborador-linha')?.remove();
                atualizar();
            }
        });
        atualizar();
    }

    // ─── Destaque do item de permissão marcado (fallback sem :has()) ───
    const permItems = document.querySelectorAll('.perm-item');
    if (permItems.length) {
        const marcar = input => input.closest('.perm-item')?.classList.toggle('is-checked', input.checked);
        permItems.forEach(item => {
            const input = item.querySelector('.form-check-input');
            if (!input) return;
            marcar(input);
            input.addEventListener('change', () => marcar(input));
        });
    }

    // ─── Fechar toasts ao clicar ───
    document.querySelectorAll('.toast .btn-close').forEach(btn => {
        btn.addEventListener('click', () => {
            const toastEl = btn.closest('.toast');
            const toast = bootstrap.Toast.getInstance(toastEl);
            if (toast) toast.hide();
        });
    });

});
