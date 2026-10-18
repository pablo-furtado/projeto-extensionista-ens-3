from django.db import models
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.utils import timezone


class Company(models.Model):
    name = models.CharField(max_length=100)
    cpf_cnpj = models.CharField(max_length=14, unique=True)
    cep = models.CharField(max_length=8)
    phone_number = models.CharField(max_length=15)
    email = models.EmailField(unique=True)
    onboarding_completed = models.BooleanField(default=False)

    def __str__(self):
        return self.name


class CompanyMembership(models.Model):

    class Role(models.TextChoices):
        ADMIN = "ADMIN", "Administrador"
        RECEPTION = "RECEPTION", "Recepção"
        FINANCIAL = "FINANCIAL", "Financeiro"
        PROFESSIONAL = "PROFESSIONAL", "Profissional"

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="company_memberships"
    )

    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name="memberships"
    )

    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.RECEPTION
    )

    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "company"],
                name="unique_user_company"
            )
        ]

    def __str__(self):
        return f"{self.user.username} - {self.company.name}"
    
class Employee(models.Model):
    membership = models.OneToOneField(
        CompanyMembership,
        on_delete=models.CASCADE,
        related_name="employee"
    )

    name = models.CharField(max_length=100)
    birth_date = models.DateField()
    cpf = models.CharField(max_length=11, unique=True)
    address = models.CharField(max_length=200)
    cep = models.CharField(max_length=8)

    def __str__(self):
        return self.name

class Patient(models.Model):
    name = models.CharField(max_length=100)
    birth_date = models.DateField()
    cpf = models.CharField(max_length=11, unique=True)
    cep = models.CharField(max_length=8)

    sex = models.CharField(
        max_length=1,
        choices=[
            ("M", "Masculino"),
            ("F", "Feminino"),
        ]
    )

    phone_number = models.CharField(max_length=15)

    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name="patients"
    )

    def __str__(self):
        return self.name





class TreatmentCompany(models.Model):
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="company_treatments")
    name = models.CharField("Nome do tratamento", max_length=100)
    description = models.TextField("Descrição", blank=True)
    duration_minutes = models.PositiveIntegerField("Duração em minutos", default=30, validators=[MinValueValidator(1)])
    price = models.DecimalField("Preço por sessão", max_digits=10, decimal_places=2, default=0, validators=[MinValueValidator(0)])

    fixed_cost = models.DecimalField(
        "Custo fixo", max_digits=10, decimal_places=2, default=0.00, help_text="Custo fixo por unidade de tratamento, como aluguel, salários ou despesas gerais.",
        null=True, blank=True, validators=[MinValueValidator(0)]
    )
    variable_cost = models.DecimalField(
        "Custo variável", max_digits=10, decimal_places=2, default=0.00, help_text="Custo variável por unidade de tratamento, como materiais ou insumos utilizados.",
        null=True, blank=True, validators=[MinValueValidator(0)]
    )
    max_discount_percentage = models.DecimalField(
        "Desconto máximo (%)", max_digits=5, decimal_places=2, default=0.00,
        null=True, blank=True, help_text="Porcentagem máxima de desconto que pode ser aplicada a este tratamento.",
        validators=[MinValueValidator(0), MaxValueValidator(100)]
    )
    def __str__(self):
        return self.name



class TreatmentSession(models.Model):
    session_number = models.PositiveIntegerField("Número da sessão", validators=[MinValueValidator(1)])
    session_held = models.PositiveIntegerField("Sessão realizada", default=0, validators=[MaxValueValidator(1)])
    date = models.DateField("Data da realização", null=True, blank=True)
    notes = models.TextField("Observações", blank=True)
    treatment = models.ForeignKey("Treatment", on_delete=models.PROTECT, related_name="sessions", verbose_name="Tratamento adquirido")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["treatment", "session_number"], name="unique_treatment_session_number"),
            models.CheckConstraint(condition=models.Q(session_held__in=[0, 1]), name="session_used_at_most_once"),
            models.CheckConstraint(condition=models.Q(session_number__gte=1), name="positive_session_number"),
        ]
        ordering = ["session_number"]

    def __str__(self):
        return f"{self.treatment.patient.name} · {self.treatment.name} · Sessão {self.session_number}"

    def clean(self):
        super().clean()
        if self.treatment_id and self.session_number and self.session_number > self.treatment.qty_sessions:
            raise ValidationError({"session_number": "A sessão excede a quantidade adquirida."})
        if bool(self.session_held) != bool(self.date):
            raise ValidationError("A data de realização deve ser preenchida apenas nas sessões utilizadas.")


