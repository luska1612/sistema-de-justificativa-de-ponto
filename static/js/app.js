/**
 * Sistema de Justificativas de Ponto — JavaScript
 */

document.addEventListener('DOMContentLoaded', () => {

    document.querySelectorAll('input[name="horario_entrada"], input[name="horario_saida"]').forEach(input => {
        input.addEventListener('input', event => {
            const digits = event.target.value.replace(/\D/g, '').slice(0, 4);
            event.target.value = digits.length > 2 ? `${digits.slice(0, 2)}:${digits.slice(2)}` : digits;
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
    const multiplos = document.querySelector('#temMultiplos');
    const adicionar = document.querySelector('#adicionar-colaborador');
    if (lista && multiplos && adicionar) {
        const atualizar = () => {
            const linhas = lista.querySelectorAll('.colaborador-linha');
            linhas.forEach((linha, i) => {
                linha.querySelector('.remover-colaborador').disabled = i === 0;
            });
            adicionar.classList.toggle('d-none', !multiplos.checked);
        };
        multiplos.addEventListener('change', atualizar);
        adicionar.addEventListener('click', () => {
            const linha = lista.querySelector('.colaborador-linha').cloneNode(true);
            linha.querySelectorAll('input').forEach(input => { input.value = ''; });
            linha.querySelector('.remover-colaborador').disabled = false;
            lista.appendChild(linha);
            atualizar();
        });
        lista.addEventListener('click', event => {
            if (event.target.closest('.remover-colaborador')) {
                event.target.closest('.colaborador-linha').remove();
                atualizar();
            }
        });
        atualizar();
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
