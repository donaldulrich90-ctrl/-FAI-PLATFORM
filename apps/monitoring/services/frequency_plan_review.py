"""Préparation d'un plan airOS, sans exécution ni sauvegarde en flash.

Cette opération écrit temporairement des fichiers : ce n'est pas un diagnostic
en lecture seule. Les archives restent sur l'antenne si la restauration échoue.
"""
import hashlib
import re
import uuid

from django.conf import settings

from .airos_soft_apply import checked_exec, inspect_device, runtime


# BusyBox est compilé avec une sélection d'outils : ne pas supposer que cmp existe.
# diff sans option suffit à comparer les fichiers et est utilisé par airOS lui-même.
PREFLIGHT_SCRIPT = r'''set -eu
for utility in cat cp diff find grep ls md5sum mkdir rm rmdir sed sort tar; do
    if ! command -v "$utility" >/dev/null 2>&1; then
        echo "Outil airOS requis absent : $utility ; préparation refusée avant toute écriture." >&2
        exit 1
    fi
done
test -x /sbin/ubntconf
'''


def inventory_script(*, legacy=False):
    """Empreintes et métadonnées utiles, sans dates ni écritures sur l'antenne.

    Les marqueurs d'erreur empêchent find/sort de masquer un fichier illisible.
    Le format historique est conservé pour contrôler les anciennes sauvegardes.
    """
    metadata = r'''find . -type l -exec /bin/sh -c 'ls -ld "$1" || echo FAI_INVENTORY_ERROR' sh '{}' ';' || echo FAI_INVENTORY_ERROR'''
    if not legacy:
        # Conserver mode, propriétaire, groupe, chemin et destination du lien.
        # ls -n évite que la résolution des noms d'utilisateurs change le résultat.
        metadata = r'''{
    find . -exec /bin/sh -c 'LC_ALL=C ls -ldn "$1" || echo FAI_INVENTORY_ERROR' sh '{}' ';' || echo FAI_INVENTORY_ERROR
} | sed 's/^\([^ ][^ ]*\)  *[^ ][^ ]*  *\([^ ][^ ]*\)  *\([^ ][^ ]*\)  *[^ ][^ ]*  *[^ ][^ ]*  *[^ ][^ ]*  *[^ ][^ ]*  */META \1 \2 \3 /' || echo FAI_INVENTORY_ERROR'''
    return r'''(cd /etc && {
    find . -type f -exec /bin/sh -c 'md5sum "$1" || echo FAI_INVENTORY_ERROR' sh '{}' ';' || echo FAI_INVENTORY_ERROR
    __METADATA__
} | LC_ALL=C sort)
'''.replace('__METADATA__', metadata)


def normalize_manifest(text):
    """Ne retirer que les dates des anciennes lignes décrivant les liens."""
    if not text:
        raise ValueError('Inventaire de services vide.')
    records = []
    for line in text.splitlines():
        if re.fullmatch(r'[0-9a-f]{32}  \./[^\r\n]+', line):
            records.append(line)
        elif re.fullmatch(r'META [bcdlps-][^ ]{9,} \d+ \d+ (?:\.|\./[^\r\n]+)', line):
            records.append(line)
        elif line.startswith('l'):
            parts = line.split(None, 8)
            if (len(parts) != 9 or not re.fullmatch(r'l[^ ]{9,}', parts[0])
                    or not parts[1].isdigit() or not parts[4].isdigit()
                    or not parts[8].startswith('./') or ' -> ' not in parts[8]):
                raise ValueError('Inventaire historique de liens non reconnu.')
            records.append('LINK ' + ' '.join((parts[0], parts[2], parts[3], parts[8])))
        else:
            raise ValueError('Inventaire de services incomplet ou non reconnu.')
    if len(records) != len(set(records)):
        raise ValueError('Inventaire de services dupliqué.')
    return sorted(records)


