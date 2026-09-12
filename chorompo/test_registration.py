from unittest.mock import patch
from io import StringIO

from django.contrib.auth.models import User
from django.core import mail
from django.db import IntegrityError
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from .forms import AppointmentForm
from .models import Appointment, Company, CompanyMembership, Employee, Patient, Treatment, TreatmentCompany, TreatmentSession
from .registration import company_from_token, registration_token


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class RegistrationFlowTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Clínica Aurora", cpf_cnpj="11222333000181", cep="78000000", phone_number="65999999999", email="clinica@example.com")
        self.profile = {
            "name": "Ana Silva", "birth_date": "1990-01-15", "cpf": "529.982.247-25", "address": "Rua das Flores, 10", "cep": "78000-000",
            "username": "ana.admin", "email": "ataque@example.com", "password1": "Clinica!2468Segura", "password2": "Clinica!2468Segura",
        }

    def grant(self, client=None):
        client = client or self.client
        session = client.session
        session["registration_grant"] = registration_token(self.company)
        session.save()

    def create_admin(self):
        self.grant()
        return self.client.post(reverse("chorompo:administrator_create"), self.profile)

    def test_new_email_goes_to_company_form(self):
        response = self.client.post(reverse("chorompo:registration_start"), {"email": "nova@example.com"})
        self.assertRedirects(response, reverse("chorompo:company_create"))
        self.assertEqual(self.client.session["registration_email"], "nova@example.com")

    def test_existing_company_requires_email_confirmation(self):
        response = self.client.post(reverse("chorompo:company_create"), {"email": "CLINICA@example.com"})
        self.assertRedirects(response, reverse("chorompo:registration_start"))
        self.assertNotIn("registration_grant", self.client.session)
        response = self.client.post(reverse("chorompo:registration_start"), {"email": "CLINICA@example.com"})
        self.assertContains(response, "Confira seu e-mail")
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [self.company.email])
        link = next(line for line in mail.outbox[0].body.splitlines() if line.startswith("http"))
        response = self.client.get(link)
        self.assertRedirects(response, reverse("chorompo:administrator_create"))

    def test_email_resend_cooldown(self):
        for _ in range(2):
            response = self.client.post(reverse("chorompo:registration_start"), {"email": self.company.email})
        self.assertEqual(len(mail.outbox), 1)
        self.assertContains(response, "Aguarde um minuto")

    def test_mail_failure_does_not_authorize_registration(self):
        with patch("chorompo.views.send_mail", side_effect=OSError):
            response = self.client.post(reverse("chorompo:registration_start"), {"email": self.company.email})
        self.assertContains(response, "Não foi possível enviar")
        self.assertNotIn("registration_grant", self.client.session)

    def test_profile_without_grant_is_blocked(self):
        response = self.client.post(reverse("chorompo:administrator_create"), {**self.profile, "company": self.company.pk})
        self.assertRedirects(response, reverse("chorompo:registration_start"))
        self.assertFalse(User.objects.exists())

    def test_invalid_and_expired_tokens(self):
        self.assertIsNone(company_from_token("forged"))
        with patch("django.core.signing.time.time", return_value=1):
            expired = registration_token(self.company)
        self.assertIsNone(company_from_token(expired))
        response = self.client.get(reverse("chorompo:registration_verify", args=[expired]))
        self.assertRedirects(response, reverse("chorompo:registration_start"))
        self.assertNotIn("registration_grant", self.client.session)

    @override_settings(EMAIL_BACKEND="chorompo.mail_backends.ReadableConsoleEmailBackend")
    def test_console_link_is_complete_and_opens_administrator_form(self):
        # Long links and accented text must remain copyable from the terminal.
        self.company.email = "cadastro.administrador.clinica@exemplo.com.br"
        self.company.save()
        stream = StringIO()
        with patch("sys.stdout", stream):
            response = self.client.post(reverse("chorompo:registration_start"), {"email": self.company.email})
        self.assertContains(response, "Confira seu e-mail")
        output = stream.getvalue()
        self.assertIn("clínica", output)
        self.assertNotIn("cl=C3=ADnica", output)
        links = [line for line in output.splitlines() if line.startswith("http")]
        self.assertEqual(len(links), 1)
        self.assertGreater(len(links[0]), 78)
        self.assertNotIn("=", links[0])
        self.assertTrue(links[0].endswith("/"))
        self.assertRedirects(self.client.get(links[0]), reverse("chorompo:administrator_create"))

    def test_truncated_link_is_reported_as_incomplete_not_expired(self):
        token = registration_token(self.company)[:72] + "="
        response = self.client.get(reverse("chorompo:registration_verify", args=[token]), follow=True)
        self.assertContains(response, "O link está inválido ou incompleto.")
        self.assertNotContains(response, "Este link expirou")
        self.assertNotIn("registration_grant", self.client.session)

    def test_expired_link_has_specific_message(self):
        with patch("django.core.signing.time.time", return_value=1):
            token = registration_token(self.company)
        response = self.client.get(reverse("chorompo:registration_verify", args=[token]), follow=True)
        self.assertContains(response, "Este link expirou.")
        self.assertNotIn("registration_grant", self.client.session)

    def test_admin_profile_creates_user_membership_employee_and_logs_in(self):
        response = self.create_admin()
        self.assertRedirects(response, reverse("chorompo:onboarding"))
        user = User.objects.get()
        self.assertTrue(user.check_password(self.profile["password1"]))
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertEqual(user.email, self.company.email)
        self.assertEqual(self.client.session["_auth_user_id"], str(user.pk))
        self.assertNotIn("registration_grant", self.client.session)
        membership = CompanyMembership.objects.get(user=user)
        self.assertEqual(membership.role, CompanyMembership.Role.ADMIN)
        self.assertEqual(membership.company, self.company)
        self.assertEqual(membership.employee.cpf, "52998224725")
        self.assertEqual(membership.employee.cep, "78000000")

    def test_weak_password_does_not_create_partial_account(self):
        self.grant()
        response = self.client.post(reverse("chorompo:administrator_create"), {**self.profile, "password1": "123", "password2": "123"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("password2", response.context["account_form"].errors)
        self.assertFalse(User.objects.exists())
        self.assertFalse(Employee.objects.exists())

    def test_employee_failure_rolls_back_entire_account(self):
        self.grant()
        with patch("chorompo.models.Employee.save", side_effect=IntegrityError):
            response = self.client.post(reverse("chorompo:administrator_create"), self.profile)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.exists())
        self.assertFalse(CompanyMembership.objects.exists())

    def test_second_session_cannot_create_another_initial_admin(self):
        other = Client()
        self.grant(other)
        token = registration_token(self.company)
        self.create_admin()
        response = other.post(reverse("chorompo:administrator_create"), {**self.profile, "username": "outro"})
        self.assertRedirects(response, reverse("chorompo:registration_start"))
        self.assertEqual(User.objects.count(), 1)
        self.assertIsNone(company_from_token(token))
        response = other.post(reverse("chorompo:registration_start"), {"email": self.company.email})
        self.assertRedirects(response, reverse("chorompo:login"))

    def test_onboarding_is_required_and_completed_once(self):
        self.create_admin()
        self.assertRedirects(self.client.get(reverse("chorompo:dashboard")), reverse("chorompo:onboarding"))
        response = self.client.post(reverse("chorompo:onboarding"), {
            "name": self.company.name, "cpf_cnpj": self.company.cpf_cnpj, "cep": self.company.cep,
            "phone_number": self.company.phone_number, "email": self.company.email,
        })
        self.assertRedirects(response, reverse("chorompo:dashboard"))

        self.company.refresh_from_db()
        self.assertTrue(self.company.onboarding_completed)
        self.assertRedirects(self.client.get(reverse("chorompo:onboarding")), reverse("chorompo:dashboard"))
        for name in ["patients", "treatments", "appointments", "employees"]:
            self.assertEqual(self.client.get(reverse(f"chorompo:{name}")).status_code, 200)
        self.client.post(reverse("chorompo:logout"))
        response = self.client.post(reverse("chorompo:login"), {"username": self.profile["username"], "password": self.profile["password1"]})
        self.assertRedirects(response, reverse("chorompo:dashboard"))

    def test_existing_membership_is_rechecked_inside_transaction(self):
        self.create_admin()
        User.objects.update(email="outro-endereco@example.com")
        other = Client()
        # Simulate a grant read before another request finished creating a member.
        with patch("chorompo.views.company_from_token", return_value=self.company):
            response = other.post(reverse("chorompo:administrator_create"), {
                **self.profile, "username": "outro.admin", "cpf": "12345678901",
            })
        self.assertRedirects(response, reverse("chorompo:login"))
        self.assertEqual(CompanyMembership.objects.count(), 1)
        self.assertEqual(User.objects.count(), 1)


class PlatformAccessTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Clínica A", cpf_cnpj="11222333000181", cep="78000000", phone_number="65999999999", email="a@example.com", onboarding_completed=True)
        self.other = Company.objects.create(name="Clínica B", cpf_cnpj="52998224725", cep="78000000", phone_number="65999999999", email="b@example.com", onboarding_completed=True)
        self.admin = User.objects.create_user("admin", "admin@example.com", "Segura!2468Senha")
        self.membership = CompanyMembership.objects.create(user=self.admin, company=self.company, role="ADMIN")
        self.employee = Employee.objects.create(membership=self.membership, name="Administrador", birth_date="1990-01-01", cpf="11122233344", address="Rua A", cep="78000000")
        self.client.force_login(self.admin)

    def patient(self, company, name, cpf):
        return Patient.objects.create(company=company, name=name, cpf=cpf, birth_date="2000-01-01", cep="78000000", sex="F", phone_number="65999999999")

    def test_modules_require_login(self):
        client = Client()
        for name in ["dashboard", "onboarding", "patients", "treatments", "appointments", "employees"]:
            response = client.get(reverse(f"chorompo:{name}"))
            self.assertEqual(response.status_code, 302)
            self.assertTrue(response.url.startswith(reverse("chorompo:login")))

    def test_lists_do_not_expose_other_clinic(self):
        self.patient(self.company, "Paciente visível", "22233344455")
        self.patient(self.other, "Paciente confidencial", "33344455566")
        TreatmentCompany.objects.create(company=self.other, name="Tratamento confidencial")
        response = self.client.get(reverse("chorompo:patients"))
        self.assertContains(response, "Paciente visível")
        self.assertNotContains(response, "Paciente confidencial")
        self.assertNotContains(self.client.get(reverse("chorompo:treatments")), "Tratamento confidencial")

    def test_posted_company_cannot_change_record_owner(self):
        response = self.client.post(reverse("chorompo:patients"), {
            "name": "Paciente novo", "birth_date": "2000-01-01", "cpf": "529.982.247-25", "cep": "78000-000", "sex": "F", "phone_number": "(65) 99999-9999", "company": self.other.pk,
        })
        self.assertRedirects(response, reverse("chorompo:patients"))
        self.assertEqual(Patient.objects.get().company, self.company)
        response = self.client.post(reverse("chorompo:treatments"), {"name": "Consulta", "duration_minutes": 30, "price": "100.00", "company": self.other.pk})
        self.assertRedirects(response, reverse("chorompo:treatments"))
        self.assertEqual(TreatmentCompany.objects.get().company, self.company)

    def test_appointment_rejects_other_clinic_relations(self):
        foreign_patient = self.patient(self.other, "Paciente externo", "33344455566")
        catalog = TreatmentCompany.objects.create(company=self.other, name="Externo")
        foreign_treatment = Treatment.objects.create(company=self.other, patient=foreign_patient, treatment=catalog, name="Externo")
        form = AppointmentForm({"patient": foreign_patient.pk, "treatment": foreign_treatment.pk, "professional": self.employee.pk, "starts_at": "2027-01-10T10:00"}, company=self.company)
        self.assertFalse(form.is_valid())
        self.assertIn("patient", form.errors)
        self.assertIn("treatment", form.errors)
        self.assertFalse(Appointment.objects.exists())

    def test_appointment_saves_for_current_clinic(self):
        patient = self.patient(self.company, "Paciente A", "22233344455")
        catalog = TreatmentCompany.objects.create(company=self.company, name="Consulta")
        treatment = Treatment.objects.create(company=self.company, patient=patient, treatment=catalog, name="Consulta")
        session = TreatmentSession.objects.create(treatment=treatment, session_number=1)
        response = self.client.post(reverse("chorompo:appointments"), {"patient": patient.pk, "treatment": treatment.pk, "session": session.pk, "professional": self.employee.pk, "starts_at": "2027-01-10T10:00"})
        self.assertRedirects(response, reverse("chorompo:appointments"))
        self.assertEqual(Appointment.objects.get().company, self.company)
        self.assertContains(self.client.get(reverse("chorompo:appointments")), "10/01/2027 10:00")

    def test_admin_can_create_employee_with_login_and_role(self):
        response = self.client.post(reverse("chorompo:employees"), {
            "name": "Recepcionista", "birth_date": "1995-01-01", "cpf": "529.982.247-25", "address": "Rua B", "cep": "78000-000", "role": "RECEPTION",
            "username": "recepcao", "email": "recepcao@example.com", "password1": "Funcionario!2468Seguro", "password2": "Funcionario!2468Seguro", "company": self.other.pk,
        })
        self.assertRedirects(response, reverse("chorompo:employees"))
        employee = Employee.objects.get(name="Recepcionista")
        self.assertEqual(employee.membership.company, self.company)
        self.assertEqual(employee.membership.role, "RECEPTION")
        self.assertTrue(employee.membership.user.check_password("Funcionario!2468Seguro"))
        self.assertEqual(self.client.session["_auth_user_id"], str(self.admin.pk))

    def test_reception_cannot_create_employee_or_escalate_privileges(self):
        self.membership.role = "RECEPTION"
        self.membership.save()
        self.assertEqual(self.client.get(reverse("chorompo:patients")).status_code, 200)
        for method in [self.client.get, self.client.post]:
            self.assertEqual(method(reverse("chorompo:employees"), {"role": "ADMIN"}).status_code, 403)
        self.assertEqual(self.client.get(reverse("chorompo:treatments")).status_code, 403)
        dashboard = self.client.get(reverse("chorompo:dashboard"))
        self.assertNotContains(dashboard, reverse("chorompo:employees"))
        self.assertNotContains(dashboard, reverse("chorompo:treatments"))

    def test_inactive_membership_and_forged_company_are_denied(self):
        self.membership.is_active = False
        self.membership.save()
        self.assertEqual(self.client.get(reverse("chorompo:patients")).status_code, 403)
        self.membership.is_active = True
        self.membership.save()
        session = self.client.session
        session["active_company_id"] = self.other.pk
        session.save()
        self.assertEqual(self.client.get(reverse("chorompo:patients")).status_code, 403)

    def test_post_endpoints_require_csrf(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.admin)
        for name in ["onboarding", "patients", "treatments", "appointments", "employees", "logout"]:
            self.assertEqual(client.post(reverse(f"chorompo:{name}"), {}).status_code, 403)

    def test_non_admin_cannot_complete_onboarding(self):
        self.company.onboarding_completed = False
        self.company.save()
        self.membership.role = "RECEPTION"
        self.membership.save()
        response = self.client.post(reverse("chorompo:onboarding"), {"onboarding_completed": True})
        self.assertContains(response, "O administrador precisa concluir")
        self.company.refresh_from_db()
        self.assertFalse(self.company.onboarding_completed)

    def test_invalid_employee_does_not_leave_user_or_membership(self):
        response = self.client.post(reverse("chorompo:employees"), {
            "name": "Outra pessoa", "birth_date": "1995-01-01", "cpf": self.employee.cpf, "address": "Rua B", "cep": "78000-000", "role": "ADMIN",
            "username": "outra.pessoa", "email": "outra@example.com", "password1": "Funcionario!2468Seguro", "password2": "Funcionario!2468Seguro",
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn("cpf", response.context["form"].errors)
        self.assertEqual(User.objects.count(), 1)
        self.assertEqual(CompanyMembership.objects.count(), 1)