class EvolutionOfTreatment(models.Model):
    treatment = models.ForeignKey(TreatmentSession, on_delete=models.PROTECT, related_name="evolutions", verbose_name="Sessão")
    date = models.DateField("Data da evolução", default=timezone.localdate)
    notes = models.TextField("Evolução e observações")
    uses_session = models.BooleanField("Registrar realização desta sessão", default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    employee = models.ForeignKey(Employee, on_delete=models.PROTECT, related_name="evolutions", verbose_name="Profissional")

    class Meta:
        ordering = ["-date", "-created_at", "-pk"]

    def __str__(self):
        return f"Evolução - {self.treatment.treatment.name} - {self.date}"

    def clean(self):
        super().clean()
        if self.date and self.date > timezone.localdate():
            raise ValidationError({"date": "A evolução não pode ter uma data futura."})
        if self.employee_id and self.treatment_id:
            membership = self.employee.membership
            if (membership.company_id != self.treatment.treatment.company_id
                or not membership.is_active or not membership.user.is_active
                or membership.role not in (CompanyMembership.Role.ADMIN, CompanyMembership.Role.PROFESSIONAL)):
                raise ValidationError({"employee": "Selecione um profissional ativo desta clínica."})


class TreatmentPackage(models.Model):
    company = models.ForeignKey(Company, on_delete=models.PROTECT, related_name="treatment_packages")
    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name="treatment_packages", verbose_name="Paciente")
    name = models.CharField("Nome do pacote", max_length=100, default="Pacote de tratamentos")
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def total_price(self):
        return self.treatments.aggregate(total=models.Sum("price"))["total"] or 0

    def clean(self):
        if self.patient_id and self.patient.company_id != self.company_id:
            raise ValidationError({"patient": "Selecione um paciente desta clínica."})


class Treatment(models.Model):
    package = models.ForeignKey(TreatmentPackage, on_delete=models.PROTECT, related_name="treatments", null=True, blank=True, verbose_name="Pacote de compra")
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="treatments")
    name = models.CharField("Nome do tratamento", max_length=100)
    description = models.TextField("Descrição", blank=True)
    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name="treatments", verbose_name="Paciente")
    treatment = models.ForeignKey(TreatmentCompany, on_delete=models.PROTECT, related_name="patient_treatments", verbose_name="Tratamento do catálogo")
    qty_sessions = models.PositiveIntegerField("Quantidade de sessões", default=1, validators=[MinValueValidator(1), MaxValueValidator(1000)], help_text="De 1 a 1.000 sessões por aquisição.")
    price = models.DecimalField("Valor total adquirido", max_digits=10, decimal_places=2, default=0, validators=[MinValueValidator(0)])
    discount_percentage = models.DecimalField("Desconto (%)", max_digits=5, decimal_places=2, default=0, validators=[MinValueValidator(0), MaxValueValidator(100)])
    is_active = models.BooleanField("Ativo", default=True)
    
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        constraints = [models.CheckConstraint(condition=models.Q(qty_sessions__gte=1, qty_sessions__lte=1000), name="valid_purchased_session_quantity")]


    def __str__(self):
        return f"{self.patient.name} · {self.name} · Aquisição #{self.pk}"

    @property
    def used_sessions(self):
        return self.sessions.filter(session_held=1).count()

    @property
    def remaining_sessions(self):
        return self.qty_sessions - self.used_sessions

    def clean(self):
        super().clean()
        errors = {}
        if self.patient_id and self.patient.company_id != self.company_id:
            errors["patient"] = "Selecione um paciente desta clínica."
        if self.treatment_id and self.treatment.company_id != self.company_id:
            errors["treatment"] = "Selecione um tratamento do catálogo desta clínica."
        if self.package_id and (self.package.company_id != self.company_id or self.package.patient_id != self.patient_id):
            errors["package"] = "O pacote deve pertencer ao mesmo paciente e clínica."
        if errors:
            raise ValidationError(errors)


