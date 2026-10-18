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
from .forms import AppointmentForm, FinanceFilterForm
from .models import Appointment, Company
from .treatment_services import save_appointment
from .views import platform_context


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
    appointment = get_object_or_404(Appointment, pk=pk, company=request.company, canceled_at__isnull=True)
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
        "appointment": appointment,
    })


@clinic_required("appointments")
@require_http_methods(["GET", "POST"])
def appointment_remove(request, pk):
    appointment = get_object_or_404(Appointment, pk=pk, company=request.company)
    if request.method == "POST":
        with transaction.atomic():
            Company.objects.select_for_update().get(pk=request.company.pk)
            appointment = get_object_or_404(Appointment.objects.select_for_update(), pk=pk, company=request.company)
            if not appointment.canceled_at:
                appointment.canceled_at = timezone.now()
                appointment.canceled_session = appointment.session
                appointment.session = None
                appointment.save(update_fields=["canceled_at", "canceled_session", "session"])
        messages.success(request, "Agendamento cancelado. O histórico e as sessões realizadas foram preservados.")
        return redirect(reverse("chorompo:appointments") + "?date=" + timezone.localdate(appointment.starts_at).isoformat())
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
