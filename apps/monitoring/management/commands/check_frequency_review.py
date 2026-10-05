from django.core.management.base import BaseCommand, CommandError

from apps.core.models import NetworkDevice
from apps.monitoring.models import FrequenceConfig
from apps.monitoring.services.frequency_plan_review import check_saved_review
from apps.monitoring.services.ubiquiti_ssh import _connect


class Command(BaseCommand):
    help = ('Contrôle une sauvegarde de préparation sans modifier la configuration. '
            '--release-lock libère uniquement le verrou vide après validation.')

    def add_arguments(self, parser):
        parser.add_argument('--device', type=int, required=True)
        parser.add_argument('--archive', required=True)
        parser.add_argument('--release-lock', action='store_true')

    def handle(self, *args, **options):
        try:
            device = NetworkDevice.objects.select_related('parent_mikrotik').get(
                pk=options['device'], vendor='ubiquiti', is_active=True)
        except NetworkDevice.DoesNotExist:
            raise CommandError('Antenne Ubiquiti active introuvable.')
        config = FrequenceConfig.objects.filter(device=device).first()
        if config is None or config.auto_switch or config.scan_actif:
            raise CommandError('Configuration requise, avec basculement automatique et scan actif désactivés.')
        result = check_saved_review(_connect, device, options['archive'],
                                    release_lock=options.get('release_lock', False))
        if not result['ok']:
            raise CommandError(result['message'])
        self.stdout.write(f"Antenne : {device.name} (id {device.pk}) ; fréquence : {result['freq_mhz']} MHz")
        self.stdout.write('Configurations radio, ancien plan et fichiers de services conformes aux sauvegardes.')
        if result['legacy']:
            self.stdout.write('Inventaire historique : contenus des fichiers et destinations, permissions et propriétaires des liens contrôlés ; dates exclues.')
        else:
            self.stdout.write('Dates exclues ; contenus, destinations, permissions et propriétaires contrôlés.')
        self.stdout.write('Verrou libéré.' if result['released'] else 'Contrôle en lecture seule ; verrou conservé.')
        self.stdout.write('Sauvegardes conservées : ' + result['archive'])
        self.stdout.write('Aucune fréquence appliquée, aucun redémarrage demandé, aucune approbation ajoutée.')
