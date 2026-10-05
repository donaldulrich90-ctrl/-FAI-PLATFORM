"""Application rapide airOS, sans repli vers une relance générale.

La présence du script ne prouve pas sa compatibilité : validation terrain requise.
La fréquence en service et l'identifiant de démarrage sont vérifiés séparément.
"""
import re
import time
import uuid
import hashlib
from django.conf import settings

SOFT_APPLY = '/usr/etc/rc.d/rc.softrestart'


def checked_exec(client, command):
    _, stdout, stderr = client.exec_command(command, timeout=20)
    out = stdout.read().decode('utf-8', errors='replace')
    err = stderr.read().decode('utf-8', errors='replace')
    if stdout.channel.recv_exit_status() != 0:
        raise RuntimeError('Commande airOS refusée : ' + err.strip()[:160])
    return out.strip()


def runtime(client):
    out = checked_exec(client, 'iwconfig ath0')
    match = re.search(r'Frequency[:=]\s*(\d+(?:\.\d+)?)\s*GHz', out, re.I)
    if not match:
        raise RuntimeError('Fréquence radio en service illisible.')
    boot = checked_exec(client, 'cat /proc/sys/kernel/random/boot_id')
    if not re.fullmatch(r'[0-9a-fA-F-]{36}', boot):
        raise RuntimeError('Identifiant de démarrage indisponible.')
    return {'freq_mhz': round(float(match.group(1)) * 1000), 'boot_id': boot}


def inspect_device(client):
    state = runtime(client)
    config = checked_exec(client, "grep -E '^radio\\.1\\.(freq|chanbw)=' /tmp/system.cfg")
    freq = re.findall(r'^radio\.1\.freq=(\d+)$', config, re.M)
    width = re.findall(r'^radio\.1\.chanbw=(\d+)$', config, re.M)
    if len(freq) != 1 or len(width) != 1 or int(width[0]) != 20:
        raise RuntimeError('Seules les configurations radio 20 MHz reconnues sont prises en charge.')
    if int(freq[0]) != state['freq_mhz']:
        raise RuntimeError('Fréquence configurée différente de la fréquence en service.')
    checked_exec(client, 'test -x /sbin/ubntconf && test ! -e /tmp/.force && test ! -e /var/run/testmode && test ! -e /tmp/.rc_is_running')
    return state


