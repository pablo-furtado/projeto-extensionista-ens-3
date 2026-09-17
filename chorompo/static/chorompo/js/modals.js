(() => {
    if (!window.HTMLDialogElement || !HTMLDialogElement.prototype.showModal) return;
    const remote = document.createElement('dialog');
    remote.className = 'erp-modal';
    remote.setAttribute('aria-labelledby', 'edit-modal-title');
    remote.innerHTML = '<header class="modal-header"><h2 id="edit-modal-title">Editar registro</h2><button type="button" class="modal-close" data-modal-close aria-label="Fechar formulário">×</button></header><div class="modal-body"></div>';
    document.body.append(remote);
    let controller;
    remote.addEventListener('close', () => controller?.abort());
    function focusField(dialog) {
        dialog.querySelector('[aria-invalid="true"], input:not([type="hidden"]):not([disabled]), select, textarea')?.focus();
    }
    function displayEditor(html) {
        const page = new DOMParser().parseFromString(html, 'text/html');
        const editor = page.getElementById('record-editor');
        if (!editor) return false;
        const form = editor.querySelector('form');
        // Avoid duplicate IDs alongside the creation form.
        form.querySelectorAll('[id]').forEach(node => { node.id = `edit-${node.id}`; });
        form.querySelectorAll('[for], [aria-describedby], [aria-labelledby]').forEach(node => {
            ['for', 'aria-describedby', 'aria-labelledby'].forEach(attr => {
                if (node.hasAttribute(attr)) node.setAttribute(attr, node.getAttribute(attr).split(' ').map(id => `edit-${id}`).join(' '));
            });
        });
        remote.querySelector('h2').textContent = editor.dataset.title;
        remote.querySelector('.modal-body').replaceChildren(form);
        return true;
    }
    document.addEventListener('click', async event => {
        const close = event.target.closest('[data-modal-close], [data-modal-cancel]');
        if (close?.closest('dialog')) {
            event.preventDefault();
            close.closest('dialog').close();
            return;
        }
        const opener = event.target.closest('[data-modal-open]');
        if (opener) {
            event.preventDefault();
            const dialog = document.getElementById(opener.dataset.modalOpen);
            dialog.showModal();
            focusField(dialog);
            return;
        }
        const link = event.target.closest('a[data-modal-edit]');
        if (!link || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey || event.button !== 0) return;
        event.preventDefault();
        controller?.abort();
        controller = new AbortController();
        remote.querySelector('h2').textContent = 'Carregando formulário…';
        remote.querySelector('.modal-body').textContent = 'Aguarde um instante.';
        remote.showModal();
        try {
            const response = await fetch(link.href, {credentials: 'same-origin', signal: controller.signal});
            if (response.redirected || !response.ok) { window.location.assign(response.url); return; }
            if (!displayEditor(await response.text())) { window.location.assign(link.href); return; }
            focusField(remote);
        } catch (error) {
            if (error.name === 'AbortError') return;
            const fallback = document.createElement('a');
            fallback.href = link.href;
            fallback.textContent = 'Não foi possível carregar. Abrir formulário em uma página.';
            remote.querySelector('.modal-body').replaceChildren(fallback);
        }
    });
    remote.addEventListener('submit', async event => {
        const form = event.target;
        event.preventDefault();
        if (form.dataset.saving) return;
        form.dataset.saving = 'true';
        const submit = form.querySelector('[type="submit"]');
        submit.disabled = true;
        try {
            const response = await fetch(form.action, {method: 'POST', body: new FormData(form), credentials: 'same-origin'});
            if (response.redirected || !response.ok) { window.location.assign(response.url); return; }
            if (displayEditor(await response.text())) { focusField(remote); return; }
            throw new Error('Unexpected response');
        } catch (_) {
            const message = document.createElement('p');
            message.className = 'error-summary';
            message.setAttribute('role', 'alert');
            message.textContent = 'Não foi possível confirmar o salvamento. Confira a listagem antes de tentar novamente.';
            form.prepend(message);
        } finally {
            delete form.dataset.saving;
            submit.disabled = false;
        }
    });
    document.querySelectorAll('dialog[data-auto-open]').forEach(dialog => { dialog.showModal(); focusField(dialog); });
})();