def check_saved_review(connect, device, directory, *, release_lock=False):
    """Contrôler une sauvegarde ; libération explicite du seul verrou vide.

    Aucune restauration ni application de configuration n'est effectuée.
    Les sauvegardes restent intactes, même si le verrou est libéré.
    """
    if not re.fullmatch(r'/tmp/fai-review-[0-9a-f]{32}', directory):
        return {'ok': False, 'message': 'Répertoire de sauvegarde invalide.'}
    if getattr(settings, 'FREQUENCY_COMMANDS_VERIFIED', False):
        return {'ok': False, 'message': 'Désactiver les commandes réelles avant le contrôle.'}
    client = None
    try:
        client = connect(device)
        checked_exec(client, f'test -d {directory} && test ! -L {directory}')
        for name in ('system.cfg', 'running.cfg', 'etc.before'):
            checked_exec(client, f'test -f {directory}/{name} && test ! -L {directory}/{name}')
        state = inspect_device(client)
        saved_system = checked_exec(client, f'cat {directory}/system.cfg')
        saved_running = checked_exec(client, f'cat {directory}/running.cfg')
        if (saved_system != checked_exec(client, 'cat /tmp/system.cfg')
                or saved_running != checked_exec(client, 'cat /tmp/running.cfg')):
            return {'ok': False, 'message': 'Configuration différente de la sauvegarde ; verrou conservé.'}
        if sorted(saved_system.splitlines()) != sorted(saved_running.splitlines()):
            return {'ok': False, 'message': 'Sauvegardes de configuration incohérentes ; verrou conservé.'}
        saved_manifest = checked_exec(client, f'cat {directory}/etc.before')
        legacy = not any(line.startswith('META ') for line in saved_manifest.splitlines())
        current_manifest = checked_exec(client, inventory_script(legacy=legacy))
        if normalize_manifest(saved_manifest) != normalize_manifest(current_manifest):
            return {'ok': False, 'message': 'Contenu ou métadonnées de services différents ; verrou conservé.'}
        checked_exec(client, f'''if test -e {directory}/diff.before; then
    test -f {directory}/diff.before && test ! -L {directory}/diff.before &&
    test -f /tmp/diff.sh && test ! -L /tmp/diff.sh &&
    diff {directory}/diff.before /tmp/diff.sh >/dev/null
else
    test ! -e /tmp/diff.sh && test ! -L /tmp/diff.sh
fi''')
        if runtime(client) != state:
            return {'ok': False, 'message': 'État radio modifié pendant le contrôle ; verrou conservé.'}
        if release_lock:
            processes = checked_exec(client, 'ps')
            if re.search(r'(^|[ /])ubntconf(?:\s|$)', processes, re.M) or directory in processes:
                return {'ok': False, 'message': 'Préparation encore en cours ; verrou conservé.'}
            # Recontrôler les fichiers radio et les marqueurs immédiatement avant
            # rmdir. Ne jamais supprimer récursivement un verrou ou une archive.
            checked_exec(client, f'''test -d /tmp/fai-frequency-review.lock && test ! -L /tmp/fai-frequency-review.lock &&
test ! -e /tmp/.force && test ! -e /var/run/testmode && test ! -e /tmp/.rc_is_running &&
diff {directory}/system.cfg /tmp/system.cfg >/dev/null &&
diff {directory}/running.cfg /tmp/running.cfg >/dev/null &&
rmdir /tmp/fai-frequency-review.lock''')
        return {'ok': True, 'freq_mhz': state['freq_mhz'], 'archive': directory,
                'released': release_lock, 'legacy': legacy}
    except Exception as exc:
        return {'ok': False, 'message': str(exc)[:240]}
    finally:
        if client is not None:
            client.close()


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
    return PREFLIGHT_SCRIPT + r'''umask 077
work=__DIRECTORY__
lock=/tmp/fai-frequency-review.lock
mkdir "$lock" || { echo 'Autre préparation en cours.' >&2; exit 1; }
if ! mkdir "$work"; then rmdir "$lock"; exit 1; fi
staged=0
had_plan=0
same_file() {
    diff "$1" "$2" >/dev/null
}
manifest() {
    __INVENTORY__ > "$work/inventory.raw" || { echo 'Collecte des services refusée.' >&2; return 1; }
    if test ! -s "$work/inventory.raw" || grep -q FAI_INVENTORY_ERROR "$work/inventory.raw"; then
        echo 'Inventaire des services vide ou incomplet.' >&2
        return 1
    fi
    cat "$work/inventory.raw"
}
finish() {
    code=$?
    trap - EXIT HUP INT TERM
    restored=1
    if [ "$staged" = 1 ]; then
        cp -p "$work/system.cfg" /tmp/system.cfg || restored=0
        same_file "$work/system.cfg" /tmp/system.cfg || restored=0
        same_file "$work/running.cfg" /tmp/running.cfg || restored=0
        if ! manifest > "$work/etc.after"; then
            restored=0
        elif ! same_file "$work/etc.before" "$work/etc.after"; then
            tar -xf "$work/etc.tar" -C /etc || restored=0
            manifest > "$work/etc.after" || restored=0
            same_file "$work/etc.before" "$work/etc.after" || restored=0
        fi
        if [ "$had_plan" = 1 ]; then
            cp -p "$work/diff.before" /tmp/diff.sh || restored=0
            same_file "$work/diff.before" /tmp/diff.sh || restored=0
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
same_file "$work/etc.before" "$work/etc.after"
same_file "$work/system.cfg" /tmp/system.cfg
same_file "$work/running.cfg" /tmp/running.cfg
staged=1
sed -i 's/^radio\.1\.freq=[0-9][0-9]*$/radio.1.freq=__TARGET__/' /tmp/system.cfg
test "$(grep -E '^radio\.1\.freq=' /tmp/system.cfg)" = 'radio.1.freq=__TARGET__'
# Supprimer l'ancien plan avant génération : ne jamais présenter un plan périmé.
rm -f /tmp/diff.sh
if ! /sbin/ubntconf -p /tmp/running.cfg > "$work/prepare.log" 2>&1; then
    echo 'Préparateur rapide refusé ; aucun repli.' >&2
    exit 1
fi
test ! -e /tmp/.force && test ! -e /var/run/testmode && test ! -e /tmp/.rc_is_running
test -s /tmp/diff.sh && test ! -L /tmp/diff.sh
cat /tmp/diff.sh
'''.replace('__DIRECTORY__', directory).replace('__TARGET__', str(target)).replace('__INVENTORY__', inventory_script().strip())


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
        # Une session en lecture seule permet de signaler une dépendance absente
        # sans annoncer à tort une restauration incertaine ou une archive créée.
        checked_exec(client, PREFLIGHT_SCRIPT)
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
        result = {'ok': False, 'uncertain': entered_preparation, 'message': str(exc)[:240]}
        if entered_preparation:
            result['archive'] = directory
        return result
    finally:
        if client is not None:
            client.close()
