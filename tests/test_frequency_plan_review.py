import hashlib
import os
from pathlib import Path
import subprocess
from types import SimpleNamespace as Obj
from unittest.mock import MagicMock, patch
from io import StringIO

import pytest
from django.test import override_settings
from django.core.management.base import CommandError

from apps.monitoring.services.frequency_plan_review import (
    PREFLIGHT_SCRIPT, check_saved_review, inventory_script, normalize_manifest,
    preparation_script, review_frequency_plan,
)

BOOT = '12345678-1234-1234-1234-123456789012'
STATE = {'freq_mhz': 5135, 'boot_id': BOOT}
CFG = 'radio.1.freq=5135\nradio.1.chanbw=20'
PLAN = 'kill -1 1\n/bin/chsw 5895 5895; iwconfig_code=$?'
ARCHIVE = '/tmp/fai-review-' + 'a' * 32
HASH_LINE = 'fb4b2313b59f4a9ac195910e75e1e169  ./inittab'
OLD_LINK = 'lrwxrwxrwx 1 AdminFas admin 17 Jan  1  1970 ./services -> /usr/etc/services'
LATER_LINK = OLD_LINK.replace('Jan  1  1970', 'Oct  5 14:16')


def test_legacy_manifest_ignores_only_dates_preserving_names_with_spaces():
    before = HASH_LINE + '\n' + OLD_LINK.replace('./services', './service file', 1)
    after = HASH_LINE + '\n' + LATER_LINK.replace('./services', './service file', 1)
    assert normalize_manifest(before) == normalize_manifest(after)


@pytest.mark.parametrize('before,after', [
    (HASH_LINE, HASH_LINE.replace('fb4b', 'aa4b')),
    (OLD_LINK, LATER_LINK.replace('/usr/etc/services', '/usr/etc/other')),
    (OLD_LINK, LATER_LINK.replace('lrwxrwxrwx', 'lrwxrwx---')),
    (OLD_LINK, LATER_LINK.replace('AdminFas', 'other')),
    (OLD_LINK, LATER_LINK.replace('admin', 'other')),
    (OLD_LINK, LATER_LINK.replace('./services', './other', 1)),
    ('META -rw-r--r-- 1000 100 ./config', 'META -rw-rw-rw- 1000 100 ./config'),
])
def test_meaningful_manifest_changes_remain_different(before, after):
    assert normalize_manifest(before) != normalize_manifest(after)


@pytest.mark.parametrize('invalid', ['', 'FAI_INVENTORY_ERROR', 'lrwxrwxrwx broken',
                                     'unexpected output', OLD_LINK + '\n' + LATER_LINK])
def test_invalid_or_duplicate_manifest_cannot_validate_restoration(invalid):
    with pytest.raises(ValueError):
        normalize_manifest(invalid)


def saved_review_responses(*, config_changed=False, services_changed=False, plan_changed=False,
                           processes='', unlock_error=False, modern=False):
    commands = []
    before = HASH_LINE + '\n' + ('META lrwxrwxrwx 1000 100 ./services -> /usr/etc/services' if modern else OLD_LINK)
    after = before if modern else HASH_LINE + '\n' + LATER_LINK
    if services_changed:
        after = after.replace('/usr/etc/services', '/usr/etc/other')
    def execute(client, command, **options):
        commands.append(command)
        if command == f'cat {ARCHIVE}/etc.before':
            return before
        if command in (f'cat {ARCHIVE}/system.cfg', f'cat {ARCHIVE}/running.cfg', 'cat /tmp/running.cfg'):
            return CFG
        if command == 'cat /tmp/system.cfg':
            return CFG.replace('5135', '5895') if config_changed else CFG
        if command == inventory_script(legacy=not modern):
            return after
        if command == 'ps':
            return processes
        if command.startswith('if test -e'):
            if plan_changed:
                raise RuntimeError('Ancien plan différent')
            return ''
        if command.startswith('test -d /tmp/fai-frequency-review.lock'):
            if unlock_error:
                raise RuntimeError('Verrou non vide')
            return ''
        if command.startswith('test -'):
            return ''
        raise AssertionError(command)
    return commands, execute


