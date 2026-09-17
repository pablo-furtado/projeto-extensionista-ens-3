(() => {
    const items = document.getElementById('package-items');
    const template = document.getElementById('package-empty-item');
    const total = document.getElementById('id_items-TOTAL_FORMS');
    const add = document.getElementById('add-package-item');
    if (!items || !template || !total || !add) return;
    add.hidden = false;
    const update = () => {
        const rows = [...items.querySelectorAll('.package-item')];
        const active = rows.filter(row => !row.querySelector('input[name$="-DELETE"]').checked);
        add.disabled = active.length >= 20 || Number(total.value) >= 40;
        rows.forEach(row => row.classList.toggle('package-item-removed', row.querySelector('input[name$="-DELETE"]').checked));
    };
    add.addEventListener('click', () => {
        if (add.disabled) return;
        const index = Number(total.value);
        items.insertAdjacentHTML('beforeend', template.innerHTML.replaceAll('__prefix__', String(index)));
        total.value = index + 1;
        update();
        items.lastElementChild.querySelector('select').focus();
    });
    items.addEventListener('change', update);
    update();
})();
