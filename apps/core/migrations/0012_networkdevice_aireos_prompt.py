from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0011_networkdevice_aireos_forward'),
    ]

    operations = [
        migrations.AddField(
            model_name='networkdevice',
            name='aireos_prompt',
            field=models.CharField(
                default='XC#',
                help_text='Prompt du shell interactif airOS : XC# (Rocket Prism, NanoStation…) ou WA# (LiteAP AC, Wave AP…).',
                max_length=8,
                verbose_name='Prompt shell airOS',
            ),
        ),
    ]