def apply_frequency(connect, device, target, *, deadline_seconds=120):
    """Ne réussit qu'après lecture du canal effectif et du même boot_id.

    Les états incertains sont signalés au décideur, qui peut tenter un retour.
    """
    if type(target) is not int or not 4900 <= target <= 5900:
        return {'ok': False, 'blocked': True, 'message': 'Fréquence invalide.'}
    client = None
    backup = '/tmp/fai-freq-' + uuid.uuid4().hex + '.cfg'
    staged = False
    started = False
    old = None
    try:
        client = connect(device)
        old = inspect_device(client)
        if old['freq_mhz'] == target:
            return {'ok': True, 'changed': False, 'message': 'Fréquence déjà en service.'}
        # Ne jamais appliquer d'autres modifications en attente avec celle de fréquence.
        system = checked_exec(client, 'cat /tmp/system.cfg')
        running = checked_exec(client, 'cat /tmp/running.cfg')
        if not system or sorted(system.replace('\r', '').splitlines()) != sorted(running.replace('\r', '').splitlines()):
            raise RuntimeError('Autres modifications en attente : application refusée.')
        checked_exec(client, f'cp /tmp/system.cfg {backup}')
        staged = True
        checked_exec(client, "sed -i 's/^radio\\.1\\.freq=[0-9][0-9]*$/radio.1.freq="
                     + str(target) + "/' /tmp/system.cfg")
        value = checked_exec(client, "grep -E '^radio\\.1\\.freq=' /tmp/system.cfg")
        if value != f'radio.1.freq={target}':
            raise RuntimeError('Écriture de fréquence non confirmée.')
        # Prépare seulement le chemin rapide. Aucun appel à rc.softrestart/save/force.
        status = checked_exec(client, 'if /sbin/ubntconf -p /tmp/running.cfg >/tmp/fai-fast-prepare.log 2>&1; then echo FAST; else echo REFUSED; fi')
        if status != 'FAST':
            raise RuntimeError('Application rapide indisponible : aucun repli vers une relance générale.')
        checked_exec(client, 'test ! -e /tmp/.force && test ! -e /var/run/testmode && test ! -e /tmp/.rc_is_running')
        plan = checked_exec(client, 'cat /tmp/diff.sh')
        digest = hashlib.sha256(plan.encode('utf-8')).hexdigest()
        approved = getattr(settings, 'FREQUENCY_FAST_APPLY_PLAN_HASHES', {})
        hashes = approved.get(str(getattr(device, 'pk', '')), []) if isinstance(approved, dict) else []
        # Un script généré doit avoir été examiné pour cet appareil avant exécution.
        if not plan or not isinstance(hashes, list) or digest not in hashes:
            raise RuntimeError('Plan rapide non validé pour cet appareil : application refusée.')
        # Refuser toute commande kill, même si l'empreinte a été approuvée.
        # Le signal envoyé au PID 1 dans certains plans airOS n'est pas validé.
        # killall reste distinct : les signaux ustatsd ne ciblent pas init.
        if re.search(r'\b(reboot|shutdown|halt|poweroff|kill|rc_stop|rc_start|rc\.softrestart|rc\.do\.softrestart)\b', plan):
            raise RuntimeError('Plan rapide interdit : relance générale ou commande kill non validée détectée.')
        plan_file = backup + '.sh'
        checked_exec(client, f'cp /tmp/diff.sh {plan_file}')
        snapshot = checked_exec(client, f'cat {plan_file}')
        if hashlib.sha256(snapshot.encode('utf-8')).hexdigest() != digest:
            raise RuntimeError('Plan modifié pendant la préparation : application refusée.')
        # Ce lancement peut couper SSH. La déconnexion n'est jamais une preuve de succès.
        started = True
        try:
            checked_exec(client, f'/bin/sh {plan_file}')
        except Exception:
            pass
        client.close()
        client = None
        deadline = time.monotonic() + deadline_seconds
        while time.monotonic() < deadline:
            probe = None
            try:
                probe = connect(device)
                current = runtime(probe)
                if current['boot_id'] != old['boot_id']:
                    return {'ok': False, 'reboot_detected': True, 'uncertain': True,
                            'message': 'Redémarrage complet détecté : intervention requise.'}
                if current['freq_mhz'] == target:
                    # Persister seulement après confirmation du canal et du même démarrage.
                    try:
                        checked_exec(probe, '/sbin/cfgmtd -w -f /tmp/system.cfg -p /etc/')
                        checked_exec(probe, 'cp /tmp/system.cfg /tmp/running.cfg')
                    except Exception:
                        return {'ok': False, 'uncertain': True, 'message':
                                'Canal appliqué mais sauvegarde non confirmée : retour à vérifier.'}
                    checked_exec(probe, f'rm -f {backup} {plan_file}')
                    return {'ok': True, 'changed': True, 'message': (
                        f'{target} MHz vérifiés en service, identifiant de démarrage inchangé.'
                    )}
            except Exception:
                pass
            finally:
                if probe is not None:
                    probe.close()
            time.sleep(5)
        return {'ok': False, 'uncertain': True, 'message': (
            'Application non confirmée dans le délai ; vérifier la liaison et le retour.'
        )}
    except Exception as exc:
        if staged and not started and client is not None:
            try:
                checked_exec(client, f'cp {backup} /tmp/system.cfg && rm -f {backup}')
            except Exception:
                return {'ok': False, 'uncertain': True,
                        'message': 'Configuration temporaire non restaurée : intervention requise.'}
        return {'ok': False, 'blocked': not started, 'message': str(exc)[:200]}
    finally:
        if client is not None:
            client.close()
