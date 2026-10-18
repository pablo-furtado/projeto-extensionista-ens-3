"""Optional real-browser check using only Django's isolated test database.

python -m pip install playwright
python -m playwright install chromium
python manage.py test tools.verify_agenda_ui --settings=config.test_settings
"""
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from tempfile import gettempdir

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.utils import timezone
from playwright.sync_api import expect, sync_playwright

from chorompo import test_treatments
from chorompo.models import Appointment, Floor, Room, RoomBlock
from chorompo.treatment_services import acquire_treatment, save_appointment


class AgendaBrowserTests(StaticLiveServerTestCase):
    def test_recurring_blocks_drag_drop_global_search_and_sixty_minute_suggestion(self):
        test_treatments.TreatmentFlowTests.setUpTestData.__func__(type(self))
        self.room.refresh_from_db()
        other_room = Room.objects.create(company=self.company, floor=self.floor, name="Sala 2", opens_at="08:00", closes_at="18:00")
        self.catalog.duration_minutes = 60
        self.catalog.save()
        purchase = acquire_treatment(company=self.company, patient=self.patient, catalog=self.catalog, qty_sessions=2, discount_percentage=Decimal(0))
        empty = acquire_treatment(company=self.company, patient=self.patient, catalog=self.catalog, qty_sessions=1, discount_percentage=Decimal(0))
        from chorompo.treatment_services import record_evolution
        record_evolution(session=empty.sessions.first(), employee=self.employee, date=timezone.localdate(), notes="Realizado", uses_session=True)
        aware = lambda text: timezone.make_aware(datetime.fromisoformat(text))
        booking = save_appointment(Appointment(company=self.company, room=self.room, patient=self.patient, professional=self.employee,
            starts_at=aware("2027-03-17T09:00"), ends_at=aware("2027-03-17T10:00")))
        self.client.force_login(self.user)
        with sync_playwright() as runtime:
            browser = runtime.chromium.launch()
            context = browser.new_context(viewport={"width": 1440, "height": 1100}, locale="pt-BR", has_touch=True)
            context.add_cookies([{"name": settings.SESSION_COOKIE_NAME, "value": self.client.cookies[settings.SESSION_COOKIE_NAME].value, "url": self.live_server_url}])
            page = context.new_page()
            page.set_default_timeout(10000)
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(self.live_server_url + '/plataforma/agenda/configuracoes/')
            page.get_by_role('link', name='+ Bloqueio', exact=True).click()
            dialog = page.locator('dialog[open]')
            room = dialog.locator('.field-room input[role="combobox"]')
            room.fill('Sala 1')
            dialog.locator('.field-room .combo-option').filter(has_text='Sala 1').click()
            recurrence = dialog.locator('.field-recurrence input[role="combobox"]')
            recurrence.fill('Dias da semana')
            dialog.locator('.field-recurrence .combo-option').filter(has_text='Dias da semana').click()
            expect(dialog.locator('.field-weekdays')).to_be_visible()
            for name in ('Segunda', 'Quarta', 'Sexta'):
                dialog.get_by_label(name, exact=True).check()
            dialog.locator('[name="starts_at"]').fill('2027-03-15T12:00')
            dialog.locator('[name="ends_at"]').fill('2027-03-15T14:00')
            dialog.locator('[name="reason"]').fill('Almoço recorrente')
            dialog.get_by_role('button', name='Salvar', exact=True).click()
            expect(page.get_by_text('Seg, Qua, Sex · 12:00–14:00', exact=True)).to_be_visible()
            page.goto(self.live_server_url + '/plataforma/agenda/?date=2027-03-17')
            expect(page.locator('.blocked-event')).to_have_count(1)
            source = page.locator(f'[data-move-url$="/{booking.pk}/mover/"]')
            target = page.get_by_role('link', name='Agendar 17/03/2027 às 10:00 · Térreo · Sala 2', exact=True)
            source.drag_to(target, source_position={"x": 20, "y": 5}, target_position={"x": 20, "y": 5})
            expect(page.locator(f'.booked-event[data-room="{other_room.pk}"]')).to_have_count(1)
            expect(page.locator('.booked-event strong')).to_have_text('10:00–11:00')
            # A rejected drop leaves the original card in place and explains why.
            source = page.locator('.booked-event')
            source.drag_to(page.locator('.blocked-event'), source_position={"x": 20, "y": 5}, target_position={"x": 20, "y": 5})
            expect(page.locator('.agenda-move-status')).to_contain_text('Sala bloqueada')
            expect(page.locator('.booked-event strong')).to_have_text('10:00–11:00')
            # Real touch input uses the dedicated handle and keeps page scrolling elsewhere.
            handle = page.locator('.booked-event .drag-handle')
            handle.scroll_into_view_if_needed()
            touch_target = page.get_by_role('link', name='Agendar 17/03/2027 às 11:00 · Térreo · Sala 1', exact=True)
            origin, destination = handle.bounding_box(), touch_target.bounding_box()
            cdp = context.new_cdp_session(page)
            cdp.send('Input.dispatchTouchEvent', {'type': 'touchStart', 'touchPoints': [{'x': origin['x'] + 8, 'y': origin['y'] + 8}]})
            cdp.send('Input.dispatchTouchEvent', {'type': 'touchMove', 'touchPoints': [{'x': destination['x'] + 20, 'y': destination['y'] + 10}]})
            cdp.send('Input.dispatchTouchEvent', {'type': 'touchEnd', 'touchPoints': []})
            expect(page.locator(f'.booked-event[data-room="{self.room.pk}"]')).to_have_count(1)
            expect(page.locator('.booked-event strong')).to_have_text('11:00–12:00')
            page.locator('.booked-event').click()
            dialog = page.locator('dialog[open]')
            expect(dialog.locator('[name="date"]')).to_have_value('2027-03-17')
            expect(dialog.locator('[name="start_time"]')).to_have_value('11:00')
            dialog.locator('.booking-extras summary').click()
            treatment = dialog.locator('.field-treatment input[role="combobox"]')
            treatment.fill('Fisioterapia')
            options = dialog.locator('.field-treatment .combo-option')
            expect(options).to_have_count(2)
            expect(options.first.locator('.combo-badge')).to_have_text('2 sessões disponíveis')
            expect(options.last.locator('.combo-badge-empty')).to_have_text('0 sessões disponíveis')
            options.first.click()
            dialog.locator('[name="end_time"]').fill('11:45')
            dialog.get_by_role('button', name='Usar duração sugerida: 60 min').click()
            expect(dialog.locator('[name="end_time"]')).to_have_value('12:00')
            expect(dialog.locator('.booking-time-tools')).to_contain_text('Duração do atendimento: 60 min')
            dialog.locator('[name="start_time"]').fill('10:30')
            dialog.get_by_role('button', name='Usar duração sugerida: 60 min').click()
            expect(dialog.locator('[name="end_time"]')).to_have_value('11:30')
            page.screenshot(path=str(Path(gettempdir()) / 'chorompo-agenda-duration.png'), full_page=True)
            dialog.get_by_role('button', name='Fechar formulário').click()
            # Search also works in ordinary and dynamically added selects.
            page.goto(self.live_server_url + '/plataforma/pacientes/')
            page.locator('[data-modal-open]').click()
            dialog = page.locator('dialog[open]')
            dialog.locator('.field-sex input[role="combobox"]').fill('Feminino')
            dialog.locator('.field-sex .combo-option').filter(has_text='Feminino').click()
            expect(dialog.locator('[name="sex"]')).to_have_value('F')
            page.goto(self.live_server_url + '/plataforma/tratamentos/pacientes/novo/')
            page.locator('#add-package-item').click()
            added = page.locator('.package-item').last
            added.locator('input[role="combobox"]').fill('Fisioterapia')
            added.locator('.combo-option').filter(has_text='Fisioterapia').click()
            expect(added.locator('select')).to_have_value(str(self.catalog.pk))
            self.assertEqual(errors, [])
            browser.close()
        booking.refresh_from_db()
        self.assertEqual(booking.starts_at, aware('2027-03-17T11:00'))
        self.assertEqual(booking.ends_at, aware('2027-03-17T12:00'))

    def test_desktop_mobile_keyboard_create_edit_cancel_and_configuration(self):
        test_treatments.TreatmentFlowTests.setUpTestData.__func__(type(self))
        self.room.refresh_from_db()
        floor = Floor.objects.create(company=self.company, name="Piso 1")
        for name, color in [("Laser", "#4866a4"), ("Avaliação", "#9b6f34"), ("Pilates", "#8763aa")]:
            Room.objects.create(company=self.company, floor=floor, name=name, color=color, opens_at="07:30", closes_at="19:00")
        aware = lambda text: timezone.make_aware(datetime.fromisoformat(text))
        purchase = acquire_treatment(company=self.company, patient=self.patient, catalog=self.catalog, qty_sessions=3, discount_percentage=Decimal(0))
        save_appointment(Appointment(company=self.company, room=self.room, patient=self.patient, professional=self.employee,
            starts_at=aware("2027-03-15T09:00"), ends_at=aware("2027-03-15T10:00")))
        RoomBlock.objects.create(room=self.room, starts_at=aware("2027-03-15T12:00"), ends_at=aware("2027-03-15T13:00"), reason="Almoço da equipe")
        self.client.force_login(self.user)
        with sync_playwright() as runtime:
            browser = runtime.chromium.launch()
            context = browser.new_context(viewport={"width": 1440, "height": 1000}, locale="pt-BR")
            context.add_cookies([{"name": settings.SESSION_COOKIE_NAME, "value": self.client.cookies[settings.SESSION_COOKIE_NAME].value, "url": self.live_server_url}])
            page = context.new_page()
            page.set_default_timeout(10000)
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(self.live_server_url + "/plataforma/agenda/?date=2027-03-15")
            expect(page.get_by_role("heading", name="Agenda diária")).to_be_visible()
            expect(page.locator('.room-heading')).to_have_count(4)
            self.assertFalse(page.evaluate('document.documentElement.scrollWidth > innerWidth'))
            screenshot = Path(gettempdir()) / "chorompo-agenda-desktop.png"
            page.screenshot(path=str(screenshot), full_page=True)
            print(f"Desktop screenshot: {screenshot}")
            # Scroll references remain pinned on both axes.
            scroller = page.locator('.timeline-scroll')
            scroller.evaluate('(node) => {node.scrollTop = 250; node.scrollLeft = 150}')
            self.assertLess(abs(page.locator('.room-heading').first.bounding_box()['y'] - scroller.bounding_box()['y']), 3)
            scroller.evaluate('(node) => {node.scrollTop = 0; node.scrollLeft = 0}')
            page.get_by_role('link', name='Agendar 15/03/2027 às 08:00 · Térreo · Sala 1', exact=True).click()
            dialog = page.locator('dialog[open]')
            expect(dialog.get_by_role('heading', name='Novo agendamento')).to_be_visible()
            expect(dialog.locator('[name="start_time"]')).to_have_value('08:00')
            expect(dialog.locator('[name="end_time"]')).to_have_value('08:30')
            patient = dialog.locator('[data-patient-search]')
            expect(patient).to_be_focused()
            patient.fill('Paciente A')
            expect(dialog.locator('.field-patient .combo-menu:visible .combo-option').first).to_be_visible()
            patient.press('ArrowDown')
            patient.press('Enter')
            dialog.locator('[name="end_time"]').fill('08:45')
            dialog.get_by_role('button', name='Salvar', exact=True).click()
            expect(page.locator('dialog[open]')).to_have_count(0)
            expect(page.locator('.booked-event')).to_have_count(2)
            # Edit, search purchased treatments, and preserve a manual end.
            page.locator('.booked-event').filter(has_text='08:00').click()
            dialog = page.locator('dialog[open]')
            dialog.locator('.booking-extras summary').click()
            treatment = dialog.locator('.field-treatment input[role="combobox"]')
            treatment.fill('Fisioterapia')
            expect(dialog.locator('.field-treatment .combo-menu:visible .combo-option').filter(has_text='Fisioterapia').first).to_be_visible()
            treatment.press('ArrowDown')
            treatment.press('Enter')
            expect(dialog.locator('select[name="treatment"]')).to_have_value(str(purchase.pk))
            expect(dialog.locator('[name="end_time"]')).to_have_value('08:45')
            dialog.get_by_role('button', name='Usar duração sugerida: 30 min').click()
            expect(dialog.locator('[name="end_time"]')).to_have_value('08:30')
            dialog.locator('[name="end_time"]').fill('08:50')
            dialog.get_by_role('button', name='Salvar', exact=True).click()
            expect(page.locator('dialog[open]')).to_have_count(0)
            # Cancellation releases the room while preserving the record.
            page.locator('.booked-event').filter(has_text='08:00').click()
            page.locator('dialog[open]').get_by_role('link', name='Cancelar agendamento').click()
            page.get_by_role('button', name='Cancelar agendamento').click()
            expect(page.locator('.booked-event')).to_have_count(1)
            # Accessible no-result state and mobile horizontal containment.
            page.set_viewport_size({"width": 390, "height": 844})
            page.goto(self.live_server_url + '/plataforma/agenda/?date=2027-03-15')
            self.assertFalse(page.evaluate('document.documentElement.scrollWidth > innerWidth'))
            mobile = Path(gettempdir()) / 'chorompo-agenda-mobile.png'
            page.screenshot(path=str(mobile), full_page=True)
            print(f"Mobile screenshot: {mobile}")
            page.get_by_role('link', name='+ Agendar', exact=True).click()
            dialog = page.locator('dialog[open]')
            dialog.locator('[data-patient-search]').fill('inexistente')
            expect(dialog.get_by_text('Nenhum resultado encontrado. Tente outro nome ou confira o cadastro.', exact=True).first).to_be_visible()
            self.assertLessEqual(dialog.bounding_box()['width'], 390)
            page.keyboard.press('Escape')
            page.keyboard.press('Escape')
            # Configuration also reuses the existing modal flow.
            page.goto(self.live_server_url + '/plataforma/agenda/configuracoes/')
            page.get_by_role('link', name='+ Piso', exact=True).click()
            dialog = page.locator('dialog[open]')
            dialog.locator('[name="name"]').fill('Piso 2')
            dialog.get_by_role('button', name='Salvar', exact=True).click()
            expect(page.get_by_text('Piso 2', exact=True)).to_be_visible()
            self.assertEqual(errors, [])
            browser.close()
        self.assertEqual(Appointment.objects.filter(canceled_at__isnull=False).count(), 1)
