from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from django.utils import timezone


class TreatmentMigrationTests(TransactionTestCase):
    def test_existing_blocks_remain_one_off_after_recurrence_migration(self):
        from datetime import timedelta
        executor = MigrationExecutor(connection)
        latest = executor.loader.graph.leaf_nodes()
        self.addCleanup(lambda: MigrationExecutor(connection).migrate(latest))
        old_target = [("chorompo", "0007_preserve_appointment_duration")]
        executor.migrate(old_target)
        old = executor.loader.project_state(old_target).apps
        company = old.get_model("chorompo", "Company").objects.create(name="Clínica", cpf_cnpj="11222333000181", cep="78000000", phone_number="65999999999", email="block@example.com")
        floor = old.get_model("chorompo", "Floor").objects.create(company=company, name="Térreo")
        room = old.get_model("chorompo", "Room").objects.create(company=company, floor=floor, name="Sala A", opens_at="08:00", closes_at="18:00")
        start = timezone.now()
        block = old.get_model("chorompo", "RoomBlock").objects.create(room=room, starts_at=start, ends_at=start + timedelta(days=2), reason="Manutenção", is_active=False)
        MigrationExecutor(connection).migrate(latest)
        from .models import RoomBlock
        preserved = RoomBlock.objects.get(pk=block.pk)
        self.assertEqual(preserved.recurrence, "ONCE")
        self.assertEqual(preserved.weekdays, [])
        self.assertIsNone(preserved.repeat_until)
        self.assertEqual(preserved.starts_at, start)
        self.assertEqual(preserved.ends_at, start + timedelta(days=2))
        self.assertFalse(preserved.is_active)

    def test_existing_catalog_and_appointments_are_preserved_without_inventing_purchases(self):
        executor = MigrationExecutor(connection)
        latest = executor.loader.graph.leaf_nodes()
        self.addCleanup(lambda: MigrationExecutor(connection).migrate(latest))
        old_target = [("chorompo", "0002_company_onboarding_completed_treatment_appointment")]
        executor.migrate(old_target)
        old = executor.loader.project_state(old_target).apps
        company = old.get_model("chorompo", "Company").objects.create(name="Clínica existente", cpf_cnpj="11222333000181", cep="78000000", phone_number="65999999999", email="clinica@example.com")
        user = old.get_model("auth", "User").objects.create(username="antigo")
        membership = old.get_model("chorompo", "CompanyMembership").objects.create(company=company, user=user, role="ADMIN")
        employee = old.get_model("chorompo", "Employee").objects.create(membership=membership, name="Profissional", birth_date="1990-01-01", cpf="11122233344", address="Rua A", cep="78000000")
        patient = old.get_model("chorompo", "Patient").objects.create(company=company, name="Paciente", birth_date="2000-01-01", cpf="22233344455", cep="78000000", sex="F", phone_number="65999999999")
        catalog = old.get_model("chorompo", "Treatment").objects.create(company=company, name="Tratamento existente", description="Preservar descrição", duration_minutes=45)
        appointment = old.get_model("chorompo", "Appointment").objects.create(company=company, patient=patient, treatment=catalog, professional=employee, starts_at=timezone.now(), notes="Preservar observações")
        MigrationExecutor(connection).migrate(latest)
        from .models import Appointment, Treatment, TreatmentCompany, TreatmentSession
        preserved = TreatmentCompany.objects.get(pk=catalog.pk)
        self.assertEqual(preserved.name, "Tratamento existente")
        self.assertEqual(preserved.description, "Preservar descrição")
        self.assertEqual(preserved.duration_minutes, 45)
        preserved_appointment = Appointment.objects.get(pk=appointment.pk)
        self.assertEqual(preserved_appointment.treatment_company_id, catalog.pk)
        self.assertEqual(preserved_appointment.patient_id, patient.pk)
        self.assertEqual(preserved_appointment.notes, "Preservar observações")
        from datetime import timedelta
        self.assertEqual(preserved_appointment.ends_at, preserved_appointment.starts_at + timedelta(minutes=45))
        self.assertIsNone(preserved_appointment.room_id)
        self.assertIsNone(preserved_appointment.treatment_id)
        self.assertIsNone(preserved_appointment.session_id)
        self.assertFalse(Treatment.objects.exists())
        self.assertFalse(TreatmentSession.objects.exists())
