import re

from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from django.utils import timezone

from .models import Appointment, Company, CompanyMembership, Employee, EvolutionOfTreatment, Patient, Treatment, TreatmentCompany, TreatmentSession


class CompanyForm(forms.ModelForm):
    cpf_cnpj = forms.CharField(label="CPF ou CNPJ", max_length=18)
    cep = forms.CharField(label="CEP", max_length=9)
    phone_number = forms.CharField(label="Telefone", max_length=20)

    class Meta:
        model = Company
        fields = ["name", "cpf_cnpj", "cep", "phone_number", "email"]
        labels = {"name": "Nome da clínica", "email": "E-mail da clínica"}
        error_messages = {
            "cpf_cnpj": {"unique": "Já existe uma clínica cadastrada com este CPF ou CNPJ."},
            "email": {"unique": "Já existe uma clínica cadastrada com este e-mail."},
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        attributes = {
            "name": {"placeholder": "Ex.: Clínica Bem Viver", "autocomplete": "organization"},
            "cpf_cnpj": {"placeholder": "CPF ou CNPJ, somente números", "inputmode": "numeric"},
            "cep": {"placeholder": "00000-000", "autocomplete": "postal-code", "inputmode": "numeric"},
            "phone_number": {"placeholder": "(65) 99999-9999", "autocomplete": "tel", "inputmode": "tel"},
            "email": {"placeholder": "contato@clinica.com.br", "autocomplete": "email"},
        }
        for name, field in self.fields.items():
            field.widget.attrs.update(attributes[name])
            field.widget.attrs["class"] = "form-input"
            field.error_messages["required"] = "Preencha este campo."

    def clean_cpf_cnpj(self):
        value = re.sub(r"[.\-/\s]", "", self.cleaned_data["cpf_cnpj"])
        if not re.fullmatch(r"(?:[0-9]{11}|[0-9]{14})", value):
            raise forms.ValidationError("Informe um CPF com 11 dígitos ou um CNPJ com 14 dígitos.")
        return value

    def clean_cep(self):
        value = re.sub(r"[-\s]", "", self.cleaned_data["cep"])
        if not re.fullmatch(r"[0-9]{8}", value):
            raise forms.ValidationError("Informe um CEP com 8 dígitos.")
        return value

    def clean_phone_number(self):
        value = re.sub(r"[()+\-\s]", "", self.cleaned_data["phone_number"])
        if not re.fullmatch(r"[0-9]{10,15}", value):
            raise forms.ValidationError("Informe um telefone com DDD, entre 10 e 15 dígitos.")
        return value

    def clean_email(self):
        value = self.cleaned_data["email"].lower()
        companies = Company.objects.filter(email__iexact=value)
        if self.instance.pk:
            companies = companies.exclude(pk=self.instance.pk)
        if companies.exists():
            raise forms.ValidationError("Já existe uma clínica cadastrada com este e-mail.")
        return value


class StyledFormMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-input")
            field.error_messages["required"] = "Preencha este campo."


class RegistrationEmailForm(StyledFormMixin, forms.Form):
    email = forms.EmailField(label="E-mail da clínica", widget=forms.EmailInput(attrs={"autocomplete": "email"}))

    def clean_email(self):
        return self.cleaned_data["email"].lower()


class AccountForm(StyledFormMixin, UserCreationForm):
    email = forms.EmailField(label="E-mail", widget=forms.EmailInput(attrs={"autocomplete": "email"}))

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "email")
        labels = {"username": "Nome de usuário para entrar"}

    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)
        if company is not None:
            self.fields["email"].initial = company.email
            self.fields["email"].disabled = True

    def clean_email(self):
        value = self.cleaned_data["email"].lower()
        if User.objects.filter(email__iexact=value).exists():
            raise forms.ValidationError("Este e-mail já tem um usuário. Entre com sua conta existente.")
        return value


class PersonalDataMixin(StyledFormMixin):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["cpf"].widget.attrs.update({"maxlength": 14, "inputmode": "numeric"})
        self.fields["cep"].widget.attrs.update({"maxlength": 9, "inputmode": "numeric"})

    def clean_cpf(self):
        value = re.sub(r"[.\-\s]", "", self.cleaned_data["cpf"])
        if not re.fullmatch(r"[0-9]{11}", value):
            raise forms.ValidationError("Informe um CPF com 11 dígitos.")
        return value

    clean_cep = CompanyForm.clean_cep

    def clean_birth_date(self):
        value = self.cleaned_data["birth_date"]
        if value > timezone.localdate():
            raise forms.ValidationError("A data de nascimento não pode estar no futuro.")
        return value


