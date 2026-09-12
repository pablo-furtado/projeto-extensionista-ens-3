from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("chorompo", "0002_company_onboarding_completed_treatment_appointment")]

    operations = [
        # Existing treatments were catalog items, not patient purchases.
        migrations.RenameModel(old_name="Treatment", new_name="TreatmentCompany"),
        migrations.RenameField(model_name="appointment", old_name="treatment", new_name="treatment_company"),
        migrations.AlterField(
            model_name="treatmentcompany", name="company",
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="company_treatments", to="chorompo.company"),
        ),
    ]