@override_settings(FREQUENCY_COMMANDS_VERIFIED=False)
@pytest.mark.parametrize('release,modern', [(False, False), (True, False), (False, True), (True, True)])
def test_saved_review_validates_current_state_and_releases_only_when_explicit(release, modern):
    client = MagicMock()
    commands, execute = saved_review_responses(modern=modern)
    with patch('apps.monitoring.services.frequency_plan_review.checked_exec', side_effect=execute), \
         patch('apps.monitoring.services.frequency_plan_review.inspect_device', return_value=STATE), \
         patch('apps.monitoring.services.frequency_plan_review.runtime', return_value=STATE):
        result = check_saved_review(MagicMock(return_value=client), Obj(), ARCHIVE, release_lock=release)
    assert result['ok'] and result['released'] == release and result['legacy'] != modern
    assert sum('rmdir /tmp/fai-frequency-review.lock' in cmd for cmd in commands) == int(release)
    assert not any('rm -' in cmd or 'tar -' in cmd or '/sbin/cfgmtd' in cmd or '/bin/chsw' in cmd for cmd in commands)
    client.close.assert_called_once()


@override_settings(FREQUENCY_COMMANDS_VERIFIED=False)
@pytest.mark.parametrize('options', [
    {'config_changed': True}, {'services_changed': True}, {'plan_changed': True},
    {'processes': '123 AdminFas /sbin/ubntconf -p /tmp/running.cfg'},
    {'processes': '123 sh ' + ARCHIVE},
])
def test_saved_review_refuses_unlock_if_config_services_plan_or_process_differ(options):
    commands, execute = saved_review_responses(**options)
    with patch('apps.monitoring.services.frequency_plan_review.checked_exec', side_effect=execute), \
         patch('apps.monitoring.services.frequency_plan_review.inspect_device', return_value=STATE), \
         patch('apps.monitoring.services.frequency_plan_review.runtime', return_value=STATE):
        result = check_saved_review(MagicMock(return_value=MagicMock()), Obj(), ARCHIVE, release_lock=True)
    assert not result['ok']
    assert not any('rmdir' in cmd for cmd in commands)


@override_settings(FREQUENCY_COMMANDS_VERIFIED=False)
def test_saved_review_cannot_remove_a_nonempty_lock():
    commands, execute = saved_review_responses(unlock_error=True)
    with patch('apps.monitoring.services.frequency_plan_review.checked_exec', side_effect=execute), \
         patch('apps.monitoring.services.frequency_plan_review.inspect_device', return_value=STATE), \
         patch('apps.monitoring.services.frequency_plan_review.runtime', return_value=STATE):
        result = check_saved_review(MagicMock(return_value=MagicMock()), Obj(), ARCHIVE, release_lock=True)
    assert not result['ok'] and 'Verrou non vide' in result['message']


@override_settings(FREQUENCY_COMMANDS_VERIFIED=False)
def test_saved_review_does_not_release_if_boot_changes_during_check():
    commands, execute = saved_review_responses()
    with patch('apps.monitoring.services.frequency_plan_review.checked_exec', side_effect=execute), \
         patch('apps.monitoring.services.frequency_plan_review.inspect_device', return_value=STATE), \
         patch('apps.monitoring.services.frequency_plan_review.runtime', return_value=dict(STATE, boot_id='changed')):
        result = check_saved_review(MagicMock(return_value=MagicMock()), Obj(), ARCHIVE, release_lock=True)
    assert not result['ok']
    assert not any('rmdir' in cmd for cmd in commands)


@pytest.mark.parametrize('directory', ['/tmp', '/etc', '/tmp/fai-review-abc; reboot'])
def test_saved_review_rejects_unrestricted_paths_before_connecting(directory):
    connect = MagicMock()
    assert not check_saved_review(connect, Obj(), directory, release_lock=True)['ok']
    connect.assert_not_called()


@override_settings(FREQUENCY_COMMANDS_VERIFIED=True)
def test_saved_review_refuses_when_real_commands_enabled():
    connect = MagicMock()
    assert not check_saved_review(connect, Obj(), ARCHIVE, release_lock=True)['ok']
    connect.assert_not_called()


