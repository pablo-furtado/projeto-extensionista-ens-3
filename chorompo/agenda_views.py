from datetime import datetime, time, timedelta

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Case, Count, IntegerField, Q, Value, When
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from .access import clinic_required
from .forms import AgendaFilterForm, AppointmentForm, FloorForm, RoomForm, RoomBlockForm
from .models import Appointment, Company, Floor, Room, RoomBlock, TreatmentSession
from .scheduling import blocks_for_day, save_configuration
from .views import platform_context


def context(request, **kwargs):
    return {**platform_context(request), "active_module": "appointments", **kwargs}


def minutes(value):
    return value.hour * 60 + value.minute


@clinic_required("appointments")
@require_http_methods(["GET", "POST"])
def appointments(request):
    if request.method == "POST":
        return appointment_create(request)
    filter_data = request.GET.copy()
    filter_data.setdefault("date", timezone.localdate().isoformat())
    filters = AgendaFilterForm(filter_data, company=request.company)
    valid = filters.is_valid() if filters.is_bound else True
    data = filters.cleaned_data if filters.is_bound and valid else {}
    selected = data.get("date") or timezone.localdate()
    selected = max(datetime(1900, 1, 1).date(), min(selected, datetime(9998, 12, 1).date()))
    start = timezone.make_aware(datetime.combine(selected, time.min))
    end = start + timedelta(days=1)
    bookings = list(request.company.appointments.filter(canceled_at__isnull=True, starts_at__lt=end, ends_at__gt=start).select_related(
        "room__floor", "patient", "professional", "treatment_company", "session"))
    blocks = [block for block in blocks_for_day(request.company, selected) if block.starts_at < end and block.ends_at > start]
    occupied_room_ids = {item.room_id for item in bookings + blocks}
    rooms = request.company.rooms.select_related("floor").filter(Q(is_active=True, floor__is_active=True) | Q(pk__in=occupied_room_ids))
    if data.get("floor"):
        rooms = rooms.filter(floor=data["floor"])
    if data.get("room"):
        rooms = rooms.filter(pk=data["room"].pk)
    rooms = list(rooms)
    room_ids = {room.pk for room in rooms}
    bookings = [item for item in bookings if item.room_id in room_ids or (not item.room_id and not data.get("room") and not data.get("floor"))]
    blocks = [item for item in blocks if item.room_id in room_ids]
    lower = min([minutes(room.opens_at) for room in rooms] + [minutes(timezone.localtime(max(item.starts_at, start))) for item in bookings + blocks] or [480])
    upper = max([minutes(room.closes_at) for room in rooms] + [1440 if item.ends_at >= end else minutes(timezone.localtime(item.ends_at)) for item in bookings + blocks] or [1080])
    lower = lower // 30 * 30
    upper = min(1440, (upper + 29) // 30 * 30)
    columns = [{"room": room, "events": []} for room in rooms]
    if any(not item.room_id for item in bookings):
        columns.append({"room": None, "events": []})
    by_room = {column["room"].pk if column["room"] else None: column for column in columns}
    count = 0
    query = (data.get("q") or "").casefold()
    for item in bookings + blocks:
        is_block = isinstance(item, RoomBlock)
        match = is_block or ((not data.get("professional") or item.professional_id == data["professional"].pk) and (
            not query or query in f"{item.patient.name} {item.professional.name} {item.treatment_company or ''}".casefold()))
        if match and not is_block:
            count += 1
        event_start = max(0, (max(item.starts_at, start) - start).total_seconds() / 60 - lower)
        event_end = (min(item.ends_at, end) - start).total_seconds() / 60 - lower
        by_room[item.room_id]["events"].append({"item": item, "block": is_block, "top": round(event_start * 2), "height": max(1, round((event_end - event_start) * 2)), "muted": not match})
    for column in columns:
        room = column["room"]
        column["slots"] = []
        if room:
            column["closed_before"] = max(0, (minutes(room.opens_at) - lower) * 2)
            column["closed_after_top"] = max(0, (minutes(room.closes_at) - lower) * 2)
            column["closed_after_height"] = max(0, (upper - minutes(room.closes_at)) * 2)
            if room.is_active and room.floor.is_active:
                cursor = start + timedelta(minutes=minutes(room.opens_at))
                closing = start + timedelta(minutes=minutes(room.closes_at))
                occupied = sorted([(item.starts_at, item.ends_at) for item in bookings + blocks if item.room_id == room.pk])
                gaps = []
                for busy_start, busy_end in occupied:
                    if cursor < min(busy_start, closing):
                        gaps.append((cursor, min(busy_start, closing)))
                    cursor = max(cursor, busy_end)
                if cursor < closing:
                    gaps.append((cursor, closing))
                for free_start, free_end in gaps:
                    slot_start = free_start
                    while slot_start < free_end:
                        slot_end = min(slot_start + timedelta(minutes=15), free_end)
                        suggested_end = min(slot_start + timedelta(minutes=30), free_end)
                        params = f"?room={room.pk}&starts_at={timezone.localtime(slot_start):%Y-%m-%dT%H:%M}&ends_at={timezone.localtime(suggested_end):%Y-%m-%dT%H:%M}"
                        column["slots"].append({"top": round(((slot_start - start).total_seconds() / 60 - lower) * 2), "height": max(1, round((slot_end - slot_start).total_seconds() / 30)), "label": timezone.localtime(slot_start).strftime("%H:%M"), "url": reverse("chorompo:appointment_create") + params})
                        slot_start = slot_end
        # Older records may overlap. Give simultaneous events separate lanes.
        active, group = [], []
        def finish_group():
            lanes = max((entry["lane"] for entry in group), default=0) + 1
            for entry in group:
                entry["left"] = f'{entry["lane"] * 100 / lanes:.3f}'
                entry["width"] = f'{100 / lanes:.3f}'
        for entry in sorted(column["events"], key=lambda e: e["top"]):
            active = [e for e in active if e["top"] + e["height"] > entry["top"]]
            if not active and group:
                finish_group()
                group = []
            used = {e["lane"] for e in active}
            lane = 0
            while lane in used:
                lane += 1
            entry["lane"] = lane
            active.append(entry)
            group.append(entry)
        finish_group()
    params = request.GET.copy()
    params["date"] = (selected - timedelta(days=1)).isoformat()
    previous = params.urlencode()
    params["date"] = (selected + timedelta(days=1)).isoformat()
    return render(request, "chorompo/agenda.html", context(request,
        filters=filters, selected=selected, previous=previous, next=params.urlencode(), columns=columns,
        ticks=[{"top": (n - lower) * 2, "label": f"{n // 60:02d}:{n % 60:02d}"} for n in range(lower, upper + 1, 30)],
        timeline_height=(upper - lower) * 2, appointment_count=count, block_count=len(blocks),
        timeline_start=lower,
        has_search=bool(query or data.get("professional")), room_count=len(rooms),
    ))


@clinic_required("appointments")
@require_http_methods(["POST"])
def appointment_move(request, pk):
    from django import forms
    from .treatment_services import save_appointment
    try:
        new_start = forms.DateTimeField().clean(request.POST.get("starts_at"))
        expected_start = forms.DateTimeField().clean(request.POST.get("expected_start"))
        expected_end = forms.DateTimeField().clean(request.POST.get("expected_end"))
        room = get_object_or_404(Room, company=request.company, pk=request.POST.get("room") if request.POST.get("room", "").isdigit() else 0)
        with transaction.atomic():
            Company.objects.select_for_update().get(pk=request.company.pk)
            item = get_object_or_404(Appointment.objects.select_for_update(), company=request.company, pk=pk)
            if item.starts_at != expected_start or item.ends_at != expected_end or str(item.room_id or "") != request.POST.get("expected_room", ""):
                return JsonResponse({"error": "Este atendimento foi alterado por outra pessoa. Atualize a agenda antes de mover."}, status=409)
            duration = item.ends_at - item.starts_at
            item.room = room
            item.starts_at = new_start
            item.ends_at = new_start + duration
            save_appointment(item)
    except ValidationError as error:
        return JsonResponse({"error": " ".join(error.messages)}, status=400)
    except IntegrityError:
        return JsonResponse({"error": "Não foi possível mover. Atualize a agenda e confira a disponibilidade."}, status=409)
    return JsonResponse({"message": "Agendamento movido. A duração foi mantida."})


@clinic_required("appointments")
@require_http_methods(["GET", "POST"])
def appointment_create(request):
    from .management_views import persist_appointment
    initial = {key: request.GET[key] for key in ("room", "starts_at", "ends_at") if key in request.GET}
    form = AppointmentForm(request.POST if request.method == "POST" else None, company=request.company, initial=initial)
    if request.method == "POST" and form.is_valid() and persist_appointment(form):
        messages.success(request, "Agendamento criado.")
        return redirect(reverse("chorompo:appointments") + "?date=" + timezone.localdate(form.instance.starts_at).isoformat())
    return render(request, "chorompo/edit.html", context(request, form=form, title="Novo agendamento", back_url=reverse("chorompo:appointments")))


@clinic_required("appointments")
@require_http_methods(["GET"])
def search(request):
    kind = request.GET.get("kind")
    query = request.GET.get("q", "").strip()[:100]
    try:
        page = max(1, min(10000, int(request.GET.get("page", "1"))))
    except ValueError:
        page = 1
    if kind == "patient":
        records = request.company.patients.filter(Q(name__icontains=query) | Q(phone_number__icontains=query) | Q(cpf__icontains=query)).order_by("name", "pk")
        build = lambda item: {"id": item.pk, "label": f"{item.name} · {item.birth_date:%d/%m/%Y} · {item.phone_number}"}
    elif kind == "treatment":
        patient = request.GET.get("patient", "")
        if not patient.isdigit():
            return JsonResponse({"results": [], "more": False})
        appointment = request.GET.get("appointment", "")
        own_session = Q(sessions__appointment__pk=int(appointment)) if appointment.isdigit() else Q(pk__in=[])
        records = request.company.treatments.filter(is_active=True, patient_id=patient).filter(Q(name__icontains=query) | Q(description__icontains=query)).select_related("treatment").annotate(
            available_count=Count("sessions", filter=Q(sessions__session_held=0) & (Q(sessions__appointment__isnull=True) | own_session)),
        ).annotate(availability_order=Case(When(available_count__gt=0, then=Value(0)), default=Value(1), output_field=IntegerField())).order_by("availability_order", "-available_count", "name", "pk")
        build = lambda item: {"id": item.pk, "label": f"{item.name} · Aquisição #{item.pk} · {item.treatment.duration_minutes} min", "duration": item.treatment.duration_minutes, "available": item.available_count}
    elif kind == "session":
        treatment = request.GET.get("treatment", "")
        if not treatment.isdigit():
            return JsonResponse({"results": [], "more": False})
        records = TreatmentSession.objects.filter(treatment__company=request.company, treatment__is_active=True, treatment_id=treatment, session_held=0, appointment__isnull=True).order_by("session_number")
        if query:
            records = records.filter(session_number=int(query)) if query.isdigit() else records.none()
        build = lambda item: {"id": item.pk, "label": f"Sessão {item.session_number}"}
    else:
        return JsonResponse({"results": [], "more": False}, status=400)
    records = list(records[(page - 1) * 20:page * 20 + 1])
    return JsonResponse({"results": [build(item) for item in records[:20]], "more": len(records) > 20})


@clinic_required("employees")
@require_http_methods(["GET"])
def settings(request):
    page = Paginator(RoomBlock.objects.filter(room__company=request.company).select_related("room__floor").order_by("-starts_at"), 20).get_page(request.GET.get("page"))
    return render(request, "chorompo/agenda_settings.html", context(request, active_module="agenda_settings",
        floors=request.company.floors.all(), rooms=request.company.rooms.select_related("floor"),
        blocks=page, page_obj=page))


@clinic_required("employees")
@require_http_methods(["GET", "POST"])
def setting_edit(request, kind, pk=None):
    choices = {"piso": (Floor, FloorForm, "piso"), "sala": (Room, RoomForm, "sala"), "bloqueio": (RoomBlock, RoomBlockForm, "bloqueio")}
    if kind not in choices:
        from django.http import Http404
        raise Http404
    model, form_type, label = choices[kind]
    scope = {"room__company": request.company} if model is RoomBlock else {"company": request.company}
    instance = get_object_or_404(model, pk=pk, **scope) if pk else None
    form = form_type(request.POST if request.method == "POST" else None, instance=instance, company=request.company)
    if request.method == "POST" and form.is_valid():
        try:
            save_configuration(form, request.company)
        except (ValidationError, IntegrityError) as error:
            form.add_error(None, " ".join(error.messages) if isinstance(error, ValidationError) else "Já existe um registro com este nome. Escolha outro nome.")
        else:
            messages.success(request, "Configuração salva. O histórico de agendamentos foi preservado.")
            return redirect("chorompo:agenda_settings")
    return render(request, "chorompo/edit.html", context(request, active_module="agenda_settings", form=form,
        title=("Editar " if pk else "Cadastrar ") + label, back_url=reverse("chorompo:agenda_settings")))
