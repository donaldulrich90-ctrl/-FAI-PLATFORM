"""Diagnostic en lecture seule depuis l'environnement réellement connecté aux antennes."""
from django.core.management.base import BaseCommand, CommandError
from apps.core.models import NetworkDevice
from apps.monitoring.services.ubiquiti_ssh import _connect
from apps.monitoring.services.airos_soft_apply import inspect_device, checked_exec


class Command(BaseCommand):
    help = 'Vérifie l’accès et les préconditions de fréquence, sans aucune écriture.'

    def add_arguments(self, parser):
        parser.add_argument('--device', type=int, required=True, help='Identifiant de l’antenne dans l’application')

    def handle(self, *args, **options):
        try:
            device = NetworkDevice.objects.select_related('parent_mikrotik').get(
                pk=options['device'], vendor='ubiquiti', is_active=True,
            )
        except NetworkDevice.DoesNotExist:
            raise CommandError('Antenne Ubiquiti active introuvable.')
        client = None
        try:
            client = _connect(device)
            state = inspect_device(client)
            self.stdout.write(f"Antenne : {device.name} (id {device.pk})")
            self.stdout.write(f"Fréquence en service : {state['freq_mhz']} MHz")
            self.stdout.write('Identifiant de démarrage lisible ; configuration 20 MHz cohérente.')
            self.stdout.write('Préparateur rapide présent ; aucun mode test/force/application en cours détecté.')
            self.stdout.write('Aucun plan rapide n’a été préparé, approuvé ou exécuté par ce diagnostic.')
            self.stdout.write('Diagnostic en lecture seule réussi. Compatibilité terrain NON prouvée.')
            self.stdout.write('Aucune écriture ni application de configuration effectuée.')
        except Exception as exc:
            raise CommandError(str(exc))
        finally:
            if client is not None:
                client.close()
