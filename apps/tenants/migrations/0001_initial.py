# Generated manually for multi-tenant SaaS

from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="Tenant",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=128, verbose_name="Nom de l'organisation")),
                (
                    "slug",
                    models.SlugField(
                        db_index=True,
                        help_text="Identifiant technique unique (URL, API). Ex. mon-fai.",
                        max_length=64,
                        unique=True,
                    ),
                ),
                ("is_active", models.BooleanField(default=True, verbose_name="Actif")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "verbose_name": "organisation",
                "verbose_name_plural": "organisations",
                "ordering": ["name"],
            },
        ),
    ]
