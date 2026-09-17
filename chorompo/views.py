import logging
import time
from smtplib import SMTPException

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.core import signing
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods

from .access import clinic_required
from .forms import AccountForm, AppointmentForm, CompanyForm, EmployeeForm, EmployeeProfileForm, PatientForm, RegistrationEmailForm
from .group_permission import has_permission
from .models import Company, CompanyMembership, Employee, Patient
from .registration import company_from_token, load_registration_company, registration_token
from .treatment_services import save_appointment

logger = logging.getLogger(__name__)


def existing_company_redirect(request, company):
    if company.memberships.exists():
        messages.info(request, "Esta clínica já possui uma conta. Entre para acessar a plataforma.")
        return redirect("chorompo:login")
    authorized = company_from_token(request.session.get("registration_grant", ""))
    if authorized and authorized.pk == company.pk:
        return redirect("chorompo:administrator_create")
    request.session["registration_email"] = company.email
    return redirect("chorompo:registration_start")


@never_cache
@require_http_methods(["GET", "POST"])
def company_create(request):
    if request.user.is_authenticated:
        return redirect("chorompo:dashboard")
    if request.method == "POST":
        email_form = RegistrationEmailForm(request.POST)
        if email_form.is_valid():
            company = Company.objects.filter(email__iexact=email_form.cleaned_data["email"]).first()
            if company:
                return existing_company_redirect(request, company)
    form = CompanyForm(request.POST if request.method == "POST" else None, initial={"email": request.session.get("registration_email", "")})
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                company = form.save()
        except IntegrityError:
            form.add_error(None, "Estes dados já foram cadastrados. Confira o e-mail e o CPF/CNPJ.")
        else:
            request.session["registration_grant"] = registration_token(company)
            request.session.pop("registration_email", None)
            messages.success(request, f'A clínica "{company.name}" foi cadastrada com sucesso! Crie agora seu perfil de administrador.')
            return redirect("chorompo:administrator_create")
    return render(request, "chorompo/company_form.html", {"form": form})


@never_cache
@require_http_methods(["GET", "POST"])
def registration_start(request):
    if request.user.is_authenticated:
        return redirect("chorompo:dashboard")
    form = RegistrationEmailForm(request.POST if request.method == "POST" else None, initial={"email": request.session.get("registration_email", "")})
    if request.method == "POST" and form.is_valid():
        email = form.cleaned_data["email"]
        company = Company.objects.filter(email__iexact=email).first()
        if company is None:
            request.session["registration_email"] = email
            return redirect("chorompo:company_create")
        if company.memberships.exists():
            return existing_company_redirect(request, company)
        authorized = company_from_token(request.session.get("registration_grant", ""))
        if authorized and authorized.pk == company.pk:
            return redirect("chorompo:administrator_create")
        if time.time() - request.session.get("registration_email_sent_at", 0) < 60:
            form.add_error(None, "Aguarde um minuto antes de solicitar outro link.")
        else:
            url = request.build_absolute_uri(reverse("chorompo:registration_verify", args=[registration_token(company)]))
            try:
                send_mail(
                    "Continue o cadastro da sua clínica na Chorompo",
                    f"Para criar o primeiro administrador da sua clínica, acesse:\n\n{url}\n\nO link expira em uma hora. Se você não solicitou o cadastro, ignore esta mensagem.",
                    settings.DEFAULT_FROM_EMAIL, [company.email], fail_silently=False,
                )
            except (SMTPException, OSError):
                logger.warning("Falha no envio do link de cadastro da clínica %s", company.pk)
                form.add_error(None, "Não foi possível enviar o link. Tente novamente em instantes.")
            else:
                request.session["registration_email_sent_at"] = time.time()
                return render(request, "chorompo/registration_sent.html")
    return render(request, "chorompo/registration_start.html", {"form": form})


@never_cache
@require_http_methods(["GET"])
def registration_verify(request, token):
    try:
        company = load_registration_company(token)
    except signing.SignatureExpired:
        messages.error(request, "Este link expirou. Solicite um novo link para continuar o cadastro.")
        return redirect("chorompo:registration_start")
    except signing.BadSignature:
        messages.error(request, "O link está inválido ou incompleto. Copie o endereço completo recebido ou solicite um novo link.")
        return redirect("chorompo:registration_start")
    if company is None:
        messages.error(request, "Este cadastro já foi concluído ou os dados da clínica foram alterados. Entre na sua conta ou solicite um novo link.")
        return redirect("chorompo:registration_start")
    request.session.cycle_key()
    request.session["registration_grant"] = token
    return redirect("chorompo:administrator_create")


