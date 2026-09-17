from datetime import timedelta
from decimal import Decimal

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Count, Q, Sum
from django.db.models.functions import TruncMonth
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from .access import clinic_required
from .forms import AgendaFilterForm, AppointmentForm, FinanceFilterForm
from .models import Appointment
from .treatment_services import save_appointment
from .views import platform_context


@clinic_required("appointments")
@require_http_methods(["GET", "POST"])
def appointments(request):
    filters = AgendaFilterForm(request.GET, company=request.company)
    valid = filters.is_valid()
    selected = (filters.cleaned_data.get("date") if valid else None) or timezone.localdate()
    # Leave enough room for week navigation even for manually entered extreme dates.
    selected = max(timezone.datetime(1900, 1, 1).date(), min(selected, timezone.datetime(9998, 12, 1).date()))
    start = selected - timedelta(days=selected.weekday())
    end = start + timedelta(days=6)
    records = request.company.appointments.select_related("patient", "professional", "treatment_company", "session")
    records = records.filter(starts_at__date__range=(start, end))
    if valid:
        if filters.cleaned_data.get("q"):
            q = filters.cleaned_data["q"]
            records = records.filter(Q(patient__name__icontains=q) | Q(treatment_company__name__icontains=q) | Q(professional__name__icontains=q))
        if filters.cleaned_data.get("professional"):
            records = records.filter(professional=filters.cleaned_data["professional"])
    else:
        records = records.none()
    form = AppointmentForm(request.POST if request.method == "POST" else None, company=request.company)
    if request.method == "POST" and form.is_valid():
        if persist_appointment(form):
            messages.success(request, "Agendamento criado com sucesso.")
            return redirect(reverse("chorompo:appointments") + "?date=" + timezone.localdate(form.instance.starts_at).isoformat())
    days = [{"date": start + timedelta(days=i), "appointments": []} for i in range(7)]
    for appointment in records:
        days[(timezone.localdate(appointment.starts_at) - start).days]["appointments"].append(appointment)
    params = request.GET.copy()
    params["date"] = (start - timedelta(days=7)).isoformat()
    previous = params.urlencode()
    params["date"] = (start + timedelta(days=7)).isoformat()
    return render(request, "chorompo/agenda.html", {
        **platform_context(request), "active_module": "appointments", "form": form, "filters": filters,
        "days": days, "start": start, "end": end, "previous": previous, "next": params.urlencode(),
        "today": timezone.localdate(), "appointment_count": sum(len(day["appointments"]) for day in days),
    })


def persist_appointment(form):
    try:
        save_appointment(form.save(commit=False))
    except ValidationError as error:
        form.add_error(None, " ".join(error.messages))
    except IntegrityError:
        form.add_error(None, "Esta sessão já foi agendada. Atualize a página e selecione outra sessão.")
    else:
        return True
    return False


@clinic_required("appointments")
@require_http_methods(["GET", "POST"])
def appointment_edit(request, pk):
    appointment = get_object_or_404(Appointment, pk=pk, company=request.company)
    form = AppointmentForm(request.POST if request.method == "POST" else None, instance=appointment, company=request.company)
    if appointment.session_id and appointment.session.session_held:
        messages.error(request, "Este atendimento já foi realizado e não pode ser reagendado.")
        return redirect("chorompo:appointments")
    if request.method == "POST" and form.is_valid() and persist_appointment(form):
        messages.success(request, "Agendamento atualizado.")
        return redirect(reverse("chorompo:appointments") + "?date=" + timezone.localdate(form.instance.starts_at).isoformat())
    return render(request, "chorompo/edit.html", {
        **platform_context(request), "active_module": "appointments", "title": "Editar agendamento",
        "form": form, "back_url": reverse("chorompo:appointments"),
    })


@clinic_required("appointments")
@require_http_methods(["GET", "POST"])
def appointment_remove(request, pk):
    appointment = get_object_or_404(Appointment, pk=pk, company=request.company)
    if request.method == "POST":
        with transaction.atomic():
            appointment = get_object_or_404(Appointment.objects.select_for_update(), pk=pk, company=request.company)
            appointment.delete()
        messages.success(request, "Agendamento removido. O histórico clínico e as sessões realizadas foram preservados.")
        return redirect("chorompo:appointments")
    return render(request, "chorompo/appointment_remove.html", {
        **platform_context(request), "active_module": "appointments", "appointment": appointment,
    })


@clinic_required("finance")
@require_http_methods(["GET"])
def finance(request):
    filters = FinanceFilterForm(request.GET)
    records = request.company.treatments.select_related("patient")
    if filters.is_valid():
        data = filters.cleaned_data
        if data.get("q"):
            records = records.filter(Q(name__icontains=data["q"]) | Q(patient__name__icontains=data["q"]))
        if data.get("start"):
            records = records.filter(created_at__date__gte=data["start"])
        if data.get("end"):
            records = records.filter(created_at__date__lte=data["end"])
    else:
        records = records.none()
    totals = records.aggregate(total=Sum("price"), count=Count("pk"), sessions=Sum("qty_sessions"))
    total = totals["total"] or Decimal("0")
    monthly = list(records.order_by().annotate(month=TruncMonth("created_at")).values("month").annotate(total=Sum("price")).order_by("-month")[:6])
    maximum = max((item["total"] for item in monthly), default=0)
    for item in monthly:
        item["width"] = round(item["total"] / maximum * 100) if maximum else 0
    return render(request, "chorompo/finance.html", {
        **platform_context(request), "active_module": "finance", "filters": filters,
        "total": total, "sales_count": totals["count"], "sessions_count": totals["sessions"] or 0,
        "average": total / totals["count"] if totals["count"] else Decimal("0"),
        "monthly": reversed(monthly), "page_obj": Paginator(records.order_by("-created_at", "-pk"), 20).get_page(request.GET.get("page")),
    })
