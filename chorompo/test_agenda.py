from datetime import datetime, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from .forms import AppointmentForm, RoomBlockForm, RoomForm
from .models import Appointment, Floor, Room, RoomBlock
from .scheduling import save_configuration
from . import test_treatments
from .treatment_services import acquire_treatment, save_appointment


class DailyAgendaTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        test_treatments.TreatmentFlowTests.setUpTestData.__func__(cls)

    def setUp(self):
        self.client.force_login(self.user)
        self.room.refresh_from_db()

    def data(self, **overrides):
        return {"room": self.room.pk, "patient": self.patient.pk, "professional": self.employee.pk,
                "starts_at": "2027-03-15T09:00", "ends_at": "2027-03-15T09:45", **overrides}

    def booking(self, **overrides):
        form = AppointmentForm(self.data(**overrides), company=self.company)
        self.assertTrue(form.is_valid(), form.errors)
        return save_appointment(form.save(commit=False))

    def instant(self, text):
        return timezone.make_aware(datetime.fromisoformat(text))

    def test_home_opens_daily_agenda_and_overview_remains_available(self):
        self.assertContains(self.client.get(reverse("chorompo:dashboard")), "Agenda diária")
        self.assertTemplateUsed(self.client.get(reverse("chorompo:dashboard"), {"overview": 1}), "chorompo/dashboard.html")

    def test_create_without_treatment_and_edit_manual_end(self):
        response = self.client.post(reverse("chorompo:appointment_create"), self.data())
        self.assertRedirects(response, reverse("chorompo:appointments") + "?date=2027-03-15")
        booking = Appointment.objects.get()
        self.assertIsNone(booking.treatment_id)
        self.assertIsNone(booking.treatment_company_id)
        self.assertEqual(timezone.localtime(booking.ends_at).strftime("%H:%M"), "09:45")
        response = self.client.post(reverse("chorompo:appointment_edit", args=[booking.pk]), self.data(ends_at="2027-03-15T10:10"))
        self.assertEqual(response.status_code, 302)
        booking.refresh_from_db()
        self.assertEqual(timezone.localtime(booking.ends_at).strftime("%H:%M"), "10:10")

    def test_treatment_never_replaces_submitted_end_and_can_be_removed(self):
        purchase = acquire_treatment(company=self.company, patient=self.patient, catalog=self.catalog, qty_sessions=2, discount_percentage=Decimal(0))
        booking = self.booking(treatment=purchase.pk, ends_at="2027-03-15T10:20")
        self.assertEqual(booking.ends_at, self.instant("2027-03-15T10:20"))
        response = self.client.post(reverse("chorompo:appointment_edit", args=[booking.pk]), self.data())
        self.assertEqual(response.status_code, 302)
        booking.refresh_from_db()
        self.assertIsNone(booking.treatment_company_id)

    def test_interval_boundaries_and_missing_required_times(self):
        for overrides, field in [({"ends_at": "2027-03-15T09:00"}, "ends_at"),
                                 ({"starts_at": "2027-03-15T07:45"}, "ends_at"),
                                 ({"ends_at": "2027-03-15T18:15"}, "ends_at"),
                                 ({"ends_at": "2027-03-16T09:45"}, "ends_at"),
                                 ({"ends_at": ""}, "ends_at"), ({"room": ""}, "room")]:
            with self.subTest(overrides=overrides):
                form = AppointmentForm(self.data(**overrides), company=self.company)
                self.assertFalse(form.is_valid())
                self.assertIn("end_time" if field == "ends_at" else field, form.errors)
        self.booking(starts_at="2027-03-15T08:00", ends_at="2027-03-15T18:00")

    def test_room_patient_and_professional_conflicts_and_adjacent_times(self):
        self.booking()
        form = AppointmentForm(self.data(starts_at="2027-03-15T09:30"), company=self.company)
        self.assertFalse(form.is_valid())
        self.assertIn("ocupado", str(form.errors))
        other_room = Room.objects.create(company=self.company, floor=self.floor, name="Sala 2", opens_at="08:00", closes_at="18:00")
        form = AppointmentForm(self.data(room=other_room.pk), company=self.company)
        self.assertFalse(form.is_valid())
        self.assertIn("paciente", str(form.errors))
        from .models import Patient
        patient = Patient.objects.create(company=self.company, name="Outro", birth_date="2000-01-01", cpf="88888888888", cep="78000000", sex="M", phone_number="65999999999")
        form = AppointmentForm(self.data(room=other_room.pk, patient=patient.pk), company=self.company)
        self.assertFalse(form.is_valid())
        self.assertIn("profissional", str(form.errors))
        self.booking(starts_at="2027-03-15T09:45", ends_at="2027-03-15T10:00")

    def test_blocked_period_rejected_and_rechecked_after_form_validation(self):
        form = AppointmentForm(self.data(), company=self.company)
        self.assertTrue(form.is_valid(), form.errors)
        block = RoomBlock.objects.create(room=self.room, starts_at=self.instant("2027-03-15T08:30"), ends_at=self.instant("2027-03-15T10:00"), reason="Manutenção")
        with self.assertRaisesMessage(ValidationError, "Manutenção"):
            save_appointment(form.save(commit=False))
        invalid = AppointmentForm(self.data(), company=self.company)
        self.assertFalse(invalid.is_valid())
        block.is_active = False
        block.save()
        self.booking()

    def test_block_cannot_hide_an_existing_appointment(self):
        self.booking()
        form = RoomBlockForm({"room": self.room.pk, "starts_at": "2027-03-15T08:00", "ends_at": "2027-03-15T10:00", "reason": "Almoço", "is_active": "on"}, company=self.company)
        self.assertFalse(form.is_valid())
        self.assertIn("Reagende", str(form.errors))

    def test_daily_grid_filters_full_hours_prefill_and_no_false_free_slots(self):
        booking = self.booking()
        RoomBlock.objects.create(room=self.room, starts_at=self.instant("2027-03-15T12:00"), ends_at=self.instant("2027-03-15T13:00"), reason="Almoço")
        response = self.client.get(reverse("chorompo:appointments"), {"date": "2027-03-15", "floor": self.floor.pk})
        self.assertEqual(response.context["appointment_count"], 1)
        self.assertContains(response, "08:00")
        self.assertContains(response, "18:00")
        self.assertContains(response, "Almoço")
        self.assertContains(response, "width: 100.000%")
        column = response.context["columns"][0]
        self.assertNotIn("09:00", [slot["label"] for slot in column["slots"]])
        self.assertNotIn("12:00", [slot["label"] for slot in column["slots"]])
        slot = column["slots"][0]
        form = self.client.get(slot["url"]).context["form"]
        self.assertEqual(str(form["room"].value()), str(self.room.pk))
        self.assertEqual(form["starts_at"].value(), "2027-03-15T08:00")
        self.assertEqual(self.client.get(reverse("chorompo:appointments"), {"date": "2027-03-16"}).context["appointment_count"], 0)
        filtered = self.client.get(reverse("chorompo:appointments"), {"date": "2027-03-15", "q": "inexistente"})
        self.assertEqual(filtered.context["appointment_count"], 0)
        self.assertContains(filtered, self.patient.name)
        self.assertContains(filtered, "event-muted")

    def test_multiday_block_is_clipped_but_visible(self):
        RoomBlock.objects.create(room=self.room, starts_at=self.instant("2027-03-14T17:00"), ends_at=self.instant("2027-03-16T10:00"), reason="Feriado")
        response = self.client.get(reverse("chorompo:appointments"), {"date": "2027-03-15"})
        self.assertContains(response, "Feriado")
        self.assertEqual(response.context["columns"][0]["slots"], [])
        self.assertEqual(response.context["timeline_height"], 2880)

    def test_short_free_gap_remains_clickable_after_manual_end(self):
        self.booking(ends_at="2027-03-15T09:50")
        response = self.client.get(reverse("chorompo:appointments"), {"date": "2027-03-15"})
        slots = response.context["columns"][0]["slots"]
        self.assertTrue(any(slot["label"] == "09:50" for slot in slots))

    def test_room_deactivation_is_rechecked_after_form_validation(self):
        form = AppointmentForm(self.data(), company=self.company)
        self.assertTrue(form.is_valid(), form.errors)
        Room.objects.filter(pk=self.room.pk).update(is_active=False)
        with self.assertRaisesMessage(ValidationError, "desativado"):
            save_appointment(form.save(commit=False))

    def test_cancel_preserves_audit_releases_room_and_session(self):
        purchase = acquire_treatment(company=self.company, patient=self.patient, catalog=self.catalog, qty_sessions=1, discount_percentage=Decimal(0))
        session = purchase.sessions.first()
        booking = self.booking(treatment=purchase.pk, session=session.pk)
        self.client.post(reverse("chorompo:appointment_remove", args=[booking.pk]))
        booking.refresh_from_db()
        self.assertIsNotNone(booking.canceled_at)
        self.assertEqual(booking.canceled_session_id, session.pk)
        self.assertIsNone(booking.session_id)
        self.assertEqual(self.client.get(reverse("chorompo:appointment_edit", args=[booking.pk])).status_code, 404)
        self.booking(treatment=purchase.pk, session=session.pk)

    def test_floor_room_crud_and_soft_deactivation_preserves_history(self):
        create = reverse("chorompo:agenda_setting_create", args=["piso"])
        self.assertRedirects(self.client.post(create, {"name": "Piso 2", "is_active": "on"}), reverse("chorompo:agenda_settings"))
        floor = self.company.floors.get(name="Piso 2")
        response = self.client.post(reverse("chorompo:agenda_setting_create", args=["sala"]), {"name": "Laser", "floor": floor.pk, "opens_at": "07:30", "closes_at": "19:00", "color": "#3465aa", "is_active": "on"})
        self.assertEqual(response.status_code, 302)
        booking = self.booking()
        self.client.post(reverse("chorompo:agenda_setting_edit", args=["piso", self.floor.pk]), {"name": "Térreo"})
        booking.refresh_from_db()
        self.assertEqual(booking.room_id, self.room.pk)
        form = AppointmentForm(self.data(starts_at="2027-03-15T10:00", ends_at="2027-03-15T11:00"), company=self.company)
        self.assertFalse(form.is_valid())
        self.assertContains(self.client.get(reverse("chorompo:appointments"), {"date": "2027-03-15"}), self.patient.name)

    def test_room_hours_change_cannot_invalidate_future_booking(self):
        tomorrow = timezone.localdate() + timedelta(days=1)
        self.booking(starts_at=f"{tomorrow}T09:00", ends_at=f"{tomorrow}T09:45")
        form = RoomForm({"name": self.room.name, "floor": self.floor.pk, "opens_at": "10:00", "closes_at": "18:00", "color": "#176f60", "is_active": "on"}, company=self.company, instance=self.room)
        self.assertTrue(form.is_valid(), form.errors)
        with self.assertRaisesMessage(ValidationError, "Reagende"):
            save_configuration(form, self.company)

    def test_search_is_paginated_and_scoped_to_clinic_and_patient(self):
        from .models import Patient
        Patient.objects.bulk_create([Patient(company=self.company, name=f"Maria {i:02d}", birth_date="2000-01-01", cpf=f"{i:011d}", cep="78000000", sex="F", phone_number="65988888888") for i in range(25)])
        url = reverse("chorompo:agenda_search")
        data = self.client.get(url, {"kind": "patient", "q": "Maria"}).json()
        self.assertEqual(len(data["results"]), 20)
        self.assertTrue(data["more"])
        self.assertEqual(len(self.client.get(url, {"kind": "patient", "q": "Maria", "page": 2}).json()["results"]), 5)
        self.assertEqual(self.client.get(url, {"kind": "patient", "q": self.foreign_patient.name}).json()["results"], [])
        acquire_treatment(company=self.company, patient=self.patient, catalog=self.catalog, qty_sessions=1, discount_percentage=Decimal(0))
        self.assertEqual(self.client.get(url, {"kind": "treatment", "patient": self.foreign_patient.pk}).json()["results"], [])
        result = self.client.get(url, {"kind": "treatment", "patient": self.patient.pk}).json()["results"][0]
        self.assertIn("Aquisição #", result["label"])
        self.assertEqual(result["duration"], 30)

    def test_foreign_configuration_and_role_access_are_rejected(self):
        foreign_floor = Floor.objects.create(company=self.other, name="Externo")
        foreign_room = Room.objects.create(company=self.other, floor=foreign_floor, name="Externa", opens_at="08:00", closes_at="18:00")
        self.assertFalse(AppointmentForm(self.data(room=foreign_room.pk), company=self.company).is_valid())
        self.assertEqual(self.client.get(reverse("chorompo:agenda_setting_edit", args=["sala", foreign_room.pk])).status_code, 404)
        form = RoomForm({"name": "Ataque", "floor": foreign_floor.pk, "opens_at": "08:00", "closes_at": "18:00", "color": "#176f60"}, company=self.company)
        self.assertFalse(form.is_valid())
        self.membership.role = "RECEPTION"
        self.membership.save()
        self.assertEqual(self.client.get(reverse("chorompo:agenda_settings")).status_code, 403)
        self.assertEqual(self.client.get(reverse("chorompo:agenda_search"), {"kind": "patient"}).status_code, 200)
        self.membership.role = "FINANCIAL"
        self.membership.save()
        self.assertEqual(self.client.get(reverse("chorompo:agenda_search"), {"kind": "patient"}).status_code, 403)

    def test_new_mutations_require_csrf(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        for name, args in [("appointment_create", []), ("agenda_setting_create", ["piso"]), ("agenda_setting_create", ["bloqueio"])]:
            self.assertEqual(client.post(reverse("chorompo:" + name, args=args), self.data()).status_code, 403)

    def recurring(self, **overrides):
        return {"room": self.room.pk, "reason": "Almoço recorrente", "recurrence": "WEEKLY", "starts_at": "2027-03-15T12:00", "ends_at": "2027-03-15T14:00", "weekdays": ["0", "2", "4"], "is_active": "on", **overrides}

    def test_weekly_blocks_apply_only_on_selected_days_and_until_inclusive(self):
        form = RoomBlockForm(self.recurring(repeat_until="2027-03-22"), company=self.company)
        self.assertTrue(form.is_valid(), form.errors)
        save_configuration(form, self.company)
        for day, count in [("2027-03-14", 0), ("2027-03-15", 1), ("2027-03-16", 0), ("2027-03-17", 1), ("2027-03-19", 1), ("2027-03-22", 1), ("2027-03-24", 0)]:
            with self.subTest(day=day):
                response = self.client.get(reverse("chorompo:appointments"), {"date": day})
                self.assertEqual(response.context["block_count"], count)
        blocked = AppointmentForm(self.data(starts_at="2027-03-17T13:00", ends_at="2027-03-17T13:30"), company=self.company)
        self.assertFalse(blocked.is_valid())
        self.assertIn("bloqueada", str(blocked.errors))
        self.booking(starts_at="2027-03-16T13:00", ends_at="2027-03-16T13:30")
        self.booking(starts_at="2027-03-17T14:00", ends_at="2027-03-17T14:30")

    def test_daily_recurrence_indefinite_and_deactivation(self):
        form = RoomBlockForm(self.recurring(recurrence="DAILY", weekdays=[]), company=self.company)
        self.assertTrue(form.is_valid(), form.errors)
        block = save_configuration(form, self.company)
        response = self.client.get(reverse("chorompo:appointments"), {"date": "2028-01-02"})
        self.assertEqual(response.context["block_count"], 1)
        block.is_active = False
        block.save()
        self.assertEqual(self.client.get(reverse("chorompo:appointments"), {"date": "2028-01-02"}).context["block_count"], 0)

    def test_recurrence_validation_and_future_booking_conflicts(self):
        for overrides, field in [({"weekdays": []}, "weekdays"), ({"repeat_until": "2027-03-14"}, "repeat_until"), ({"ends_at": "2027-03-16T14:00"}, "ends_at"), ({"weekdays": [7]}, "weekdays")]:
            form = RoomBlockForm(self.recurring(**overrides), company=self.company)
            self.assertFalse(form.is_valid())
            self.assertIn(field, form.errors)
        self.booking(starts_at="2027-03-17T13:00", ends_at="2027-03-17T13:30")
        invalid = RoomBlockForm(self.recurring(), company=self.company)
        self.assertFalse(invalid.is_valid())
        self.assertIn("17/03/2027", str(invalid.errors))
        valid = RoomBlockForm(self.recurring(weekdays=["1"]), company=self.company)
        self.assertTrue(valid.is_valid(), valid.errors)

    def test_recurrence_is_rechecked_when_saving_after_another_booking(self):
        form = RoomBlockForm(self.recurring(), company=self.company)
        self.assertTrue(form.is_valid(), form.errors)
        self.booking(starts_at="2027-03-19T13:00", ends_at="2027-03-19T13:30")
        with self.assertRaisesMessage(ValidationError, "19/03/2027"):
            save_configuration(form, self.company)

    def move(self, booking, **overrides):
        data = {"room": self.room.pk, "starts_at": "2027-03-15T10:00", "expected_start": booking.starts_at.isoformat(), "expected_end": booking.ends_at.isoformat(), "expected_room": str(booking.room_id or ""), **overrides}
        return self.client.post(reverse("chorompo:appointment_move", args=[booking.pk]), data)

    def test_drag_move_preserves_duration_and_can_change_room(self):
        booking = self.booking()
        other_room = Room.objects.create(company=self.company, floor=self.floor, name="Outra sala", opens_at="08:00", closes_at="18:00")
        response = self.move(booking, room=other_room.pk, starts_at="2027-03-15T15:15")
        self.assertEqual(response.status_code, 200, response.content)
        booking.refresh_from_db()
        self.assertEqual(booking.room_id, other_room.pk)
        self.assertEqual(booking.starts_at, self.instant("2027-03-15T15:15"))
        self.assertEqual(booking.ends_at, self.instant("2027-03-15T16:00"))

    def test_drag_move_rejects_conflicts_hours_and_recurring_blocks(self):
        booking = self.booking()
        self.booking(starts_at="2027-03-15T10:15", ends_at="2027-03-15T10:45")
        for start in ("2027-03-15T10:00", "2027-03-15T07:00", "2027-03-15T17:30"):
            self.assertEqual(self.move(booking, starts_at=start).status_code, 400)
        form = RoomBlockForm(self.recurring(), company=self.company)
        self.assertTrue(form.is_valid(), form.errors)
        save_configuration(form, self.company)
        response = self.move(booking, starts_at="2027-03-17T12:30")
        self.assertEqual(response.status_code, 400)
        booking.refresh_from_db()
        self.assertEqual(booking.starts_at, self.instant("2027-03-15T09:00"))

    def test_drag_move_checks_stale_state_tenant_permissions_and_csrf(self):
        booking = self.booking()
        self.assertEqual(self.move(booking, expected_room="9999").status_code, 409)
        self.assertEqual(self.move(booking, expected_start="bad").status_code, 400)
        foreign_floor = Floor.objects.create(company=self.other, name="Outro piso")
        foreign_room = Room.objects.create(company=self.other, floor=foreign_floor, name="Sala externa", opens_at="08:00", closes_at="18:00")
        self.assertEqual(self.move(booking, room=foreign_room.pk).status_code, 404)
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        url = reverse("chorompo:appointment_move", args=[booking.pk])
        self.assertEqual(client.post(url, {}).status_code, 403)
        self.assertEqual(self.client.get(url).status_code, 405)
        self.membership.role = "FINANCIAL"
        self.membership.save()
        self.assertEqual(self.move(booking).status_code, 403)

    def test_drag_move_rejects_realized_and_canceled_appointments(self):
        purchase = acquire_treatment(company=self.company, patient=self.patient, catalog=self.catalog, qty_sessions=1, discount_percentage=Decimal(0))
        session = purchase.sessions.first()
        booking = self.booking(treatment=purchase.pk, session=session.pk)
        from .treatment_services import record_evolution
        record_evolution(session=session, employee=self.employee, date=timezone.localdate(), notes="Realizado", uses_session=True)
        self.assertEqual(self.move(booking).status_code, 400)
        self.client.post(reverse("chorompo:appointment_remove", args=[booking.pk]))
        self.assertEqual(self.move(booking).status_code, 400)

    def test_treatment_search_available_first_and_zero_highlight_metadata(self):
        zero = acquire_treatment(company=self.company, patient=self.patient, catalog=self.catalog, qty_sessions=1, discount_percentage=Decimal(0))
        free = acquire_treatment(company=self.company, patient=self.patient, catalog=self.catalog, qty_sessions=2, discount_percentage=Decimal(0))
        self.booking(treatment=zero.pk, session=zero.sessions.first().pk)
        url = reverse("chorompo:agenda_search")
        results = self.client.get(url, {"kind": "treatment", "patient": self.patient.pk}).json()["results"]
        self.assertEqual([item["id"] for item in results], [free.pk, zero.pk])
        self.assertEqual([item["available"] for item in results], [2, 0])
        booking = Appointment.objects.get()
        own = self.client.get(url, {"kind": "treatment", "patient": self.patient.pk, "appointment": booking.pk}).json()["results"]
        self.assertEqual(own[1]["available"], 1)

    def test_separate_date_and_time_fields_override_stale_hidden_values(self):
        form = AppointmentForm(self.data(date="2027-03-16", start_time="10:00", end_time="11:00"), company=self.company)
        self.assertTrue(form.is_valid(), form.errors)
        booking = save_appointment(form.save(commit=False))
        self.assertEqual(booking.starts_at, self.instant("2027-03-16T10:00"))
        self.assertEqual(booking.ends_at, self.instant("2027-03-16T11:00"))