def save_employee(account_form, profile_form, company, role):
    # Call only inside a transaction: User, membership and Employee form one account.
    user = account_form.save(commit=False)
    user.first_name = profile_form.cleaned_data["name"][:150]
    user.save()
    membership = CompanyMembership.objects.create(user=user, company=company, role=role)
    employee = profile_form.save(commit=False)
    employee.membership = membership
    employee.save()
    return user


@sensitive_post_parameters("password1", "password2")
@never_cache
@require_http_methods(["GET", "POST"])
def administrator_create(request):
    if request.user.is_authenticated:
        return redirect("chorompo:dashboard")
    company = company_from_token(request.session.get("registration_grant", ""))
    if company is None:
        messages.info(request, "Informe o e-mail da clínica para iniciar ou retomar seu cadastro.")
        return redirect("chorompo:registration_start")
    data = request.POST if request.method == "POST" else None
    account_form = AccountForm(data, company=company)
    form = EmployeeProfileForm(data)
    if request.method == "POST":
        account_valid, profile_valid = account_form.is_valid(), form.is_valid()
        if account_valid and profile_valid:
            try:
                with transaction.atomic():
                    locked_company = Company.objects.select_for_update().get(pk=company.pk)
                    if locked_company.memberships.exists():
                        messages.info(request, "O administrador desta clínica já foi cadastrado. Entre na plataforma.")
                        return redirect("chorompo:login")
                    user = save_employee(account_form, form, locked_company, CompanyMembership.Role.ADMIN)
            except IntegrityError:
                form.add_error(None, "Não foi possível concluir: usuário, e-mail ou CPF já cadastrado. Confira os dados.")
            else:
                request.session.pop("registration_grant", None)
                request.session.pop("registration_email", None)
                login(request, user)
                request.session["active_company_id"] = company.pk
                return redirect("chorompo:onboarding")
    return render(request, "chorompo/administrator_form.html", {"form": form, "account_form": account_form, "company": company})


MODULES = [
    {"key": "patients", "title": "Pacientes", "description": "Organize os dados dos pacientes da clínica.", "url": "chorompo:patients", "icon": "P"},
    {"key": "treatments", "title": "Tratamentos", "description": "Acompanhe as aquisições dos pacientes, as sessões e as evoluções.", "url": "chorompo:treatment_purchases", "icon": "T"},
    {"key": "appointments", "title": "Agenda", "description": "Agende atendimentos com pacientes e profissionais.", "url": "chorompo:appointments", "icon": "A"},
    {"key": "finance", "title": "Financeiro", "description": "Acompanhe as vendas e os indicadores da clínica.", "url": "chorompo:finance", "icon": "$"},
]


SETTINGS_MODULES = [
    {"key": "employees", "permission": "employees", "title": "Funcionários", "url": "chorompo:employees", "icon": "F"},
    {"key": "treatment_catalog", "permission": "treatments", "title": "Catálogo da clínica", "url": "chorompo:treatments", "icon": "C"},
]


def platform_context(request):
    params = request.GET.copy()
    params.pop("page", None)
    return {
        "company": request.company, "membership": request.membership,
        "modules": [module for module in MODULES if has_permission(request.membership, module["key"])],
        "settings_modules": [module for module in SETTINGS_MODULES if has_permission(request.membership, module["permission"])],
        "filter_query": params.urlencode(),
        "can_manage_treatments": has_permission(request.membership, "treatments"),
    }


@clinic_required(onboarding=True)
@require_http_methods(["GET", "POST"])
def onboarding(request):
    if request.company.onboarding_completed:
        return redirect("chorompo:dashboard")
    if request.membership.role != CompanyMembership.Role.ADMIN:
        return render(request, "chorompo/onboarding_wait.html", platform_context(request))
    form = CompanyForm(request.POST if request.method == "POST" else None, instance=request.company)
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                company = form.save(commit=False)
                company.onboarding_completed = True
                company.save()
        except IntegrityError:
            form.add_error(None, "O e-mail ou CPF/CNPJ informado já está cadastrado.")
        else:
            messages.success(request, "Tudo pronto! Sua clínica já tem acesso aos módulos base.")
            return redirect("chorompo:dashboard")
    return render(request, "chorompo/onboarding.html", {**platform_context(request), "form": form})


@clinic_required()
@require_http_methods(["GET"])
def dashboard(request):
    today = timezone.localdate()
    stats = []
    if has_permission(request.membership, "patients"):
        stats.append({"label": "Pacientes cadastrados", "value": request.company.patients.count()})
    if has_permission(request.membership, "appointments"):
        stats.append({"label": "Atendimentos hoje", "value": request.company.appointments.filter(starts_at__date=today).count()})
        stats.append({"label": "Agendamentos futuros", "value": request.company.appointments.filter(starts_at__gte=timezone.now()).count()})
    if has_permission(request.membership, "treatments"):
        stats.append({"label": "Tratamentos no catálogo", "value": request.company.company_treatments.count()})
    return render(request, "chorompo/dashboard.html", {**platform_context(request), "stats": stats, "today": today})


