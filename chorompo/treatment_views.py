from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from .access import clinic_required
from .forms import EvolutionOfTreatmentForm, TreatmentCompanyForm, TreatmentForm, TreatmentPackageForm, TreatmentPackageFormSet
from .models import Employee, Treatment, TreatmentCompany, TreatmentPackage, TreatmentSession
from .treatment_services import acquire_package, acquire_treatment, record_evolution
from .views import platform_context


def context(request, **kwargs):
    active = "treatment_catalog" if kwargs.get("treatment_tab") in ("catalog", "manage") else "treatments"
    return {**platform_context(request), "active_module": active, **kwargs}


def purchases_for(company):
    return Treatment.objects.filter(company=company).select_related("patient", "treatment", "package").annotate(
        used_count=Count("sessions", filter=Q(sessions__session_held=1)),
    ).order_by("-created_at", "-pk")


@clinic_required("treatments")
@require_http_methods(["GET", "POST"])
def catalog(request):
    if request.method == "POST":
        return catalog_create(request)
    query = request.GET.get("q", "").strip()[:100]
    records = request.company.company_treatments.order_by("name", "pk")
    if query:
        records = records.filter(Q(name__icontains=query) | Q(description__icontains=query))
    page = Paginator(records, 20).get_page(request.GET.get("page"))
    return render(request, "chorompo/treatments/catalog.html", context(request, page_obj=page, treatment_tab="catalog", query=query))


@clinic_required("treatments")
@require_http_methods(["GET", "POST"])
def catalog_create(request):
    form = TreatmentCompanyForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            item = form.save(commit=False)
            item.company = request.company
            item.save()
        messages.success(request, "Tratamento adicionado ao catálogo da clínica.")
        return redirect("chorompo:treatments")
    
    return render(request, "chorompo/treatments/catalog_edit.html", context(request, form=form, treatment_tab="manage"))


@clinic_required("treatments")
@require_http_methods(["GET", "POST"])
def catalog_edit(request, pk):
    item = get_object_or_404(TreatmentCompany, pk=pk, company=request.company)
    form = TreatmentCompanyForm(request.POST if request.method == "POST" else None, instance=item)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Catálogo atualizado. Os valores das aquisições já registradas foram mantidos.")
        return redirect("chorompo:treatments")
    return render(request, "chorompo/treatments/catalog_edit.html", context(request, form=form, item=item, treatment_tab="manage"))


@clinic_required("treatments")
@require_http_methods(["GET", "POST"])
def purchases(request):
    if request.method == "POST":
        return purchase_create(request)
    query = request.GET.get("q", "").strip()[:100]
    records = purchases_for(request.company)
    if query:
        records = records.filter(Q(name__icontains=query) | Q(patient__name__icontains=query) | Q(package__name__icontains=query))
    page = Paginator(records, 20).get_page(request.GET.get("page"))
    return render(request, "chorompo/treatments/purchases.html", context(request, page_obj=page, treatment_tab="purchases", query=query))


@clinic_required("treatments")
@require_http_methods(["GET", "POST"])
def purchase_create(request):
    data = request.POST if request.method == "POST" else None
    # Keep accepting previously opened single-treatment forms.
    legacy = request.method == "POST" and "treatment" in request.POST and "items-TOTAL_FORMS" not in request.POST
    form = (TreatmentForm if legacy else TreatmentPackageForm)(data, company=request.company)
    formset = TreatmentPackageFormSet(None if legacy else data, prefix="items", form_kwargs={"company": request.company})
    form_valid = form.is_valid() if request.method == "POST" else False
    items_valid = formset.is_valid() if request.method == "POST" and not legacy else legacy
    if form_valid and items_valid:
        try:
            if legacy:
                treatment = acquire_treatment(
                    company=request.company, patient=form.cleaned_data["patient"], catalog=form.cleaned_data["treatment"],
                    qty_sessions=form.cleaned_data["qty_sessions"], discount_percentage=form.cleaned_data["discount_percentage"],
                )
            else:
                package = acquire_package(
                    company=request.company, patient=form.cleaned_data["patient"], name=form.cleaned_data["name"],
                    items=[item.cleaned_data for item in formset if item.cleaned_data and not item.cleaned_data.get("DELETE")],
                )
        except ValidationError as error:
            form.add_error(None, " ".join(error.messages))
        except IntegrityError:
            form.add_error(None, "Não foi possível registrar a aquisição. Confira os dados e tente novamente.")
        else:
            if not legacy:
                messages.success(request, "Pacote registrado com todos os tratamentos e suas sessões.")
                return redirect("chorompo:treatment_package_detail", pk=package.pk)
            messages.success(request, f"Tratamento vinculado ao paciente com {treatment.qty_sessions} sessões disponíveis.")
            return redirect("chorompo:treatment_detail", pk=treatment.pk)
    return render(request, "chorompo/treatments/purchase_form.html", context(request, form=form, formset=formset, treatment_tab="purchases"))


@clinic_required("treatments")
@require_http_methods(["GET"])
def package_detail(request, pk):
    package = get_object_or_404(TreatmentPackage.objects.select_related("patient"), pk=pk, company=request.company)
    treatments = list(purchases_for(request.company).filter(package=package))
    return render(request, "chorompo/treatments/package.html", context(
        request, package=package, treatments=treatments, total=sum(item.price for item in treatments),
        total_sessions=sum(item.qty_sessions for item in treatments), treatment_tab="purchases",
    ))


@clinic_required("treatments")
@require_http_methods(["GET"])
def treatment_detail(request, pk):
    treatment = get_object_or_404(purchases_for(request.company), pk=pk)
    sessions = treatment.sessions.select_related("appointment").annotate(evolution_count=Count("evolutions")).order_by("session_number")
    page = Paginator(sessions, 30).get_page(request.GET.get("page"))
    return render(request, "chorompo/treatments/detail.html", context(
        request, treatment=treatment, page_obj=page, remaining=treatment.qty_sessions - treatment.used_count, treatment_tab="purchases",
    ))


@clinic_required("treatments")
@require_http_methods(["GET", "POST"])
def session_detail(request, pk):
    session = get_object_or_404(TreatmentSession.objects.select_related("treatment__patient", "treatment__treatment"), pk=pk, treatment__company=request.company)
    employee = Employee.objects.filter(membership=request.membership).first()
    if employee is None:
        raise PermissionDenied("Seu usuário precisa de um perfil de funcionário para registrar evoluções.")
    form = EvolutionOfTreatmentForm(request.POST if request.method == "POST" else None, session=session, employee=employee)
    if request.method == "POST" and form.is_valid():
        try:
            record_evolution(session=session, employee=employee, **form.cleaned_data)
        except ValidationError as error:
            form.add_error(None, " ".join(error.messages))
        except IntegrityError:
            form.add_error(None, "Não foi possível registrar a evolução. Atualize a página e confira a sessão.")
        else:
            messages.success(request, "Evolução registrada e sessão marcada como realizada." if form.cleaned_data["uses_session"] else "Evolução registrada. O saldo de sessões não foi alterado.")
            return redirect("chorompo:session_detail", pk=session.pk)
    page = Paginator(session.evolutions.select_related("employee"), 15).get_page(request.GET.get("page"))
    return render(request, "chorompo/treatments/session.html", context(request, session=session, form=form, page_obj=page, treatment_tab="purchases", query=request.GET.get("q", "")))
