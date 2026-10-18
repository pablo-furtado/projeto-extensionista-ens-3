import re
from datetime import datetime

from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from django.utils import timezone
from django.db.models import Q

from .models import Appointment, Company, CompanyMembership, Employee, EvolutionOfTreatment, Floor, Room, RoomBlock, Patient, Treatment, TreatmentCompany, TreatmentSession


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


class TreatmentPackageForm(StyledFormMixin, forms.Form):
    patient = forms.ModelChoiceField(label="Paciente", queryset=Patient.objects.none())
    name = forms.CharField(label="Nome do pacote", max_length=100, initial="Pacote de tratamentos")

    def __init__(self, *args, company, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["patient"].queryset = company.patients.order_by("name")


class TreatmentPackageItemForm(TreatmentForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields.pop("patient")


class BaseTreatmentPackageFormSet(forms.BaseFormSet):
    def add_fields(self, form, index):
        super().add_fields(form, index)
        form.fields["DELETE"].label = "Remover do pacote"

    def clean(self):
        super().clean()
        if any(self.errors):
            return
        seen = set()
        for form in self.forms:
            if not form.cleaned_data or form.cleaned_data.get("DELETE"):
                continue
            catalog = form.cleaned_data["treatment"]
            if catalog.pk in seen:
                raise forms.ValidationError("Selecione cada tratamento uma única vez e informe a quantidade de sessões desejada.")
            seen.add(catalog.pk)


TreatmentPackageFormSet = forms.formset_factory(
    TreatmentPackageItemForm, formset=BaseTreatmentPackageFormSet,
    extra=0, min_num=1, validate_min=True, max_num=20, validate_max=True,
    absolute_max=40, can_delete=True,
)


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
    date = forms.DateField(label="Data", widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))
    start_time = forms.TimeField(label="Início", widget=forms.TimeInput(attrs={"type": "time"}, format="%H:%M"))
    end_time = forms.TimeField(label="Fim", widget=forms.TimeInput(attrs={"type": "time"}, format="%H:%M"))

    class Meta:
        model = Appointment
        fields = ("room", "date", "start_time", "end_time", "patient", "professional", "treatment", "session", "notes", "starts_at", "ends_at")
        labels = {"starts_at": "Início", "ends_at": "Término", "treatment": "Tratamento adquirido", "session": "Sessão adquirida"}
        widgets = {
            "starts_at": forms.HiddenInput(),
            "ends_at": forms.HiddenInput(),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, company, **kwargs):
        # Accept earlier open forms while the UI uses one date and two time fields.
        self.legacy_cross_day = False
        if args and args[0] is not None:
            data = args[0].copy()
            if not data.get("date"):
                try:
                    start = datetime.fromisoformat(data.get("starts_at", ""))
                    end = datetime.fromisoformat(data.get("ends_at", ""))
                    self.legacy_cross_day = start.date() != end.date()
                    data.update({"date": start.date().isoformat(), "start_time": start.strftime("%H:%M"), "end_time": end.strftime("%H:%M")})
                except (TypeError, ValueError):
                    pass
            args = (data, *args[1:])
        super().__init__(*args, **kwargs)
        self.instance.company = company
        for name in ("starts_at", "ends_at"):
            value = self.initial.get(name)
            try:
                value = datetime.fromisoformat(value) if isinstance(value, str) else value
                if value:
                    value = timezone.localtime(value) if timezone.is_aware(value) else value
                    self.initial.setdefault("date", value.date())
                    self.initial.setdefault("start_time" if name == "starts_at" else "end_time", value.time())
            except (TypeError, ValueError):
                pass
            self.fields[name].required = False
        self.initial.setdefault("date", timezone.localdate())
        self.fields["room"].required = True
        self.fields["room"].queryset = company.rooms.filter(is_active=True, floor__is_active=True).select_related("floor")
        self.fields["patient"].queryset = company.patients.order_by("name")
        self.fields["patient"].label_from_instance = lambda item: f"{item.name} · {item.birth_date:%d/%m/%Y} · {item.phone_number}"
        self.fields["treatment"].queryset = company.treatments.filter(is_active=True).select_related("patient", "treatment").order_by("name", "pk")
        self.fields["treatment"].help_text = "Opcional. Selecionar um tratamento não consome sessões."
        self.fields["session"].help_text = "Opcional. Vincule uma sessão adquirida para acompanhar sua realização."
        from django.urls import reverse
        for name in ("patient", "treatment"):
            selected = self.data.get(self.add_prefix(name)) if self.is_bound else self.initial.get(name)
            selected = selected.pk if hasattr(selected, "pk") else selected
            self.fields[name].queryset = self.fields[name].queryset.filter(pk=selected) if str(selected or "").isdigit() else self.fields[name].queryset.none()
            self.fields[name].widget.attrs.update({"data-search-url": reverse("chorompo:agenda_search"), "data-search-kind": name})
            self.fields[name].widget.attrs["data-appointment"] = self.instance.pk or ""
        selected_treatment = self.fields["treatment"].queryset.first()
        if selected_treatment:
            self.fields["treatment"].widget.attrs["data-duration"] = selected_treatment.treatment.duration_minutes
        self.fields["session"].queryset = TreatmentSession.objects.filter(
            treatment__company=company, treatment__is_active=True, session_held=0,
        ).filter(Q(appointment__isnull=True) | Q(appointment__pk=self.instance.pk)).select_related("treatment__patient").order_by("treatment_id", "session_number")
        treatment_id = self.data.get(self.add_prefix("treatment")) if self.is_bound else self.initial.get("treatment")
        if str(treatment_id or "").isdigit():
            self.fields["session"].queryset = self.fields["session"].queryset.filter(treatment_id=treatment_id)
        else:
            self.fields["session"].queryset = self.fields["session"].queryset.none()
        selected_session = self.data.get(self.add_prefix("session")) if self.is_bound else self.initial.get("session")
        self.fields["session"].queryset = self.fields["session"].queryset.filter(pk=selected_session) if str(selected_session or "").isdigit() else self.fields["session"].queryset.none()
        self.fields["session"].widget.attrs.update({"data-search-url": reverse("chorompo:agenda_search"), "data-search-kind": "session"})
        self.fields["professional"].queryset = Employee.objects.filter(
            membership__company=company, membership__is_active=True, membership__user__is_active=True,
            membership__role__in=[CompanyMembership.Role.ADMIN, CompanyMembership.Role.PROFESSIONAL],
        ).order_by("name")
        if self.fields["professional"].queryset.count() == 1:
            self.fields["professional"].initial = self.fields["professional"].queryset.first().pk

    def clean(self):
        data = super().clean()
        for model_name, time_name in (("starts_at", "start_time"), ("ends_at", "end_time")):
            if data.get("date") and data.get(time_name):
                data[model_name] = timezone.make_aware(datetime.combine(data["date"], data[time_name]))
            else:
                data[model_name] = None
        if self.legacy_cross_day:
            self.add_error("end_time", "Início e fim devem estar no mesmo dia.")
        treatment = data.get("treatment")
        if treatment:
            self.instance.treatment_company = treatment.treatment
        else:
            self.instance.treatment_company = None
        return data

    def _update_errors(self, errors):
        if hasattr(errors, "error_dict"):
            errors = forms.ValidationError({{"starts_at": "start_time", "ends_at": "end_time"}.get(name, name): values for name, values in errors.error_dict.items()})
        super()._update_errors(errors)


class SearchForm(forms.Form):
    q = forms.CharField(label="Buscar", required=False, max_length=100,
                        widget=forms.TextInput(attrs={"placeholder": "Digite para buscar…", "type": "search"}))


class AgendaFilterForm(SearchForm):
    date = forms.DateField(label="Data", required=False, widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))
    floor = forms.ModelChoiceField(label="Piso", required=False, queryset=Floor.objects.none(), empty_label="Todos os pisos")
    room = forms.ModelChoiceField(label="Sala", required=False, queryset=Room.objects.none(), empty_label="Todas as salas")
    professional = forms.ModelChoiceField(label="Profissional", required=False, queryset=Employee.objects.none(), empty_label="Todos os profissionais")

    def __init__(self, *args, company, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["professional"].queryset = Employee.objects.filter(membership__company=company).order_by("name")
        self.fields["professional"].widget.attrs["id"] = "filter-professional"
        self.fields["floor"].queryset = company.floors.all()
        self.fields["room"].queryset = company.rooms.select_related("floor")
        self.order_fields(["date", "floor", "room", "professional", "q"])
        for name in ("date", "floor", "room", "q"):
            self.fields[name].widget.attrs["id"] = "filter-" + name


class FloorForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Floor
        fields = ("name", "is_active")

    def __init__(self, *args, company, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.company = company


class RoomForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Room
        fields = ("floor", "name", "opens_at", "closes_at", "color", "is_active")
        widgets = {"opens_at": forms.TimeInput(attrs={"type": "time"}, format="%H:%M"), "closes_at": forms.TimeInput(attrs={"type": "time"}, format="%H:%M"), "color": forms.TextInput(attrs={"type": "color"})}
        help_texts = {"opens_at": "Funcionamento diário. Use bloqueios para feriados e ausências.", "is_active": "Desativar mantém o histórico e impede novos agendamentos."}

    def __init__(self, *args, company, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.company = company
        self.fields["floor"].queryset = company.floors.all()


class RoomBlockForm(StyledFormMixin, forms.ModelForm):
    weekdays = forms.TypedMultipleChoiceField(label="Dias da semana", choices=[(0, "Segunda"), (1, "Terça"), (2, "Quarta"), (3, "Quinta"), (4, "Sexta"), (5, "Sábado"), (6, "Domingo")], coerce=int, required=False, widget=forms.CheckboxSelectMultiple)
    class Meta:
        model = RoomBlock
        fields = ("room", "reason", "recurrence", "starts_at", "ends_at", "weekdays", "repeat_until", "is_active")
        widgets = {**{name: forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M") for name in ("starts_at", "ends_at")}, "repeat_until": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")}
        help_texts = {"starts_at": "Na repetição, a data indica quando a regra começa e a hora indica o início de cada bloqueio.", "repeat_until": "Deixe em branco para repetir sem data final. A data final é inclusiva."}

    def __init__(self, *args, company, **kwargs):
        if args and args[0] is not None:
            data = args[0].copy()
            data.setdefault("recurrence", RoomBlock.Recurrence.ONCE)
            args = (data, *args[1:])
        super().__init__(*args, **kwargs)
        self.fields["room"].queryset = company.rooms.select_related("floor")

    def clean(self):
        data = super().clean()
        if data.get("recurrence") != RoomBlock.Recurrence.WEEKLY:
            data["weekdays"] = []
        if data.get("recurrence") == RoomBlock.Recurrence.ONCE:
            data["repeat_until"] = None
        return data


class FinanceFilterForm(SearchForm):
    start = forms.DateField(label="De", required=False, widget=forms.DateInput(attrs={"type": "date"}))
    end = forms.DateField(label="Até", required=False, widget=forms.DateInput(attrs={"type": "date"}))

    def clean(self):
        data = super().clean()
        if data.get("start") and data.get("end") and data["start"] > data["end"]:
            raise forms.ValidationError("A data final deve ser igual ou posterior à data inicial.")
        return data
