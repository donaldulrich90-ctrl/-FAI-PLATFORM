import django.db.models.deletion
from django.db import migrations, models


def fill_finance_tenants(apps, schema_editor):
    Site = apps.get_model("core", "Site")
    User = apps.get_model("accounts", "User")
    Tenant = apps.get_model("tenants", "Tenant")
    CashJournalEntry = apps.get_model("finance", "CashJournalEntry")
    CaisseDailyReport = apps.get_model("finance", "CaisseDailyReport")
    MaintenanceTicket = apps.get_model("finance", "MaintenanceTicket")
    default = Tenant.objects.get(slug="default")

    for row in CashJournalEntry.objects.all():
        tid = None
        if row.site_id:
            tid = Site.objects.values_list("tenant_id", flat=True).get(pk=row.site_id)
        elif row.created_by_id:
            tid = User.objects.filter(pk=row.created_by_id).values_list("tenant_id", flat=True).first()
        if tid is None:
            tid = default.pk
        row.tenant_id = tid
        row.save(update_fields=["tenant_id"])

    for row in CaisseDailyReport.objects.all():
        tid = default.pk
        if row.closed_by_id:
            t = User.objects.filter(pk=row.closed_by_id).values_list("tenant_id", flat=True).first()
            if t:
                tid = t
        row.tenant_id = tid
        row.save(update_fields=["tenant_id"])

    for row in MaintenanceTicket.objects.all():
        row.tenant_id = Site.objects.values_list("tenant_id", flat=True).get(pk=row.site_id)
        row.save(update_fields=["tenant_id"])


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("finance", "0002_maintenanceticket_faulty_link_caissedailyreport"),
        ("core", "0007_site_tenant"),
        ("accounts", "0003_user_tenant"),
        ("tenants", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="cashjournalentry",
            name="tenant",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="cash_journal_entries",
                to="tenants.tenant",
                verbose_name="Organisation",
            ),
        ),
        migrations.AddField(
            model_name="caissedailyreport",
            name="tenant",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="caisse_daily_reports",
                to="tenants.tenant",
                verbose_name="Organisation",
            ),
        ),
        migrations.AddField(
            model_name="maintenanceticket",
            name="tenant",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="maintenance_tickets",
                to="tenants.tenant",
                verbose_name="Organisation",
            ),
        ),
        migrations.RunPython(fill_finance_tenants, noop_reverse),
        migrations.AlterField(
            model_name="cashjournalentry",
            name="tenant",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="cash_journal_entries",
                to="tenants.tenant",
                verbose_name="Organisation",
            ),
        ),
        migrations.AlterField(
            model_name="caissedailyreport",
            name="tenant",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="caisse_daily_reports",
                to="tenants.tenant",
                verbose_name="Organisation",
            ),
        ),
        migrations.AlterField(
            model_name="caissedailyreport",
            name="report_date",
            field=models.DateField(db_index=True, verbose_name="Date"),
        ),
        migrations.AddConstraint(
            model_name="caissedailyreport",
            constraint=models.UniqueConstraint(
                fields=("tenant", "report_date"),
                name="finance_caissedailyreport_tenant_report_date_uniq",
            ),
        ),
        migrations.AlterField(
            model_name="maintenanceticket",
            name="tenant",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="maintenance_tickets",
                to="tenants.tenant",
                verbose_name="Organisation",
            ),
        ),
        migrations.AlterField(
            model_name="maintenanceticket",
            name="reference",
            field=models.CharField(db_index=True, editable=False, max_length=32),
        ),
        migrations.AddConstraint(
            model_name="maintenanceticket",
            constraint=models.UniqueConstraint(
                fields=("tenant", "reference"),
                name="finance_maintenanceticket_tenant_reference_uniq",
            ),
        ),
    ]
