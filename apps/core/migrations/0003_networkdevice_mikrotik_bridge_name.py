from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0002_ptplink"),
    ]

    operations = [
        migrations.AddField(
            model_name="networkdevice",
            name="mikrotik_bridge_name",
            field=models.CharField(
                blank=True,
                help_text="Nom de l’interface bridge pour /interface bridge filter (ex. bridge). "
                "Vide = paramètre MIKROTIK_DEFAULT_BRIDGE_NAME.",
                max_length=48,
                verbose_name="Bridge MikroTik (filtre MAC)",
            ),
        ),
    ]
