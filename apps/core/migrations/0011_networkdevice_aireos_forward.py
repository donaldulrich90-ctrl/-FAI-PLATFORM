from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0010_networkdevice_mikrotik_monitoring'),
    ]

    operations = [
        migrations.AddField(
            model_name='networkdevice',
            name='ssh_forward_port',
            field=models.PositiveIntegerField(
                blank=True,
                help_text='Port de forwarding SSH configuré sur le MikroTik parent vers cette antenne airOS (ex. 2222). Si renseigné, la connexion SSH directe à l\'antenne est utilisée pour les métriques.',
                null=True,
                verbose_name='Port SSH forwarding airOS',
            ),
        ),
        migrations.AddField(
            model_name='networkdevice',
            name='aireos_username',
            field=models.CharField(
                blank=True,
                help_text='Username SSH pour la connexion directe à l\'antenne airOS (ex. AdminFasoEq).',
                max_length=64,
                verbose_name='Username airOS',
            ),
        ),
    ]
