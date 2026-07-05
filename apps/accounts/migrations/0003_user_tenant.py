import django.db.models.deletion
from django.db import migrations, models


def assign_default_tenant(apps, schema_editor):
    Tenant = apps.get_model("tenants", "Tenant")
    User = apps.get_model("accounts", "User")
    t = Tenant.objects.get(slug="default")
    User.objects.filter(tenant__isnull=True, is_superuser=False).update(tenant_id=t.pk)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0002_remove_user_can_sell_tickets_and_more"),
        ("tenants", "0001_initial"),
        ("core", "0007_site_tenant"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="tenant",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="users",
                to="tenants.tenant",
                verbose_name="Organisation",
                help_text="Vide pour les super-utilisateurs plateforme ; obligatoire pour le personnel d'un FAI.",
            ),
        ),
        migrations.RunPython(assign_default_tenant, noop_reverse),
    ]