def responses(*, pending=False, prepare_error=False, preflight_error=False, restored=True):
    commands = []
    reads = {'system': 0}
    def execute(client, command, **options):
        commands.append(command)
        if command == 'cat /tmp/system.cfg':
            reads['system'] += 1
            return CFG if restored or reads['system'] == 1 else CFG.replace('5135', '5895')
        if command == 'cat /tmp/running.cfg':
            return CFG + ('\nother=pending' if pending else '')
        if command == PREFLIGHT_SCRIPT:
            if preflight_error:
                raise RuntimeError('Outil airOS requis absent : diff ; préparation refusée avant toute écriture.')
            return ''
        if command.startswith('set -eu\n'):
            if prepare_error:
                raise RuntimeError('Préparateur refusé')
            return PLAN
        raise AssertionError(command)
    return commands, execute


@override_settings(FREQUENCY_COMMANDS_VERIFIED=False)
def test_review_returns_exact_unapproved_plan_with_restored_state():
    client = MagicMock()
    commands, execute = responses()
    with patch('apps.monitoring.services.frequency_plan_review.checked_exec', side_effect=execute), \
         patch('apps.monitoring.services.frequency_plan_review.inspect_device', return_value=STATE), \
         patch('apps.monitoring.services.frequency_plan_review.runtime', return_value=STATE):
        result = review_frequency_plan(MagicMock(return_value=client), Obj(), 5895)
    assert result['ok'] and result['restored'] and result['target_matches']
    assert result['execution_blocked']
    assert result['plan'] == PLAN
    assert result['sha256'] == hashlib.sha256(PLAN.encode()).hexdigest()
    assert not any(cmd.startswith('/bin/sh ') or cmd.startswith('/sbin/cfgmtd ') for cmd in commands)
    client.close.assert_called_once()


@override_settings(FREQUENCY_COMMANDS_VERIFIED=False)
def test_missing_dependency_prevents_preparation_without_uncertain_restoration():
    client = MagicMock()
    commands, execute = responses(preflight_error=True)
    with patch('apps.monitoring.services.frequency_plan_review.checked_exec', side_effect=execute), \
         patch('apps.monitoring.services.frequency_plan_review.inspect_device', return_value=STATE):
        result = review_frequency_plan(MagicMock(return_value=client), Obj(), 5895)
    assert not result['ok'] and not result['uncertain']
    assert 'archive' not in result and 'plan' not in result
    assert 'avant toute écriture' in result['message']
    assert commands == ['cat /tmp/system.cfg', 'cat /tmp/running.cfg', PREFLIGHT_SCRIPT]
    client.close.assert_called_once()


@pytest.mark.parametrize('target', ['5895; reboot', True, 4800, 6000])
def test_invalid_proposal_never_connects(target):
    connect = MagicMock()
    assert not review_frequency_plan(connect, Obj(), target)['ok']
    connect.assert_not_called()


@override_settings(FREQUENCY_COMMANDS_VERIFIED=True)
def test_review_refuses_when_real_commands_enabled():
    connect = MagicMock()
    assert not review_frequency_plan(connect, Obj(), 5895)['ok']
    connect.assert_not_called()


@override_settings(FREQUENCY_COMMANDS_VERIFIED=False)
def test_pending_other_changes_prevent_preparation():
    commands, execute = responses(pending=True)
    with patch('apps.monitoring.services.frequency_plan_review.checked_exec', side_effect=execute), \
         patch('apps.monitoring.services.frequency_plan_review.inspect_device', return_value=STATE):
        result = review_frequency_plan(MagicMock(return_value=MagicMock()), Obj(), 5895)
    assert not result['ok']
    assert not any(cmd.startswith('set -eu\n') for cmd in commands)


