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
from .models import Appointment, Company, CompanyMembership, Employee, EvolutionOfTreatment, Patient, Treatment, TreatmentCompany, TreatmentPackage, TreatmentSession
from .treatment_services import acquire_treatment, record_evolution


class TreatmentFlowTests(TestCase):
    def test_purchase_form_has_its_own_page_and_saves_package(self):
        listing = self.client.get(reverse("chorompo:treatment_purchases"))
        self.assertNotContains(listing, 'id="package-form"')
        self.assertContains(listing, reverse("chorompo:treatment_purchase_create"))
        page = self.client.get(reverse("chorompo:treatment_purchase_create"))
        self.assertContains(page, 'id="package-form"')
        response = self.client.post(reverse("chorompo:treatment_purchase_create"), self.package_data())
        self.assertRedirects(response, reverse("chorompo:treatment_package_detail", args=[TreatmentPackage.objects.get().pk]))

    def test_settings_separates_catalog_and_employees_from_operations(self):
        response = self.client.get(reverse("chorompo:treatments"))
        self.assertEqual(response.context["active_module"], "treatment_catalog")
        self.assertNotIn("employees", [item["key"] for item in response.context["modules"]])
        self.assertEqual({item["key"] for item in response.context["settings_modules"]}, {"employees", "treatment_catalog"})
        self.assertContains(response, 'class="nav-settings" open')
        self.assertContains(response, reverse("chorompo:treatment_company_create"))
        self.assertNotContains(self.client.get(reverse("chorompo:treatment_purchases")), reverse("chorompo:treatment_company_create"))

    def test_reception_has_no_internal_settings_or_purchase_access(self):
        self.membership.role = "RECEPTION"
        self.membership.save()
        response = self.client.get(reverse("chorompo:patients"))
        self.assertEqual(response.context["settings_modules"], [])
        self.assertNotContains(response, 'class="nav-settings"')
        for method in (self.client.get, self.client.post):
            self.assertEqual(method(reverse("chorompo:treatment_purchase_create")).status_code, 403)

    def package_data(self):
        second = TreatmentCompany.objects.create(company=self.company, name="Pilates do pacote", price=Decimal("80.00"))
        return {
            "patient": self.patient.pk, "name": "Pacote de reabilitação",
            "items-TOTAL_FORMS": "2", "items-INITIAL_FORMS": "0",
            "items-0-treatment": self.catalog.pk, "items-0-qty_sessions": "3", "items-0-discount_percentage": "10",
            "items-1-treatment": second.pk, "items-1-qty_sessions": "2", "items-1-discount_percentage": "0",
        }

    def test_package_creates_all_treatments_and_independent_sessions(self):
        response = self.client.post(reverse("chorompo:treatment_purchases"), self.package_data())
        package = TreatmentPackage.objects.get()
        self.assertRedirects(response, reverse("chorompo:treatment_package_detail", args=[package.pk]))
        self.assertEqual(package.patient, self.patient)
        self.assertEqual(package.company, self.company)
        self.assertEqual(package.total_price, Decimal("430.00"))
        self.assertEqual(package.treatments.count(), 2)
        self.assertEqual(TreatmentSession.objects.count(), 5)
        treatment = package.treatments.get(treatment=self.catalog)
        self.assertEqual(list(treatment.sessions.values_list("session_number", flat=True)), [1, 2, 3])
        record_evolution(session=treatment.sessions.first(), employee=self.employee, date=timezone.localdate(), notes="Realizada", uses_session=True)
        self.assertEqual(treatment.used_sessions, 1)
        self.assertEqual(package.treatments.exclude(pk=treatment.pk).get().used_sessions, 0)
        self.assertContains(self.client.get(reverse("chorompo:treatment_package_detail", args=[package.pk])), "430,00")

    def test_package_invalid_item_preserves_input_and_saves_nothing(self):
        data = self.package_data()
        data["items-1-qty_sessions"] = "0"
        response = self.client.post(reverse("chorompo:treatment_purchases"), data)
        self.assertContains(response, "Pacote de reabilitação")
        self.assertIn("qty_sessions", response.context["formset"].forms[1].errors)
        self.assertFalse(TreatmentPackage.objects.exists())
        self.assertFalse(Treatment.objects.exists())

    def test_package_failure_in_second_item_rolls_back_everything(self):
        from .treatment_services import acquire_treatment
        data = self.package_data()
        calls = 0
        def fail_second(**kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise IntegrityError("second item failed")
            return acquire_treatment(**kwargs)
        with patch("chorompo.treatment_services.acquire_treatment", side_effect=fail_second):
            response = self.client.post(reverse("chorompo:treatment_purchases"), data)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(calls, 2)
        self.assertFalse(TreatmentPackage.objects.exists())
        self.assertFalse(Treatment.objects.exists())
        self.assertFalse(TreatmentSession.objects.exists())

    def test_package_rejects_duplicate_and_foreign_treatments(self):
        data = self.package_data()
        for catalog in [self.catalog, self.foreign_catalog]:
            data["items-1-treatment"] = catalog.pk
            response = self.client.post(reverse("chorompo:treatment_purchases"), data)
            self.assertEqual(response.status_code, 200)
            self.assertFalse(TreatmentPackage.objects.exists())

    def test_package_deleted_item_is_not_purchased(self):
        data = self.package_data()
        data["items-1-DELETE"] = "on"
        response = self.client.post(reverse("chorompo:treatment_purchases"), data)
        package = TreatmentPackage.objects.get()
        self.assertRedirects(response, reverse("chorompo:treatment_package_detail", args=[package.pk]))
        self.assertEqual(package.treatments.count(), 1)
        self.assertEqual(package.total_price, Decimal("270.00"))

    def test_package_requires_patient_from_clinic_and_management_form(self):
        data = self.package_data()
        data["patient"] = self.foreign_patient.pk
        response = self.client.post(reverse("chorompo:treatment_purchases"), data)
        self.assertIn("patient", response.context["form"].errors)
        data["patient"] = self.patient.pk
        del data["items-TOTAL_FORMS"]
        response = self.client.post(reverse("chorompo:treatment_purchases"), data)
        self.assertTrue(response.context["formset"].non_form_errors())
        self.assertFalse(TreatmentPackage.objects.exists())

    def test_foreign_package_is_not_accessible(self):
        package = TreatmentPackage.objects.create(company=self.other, patient=self.foreign_patient)
        self.assertEqual(self.client.get(reverse("chorompo:treatment_package_detail", args=[package.pk])).status_code, 404)

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
        self.assertRedirects(response, reverse("chorompo:appointments") + "?date=2027-01-01")
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
