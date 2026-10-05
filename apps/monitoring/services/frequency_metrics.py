"""Mesures RF en lecture seule, via le transport de gestion disponible."""
import json
import re
from .snmp_ubiquiti import UbiquitiFullMetrics, UbiquitiAirMAXSnmpService
from .ubiquiti_ssh import _connect
from .airos_soft_apply import checked_exec


def parse_radio(output):
    freq = re.search(r'Frequency[:=]\s*(\d+(?:\.\d+)?)\s*GHz', output, re.I)
    signal = re.search(r'Signal level[:=]\s*(-?\d+)\s*dBm', output, re.I)
    noise = re.search(r'Noise level[:=]\s*(-?\d+)\s*dBm', output, re.I)
    if not all((freq, signal, noise)):
        raise ValueError('Fréquence, signal ou bruit absent de la lecture radio.')
    return round(float(freq.group(1)) * 1000), int(signal.group(1)), int(noise.group(1))


def fetch_frequency_metrics(device):
    if not getattr(device, 'ssh_forward_port', None):
        return UbiquitiAirMAXSnmpService(device).fetch_full_metrics()
    client = None
    try:
        client = _connect(device)
        freq, signal, noise = parse_radio(checked_exec(client, 'iwconfig ath0'))
        raw = checked_exec(client, 'wstalist')
        clients = json.loads(raw)
        if not isinstance(clients, list) or any(not isinstance(c, dict) or not c.get('mac') for c in clients):
            raise ValueError('Liste des clients SSH non exploitable.')
        return UbiquitiFullMetrics(online=True, freq_mhz=freq, rssi_dbm=signal,
                                  noise_floor_dbm=noise, avg_signal_dbm=signal,
                                  client_count=len(clients))
    except Exception:
        # Ne pas journaliser la sortie iwconfig (elle peut contenir des clés).
        return UbiquitiFullMetrics(error='Mesures SSH indisponibles ou incomplètes ; aucun basculement autorisé.')
    finally:
        if client is not None:
            client.close()