@override_settings(FREQUENCY_COMMANDS_VERIFIED=False)
@pytest.mark.parametrize('after,restored', [
    ({'freq_mhz': 5895, 'boot_id': BOOT}, True),
    ({'freq_mhz': 5135, 'boot_id': '87654321-1234-1234-1234-123456789012'}, True),
    (STATE, False),
])
def test_review_reports_uncertain_if_final_state_differs(after, restored):
    commands, execute = responses(restored=restored)
    with patch('apps.monitoring.services.frequency_plan_review.checked_exec', side_effect=execute), \
         patch('apps.monitoring.services.frequency_plan_review.inspect_device', return_value=STATE), \
         patch('apps.monitoring.services.frequency_plan_review.runtime', return_value=after):
        result = review_frequency_plan(MagicMock(return_value=MagicMock()), Obj(), 5895)
    assert not result['ok'] and result['uncertain']


@override_settings(FREQUENCY_COMMANDS_VERIFIED=False)
def test_preparation_error_never_yields_plan_for_approval():
    commands, execute = responses(prepare_error=True)
    with patch('apps.monitoring.services.frequency_plan_review.checked_exec', side_effect=execute), \
         patch('apps.monitoring.services.frequency_plan_review.inspect_device', return_value=STATE):
        result = review_frequency_plan(MagicMock(return_value=MagicMock()), Obj(), 5895)
    assert not result['ok'] and result['uncertain']
    assert 'plan' not in result


@pytest.mark.parametrize('directory', ['/tmp', '/etc', '/tmp/fai-review-abc; reboot'])
def test_remote_backup_directory_is_restricted(directory):
    with pytest.raises(ValueError):
        preparation_script(5895, directory)