class Floor(models.Model):
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="floors")
    name = models.CharField("Nome do piso", max_length=80)
    is_active = models.BooleanField("Ativo", default=True)

    class Meta:
        ordering = ["name", "pk"]
        constraints = [models.UniqueConstraint(fields=["company", "name"], name="unique_company_floor")]

    def __str__(self):
        return self.name


class Room(models.Model):
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="rooms")
    floor = models.ForeignKey(Floor, on_delete=models.PROTECT, related_name="rooms", verbose_name="Piso")
    name = models.CharField("Nome da sala", max_length=80)
    opens_at = models.TimeField("Abertura")
    closes_at = models.TimeField("Encerramento")
    color = models.CharField("Cor de identificação", max_length=7, default="#176f60")
    is_active = models.BooleanField("Ativa", default=True)

    class Meta:
        ordering = ["floor__name", "name", "pk"]
        constraints = [
            models.UniqueConstraint(fields=["floor", "name"], name="unique_floor_room"),
            models.CheckConstraint(condition=models.Q(closes_at__gt=models.F("opens_at")), name="room_positive_hours"),
        ]

    def __str__(self):
        return f"{self.floor.name} · {self.name}"

    def clean(self):
        import re
        if self.floor_id and self.floor.company_id != self.company_id:
            raise ValidationError({"floor": "Selecione um piso desta clínica."})
        if self.opens_at and self.closes_at and self.opens_at >= self.closes_at:
            raise ValidationError({"closes_at": "O encerramento deve ser após a abertura, no mesmo dia."})
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", self.color or ""):
            raise ValidationError({"color": "Escolha uma cor válida."})


class RoomBlock(models.Model):
    class Recurrence(models.TextChoices):
        ONCE = "ONCE", "Somente neste período"
        DAILY = "DAILY", "Todos os dias"
        WEEKLY = "WEEKLY", "Dias da semana"

    room = models.ForeignKey(Room, on_delete=models.PROTECT, related_name="blocks", verbose_name="Sala")
    starts_at = models.DateTimeField("Início")
    ends_at = models.DateTimeField("Término")
    reason = models.CharField("Motivo", max_length=160)
    is_active = models.BooleanField("Bloqueio ativo", default=True)
    recurrence = models.CharField("Repetir bloqueio", max_length=10, choices=Recurrence.choices, default=Recurrence.ONCE)
    weekdays = models.JSONField("Dias da semana", default=list, blank=True)
    repeat_until = models.DateField("Repetir até", null=True, blank=True)

    class Meta:
        ordering = ["starts_at"]
        constraints = [models.CheckConstraint(condition=models.Q(ends_at__gt=models.F("starts_at")), name="block_positive_duration")]

    def clean(self):
        super().clean()
        if self.starts_at and self.ends_at and self.ends_at <= self.starts_at:
            raise ValidationError({"ends_at": "Informe um término após o início."})
        if not isinstance(self.weekdays, list) or any(type(day) is not int or day not in range(7) for day in self.weekdays):
            raise ValidationError({"weekdays": "Selecione dias da semana válidos."})
        if self.recurrence == self.Recurrence.WEEKLY and not self.weekdays:
            raise ValidationError({"weekdays": "Selecione pelo menos um dia da semana."})
        if self.starts_at and self.ends_at:
            start, end = timezone.localtime(self.starts_at), timezone.localtime(self.ends_at)
            if self.recurrence != self.Recurrence.ONCE:
                if start.date() != end.date():
                    raise ValidationError({"ends_at": "Para repetir o bloqueio, início e término devem estar no mesmo dia."})
                if self.repeat_until and self.repeat_until < start.date():
                    raise ValidationError({"repeat_until": "A data final deve ser igual ou posterior ao início da repetição."})
            if self.is_active and self.room_id:
                from .scheduling import block_overlaps
                records = Appointment.objects.filter(room_id=self.room_id, canceled_at__isnull=True, ends_at__gt=self.starts_at)
                if self.recurrence == self.Recurrence.ONCE:
                    records = records.filter(starts_at__lt=self.ends_at)
                elif self.repeat_until:
                    records = records.filter(starts_at__date__lte=self.repeat_until)
                for booking in records.iterator():
                    if block_overlaps(self, booking.starts_at, booking.ends_at):
                        raise ValidationError(f"Há atendimento em {timezone.localtime(booking.starts_at):%d/%m/%Y às %H:%M}. Reagende ou cancele o atendimento antes de bloquear a sala.")

    @property
    def repetition_label(self):
        names = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]
        if self.recurrence == self.Recurrence.WEEKLY:
            return ", ".join(names[day] for day in sorted(self.weekdays))
        return self.get_recurrence_display()


