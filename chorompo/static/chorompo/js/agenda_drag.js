(() => {
    const agenda = document.querySelector('.daily-agenda');
    if (!agenda) return;
    const scroller = agenda.querySelector('.timeline-scroll');
    if (!scroller) return;
    const status = agenda.querySelector('.agenda-move-status');
    const csrf = agenda.querySelector('[name="csrfmiddlewaretoken"]').value;
    const lower = Number(agenda.dataset.startMinute);
    let source, offset = 0, target, preview, busy = false, touch, suppressUntil = 0;
    try {
        const saved = JSON.parse(sessionStorage.getItem('agenda-scroll') || 'null');
        if (saved?.url === location.href) { scroller.scrollTop = saved.top; scroller.scrollLeft = saved.left; sessionStorage.removeItem('agenda-scroll'); }
    } catch (_) { /* Scrolling still works when storage is unavailable. */ }
    const labelTime = minute => `${String(Math.floor(minute / 60)).padStart(2, '0')}:${String(minute % 60).padStart(2, '0')}`;
    function report(message, error = false) {
        status.hidden = false;
        status.classList.toggle('is-error', error);
        status.setAttribute('role', error ? 'alert' : 'status');
        status.textContent = message;
    }
    function begin(card, clientY) {
        source = card;
        source.classList.add('is-dragging');
        const duration = (new Date(card.dataset.end) - new Date(card.dataset.start)) / 60000;
        offset = Math.max(0, Math.min(duration - 1, (clientY - card.getBoundingClientRect().top) / 2));
        preview = document.createElement('div'); preview.className = 'move-preview';
        report('Solte em uma sala e horário. A duração será mantida. Para cancelar, pressione Escape.');
    }
    function locate(clientX, clientY) {
        const column = document.elementFromPoint(clientX, clientY)?.closest('.room-timeline[data-room]');
        if (!column?.dataset.room) { target = null; preview?.remove(); return; }
        const minute = Math.max(0, Math.min(1439, lower + Math.round(((clientY - column.getBoundingClientRect().top) / 2 - offset) / 15) * 15));
        const duration = (new Date(source.dataset.end) - new Date(source.dataset.start)) / 60000;
        target = {room: column.dataset.room, minute};
        preview.style.top = `${(minute - lower) * 2}px`;
        preview.style.height = `${duration * 2}px`;
        preview.textContent = `${labelTime(minute)}–${labelTime(minute + duration)} · ${column.dataset.roomLabel}`;
        column.append(preview);
        const box = scroller.getBoundingClientRect();
        if (clientY > box.bottom - 40) scroller.scrollTop += 16;
        else if (clientY < box.top + 100) scroller.scrollTop -= 16;
        if (clientX > box.right - 35) scroller.scrollLeft += 16;
        else if (clientX < box.left + 70) scroller.scrollLeft -= 16;
    }
    function cleanup() { source?.classList.remove('is-dragging'); preview?.remove(); source = null; preview = null; target = null; touch = null; }
    async function commit() {
        const card = source, destination = target;
        cleanup();
        suppressUntil = Date.now() + 600;
        if (!card || !destination || busy) { status.hidden = true; return; }
        busy = true;
        report('Validando disponibilidade e movendo atendimento…');
        agenda.setAttribute('aria-busy', 'true');
        try {
            const response = await fetch(card.dataset.moveUrl, {method: 'POST', credentials: 'same-origin', headers: {'X-CSRFToken': csrf}, body: new URLSearchParams({
                room: destination.room, starts_at: `${agenda.dataset.date}T${labelTime(destination.minute)}`,
                expected_start: card.dataset.start, expected_end: card.dataset.end, expected_room: card.dataset.room,
            })});
            if (!response.headers.get('content-type')?.includes('application/json')) throw new Error('Não foi possível confirmar a alteração. Atualize a agenda e confira o atendimento.');
            const result = await response.json();
            if (!response.ok) throw new Error(result.error || 'Não foi possível mover este atendimento.');
            report(result.message);
            try { sessionStorage.setItem('agenda-scroll', JSON.stringify({url: location.href, top: scroller.scrollTop, left: scroller.scrollLeft})); } catch (_) {}
            location.reload();
        } catch (error) { report(error.message || 'Falha de conexão. Confira a agenda antes de tentar novamente.', true); }
        finally { busy = false; agenda.removeAttribute('aria-busy'); }
    }
    agenda.addEventListener('dragstart', event => {
        const card = event.target.closest('[data-move-url]');
        if (!card || busy) { event.preventDefault(); return; }
        begin(card, event.clientY);
        event.dataTransfer.effectAllowed = 'move';
        event.dataTransfer.setData('text/plain', card.dataset.moveUrl);
    });
    agenda.addEventListener('dragover', event => {
        if (!source || touch) return;
        event.preventDefault(); event.dataTransfer.dropEffect = 'move';
        locate(event.clientX, event.clientY);
    });
    agenda.addEventListener('drop', event => { if (!source || touch) return; event.preventDefault(); locate(event.clientX, event.clientY); commit(); });
    agenda.addEventListener('dragend', () => { if (source && !touch) { cleanup(); status.hidden = true; } });
    agenda.addEventListener('pointerdown', event => {
        if (event.pointerType === 'mouse' || busy) return;
        const handle = event.target.closest('.drag-handle');
        const card = handle?.closest('[data-move-url]');
        if (!card) return;
        event.preventDefault();
        begin(card, event.clientY);
        touch = {id: event.pointerId, handle};
        handle.setPointerCapture(event.pointerId);
    });
    agenda.addEventListener('pointermove', event => { if (touch?.id === event.pointerId) { event.preventDefault(); locate(event.clientX, event.clientY); } });
    agenda.addEventListener('pointerup', event => { if (touch?.id === event.pointerId) { event.preventDefault(); commit(); } });
    agenda.addEventListener('pointercancel', () => { if (touch) { cleanup(); status.hidden = true; } });
    document.addEventListener('keydown', event => { if (event.key === 'Escape' && source) { cleanup(); status.hidden = true; } });
    document.addEventListener('click', event => { if (Date.now() < suppressUntil) { event.preventDefault(); event.stopImmediatePropagation(); } }, true);
})();
