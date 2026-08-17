from decimal import Decimal

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('core', '0001_initial'),
        ('tenants', '0001_initial'),
        ('finance', '0001_initial'),
        ('wifi_zone', '0013_add_duration_2h_4h'),
    ]

    operations = [
        migrations.CreateModel(
            name='TicketConsommation',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('code', models.CharField(db_index=True, max_length=32, verbose_name='Code ticket')),
                ('duration', models.CharField(choices=[('2h', '2 heures'), ('3h', '3 heures'), ('4h', '4 heures'), ('1d', '24 heures (1 jour)'), ('5j', '5 jours'), ('1w', '7 jours'), ('30j', '30 jours'), ('illimite', 'Illimité')], max_length=8, verbose_name='Durée')),
                ('price_xof', models.DecimalField(decimal_places=0, default=Decimal('0'), max_digits=12, verbose_name='Prix (XOF)')),
                ('commission_amount_xof', models.DecimalField(decimal_places=0, default=Decimal('0'), max_digits=12, verbose_name='Commission (XOF)')),
                ('net_to_isp_xof', models.DecimalField(decimal_places=0, default=Decimal('0'), max_digits=12, verbose_name='Net FAI (XOF)')),
                ('mac_address', models.CharField(blank=True, max_length=17, verbose_name='MAC du client')),
                ('client_ip', models.GenericIPAddressField(blank=True, null=True, verbose_name='IP du client')),
                ('activated_at', models.DateTimeField(db_index=True, verbose_name='Activé le')),
                ('expires_at', models.DateTimeField(blank=True, db_index=True, help_text='Fin de validité calendaire (vide = illimité).', null=True, verbose_name='Expire le')),
                ('expired_at', models.DateTimeField(blank=True, help_text='Date effective de passage du ticket au statut Expiré.', null=True, verbose_name='Expiré le')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('cash_entry', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='ticket_consommations', to='finance.cashjournalentry', verbose_name='Écriture de caisse (preuve comptable)')),
                ('site', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='ticket_consommations', to='core.site', verbose_name='Site')),
                ('sold_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='ticket_consommations', to=settings.AUTH_USER_MODEL, verbose_name='Revendeur / vendeur')),
                ('tenant', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='ticket_consommations', to='tenants.tenant', verbose_name='Organisation')),
                ('ticket', models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='consommation', to='wifi_zone.ticket', verbose_name="Ticket d'origine")),
            ],
            options={
                'verbose_name': 'ticket consommé (archive)',
                'verbose_name_plural': 'tickets consommés (archives)',
                'ordering': ['-activated_at'],
            },
        ),
    ]