def module_page(request, *, key, title, form, records, headers, row_builder):
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                record = form.save(commit=False)
                record.company = request.company
                if key == "appointments":
                    save_appointment(record)
                else:
                    record.save()
        except ValidationError as error:
            form.add_error(None, " ".join(error.messages))
        except IntegrityError:
            form.add_error(None, "Não foi possível salvar. Confira se os dados já foram cadastrados.")
        else:
            messages.success(request, "Cadastro salvo com sucesso.")
            return redirect(f"chorompo:{key}")
    query = request.GET.get("q", "").strip()[:100]
    if query:
        records = records.filter(Q(name__icontains=query) | Q(cpf__icontains=query) | Q(phone_number__icontains=query))
    page = Paginator(records, 20).get_page(request.GET.get("page"))
    return render(request, "chorompo/module.html", {
        **platform_context(request), "title": title, "form": form, "headers": headers,
        "rows": [{"values": row_builder(record), "edit_url": reverse("chorompo:patient_edit", args=[record.pk])} for record in page], "query": query, "page_obj": page, "active_module": key,
    })


@clinic_required("patients")
@require_http_methods(["GET", "POST"])
def patients(request):
    return module_page(request, key="patients", title="Pacientes", form=PatientForm(request.POST if request.method == "POST" else None),
        records=request.company.patients.order_by("name"), headers=["Nome", "Telefone", "Nascimento"],
        row_builder=lambda patient: [patient.name, patient.phone_number, patient.birth_date.strftime("%d/%m/%Y")])


@sensitive_post_parameters("password1", "password2")
@clinic_required("employees")
@require_http_methods(["GET", "POST"])
def employees(request):
    data = request.POST if request.method == "POST" else None
    account_form, form = AccountForm(data), EmployeeForm(data)
    if request.method == "POST":
        account_valid, profile_valid = account_form.is_valid(), form.is_valid()
        if account_valid and profile_valid:
            try:
                with transaction.atomic():
                    save_employee(account_form, form, request.company, form.cleaned_data["role"])
            except IntegrityError:
                form.add_error(None, "Não foi possível concluir: usuário, e-mail ou CPF já cadastrado. Confira os dados.")
            else:
                messages.success(request, "Funcionário cadastrado com sucesso. Ele já pode entrar com o usuário e a senha definidos.")
                return redirect("chorompo:employees")
    records = Employee.objects.filter(membership__company=request.company).select_related("membership", "membership__user").order_by("name")
    query = request.GET.get("q", "").strip()[:100]
    if query:
        records = records.filter(Q(name__icontains=query) | Q(cpf__icontains=query) | Q(membership__user__username__icontains=query))
    page = Paginator(records, 20).get_page(request.GET.get("page"))
    return render(request, "chorompo/module.html", {
        **platform_context(request), "title": "Funcionários", "form": form, "account_form": account_form,
        "headers": ["Nome", "Usuário", "Perfil", "Situação"], "active_module": "employees", "page_obj": page,
        "query": query, "rows": [{"values": [employee.name, employee.membership.user.username, employee.membership.get_role_display(), "Ativo" if employee.membership.is_active and employee.membership.user.is_active else "Inativo"], "edit_url": reverse("chorompo:employee_edit", args=[employee.pk])} for employee in page],
    })


@clinic_required("patients")
@require_http_methods(["GET", "POST"])
def patient_edit(request, pk):
    patient = get_object_or_404(Patient, pk=pk, company=request.company)
    form = PatientForm(request.POST if request.method == "POST" else None, instance=patient)
    return edit_profile(request, form, "patients", "Editar paciente")


@clinic_required("employees")
@require_http_methods(["GET", "POST"])
def employee_edit(request, pk):
    employee = get_object_or_404(Employee, pk=pk, membership__company=request.company)
    form = EmployeeProfileForm(request.POST if request.method == "POST" else None, instance=employee)
    return edit_profile(request, form, "employees", "Editar funcionário")


def edit_profile(request, form, module, title):
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                form.save()
        except IntegrityError:
            form.add_error(None, "Não foi possível salvar. Confira se o CPF já foi cadastrado.")
        else:
            messages.success(request, "Cadastro atualizado com sucesso.")
            return redirect(f"chorompo:{module}")
    return render(request, "chorompo/edit.html", {
        **platform_context(request), "form": form, "title": title, "active_module": module,
        "back_url": reverse(f"chorompo:{module}"),
    })
