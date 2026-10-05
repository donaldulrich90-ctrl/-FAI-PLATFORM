from django.core.management.base import BaseCommand, CommandError

from apps.core.models import NetworkDevice
from apps.monitoring.models import FrequenceConfig
from apps.monitoring.services.frequency_plan_review import review_frequency_plan
from apps.monitoring.services.ubiquiti_ssh import _connect


class Command(BaseCommand):
    help = ('Prépare un plan de fréquence pour examen, sans l’exécuter. '
            'Écrit temporairement des fichiers airOS puis les restaure ; aucune approbation automatique.')

    def add_arguments(self, parser):
        parser.add_argument('--device', type=int, required=True)
        parser.add_argument('--target', type=int, required=True, help='Fréquence proposée en MHz')

    def handle(self, *args, **options):
        try:
            device = NetworkDevice.objects.select_related('parent_mikrotik').get(
                pk=options['device'], vendor='ubiquiti', is_active=True)
        except NetworkDevice.DoesNotExist:
            raise CommandError('Antenne Ubiquiti active introuvable.')
        config = FrequenceConfig.objects.filter(device=device).first()
        if config is None or config.auto_switch or config.scan_actif:
            raise CommandError('Configuration requise, avec basculement automatique et scan actif désactivés.')
        result = review_frequency_plan(_connect, device, options['target'])
        if not result['ok']:
            self.stderr.write(result['message'])
            if result.get('uncertain'):
                self.stderr.write('Restauration à vérifier avant toute autre opération.')
                if result.get('archive'):
                    self.stderr.write('Emplacement prévu pour les sauvegardes : ' + result['archive'])
            raise CommandError('Préparation non validée ; aucun plan exécuté par cette commande.')
        self.stdout.write(f"Antenne : {device.name} (id {device.pk})")
        self.stdout.write(f"Plan proposé : {result['freq_before']} → {result['target']} MHz, 20 MHz")
        self.stdout.write('SHA256 du programme chsw : ' + result['chsw_sha256'])
        self.stdout.write(f"Programme chsw reconnu par analyse statique : {result['chsw_known']}")
        if result['target_matches'] is None:
            self.stdout.write('Cible chsw : indéterminée ; programme non reconnu.')
        else:
            self.stdout.write(f"Cible chsw correspondante : {result['target_matches']}")
            if result['control_arg'] is not None:
                self.stdout.write(f"Arguments chsw : centre={result['center_arg']}, contrôle={result['control_arg']} MHz")
            if result['center_requires_driver_check']:
                self.stdout.write('La valeur du centre est transmise au pilote ; son acceptation reste à vérifier.')
        self.stdout.write(f"Exécution bloquée par les contrôles actuels : {result['execution_blocked']}")
        self.stdout.write('SHA256 : ' + result['sha256'])
        self.stdout.write('--- Plan à examiner, NON exécuté ---')
        self.stdout.write(result['plan'])
        self.stdout.write('Configuration restaurée ; fréquence en service et identifiant de démarrage inchangés.')
        self.stdout.write('Aucune approbation ajoutée. Compatibilité terrain du changement NON prouvée.')
