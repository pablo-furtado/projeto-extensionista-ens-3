from datetime import timedelta

from django.db import migrations, models


def backfill_end(apps, schema_editor):
    Appointment = apps.get_model("chorompo", "Appointment")
    records = Appointment.objects.using(schema_editor.connection.alias).filter(ends_at__isnull=True).select_related("treatment_company")
    for item in records.iterator():
        duration = item.treatment_company.duration_minutes if item.treatment_company_id else 30
        item.ends_at = item.starts_at + timedelta(minutes=max(1, duration))
        item.save(update_fields=["ends_at"])


class Migration(migrations.Migration):
    dependencies = [("chorompo", "0006_roomblock_appointment_canceled_at_and_more")]
    operations = [
        migrations.RunPython(backfill_end, migrations.RunPython.noop),
        migrations.AlterField(model_name="appointment", name="ends_at", field=models.DateTimeField(verbose_name="Término")),
    ]
