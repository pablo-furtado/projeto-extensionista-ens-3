from decimal import Decimal, ROUND_HALF_UP

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from .models import Appointment, CompanyMembership, EvolutionOfTreatment, Treatment, TreatmentCompany, TreatmentPackage, TreatmentSession


@transaction.atomic
def acquire_treatment(*, company, patient, catalog, qty_sessions, discount_percentage, package=None):
    catalog = TreatmentCompany.objects.select_for_update().get(pk=catalog.pk, company=company)
    if discount_percentage > (catalog.max_discount_percentage or 0):
        raise ValidationError("O desconto solicitado excede o limite do tratamento.")
    price = (catalog.price * qty_sessions * (Decimal("100") - discount_percentage) / Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    treatment = Treatment(
        company=company, patient=patient, treatment=catalog, name=catalog.name, description=catalog.description,
        qty_sessions=qty_sessions, discount_percentage=discount_percentage, price=price, package=package,
    )
    treatment.full_clean()
    treatment.save()
    TreatmentSession.objects.bulk_create([
        TreatmentSession(treatment=treatment, session_number=number)
        for number in range(1, qty_sessions + 1)
    ])
    return treatment


@transaction.atomic
def acquire_package(*, company, patient, name, items):
    if not 1 <= len(items) <= 20:
        raise ValidationError("O pacote deve conter entre 1 e 20 tratamentos.")
    ids = [item["treatment"].pk for item in items]
    if len(set(ids)) != len(ids):
        raise ValidationError("Um tratamento não pode se repetir no pacote.")
    # Lock the catalog in a stable order before creating any purchase.
    catalogs = {catalog.pk: catalog for catalog in TreatmentCompany.objects.select_for_update().filter(company=company, pk__in=ids).order_by("pk")}
    if len(catalogs) != len(ids):
        raise ValidationError("Selecione apenas tratamentos desta clínica.")
    package = TreatmentPackage(company=company, patient=patient, name=name)
    package.full_clean()
    package.save()
    for item in items:
        acquire_treatment(
            company=company, patient=patient, package=package, catalog=catalogs[item["treatment"].pk],
            qty_sessions=item["qty_sessions"], discount_percentage=item["discount_percentage"],
        )
    return package


@transaction.atomic
def record_evolution(*, session, employee, date, notes, uses_session):
    treatment = Treatment.objects.select_for_update().get(pk=session.treatment_id)
    session = TreatmentSession.objects.select_for_update().get(pk=session.pk, treatment=treatment)
    membership = CompanyMembership.objects.select_for_update().select_related("user").get(pk=employee.membership_id)
    if (membership.company_id != treatment.company_id or not membership.is_active or not membership.user.is_active
        or membership.role not in (CompanyMembership.Role.ADMIN, CompanyMembership.Role.PROFESSIONAL)):
        raise PermissionDenied("Seu perfil não pode registrar evoluções nesta clínica.")
    if uses_session:
        if not treatment.is_active:
            raise ValidationError("Este tratamento está inativo e não pode ter novas sessões utilizadas.")
        if session.session_held:
            raise ValidationError("Esta sessão já foi utilizada. Atualize a página antes de registrar outra evolução.")
    evolution = EvolutionOfTreatment(treatment=session, employee=employee, date=date, notes=notes, uses_session=uses_session)
    evolution.full_clean()
    evolution.save()
    if uses_session:
        session.session_held = 1
        session.date = date
        session.full_clean()
        session.save(update_fields=["session_held", "date"])
    return evolution


@transaction.atomic
def save_appointment(appointment):
    # Use the same lock order as session consumption to avoid scheduling a used session.
    treatment = Treatment.objects.select_for_update().get(pk=appointment.treatment_id, company=appointment.company)
    session = TreatmentSession.objects.select_for_update().get(pk=appointment.session_id, treatment=treatment)
    if Appointment.objects.filter(session=session).exclude(pk=appointment.pk).exists():
        raise ValidationError("Esta sessão já possui um agendamento.")
    appointment.treatment = treatment
    appointment.session = session
    appointment.full_clean()
    appointment.save()
    return appointment