@pytest.mark.parametrize('mode', [
    'success', 'refused', 'missing', 'hup', 'new_file', 'changed_running', 'without_old_plan',
    'without_cmp', 'without_diff', 'without_tar', 'without_md5sum', 'without_sort', 'diff_error',
    'link_dates', 'link_target', 'link_permissions', 'link_owner',
    'md5_error', 'metadata_error', 'find_error', 'sed_error',
])
def test_remote_transaction_restores_files_in_isolated_shell(tmp_path, mode):
    # Exécuter le vrai shell de préparation dans un faux système de fichiers.
    # Aucune commande d'application n'est simulée comme exécutée.
    shell = Path('C:/Program Files/Git/bin/bash.exe') if os.name == 'nt' else Path('/bin/sh')
    if not shell.exists():
        pytest.skip('Shell POSIX indisponible')
    etc, tmp = tmp_path / 'etc', tmp_path / 'tmp'
    etc.mkdir()
    tmp.mkdir()
    for name in ('system.cfg', 'running.cfg'):
        (tmp / name).write_text(CFG + '\n', encoding='utf-8')
    if mode != 'without_old_plan':
        (tmp / 'diff.sh').write_text('old plan\n', encoding='utf-8')
    (etc / 'inittab').write_text('old inittab\n', encoding='utf-8')
    # Les chemins sont produits par pytest, aucun contenu réseau n'est utilisé.
    root = tmp_path.as_posix()
    assert not any(c in root for c in " '\n\r")
    if os.name == 'nt':
        # GNU tar interprète C: comme une archive distante ; utiliser le chemin MSYS.
        root = '/' + root[0].lower() + root[2:]
    stub = '#!/bin/sh\n'
    stub += f"echo invoked > {root}/generator-invoked\n"
    stub += f"echo changed > {root}/etc/inittab\n"
    if mode == 'new_file':
        stub += f"echo new > {root}/etc/added.conf\n"
    if mode == 'changed_running':
        stub += f"echo concurrent > {root}/tmp/running.cfg\n"
    if mode == 'hup':
        stub += 'kill -HUP "$PPID"\n'
    if mode != 'missing':
        stub += f"printf 'kill -1 1\\n/bin/chsw 5895 5895; iwconfig_code=$?\\n' > {root}/tmp/diff.sh\n"
    stub += 'exit ' + ('1' if mode == 'refused' else '0') + '\n'
    generator = tmp_path / 'ubntconf'
    generator.write_text(stub, encoding='utf-8')
    generator.chmod(0o700)
    script = preparation_script(5895, '/tmp/fai-review-' + 'a' * 32)
    script = script.replace('/sbin/ubntconf', root + '/ubntconf')
    script = script.replace('/tmp/', root + '/tmp/')
    script = script.replace('cd /etc', 'cd ' + root + '/etc').replace('-C /etc', '-C ' + root + '/etc')
    missing_dependency = mode in ('without_diff', 'without_tar', 'without_md5sum', 'without_sort')
    if missing_dependency:
        utility = mode.removeprefix('without_')
        # Masquer un outil pendant le contrôle, sans modifier le système hôte.
        script = f'command() {{ case "$*" in "-v {utility}") return 127;; *) return 0;; esac; }}\n' + script
    elif mode == 'without_cmp':
        script = 'cmp() { echo "cmp unavailable" >&2; return 127; }\n' + script
    elif mode == 'diff_error':
        script = 'diff() { echo "comparison unavailable" >&2; return 2; }\n' + script
    elif mode in ('md5_error', 'metadata_error'):
        selector = 'md5sum' if mode == 'md5_error' else 'ls'
        extra = r'''find() {
    case "$*" in *__SELECTOR__*) echo FAI_INVENTORY_ERROR; return 0;; esac
    command find "$@"
}
'''
        script = extra.replace('__SELECTOR__', selector) + script
    elif mode == 'find_error':
        script = 'find() { return 1; }\n' + script
    elif mode == 'sed_error':
        script = 'sed() { return 1; }\n' + script
    elif mode.startswith('link_'):
        # BusyBox tar recrée les liens avec la date actuelle. Cette fixture
        # conserve l'écart de date après extraction, comme le retour terrain.
        extra = r'''find() {
    command find "$@" || return $?
    case "$*" in *ls*)
        mode=lrwxrwxrwx; uid=1000; destination=/usr/etc/services
        stamp='Jan  1  1970'
        if test -f __ROOT__/generator-invoked; then
            stamp='Oct  5 14:16'
            __CHANGE__
        fi
        printf '%s 1 %s 100 17 %s ./fake-link -> %s\n' "$mode" "$uid" "$stamp" "$destination"
        ;;
    esac
}
'''
        change = {'link_dates': ':', 'link_target': 'destination=/usr/etc/other',
                  'link_permissions': 'mode=lrwxrwx---', 'link_owner': 'uid=1001'}[mode]
        script = extra.replace('__ROOT__', root).replace('__CHANGE__', change) + script
    # Toujours vérifier qu'aucun accès aux vrais fichiers airOS ne subsiste.
    assert ' /etc' not in script and '=/tmp/' not in script and ' /tmp/' not in script
    outcome = subprocess.run([str(shell)], input=script, text=True, capture_output=True, timeout=20)
    assert (tmp / 'system.cfg').read_text(encoding='utf-8') == CFG + '\n', outcome.stderr
    assert (etc / 'inittab').read_text(encoding='utf-8') == 'old inittab\n', outcome.stderr
    if mode == 'without_old_plan':
        assert not (tmp / 'diff.sh').exists(), outcome.stderr
    else:
        assert (tmp / 'diff.sh').read_text(encoding='utf-8') == 'old plan\n', outcome.stderr
    if mode in ('new_file', 'changed_running', 'link_target', 'link_permissions', 'link_owner'):
        assert outcome.returncode != 0
        assert (tmp / ('fai-review-' + 'a' * 32) / 'etc.tar').exists()
        assert 'Restauration non confirmée' in outcome.stderr
    else:
        expected = 0 if mode in ('success', 'without_old_plan', 'without_cmp', 'link_dates') else (2 if mode == 'diff_error' else 1)
        assert outcome.returncode == expected, outcome.stderr
        assert not (tmp / ('fai-review-' + 'a' * 32)).exists()
        assert not (tmp / 'fai-frequency-review.lock').exists()
    if mode in ('success', 'without_old_plan', 'without_cmp', 'link_dates'):
        assert outcome.stdout.strip() == PLAN
    if missing_dependency or mode in ('diff_error', 'md5_error', 'metadata_error', 'find_error', 'sed_error'):
        assert not (tmp_path / 'generator-invoked').exists()
        assert not outcome.stdout
    if missing_dependency:
        assert f'Outil airOS requis absent : {utility}' in outcome.stderr
    if mode != 'changed_running':
        assert (tmp / 'running.cfg').read_text(encoding='utf-8') == CFG + '\n'


