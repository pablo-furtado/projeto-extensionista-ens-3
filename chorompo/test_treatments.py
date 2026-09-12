from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from .forms import AppointmentForm
from .models import Appointment, Company, CompanyMembership, Employee, EvolutionOfTreatment, Patient, Treatment, TreatmentCompany, TreatmentSession
from .treatment_services import acquire_treatment, record_evolution


class TreatmentFlowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Clínica A", cpf_cnpj="11222333000181", cep="78000000", phone_number="65999999999", email="a@example.com", onboarding_completed=True)
        cls.other = Company.objects.create(name="Clínica B", cpf_cnpj="52998224725", cep="78000000", phone_number="65999999999", email="b@example.com", onboarding_completed=True)
        cls.user = User.objects.create_user("admin.tratamentos", "admin@example.com")
        cls.membership = CompanyMembership.objects.create(user=cls.user, company=cls.company, role="ADMIN")
        cls.employee = Employee.objects.create(membership=cls.membership, name="Profissional A", birth_date="1990-01-01", cpf="11122233344", address="Rua A", cep="78000000")
        cls.patient = Patient.objects.create(company=cls.company, name="Paciente A", birth_date="2000-01-01", cpf="22233344455", cep="78000000", sex="F", phone_number="65999999999")
        cls.foreign_patient = Patient.objects.create(company=cls.other, name="Paciente confidencial", birth_date="2000-01-01", cpf="33344455566", cep="78000000", sex="F", phone_number="65999999999")
        cls.catalog = TreatmentCompany.objects.create(company=cls.company, name="Fisioterapia", description="Atendimento individual", price=Decimal("100.00"), max_discount_percentage=Decimal("10.00"))
        cls.foreign_catalog = TreatmentCompany.objects.create(company=cls.other, name="Catálogo confidencial", price=Decimal("100.00"))

    def setUp(self):
        self.client.force_login(self.user)

    def purchase(self, **kwargs):
        return acquire_treatment(**{
            "company": self.company, "patient": self.patient, "catalog": self.catalog,
            "qty_sessions": 3, "discount_percentage": Decimal("10.00"), **kwargs,
        })

    def evolution_data(self, **kwargs):
        return {"date": timezone.localdate().isoformat(), "notes": "Paciente relata melhora após a sessão.", "uses_session": "on", **kwargs}

    def test_catalog_page_saves_financial_fields_for_current_company(self):
        response = self.client.post(reverse("chorompo:treatments"), {
            "name": "Pilates", "description": "Sessão individual", "duration_minutes": 50,
            "price": "120.00", "fixed_cost": "10.00", "variable_cost": "15.00", "max_discount_percentage": "20.00", "company": self.other.pk,
        })
        self.assertRedirects(response, reverse("chorompo:treatments"))
        item = TreatmentCompany.objects.get(name="Pilates")
        self.assertEqual(item.company, self.company)
        self.assertEqual(item.price, Decimal("120.00"))
        self.assertEqual(item.fixed_cost, Decimal("10.00"))
        self.assertFalse(Treatment.objects.exists())
        self.assertNotContains(self.client.get(reverse("chorompo:treatments")), "Catálogo confidencial")

    def test_invalid_catalog_values_are_rejected(self):
        response = self.client.post(reverse("chorompo:treatments"), {
            "name": "Inválido", "duration_minutes": 0, "price": "-1", "fixed_cost": "-1", "variable_cost": "-1", "max_discount_percentage": "101",
        })
        self.assertEqual(set(response.context["form"].errors), {"duration_minutes", "price", "fixed_cost", "variable_cost", "max_discount_percentage"})
        self.assertFalse(TreatmentCompany.objects.filter(name="Inválido").exists())

    def test_catalog_edit_keeps_purchase_snapshot_and_blocks_foreign_items(self):
        treatment = self.purchase()
        response = self.client.post(reverse("chorompo:treatment_company_edit", args=[self.catalog.pk]), {
            "name": "Nome atualizado", "duration_minutes": 60, "price": "250.00", "max_discount_percentage": "20.00", "company": self.other.pk,
        })
        self.assertRedirects(response, reverse("chorompo:treatments"))
        self.catalog.refresh_from_db()
        self.assertEqual(self.catalog.price, Decimal("250.00"))
        self.assertEqual(self.catalog.company, self.company)
        treatment.refresh_from_db()
        self.assertEqual(treatment.name, "Fisioterapia")
        self.assertEqual(treatment.price, Decimal("270.00"))
        for method in [self.client.get, self.client.post]:
            self.assertEqual(method(reverse("chorompo:treatment_company_edit", args=[self.foreign_catalog.pk])).status_code, 404)

    def test_acquisition_creates_numbered_sessions_and_price_snapshot(self):
        response = self.client.post(reverse("chorompo:treatment_purchases"), {
            "patient": self.patient.pk, "treatment": self.catalog.pk, "qty_sessions": 3, "discount_percentage": "10.00", "price": "0", "company": self.other.pk,
        })
        treatment = Treatment.objects.get()
        self.assertRedirects(response, reverse("chorompo:treatment_detail", args=[treatment.pk]))
        self.assertEqual(treatment.company, self.company)
        self.assertEqual(treatment.patient, self.patient)
        self.assertEqual(treatment.treatment, self.catalog)
        self.assertEqual(treatment.price, Decimal("270.00"))
        self.assertEqual(list(treatment.sessions.values_list("session_number", flat=True)), [1, 2, 3])
        self.assertEqual(treatment.remaining_sessions, 3)
        self.catalog.name = "Novo nome"
        self.catalog.price = Decimal("200.00")
        self.catalog.save()
        treatment.refresh_from_db()
        self.assertEqual(treatment.name, "Fisioterapia")
        self.assertEqual(treatment.price, Decimal("270.00"))
        self.assertContains(self.client.get(reverse("chorompo:treatment_purchases")), "Paciente A")

    def test_invalid_quantities_and_excessive_discount_are_rejected(self):
        for quantity, discount in [(0, "0"), (1001, "0"), (1, "11")]:
            response = self.client.post(reverse("chorompo:treatment_purchases"), {
                "patient": self.patient.pk, "treatment": self.catalog.pk, "qty_sessions": quantity, "discount_percentage": discount,
            })
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.context["form"].errors)
        self.assertFalse(Treatment.objects.exists())
        self.assertFalse(TreatmentSession.objects.exists())

    def test_cannot_purchase_for_foreign_patient_or_catalog(self):
        response = self.client.post(reverse("chorompo:treatment_purchases"), {
            "patient": self.foreign_patient.pk, "treatment": self.foreign_catalog.pk, "qty_sessions": 1, "discount_percentage": "0",
        })
        self.assertIn("patient", response.context["form"].errors)
        self.assertIn("treatment", response.context["form"].errors)
        self.assertFalse(Treatment.objects.exists())

    def test_session_creation_failure_rolls_back_purchase(self):
        with patch("chorompo.treatment_services.TreatmentSession.objects.bulk_create", side_effect=IntegrityError):
            with self.assertRaises(IntegrityError):
                self.purchase()
        self.assertFalse(Treatment.objects.exists())

    def test_evolution_consumes_one_session_and_preserves_author(self):
        treatment = self.purchase()
        session = treatment.sessions.first()
        response = self.client.post(reverse("chorompo:session_detail", args=[session.pk]), self.evolution_data(employee=9999, treatment=9999))
        self.assertRedirects(response, reverse("chorompo:session_detail", args=[session.pk]))
        session.refresh_from_db()
        self.assertEqual(session.session_held, 1)
        self.assertEqual(session.date, timezone.localdate())
        self.assertEqual(treatment.remaining_sessions, 2)
        evolution = EvolutionOfTreatment.objects.get()
        self.assertEqual(evolution.employee, self.employee)
        self.assertEqual(evolution.treatment, session)
        self.assertTrue(evolution.uses_session)
        self.assertContains(self.client.get(reverse("chorompo:treatment_detail", args=[treatment.pk])), "Realizada")

    def test_complementary_evolution_does_not_consume_again(self):
        treatment = self.purchase()
        session = treatment.sessions.first()
        url = reverse("chorompo:session_detail", args=[session.pk])
        self.client.post(url, self.evolution_data())
        response = self.client.post(url, self.evolution_data(uses_session="", notes="Complemento do atendimento."))
        self.assertRedirects(response, url)
        self.assertEqual(session.evolutions.count(), 2)
        self.assertEqual(treatment.used_sessions, 1)
        self.assertContains(self.client.get(url), "Complemento do atendimento.")

    def test_duplicate_consumption_and_stale_session_are_rejected(self):
        treatment = self.purchase()
        session = treatment.sessions.first()
        url = reverse("chorompo:session_detail", args=[session.pk])
        self.client.post(url, self.evolution_data())
        response = self.client.post(url, self.evolution_data())
        self.assertContains(response, "Esta sessão já foi utilizada.")
        with self.assertRaises(ValidationError):
            record_evolution(session=session, employee=self.employee, date=timezone.localdate(), notes="Reenvio", uses_session=True)
        self.assertEqual(session.evolutions.count(), 1)
        self.assertEqual(treatment.used_sessions, 1)

    def test_future_or_blank_evolution_cannot_consume_session(self):
        treatment = self.purchase()
        session = treatment.sessions.first()
        response = self.client.post(reverse("chorompo:session_detail", args=[session.pk]), self.evolution_data(date=(timezone.localdate() + timedelta(days=1)).isoformat(), notes=" "))
        self.assertEqual(set(response.context["form"].errors), {"date", "notes"})
        self.assertFalse(EvolutionOfTreatment.objects.exists())
        self.assertEqual(treatment.used_sessions, 0)

    def test_session_save_failure_rolls_back_evolution(self):
        session = self.purchase().sessions.first()
        with patch("chorompo.models.TreatmentSession.save", side_effect=IntegrityError):
            with self.assertRaises(IntegrityError):
                record_evolution(session=session, employee=self.employee, date=timezone.localdate(), notes="Registro", uses_session=True)
        self.assertFalse(EvolutionOfTreatment.objects.exists())
        session.refresh_from_db()
        self.assertEqual(session.session_held, 0)

    def test_purchase_and_session_from_other_company_are_not_accessible(self):
        treatment = self.purchase(company=self.other, patient=self.foreign_patient, catalog=self.foreign_catalog, discount_percentage=Decimal("0"))
        session = treatment.sessions.first()
        for method in [self.client.get, self.client.post]:
            self.assertEqual(method(reverse("chorompo:session_detail", args=[session.pk]), self.evolution_data()).status_code, 404)
        self.assertEqual(self.client.get(reverse("chorompo:treatment_detail", args=[treatment.pk])).status_code, 404)
        self.assertNotContains(self.client.get(reverse("chorompo:treatment_purchases")), "Paciente confidencial")
        with self.assertRaises(PermissionDenied):
            record_evolution(session=session, employee=self.employee, date=timezone.localdate(), notes="Inválido", uses_session=True)

    def test_non_clinical_role_cannot_read_or_write_evolution(self):
        session = self.purchase().sessions.first()
        self.membership.role = "RECEPTION"
        self.membership.save()
        for method in [self.client.get, self.client.post]:
            self.assertEqual(method(reverse("chorompo:session_detail", args=[session.pk]), self.evolution_data()).status_code, 403)
        self.assertEqual(self.client.get(reverse("chorompo:treatment_purchases")).status_code, 403)
        self.assertFalse(EvolutionOfTreatment.objects.exists())

    def test_session_identity_and_quantity_are_not_editable_by_post(self):
        treatment = self.purchase()
        session = treatment.sessions.first()
        self.client.post(reverse("chorompo:session_detail", args=[session.pk]), self.evolution_data(session_number=999, qty_sessions=999, session_held=999))
        session.refresh_from_db()
        treatment.refresh_from_db()
        self.assertEqual(session.session_number, 1)
        self.assertEqual(session.session_held, 1)
        self.assertEqual(treatment.qty_sessions, 3)

    def test_appointment_must_match_patient_purchase_and_session(self):
        treatment = self.purchase()
        another = self.purchase()
        form = AppointmentForm({"patient": self.patient.pk, "treatment": treatment.pk, "session": another.sessions.first().pk, "professional": self.employee.pk, "starts_at": "2027-01-01T10:00"}, company=self.company)
        self.assertFalse(form.is_valid())
        self.assertIn("session", form.errors)
        other_patient = Patient.objects.create(company=self.company, name="Outro paciente", birth_date="2000-01-01", cpf="44455566677", cep="78000000", sex="M", phone_number="65999999999")
        form = AppointmentForm({"patient": other_patient.pk, "treatment": treatment.pk, "session": treatment.sessions.first().pk, "professional": self.employee.pk, "starts_at": "2027-01-01T10:00"}, company=self.company)
        self.assertFalse(form.is_valid())
        self.assertIn("treatment", form.errors)

    def test_booking_does_not_consume_session_and_cannot_be_duplicated(self):
        treatment = self.purchase()
        session = treatment.sessions.first()
        data = {"patient": self.patient.pk, "treatment": treatment.pk, "session": session.pk, "professional": self.employee.pk, "starts_at": "2027-01-01T10:00"}
        response = self.client.post(reverse("chorompo:appointments"), data)
        self.assertRedirects(response, reverse("chorompo:appointments"))
        self.assertEqual(treatment.used_sessions, 0)
        self.assertContains(self.client.get(reverse("chorompo:treatment_detail", args=[treatment.pk])), "Agendada")
        response = self.client.post(reverse("chorompo:appointments"), data)
        self.assertEqual(response.status_code, 200)
        self.assertIn("session", response.context["form"].errors)
        self.assertEqual(Appointment.objects.count(), 1)

    def test_used_session_cannot_be_booked(self):
        treatment = self.purchase()
        session = treatment.sessions.first()
        record_evolution(session=session, employee=self.employee, date=timezone.localdate(), notes="Realizada", uses_session=True)
        response = self.client.post(reverse("chorompo:appointments"), {"patient": self.patient.pk, "treatment": treatment.pk, "session": session.pk, "professional": self.employee.pk, "starts_at": "2027-01-01T10:00"})
        self.assertIn("session", response.context["form"].errors)
        self.assertFalse(Appointment.objects.exists())

    def test_legacy_appointment_is_still_displayed(self):
        Appointment.objects.create(company=self.company, patient=self.patient, treatment_company=self.catalog, professional=self.employee, starts_at=timezone.now())
        response = self.client.get(reverse("chorompo:appointments"))
        self.assertContains(response, "Fisioterapia")
        self.assertContains(response, "Agendamento anterior ao controle de sessões")

    def test_posts_require_csrf(self):
        session = self.purchase().sessions.first()
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        for url in [reverse("chorompo:treatments"), reverse("chorompo:treatment_purchases"), reverse("chorompo:session_detail", args=[session.pk])]:
            self.assertEqual(client.post(url, {}).status_code, 403)