class Appointment(models.Model):
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="appointments")
    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name="appointments", verbose_name="Paciente")
    treatment_company = models.ForeignKey(TreatmentCompany, on_delete=models.PROTECT, related_name="appointments", verbose_name="Tratamento do catálogo", null=True, blank=True)
    treatment = models.ForeignKey(Treatment, on_delete=models.PROTECT, related_name="appointments", verbose_name="Tratamento adquirido", null=True, blank=True)
    session = models.OneToOneField(TreatmentSession, on_delete=models.PROTECT, related_name="appointment", verbose_name="Sessão adquirida", null=True, blank=True)
    professional = models.ForeignKey(Employee, on_delete=models.PROTECT, related_name="appointments", verbose_name="Profissional")
    starts_at = models.DateTimeField("Data e horário")
    ends_at = models.DateTimeField("Término")
    room = models.ForeignKey(Room, on_delete=models.PROTECT, related_name="appointments", verbose_name="Sala", null=True, blank=True)
    canceled_at = models.DateTimeField(null=True, blank=True)
    canceled_session = models.ForeignKey(TreatmentSession, on_delete=models.PROTECT, related_name="canceled_appointments", null=True, blank=True)
    notes = models.TextField("Observações", blank=True)

    class Meta:
        ordering = ["starts_at"]
        constraints = [models.CheckConstraint(condition=models.Q(ends_at__gt=models.F("starts_at")) | models.Q(ends_at__isnull=True), name="appointment_positive_duration")]
        indexes = [models.Index(fields=["company", "starts_at"]), models.Index(fields=["room", "starts_at", "ends_at"])]

    def save(self, *args, **kwargs):
        # Retain compatibility with older integrations that only supplied a start.
        if self.starts_at and not self.ends_at:
            from .scheduling import inferred_end
            self.ends_at = inferred_end(self)
        super().save(*args, **kwargs)

    def clean(self):
        super().clean()
        errors = {}
        from .scheduling import validate_appointment
        validate_appointment(self)
        if self.patient_id and self.patient.company_id != self.company_id:
            errors["patient"] = "Selecione um paciente desta clínica."
        if self.treatment_id and self.treatment.company_id != self.company_id:
            errors["treatment"] = "Selecione um tratamento desta clínica."
        if self.treatment_id and self.treatment.patient_id != self.patient_id:
            errors["treatment"] = "O tratamento adquirido deve pertencer ao paciente selecionado."
        if self.treatment_company_id and self.treatment_company.company_id != self.company_id:
            errors["treatment_company"] = "Selecione um tratamento do catálogo desta clínica."
        if self.treatment_id and self.treatment.treatment_id != self.treatment_company_id:
            errors["treatment"] = "O catálogo deve corresponder ao tratamento adquirido."
        if self.session_id and (
            self.session.treatment_id != self.treatment_id or self.session.session_held
            or not self.session.treatment.is_active
        ):
            errors["session"] = "Selecione uma sessão disponível do tratamento adquirido."
        if self.professional_id and (
            self.professional.membership.company_id != self.company_id
            or not self.professional.membership.is_active
            or not self.professional.membership.user.is_active
            or self.professional.membership.role not in (CompanyMembership.Role.ADMIN, CompanyMembership.Role.PROFESSIONAL)
        ):
            errors["professional"] = "Selecione um profissional ativo desta clínica."
        if errors:
            raise ValidationError(errors)