@pytest.mark.parametrize('config', [None, Obj(auto_switch=True, scan_actif=False), Obj(auto_switch=False, scan_actif=True)])
def test_command_blocks_preparation_unless_both_automation_options_off(config):
    from apps.monitoring.management.commands.review_frequency_plan import Command
    with patch('apps.monitoring.management.commands.review_frequency_plan.NetworkDevice.objects') as devices, \
         patch('apps.monitoring.management.commands.review_frequency_plan.FrequenceConfig.objects') as configs, \
         patch('apps.monitoring.management.commands.review_frequency_plan.review_frequency_plan') as review:
        devices.select_related.return_value.get.return_value = Obj(pk=9)
        configs.filter.return_value.first.return_value = config
        with pytest.raises(CommandError):
            Command().handle(device=9, target=5895)
        review.assert_not_called()


def test_command_outputs_review_without_approving_or_changing_database():
    from apps.monitoring.management.commands.review_frequency_plan import Command
    output = StringIO()
    config = Obj(auto_switch=False, scan_actif=False, save=MagicMock())
    reviewed = dict(ok=True, freq_before=5135, target=5895, target_matches=True,
                    execution_blocked=True, sha256='a' * 64, plan=PLAN)
    with patch('apps.monitoring.management.commands.review_frequency_plan.NetworkDevice.objects') as devices, \
         patch('apps.monitoring.management.commands.review_frequency_plan.FrequenceConfig.objects') as configs, \
         patch('apps.monitoring.management.commands.review_frequency_plan.review_frequency_plan', return_value=reviewed):
        devices.select_related.return_value.get.return_value = Obj(pk=9, name='Central-6')
        configs.filter.return_value.first.return_value = config
        Command(stdout=output).handle(device=9, target=5895)
    assert 'NON exécuté' in output.getvalue()
    assert 'Aucune approbation ajoutée' in output.getvalue()
    config.save.assert_not_called()


@pytest.mark.parametrize('config', [None, Obj(auto_switch=True, scan_actif=False), Obj(auto_switch=False, scan_actif=True)])
def test_saved_review_command_requires_automation_off(config):
    from apps.monitoring.management.commands.check_frequency_review import Command
    with patch('apps.monitoring.management.commands.check_frequency_review.NetworkDevice.objects') as devices, \
         patch('apps.monitoring.management.commands.check_frequency_review.FrequenceConfig.objects') as configs, \
         patch('apps.monitoring.management.commands.check_frequency_review.check_saved_review') as check:
        devices.select_related.return_value.get.return_value = Obj(pk=9)
        configs.filter.return_value.first.return_value = config
        with pytest.raises(CommandError):
            Command().handle(device=9, archive=ARCHIVE, release_lock=True)
        check.assert_not_called()


def test_saved_review_command_defaults_to_read_only_and_keeps_archives():
    from apps.monitoring.management.commands.check_frequency_review import Command
    output = StringIO()
    with patch('apps.monitoring.management.commands.check_frequency_review.NetworkDevice.objects') as devices, \
         patch('apps.monitoring.management.commands.check_frequency_review.FrequenceConfig.objects') as configs, \
         patch('apps.monitoring.management.commands.check_frequency_review.check_saved_review') as check:
        device = Obj(pk=9, name='Central-6')
        devices.select_related.return_value.get.return_value = device
        config = Obj(auto_switch=False, scan_actif=False, save=MagicMock())
        configs.filter.return_value.first.return_value = config
        check.return_value = dict(ok=True, freq_mhz=5135, released=False, archive=ARCHIVE, legacy=True)
        Command(stdout=output).handle(device=9, archive=ARCHIVE)
        assert check.call_args.kwargs == {'release_lock': False}
        config.save.assert_not_called()
    assert 'lecture seule ; verrou conservé' in output.getvalue()
    assert 'Sauvegardes conservées' in output.getvalue()