class EmployeeProfileForm(PersonalDataMixin, forms.ModelForm):
    cpf = forms.CharField(label="CPF", max_length=14)
    cep = forms.CharField(label="CEP", max_length=9)

    class Meta:
        model = Employee
        fields = ("name", "birth_date", "cpf", "address", "cep")
        labels = {"name": "Nome completo", "birth_date": "Data de nascimento", "cpf": "CPF", "address": "Endereço", "cep": "CEP"}
        widgets = {"birth_date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")}


class EmployeeForm(EmployeeProfileForm):
    role = forms.ChoiceField(label="Perfil de acesso", choices=CompanyMembership.Role.choices, initial=CompanyMembership.Role.RECEPTION)


class PatientForm(PersonalDataMixin, forms.ModelForm):
    cpf = forms.CharField(label="CPF", max_length=14)
    cep = forms.CharField(label="CEP", max_length=9)
    phone_number = forms.CharField(label="Telefone", max_length=20)

    class Meta:
        model = Patient
        fields = ("name", "birth_date", "cpf", "cep", "sex", "phone_number")
        labels = {"name": "Nome completo", "birth_date": "Data de nascimento", "cpf": "CPF", "cep": "CEP", "sex": "Sexo"}
        widgets = {"birth_date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")}

    clean_phone_number = CompanyForm.clean_phone_number


class TreatmentCompanyForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = TreatmentCompany
        fields = ("name", "description", "duration_minutes", "price", "fixed_cost", "variable_cost", "max_discount_percentage")
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}


class TreatmentForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Treatment
        fields = ("patient", "treatment", "qty_sessions", "discount_percentage")
        help_texts = {"discount_percentage": "O valor total é calculado pelo preço por sessão do catálogo, respeitando o desconto máximo permitido."}

    def __init__(self, *args, company, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.company = company
        self.fields["patient"].queryset = company.patients.order_by("name")
        self.fields["treatment"].queryset = company.company_treatments.order_by("name")
        self.fields["treatment"].label_from_instance = lambda item: f"{item.name} · R$ {item.price:.2f} por sessão"

    def clean(self):
        data = super().clean()
        catalog = data.get("treatment")
        discount = data.get("discount_percentage")
        if catalog and discount is not None and discount > (catalog.max_discount_percentage or 0):
            self.add_error("discount_percentage", f"O desconto máximo deste tratamento é {catalog.max_discount_percentage or 0}%.")
        return data


class EvolutionOfTreatmentForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = EvolutionOfTreatment
        fields = ("date", "notes", "uses_session")
        widgets = {"date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"), "notes": forms.Textarea(attrs={"rows": 6})}
        help_texts = {"uses_session": "Marque apenas se o atendimento foi realizado. Cada sessão pode ser utilizada uma única vez."}

    def __init__(self, *args, session, employee, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.treatment = session
        self.instance.employee = employee
        self.fields["uses_session"].initial = not bool(session.session_held)
        if session.session_held:
            self.fields["uses_session"].help_text = "Esta sessão já foi utilizada. Registre apenas uma nova evolução, sem marcar realização."

    def clean_uses_session(self):
        value = self.cleaned_data["uses_session"]
        if value and self.instance.treatment.session_held:
            raise forms.ValidationError("Esta sessão já foi utilizada. Uma nova evolução não deve consumir outra sessão.")
        return value


class AppointmentForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Appointment
        fields = ("patient", "treatment", "session", "professional", "starts_at", "notes")
        widgets = {
            "starts_at": forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, company, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.company = company
        self.fields["patient"].queryset = company.patients.order_by("name")
        self.fields["treatment"].required = True
        self.fields["session"].required = True
        self.fields["treatment"].queryset = company.treatments.filter(is_active=True).select_related("patient").order_by("patient__name", "name", "pk")
        self.fields["session"].queryset = TreatmentSession.objects.filter(
            treatment__company=company, treatment__is_active=True, session_held=0, appointment__isnull=True,
        ).select_related("treatment__patient").order_by("treatment_id", "session_number")
        self.fields["professional"].queryset = Employee.objects.filter(
            membership__company=company, membership__is_active=True, membership__user__is_active=True,
            membership__role__in=[CompanyMembership.Role.ADMIN, CompanyMembership.Role.PROFESSIONAL],
        ).order_by("name")

    def clean(self):
        data = super().clean()
        treatment = data.get("treatment")
        if treatment:
            self.instance.treatment_company = treatment.treatment
        return data
