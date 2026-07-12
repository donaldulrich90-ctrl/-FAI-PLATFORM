import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0009_alter_networkdevice_password_hint'),
    ]

    operations = [
        migrations.AddField(
            model_name='networkdevice',
            name='parent_mikrotik',
            field=models.ForeignKey(
                blank=True,
                help_text='MikroTik central via lequel cette antenne Ubiquiti est monitorée par SSH.',
                limit_choices_to={'vendor': 'mikrotik'},
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='ubiquiti_children',
                to='core.networkdevice',
                verbose_name='MikroTik parent',
            ),
        ),
        migrations.AddField(
            model_name='networkdevice',
            name='mikrotik_interface',
            field=models.CharField(
                blank=True,
                help_text="Port bridge du MikroTik connecté à cette antenne (ex. ether5). Utilisé pour compter les clients bridge.",
                max_length=32,
                verbose_name='Interface MikroTik (monitoring)',
            ),
        ),
    ]
