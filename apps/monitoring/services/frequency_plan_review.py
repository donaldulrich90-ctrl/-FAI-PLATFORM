"""Préparation d'un plan airOS, sans exécution ni sauvegarde en flash.

Cette opération écrit temporairement des fichiers : ce n'est pas un diagnostic
en lecture seule. Les archives restent sur l'antenne si la restauration échoue.
"""
import hashlib
import re
import uuid

from django.conf import settings

from .airos_soft_apply import checked_exec, inspect_device, runtime


def preparation_script(target, directory):
    """Une seule session shell ; le piège restaure même après un échec/HUP.

    /etc est archivé car ubntconf peut régénérer des fichiers de services.
    Aucun fichier nouvellement apparu dans /etc n'est supprimé automatiquement :
    une différence résiduelle rend la restauration incertaine et garde l'archive.
    """
    if type(target) is not int or not 4900 <= target <= 5900:
        raise ValueError('Fréquence proposée invalide.')
    if not re.fullmatch(r'/tmp/fai-review-[0-9a-f]{32}', directory):
        raise ValueError('Répertoire de préparation invalide.')
    return r'''set -eu
umask 077
work=__DIRECTORY__
lock=/tmp/fai-frequency-review.lock
mkdir "$lock" || { echo 'Autre préparation en cours.' >&2; exit 1; }
if ! mkdir "$work"; then rmdir "$lock"; exit 1; fi
staged=0
had_plan=0
manifest() {
    (cd /etc && {
        find . -type f -exec md5sum '{}' ';'
        find . -type l -exec ls -ld '{}' ';'
    } | sort)
}
finish() {
    code=$?
    trap - EXIT HUP INT TERM
    restored=1
    if [ "$staged" = 1 ]; then
        cp -p "$work/system.cfg" /tmp/system.cfg || restored=0
        cmp -s "$work/system.cfg" /tmp/system.cfg || restored=0
        cmp -s "$work/running.cfg" /tmp/running.cfg || restored=0
        if ! manifest > "$work/etc.after"; then
            restored=0
        elif ! cmp -s "$work/etc.before" "$work/etc.after"; then
            tar -xf "$work/etc.tar" -C /etc || restored=0
            manifest > "$work/etc.after" || restored=0
            cmp -s "$work/etc.before" "$work/etc.after" || restored=0
        fi
        if [ "$had_plan" = 1 ]; then
            cp -p "$work/diff.before" /tmp/diff.sh || restored=0
            cmp -s "$work/diff.before" /tmp/diff.sh || restored=0
        else
            rm -f /tmp/diff.sh || restored=0
        fi
        test ! -e /tmp/.force && test ! -e /var/run/testmode && test ! -e /tmp/.rc_is_running || restored=0
    fi
    if [ "$restored" != 1 ]; then
        echo "Restauration non confirmée ; archive conservée : $work" >&2
        exit 2
    fi
    rm -rf "$work"
    rmdir "$lock"
    exit "$code"
}
trap finish EXIT
trap 'exit 1' HUP INT TERM
test -x /sbin/ubntconf
test ! -e /tmp/.force && test ! -e /var/run/testmode && test ! -e /tmp/.rc_is_running
test -f /tmp/system.cfg && test ! -L /tmp/system.cfg
test -f /tmp/running.cfg && test ! -L /tmp/running.cfg
cp -p /tmp/system.cfg "$work/system.cfg"
cp -p /tmp/running.cfg "$work/running.cfg"
if [ -e /tmp/diff.sh ]; then
    test -f /tmp/diff.sh && test ! -L /tmp/diff.sh
    cp -p /tmp/diff.sh "$work/diff.before"
    had_plan=1
fi
manifest > "$work/etc.before"
tar -cf "$work/etc.tar" -C /etc .
manifest > "$work/etc.after"
cmp -s "$work/etc.before" "$work/etc.after"
cmp -s "$work/system.cfg" /tmp/system.cfg
cmp -s "$work/running.cfg" /tmp/running.cfg
staged=1
sed -i 's/^radio.1.freq=[0-9][0-9]*$/radio.1.freq=__TARGET__/' /tmp/system.cfg
test "$(grep -E '^radio.1.freq=' /tmp/system.cfg)" = 'radio.1.freq=__TARGET__'
# Supprimer l'ancien plan avant génération : ne jamais présenter un plan périmé.
rm -f /tmp/diff.sh
if ! /sbin/ubntconf -p /tmp/running.cfg > "$work/prepare.log" 2>&1; then
    echo 'Préparateur rapide refusé ; aucun repli.' >&2
    exit 1
fi
test ! -e /tmp/.force && test ! -e /var/run/testmode && test ! -e /tmp/.rc_is_running
test -s /tmp/diff.sh && test ! -L /tmp/diff.sh
cat /tmp/diff.sh
'''.replace('__DIRECTORY__', directory).replace('__TARGET__', str(target))


def review_frequency_plan(connect, device, target):
    if type(target) is not int or not 4900 <= target <= 5900:
        return {'ok': False, 'message': 'Fréquence proposée invalide.'}
    if getattr(settings, 'FREQUENCY_COMMANDS_VERIFIED', False):
        return {'ok': False, 'message': 'Désactiver les commandes réelles avant une préparation.'}
    client = None
    entered_preparation = False
    directory = '/tmp/fai-review-' + uuid.uuid4().hex
    try:
        client = connect(device)
        before = inspect_device(client)
        if target == before['freq_mhz']:
            return {'ok': False, 'message': 'La cible est déjà en service ; aucun changement à préparer.'}
        system = checked_exec(client, 'cat /tmp/system.cfg')
        running = checked_exec(client, 'cat /tmp/running.cfg')
        if not system or sorted(system.replace('\r', '').splitlines()) != sorted(running.replace('\r', '').splitlines()):
            return {'ok': False, 'message': 'Autres modifications en attente : préparation refusée.'}
        entered_preparation = True
        plan = checked_exec(client, preparation_script(target, directory), timeout=120)
        after = runtime(client)
        if after != before:
            return {'ok': False, 'uncertain': True, 'message':
                    'Fréquence ou démarrage modifié pendant la préparation : intervention requise.'}
        restored = checked_exec(client, 'cat /tmp/system.cfg')
        if restored != system or checked_exec(client, 'cat /tmp/running.cfg') != running:
            return {'ok': False, 'uncertain': True, 'message':
                    'Configuration non restaurée à l’identique : intervention requise.'}
        if not plan:
            return {'ok': False, 'message': 'Aucun plan produit.'}
        matches = re.findall(r'(?m)^\s*/bin/chsw\s+(\d+)\s+(\d+)\s*(?:;|$)', plan)
        blocked = bool(re.search(r'\b(reboot|shutdown|halt|poweroff|kill|rc_stop|rc_start|rc\.softrestart|rc\.do\.softrestart)\b', plan))
        return {'ok': True, 'freq_before': before['freq_mhz'], 'target': target,
                'boot_id': before['boot_id'], 'plan': plan,
                'sha256': hashlib.sha256(plan.encode('utf-8')).hexdigest(),
                'target_matches': matches == [(str(target), str(target))],
                'execution_blocked': blocked, 'restored': True}
    except Exception as exc:
        return {'ok': False, 'uncertain': entered_preparation, 'archive': directory,
                'message': str(exc)[:240]}
    finally:
        if client is not None:
            client.close()
