from django.test import Client, TestCase
from django.urls import reverse

from .forms import CompanyForm
from .models import Company


class CompanyRegistrationTests(TestCase):
    def setUp(self):
        self.url = reverse("chorompo:company_create")
        self.data = {
            "name": "Clínica Bem Viver",
            "cpf_cnpj": "11.222.333/0001-81",
            "cep": "78000-000",
            "phone_number": "(65) 99999-9999",
            "email": "CONTATO@clinica.com.br",
        }

    def test_page_and_home_redirect(self):
        self.assertRedirects(self.client.get("/"), self.url)
        response = self.client.get(self.url)
        self.assertContains(response, "Cadastre sua clínica")
        self.assertContains(response, "csrfmiddlewaretoken")
        self.assertIsInstance(response.context["form"], CompanyForm)

    def test_registration_normalizes_and_redirects(self):
        response = self.client.post(self.url, self.data, follow=True)
        self.assertRedirects(response, reverse("chorompo:administrator_create"))
        self.assertContains(response, "foi cadastrada com sucesso!")
        company = Company.objects.get()
        self.assertEqual(company.cpf_cnpj, "11222333000181")
        self.assertEqual(company.cep, "78000000")
        self.assertEqual(company.phone_number, "65999999999")
        self.assertEqual(company.email, "contato@clinica.com.br")
        self.client.get(self.url)
        self.assertEqual(Company.objects.count(), 1)

    def test_accepts_formatted_cpf(self):
        form = CompanyForm(data={**self.data, "cpf_cnpj": "529.982.247-25"})
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["cpf_cnpj"], "52998224725")

    def test_invalid_fields_preserve_input_without_saving(self):
        response = self.client.post(self.url, {
            **self.data, "cpf_cnpj": "abc", "cep": "123", "phone_number": "123", "email": "inválido",
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.context["form"].errors), {"cpf_cnpj", "cep", "phone_number", "email"})
        self.assertContains(response, "Clínica Bem Viver")
        self.assertFalse(Company.objects.exists())

    def test_empty_post_shows_required_errors(self):
        response = self.client.post(self.url, {})
        self.assertEqual(len(response.context["form"].errors), 5)
        self.assertFalse(Company.objects.exists())

    def test_duplicate_document_and_email(self):
        self.client.post(self.url, self.data)
        response = self.client.post(self.url, self.data)
        self.assertRedirects(response, reverse("chorompo:administrator_create"))
        self.assertEqual(Company.objects.count(), 1)

    def test_email_uniqueness_is_case_insensitive(self):
        Company.objects.create(name="Outra clínica", cpf_cnpj="52998224725", cep="78000000", phone_number="6533334444", email="Contato@Clinica.com.br")
        form = CompanyForm(data=self.data)
        self.assertFalse(form.is_valid())
        self.assertIn("email", form.errors)

    def test_post_requires_csrf(self):
        response = Client(enforce_csrf_checks=True).post(self.url, self.data)
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Company.objects.exists())
