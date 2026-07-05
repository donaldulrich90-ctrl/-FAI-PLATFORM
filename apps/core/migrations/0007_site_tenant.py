# Multi-tenant: Site.tenant + unique (tenant, site_id)

import django.db.models.deletion
from django.db import migrations, models


def create_default_tenant_and_assign_sites(apps, schema_editor):
    Tenant = apps.get_model("tenants", "Tenant")
    Site = apps.get_model("core", "Site")
    t, _ = Tenant.objects.get_or_create(
        slug="default",
        defaults={"name": "Organisation par défaut", "is_active": True},
    )
    Site.objects.filter(tenant__isnull=True).update(tenant_id=t.pk)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("tenants", "0001_initial"),
        ("core", "0006_site_hotspot_profiles_per_duration"),
    ]

    operations = [
        migrations.AddField(
            model_name="site",
            name="tenant",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="sites",
                to="tenants.tenant",
                verbose_name="Organisation",
            ),
        ),
        migrations.RunPython(create_default_tenant_and_assign_sites, noop_reverse),
        migrations.AlterField(
            model_name="site",
            name="tenant",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="sites",
                to="tenants.tenant",
                verbose_name="Organisation",
            ),
        ),
        migrations.AlterField(
            model_name="site",
            name="site_id",
            field=models.CharField(
                db_index=True,
                help_text="Identifiant aligné sur Zabbix / routeurs / procédures terrain. Unique par organisation.",
                max_length=64,
                verbose_name="Identifiant site (réf. expl.)",
            ),
        ),
        migrations.AddConstraint(
            model_name="site",
            constraint=models.UniqueConstraint(fields=("tenant", "site_id"), name="core_site_tenant_site_id_uniq"),
        ),
    ]
