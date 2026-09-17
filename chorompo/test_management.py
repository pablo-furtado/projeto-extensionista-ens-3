from decimal import Decimal

from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from .forms import AppointmentForm
from .models import Appointment
from . import test_treatments
from .treatment_services import acquire_treatment, record_evolution


class ManagementTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        test_treatments.TreatmentFlowTests.setUpTestData.__func__(cls)

    def setUp(self):
        self.client.force_login(self.user)
        self.purchase = acquire_treatment(company=self.company, patient=self.patient, catalog=self.catalog,
                                          qty_sessions=2, discount_percentage=Decimal("10"))
        self.session = self.purchase.sessions.first()

    def booking(self):
        return Appointment.objects.create(company=self.company, patient=self.patient, treatment=self.purchase,
                                          treatment_company=self.catalog, session=self.session,
                                          professional=self.employee, starts_at=timezone.now())

    def test_patient_edit_and_tenant_isolation(self):
        url = reverse("chorompo:patient_edit", args=[self.patient.pk])
        response = self.client.post(url, {"name": "Nome atualizado", "birth_date": "2000-01-01", "cpf": self.patient.cpf,
                                          "cep": "78000000", "sex": "F", "phone_number": "65988888888", "company": self.other.pk})
        self.assertRedirects(response, reverse("chorompo:patients"))
        self.patient.refresh_from_db()
        self.assertEqual(self.patient.name, "Nome atualizado")
        self.assertEqual(self.patient.company, self.company)
        self.assertEqual(self.client.post(reverse("chorompo:patient_edit", args=[self.foreign_patient.pk]), {}).status_code, 404)

    def test_employee_edit_keeps_access_role(self):
        response = self.client.post(reverse("chorompo:employee_edit", args=[self.employee.pk]), {
            "name": "Novo nome", "birth_date": "1990-01-01", "cpf": self.employee.cpf,
            "address": "Rua nova", "cep": "78000000", "role": "RECEPTION",
        })
        self.assertRedirects(response, reverse("chorompo:employees"))
        self.employee.refresh_from_db()
        self.membership.refresh_from_db()
        self.assertEqual(self.employee.name, "Novo nome")
        self.assertEqual(self.membership.role, "ADMIN")

    def test_search_and_pagination_preserve_query(self):
        for url in ("patients", "employees", "treatments", "treatment_purchases"):
            response = self.client.get(reverse("chorompo:" + url), {"q": "inexistente", "page": 9})
            self.assertEqual(response.context["page_obj"].paginator.count, 0)
            self.assertEqual(response.context["filter_query"], "q=inexistente")

    def test_edit_booking_keeps_own_session_and_remove_releases_it(self):
        appointment = self.booking()
        url = reverse("chorompo:appointment_edit", args=[appointment.pk])
        response = self.client.post(url, {"patient": self.patient.pk, "treatment": self.purchase.pk,
                                          "session": self.session.pk, "professional": self.employee.pk,
                                          "starts_at": "2027-03-15T14:30", "notes": "Reagendado"})
        self.assertRedirects(response, reverse("chorompo:appointments") + "?date=2027-03-15")
        appointment.refresh_from_db()
        self.assertEqual(appointment.notes, "Reagendado")
        remove = reverse("chorompo:appointment_remove", args=[appointment.pk])
        self.assertContains(self.client.get(remove), "Remover agendamento?")
        self.assertTrue(Appointment.objects.filter(pk=appointment.pk).exists())
        self.assertRedirects(self.client.post(remove), reverse("chorompo:appointments"))
        self.assertFalse(Appointment.objects.filter(pk=appointment.pk).exists())
        self.assertIn(self.session, AppointmentForm(company=self.company).fields["session"].queryset)

    def test_removal_preserves_clinical_history_and_requires_csrf(self):
        appointment = self.booking()
        record_evolution(session=self.session, employee=self.employee, date=timezone.localdate(), notes="Realizado", uses_session=True)
        url = reverse("chorompo:appointment_remove", args=[appointment.pk])
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        self.assertEqual(client.post(url).status_code, 403)
        self.client.post(url)
        self.session.refresh_from_db()
        self.assertEqual(self.session.session_held, 1)
        self.assertEqual(self.session.evolutions.count(), 1)

    def test_foreign_booking_cannot_be_changed(self):
        appointment = self.booking()
        appointment.company = self.other
        appointment.save(update_fields=["company"])
        for action in ("appointment_edit", "appointment_remove"):
            for method in (self.client.get, self.client.post):
                self.assertEqual(method(reverse("chorompo:" + action, args=[appointment.pk])).status_code, 404)

    def test_week_filters_and_invalid_dates(self):
        self.booking()
        url = reverse("chorompo:appointments")
        self.assertEqual(self.client.get(url).context["appointment_count"], 1)
        self.assertEqual(self.client.get(url, {"date": "2027-03-15"}).context["appointment_count"], 0)
        self.assertEqual(self.client.get(url, {"q": "inexistente"}).context["appointment_count"], 0)
        response = self.client.get(url, {"date": "invalid", "professional": "invalid"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["filters"].errors)

    def test_finance_totals_dates_permissions_and_isolation(self):
        acquire_treatment(company=self.other, patient=self.foreign_patient, catalog=self.foreign_catalog,
                          qty_sessions=5, discount_percentage=Decimal("0"))
        url = reverse("chorompo:finance")
        response = self.client.get(url)
        self.assertEqual(response.context["total"], Decimal("180"))
        self.assertEqual(response.context["sessions_count"], 2)
        self.assertNotContains(response, self.foreign_patient.name)
        self.assertEqual(self.client.get(url, {"start": "2099-01-01"}).context["total"], 0)
        self.assertTrue(self.client.get(url, {"start": "2027-01-01", "end": "2026-01-01"}).context["filters"].errors)
        self.membership.role = "FINANCIAL"
        self.membership.save()
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(self.client.get(reverse("chorompo:appointments")).status_code, 403)
        self.membership.role = "RECEPTION"
        self.membership.save()
        self.assertEqual(self.client.get(url).status_code, 403)
