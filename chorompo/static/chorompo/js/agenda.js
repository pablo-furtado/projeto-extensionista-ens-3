(() => {
    if (window.matchMedia('(max-width: 680px)').matches) document.querySelectorAll('.agenda-extra-filters:not([data-keep-open])').forEach(node => { node.open = false; });
    let sequence = 0;
    function enhance(select) {
        if (select.dataset.enhanced) return;
        select.dataset.enhanced = 'true';
        const kind = select.dataset.searchKind || 'local';
        const local = kind === 'local';
        const form = select.closest('form');
        const wrapper = document.createElement('div');
        wrapper.className = 'search-combobox';
        const input = document.createElement('input');
        input.id = `${select.id}-search`;
        if (!select.id) { select.id = `select-${++sequence}`; input.id = `${select.id}-search`; }
        input.type = 'search';
        input.autocomplete = 'off';
        input.placeholder = local ? (select.options[0]?.value === '' ? select.options[0].textContent : 'Buscar por nome…') : kind === 'patient' ? 'Buscar nome, telefone ou CPF…' : kind === 'treatment' ? 'Buscar tratamento do paciente…' : 'Buscar sessão…';
        input.disabled = select.disabled;
        input.required = select.required;
        input.setAttribute('role', 'combobox');
        input.setAttribute('aria-autocomplete', 'list');
        input.setAttribute('aria-expanded', 'false');
        input.setAttribute('aria-required', String(select.required));
        if (kind === 'patient') input.dataset.patientSearch = 'true';
        if (select.getAttribute('aria-invalid')) input.setAttribute('aria-invalid', select.getAttribute('aria-invalid'));
        if (select.getAttribute('aria-describedby')) input.setAttribute('aria-describedby', select.getAttribute('aria-describedby'));
        input.value = select.value ? select.selectedOptions[0]?.textContent || '' : '';
        const menu = document.createElement('div');
        menu.className = 'combo-menu';
        menu.id = `combo-results-${++sequence}`;
        menu.setAttribute('role', 'listbox');
        menu.setAttribute('aria-label', local ? 'Opções disponíveis' : `Resultados de ${kind === 'patient' ? 'pacientes' : kind === 'treatment' ? 'tratamentos' : 'sessões'}`);
        menu.hidden = true;
        input.setAttribute('aria-controls', menu.id);
        const clear = document.createElement('button');
        clear.type = 'button';
        clear.className = 'combo-clear';
        clear.textContent = '×';
        clear.setAttribute('aria-label', 'Limpar seleção');
        const status = document.createElement('div');
        status.className = 'combo-hint';
        status.setAttribute('role', 'status');
        status.textContent = 'Digite para pesquisar e selecione um resultado.';
        status.hidden = local;
        select.before(wrapper);
        wrapper.append(input, clear, menu);
        wrapper.after(status);
        form.querySelectorAll('label').forEach(label => { if (label.htmlFor === select.id) label.htmlFor = input.id; });
        select.hidden = true;
        select.required = false;
        select.tabIndex = -1;
        let controller, timer, page = 1, active = -1, options = [], generation = 0;
        function close() { menu.hidden = true; input.setAttribute('aria-expanded', 'false'); input.removeAttribute('aria-activedescendant'); }
        function message(text) { menu.replaceChildren(); const node = document.createElement('div'); node.className = 'combo-message'; node.textContent = text; menu.append(node); status.textContent = text; }
        function reset() { controller?.abort(); generation++; if (local) select.value = ''; else select.replaceChildren(new Option('---------', '')); input.value = ''; close(); }
        select.addEventListener('agenda:reset', reset);
        function choose(item) {
            if (local) select.value = String(item.id);
            else select.replaceChildren(new Option(item.label, String(item.id), true, true));
            input.value = String(item.id) === '' ? '' : item.label;
            select.dataset.duration = item.duration || '';
            status.textContent = 'Selecionado: ' + item.label;
            close();
            select.dispatchEvent(new Event('change', {bubbles: true}));
        }
        async function search(append = false) {
            controller?.abort();
            controller = new AbortController();
            const current = ++generation;
            const patient = form.elements.namedItem('patient')?.value || '';
            const treatment = form.elements.namedItem('treatment')?.value || '';
            menu.hidden = false;
            input.setAttribute('aria-expanded', 'true');
            if ((kind === 'treatment' && !patient) || (kind === 'session' && !treatment)) {
                message(kind === 'treatment' ? 'Selecione primeiro o paciente.' : 'Selecione primeiro o tratamento.');
                return;
            }
            if (!append) { page = 1; options = []; active = -1; message('Buscando…'); }
            try {
                let result;
                if (local) {
                    const normalize = text => text.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLocaleLowerCase();
                    const query = select.value ? '' : normalize(input.value);
                    const matches = [...select.options].filter(option => !option.disabled && !option.parentElement.disabled && normalize(option.textContent).includes(query));
                    result = {results: matches.slice((page - 1) * 20, page * 20).map(option => ({id: option.value, label: option.textContent})), more: matches.length > page * 20};
                } else {
                    const url = new URL(select.dataset.searchUrl, location.origin);
                    url.search = new URLSearchParams({kind, q: select.value ? '' : input.value, patient, treatment, page, appointment: select.dataset.appointment || ''});
                    const response = await fetch(url, {credentials: 'same-origin', signal: controller.signal});
                    if (!response.ok || !response.headers.get('content-type')?.includes('application/json')) throw new Error();
                    result = await response.json();
                }
                if (current !== generation) return;
                menu.querySelector('.combo-more')?.remove();
                menu.querySelector('.combo-message')?.remove();
                if (!append) menu.replaceChildren();
                result.results.forEach(item => {
                    const option = document.createElement('div');
                    option.className = 'combo-option';
                    option.id = `${menu.id}-${options.length}`;
                    option.setAttribute('role', 'option');
                    option.setAttribute('aria-selected', 'false');
                    option.textContent = item.label;
                    if (item.available !== undefined) {
                        const badge = document.createElement('small');
                        badge.className = 'combo-badge' + (item.available === 0 ? ' combo-badge-empty' : '');
                        badge.textContent = `${item.available} ${item.available === 1 ? 'sessão disponível' : 'sessões disponíveis'}`;
                        option.append(badge);
                    }
                    option.addEventListener('mousedown', event => event.preventDefault());
                    option.addEventListener('click', () => choose(item));
                    options.push({node: option, item});
                    menu.append(option);
                });
                if (!options.length) message('Nenhum resultado encontrado. Tente outro nome ou confira o cadastro.');
                else status.textContent = `${options.length} resultados. Use as setas e Enter para selecionar.`;
                if (result.more) {
                    const more = document.createElement('div');
                    more.className = 'combo-more';
                    more.setAttribute('role', 'option');
                    more.id = `${menu.id}-more`;
                    more.setAttribute('aria-selected', 'false');
                    more.textContent = 'Carregar mais resultados';
                    more.addEventListener('mousedown', event => event.preventDefault());
                    more.addEventListener('click', () => { page++; search(true); });
                    menu.append(more);
                }
            } catch (error) {
                if (error.name !== 'AbortError' && current === generation) message('Não foi possível buscar. Digite novamente para tentar.');
            }
        }
        input.addEventListener('focus', () => search());
        input.addEventListener('input', () => {
            select.value = '';
            select.dispatchEvent(new Event('change', {bubbles: true}));
            controller?.abort(); generation++;
            clearTimeout(timer);
            options = []; active = -1;
            message('Buscando…');
            timer = setTimeout(() => search(), local ? 0 : 200);
        });
        input.addEventListener('keydown', event => {
            if (event.key === 'Escape') { if (!menu.hidden) { event.stopPropagation(); event.preventDefault(); close(); } return; }
            if (event.key === 'Tab') { close(); return; }
            const nodes = [...menu.querySelectorAll('[role="option"]')];
            if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
                event.preventDefault();
                if (menu.hidden) { search(); return; }
                active = Math.max(0, Math.min(nodes.length - 1, active + (event.key === 'ArrowDown' ? 1 : -1)));
                nodes.forEach((node, index) => node.setAttribute('aria-selected', String(index === active)));
                if (nodes[active]) { input.setAttribute('aria-activedescendant', nodes[active].id); nodes[active].scrollIntoView({block: 'nearest'}); }
            } else if (event.key === 'Enter' && !menu.hidden) {
                event.preventDefault();
                nodes[active >= 0 ? active : 0]?.click();
            }
        });
        clear.addEventListener('click', () => { reset(); select.dispatchEvent(new Event('change', {bubbles: true})); input.focus(); });
        wrapper.addEventListener('focusout', () => { setTimeout(() => { if (!wrapper.contains(document.activeElement)) close(); }, 0); });
    }
    function initialize(root = document) {
        root.querySelectorAll('select:not([multiple]):not([disabled])').forEach(enhance);
        root.querySelectorAll('select[name="recurrence"]').forEach(select => {
            if (select.dataset.recurrenceReady) return;
            select.dataset.recurrenceReady = 'true';
            const form = select.closest('form');
            function update() {
                form.querySelector('.field-weekdays').hidden = select.value !== 'WEEKLY';
                form.querySelector('.field-repeat_until').hidden = select.value === 'ONCE';
            }
            select.addEventListener('change', update);
            update();
        });
        root.querySelectorAll('form').forEach(form => {
            if (form.dataset.agendaReady || !form.querySelector('[data-search-kind="patient"]')) return;
            form.dataset.agendaReady = 'true';
            const patient = form.elements.namedItem('patient');
            const treatment = form.elements.namedItem('treatment');
            const session = form.elements.namedItem('session');
            const start = form.elements.namedItem('starts_at');
            const end = form.elements.namedItem('ends_at');
            const day = form.elements.namedItem('date');
            const startTime = form.elements.namedItem('start_time');
            const endTime = form.elements.namedItem('end_time');
            const tools = document.createElement('div'); tools.className = 'booking-time-tools';
            const durationLabel = document.createElement('span'); durationLabel.setAttribute('role', 'status');
            tools.append(durationLabel);
            endTime.closest('.field').after(tools);
            const suggestion = document.createElement('button');
            suggestion.type = 'button'; suggestion.className = 'duration-suggestion'; suggestion.hidden = true;
            tools.append(suggestion);
            const timeMinutes = value => { const [h, m] = value.split(':').map(Number); return h * 60 + m; };
            function updateTimes() {
                start.value = day.value && startTime.value ? `${day.value}T${startTime.value}` : '';
                end.value = day.value && endTime.value ? `${day.value}T${endTime.value}` : '';
                const duration = timeMinutes(endTime.value) - timeMinutes(startTime.value);
                durationLabel.textContent = !startTime.value || !endTime.value ? 'Informe início e fim ou aplique a duração do tratamento.' : duration > 0 ? `Duração do atendimento: ${duration} min` : 'O fim deve ser após o início, no mesmo dia.';
            }
            [day, startTime, endTime].forEach(field => field.addEventListener('input', updateTimes));
            function suggest() {
                const duration = Number(treatment.dataset.duration);
                suggestion.hidden = !duration || !treatment.value;
                suggestion.textContent = `Usar duração sugerida: ${duration} min`;
            }
            suggestion.addEventListener('click', () => {
                if (!startTime.value) { startTime.focus(); return; }
                const finish = timeMinutes(startTime.value) + Number(treatment.dataset.duration);
                if (finish >= 1440) { durationLabel.textContent = 'Esta duração ultrapassa o dia. Escolha um início mais cedo.'; return; }
                endTime.value = `${String(Math.floor(finish / 60)).padStart(2, '0')}:${String(finish % 60).padStart(2, '0')}`;
                updateTimes();
            });
            patient.addEventListener('change', () => { treatment.dispatchEvent(new Event('agenda:reset')); session.dispatchEvent(new Event('agenda:reset')); suggest(); });
            treatment.addEventListener('change', () => { session.dispatchEvent(new Event('agenda:reset')); suggest(); });
            updateTimes();
            suggest();
            const details = document.createElement('details'); details.className = 'booking-extras';
            const summary = document.createElement('summary'); summary.textContent = 'Tratamento e observações (opcional)'; details.append(summary);
            const extras = document.createElement('div'); extras.className = 'fields'; details.append(extras);
            form.querySelector('.fields').after(details);
            ['treatment', 'session', 'notes'].forEach(name => { const field = form.elements.namedItem(name)?.closest('.field'); if (field) { extras.append(field); if (field.querySelector('.field-error') || form.elements.namedItem(name).value) details.open = true; } });
        });
    }
    initialize();
    document.addEventListener('record:loaded', event => initialize(event.target));
    new MutationObserver(records => { if (records.some(record => [...record.addedNodes].some(node => node.nodeType === 1 && (node.matches?.('form, select') || node.querySelector?.('select:not([data-enhanced])'))))) initialize(); }).observe(document.body, {childList: true, subtree: true});
})();
