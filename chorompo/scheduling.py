"""Shared availability rules; mutations lock the clinic before checking intervals."""
from copy import copy
from datetime import datetime, timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .models import Appointment, Company, RoomBlock


def occurrence_on(block, day):
    if block.recurrence == RoomBlock.Recurrence.ONCE:
        return block
    anchor = timezone.localtime(block.starts_at)
    if day < anchor.date() or (block.repeat_until and day > block.repeat_until):
        return None
    if block.recurrence == RoomBlock.Recurrence.WEEKLY and day.weekday() not in block.weekdays:
        return None
    occurrence = copy(block)
    occurrence.starts_at = timezone.make_aware(datetime.combine(day, anchor.time()))
    occurrence.ends_at = timezone.make_aware(datetime.combine(day, timezone.localtime(block.ends_at).time()))
    return occurrence


def block_overlaps(block, starts_at, ends_at):
    if block.recurrence == RoomBlock.Recurrence.ONCE:
        return block.starts_at < ends_at and block.ends_at > starts_at
    day = max(timezone.localdate(starts_at), timezone.localdate(block.starts_at))
    last = timezone.localdate(ends_at)
    if block.repeat_until:
        last = min(last, block.repeat_until)
    # A weekly rule repeats within seven days, even for a long historical interval.
    for offset in range(min(8, max(0, (last - day).days + 1))):
        occurrence = occurrence_on(block, day + timedelta(days=offset))
        if occurrence and occurrence.starts_at < ends_at and occurrence.ends_at > starts_at:
            return True
    return False


def blocks_for_day(company, day):
    records = RoomBlock.objects.filter(room__company=company, is_active=True).filter(
        Q(recurrence="ONCE", starts_at__date__lte=day, ends_at__date__gte=day)
        | (Q(starts_at__date__lte=day) & ~Q(recurrence="ONCE") & (Q(repeat_until__isnull=True) | Q(repeat_until__gte=day)))
    ).select_related("room__floor")
    return [occurrence for block in records if (occurrence := occurrence_on(block, day)) is not None]


def validate_appointment(item):
    if item.canceled_at or not item.starts_at or not item.ends_at:
        return
    if item.ends_at <= item.starts_at:
        raise ValidationError({"ends_at": "O término deve ser após o início."})
    start, end = timezone.localtime(item.starts_at), timezone.localtime(item.ends_at)
    if item.room_id:
        room = item.room
        if room.company_id != item.company_id:
            raise ValidationError({"room": "Selecione uma sala desta clínica."})
        if not room.is_active or not room.floor.is_active:
            raise ValidationError({"room": "Esta sala ou piso está desativado. Escolha uma sala ativa."})
        if start.date() != end.date() or start.time() < room.opens_at or end.time() > room.closes_at:
            raise ValidationError({"ends_at": f"Esta sala funciona das {room.opens_at:%H:%M} às {room.closes_at:%H:%M}. Ajuste início e término."})
        block = next((block for block in blocks_for_day(item.company_id, start.date()) if block.room_id == room.pk and block_overlaps(block, item.starts_at, item.ends_at)), None)
        if block:
            raise ValidationError({"starts_at": f"Sala bloqueada: {block.reason}. Escolha outro horário ou sala."})
    conflicts = Appointment.objects.filter(
        company_id=item.company_id, canceled_at__isnull=True,
        starts_at__lt=item.ends_at, ends_at__gt=item.starts_at,
    ).exclude(pk=item.pk)
    resources = Q(patient_id=item.patient_id) | Q(professional_id=item.professional_id)
    if item.room_id:
        resources |= Q(room_id=item.room_id)
    conflict = conflicts.filter(resources).first()
    if conflict:
        resource = "sala" if item.room_id and conflict.room_id == item.room_id else "paciente" if conflict.patient_id == item.patient_id else "profissional"
        raise ValidationError(f"Horário ocupado: já existe atendimento para {'a sala' if resource == 'sala' else 'o ' + resource}. Escolha outro período ou altere a seleção.")


def inferred_end(item):
    duration = item.treatment_company.duration_minutes if item.treatment_company_id else 30
    return item.starts_at + timedelta(minutes=duration)


@transaction.atomic
def save_configuration(form, company):
    Company.objects.select_for_update().get(pk=company.pk)
    item = form.save(commit=False)
    if hasattr(item, "company_id"):
        item.company = company
    if isinstance(item, RoomBlock) and item.room.company_id != company.pk:
        raise ValidationError("Selecione uma sala desta clínica.")
    item.full_clean()
    # Do not silently invalidate appointments when changing a room's opening hours.
    from .models import Room
    if isinstance(item, Room) and item.pk:
        for booking in item.appointments.filter(canceled_at__isnull=True, ends_at__gte=timezone.now()):
            start, end = timezone.localtime(booking.starts_at), timezone.localtime(booking.ends_at)
            if start.date() != end.date() or start.time() < item.opens_at or end.time() > item.closes_at:
                raise ValidationError("Há atendimentos futuros fora do novo horário. Reagende esses atendimentos antes de alterar o funcionamento.")
    item.save()
    return item
