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

from apps.monitoring.services.frequency_plan_review import preparation_script, review_frequency_plan

BOOT = '12345678-1234-1234-1234-123456789012'
STATE = {'freq_mhz': 5135, 'boot_id': BOOT}
CFG = 'radio.1.freq=5135\nradio.1.chanbw=20'
PLAN = 'kill -1 1\n/bin/chsw 5895 5895; iwconfig_code=$?'


def responses(*, pending=False, prepare_error=False, restored=True):
    commands = []
    reads = {'system': 0}
    def execute(client, command, **options):
        commands.append(command)
        if command == 'cat /tmp/system.cfg':
            reads['system'] += 1
            return CFG if restored or reads['system'] == 1 else CFG.replace('5135', '5895')
        if command == 'cat /tmp/running.cfg':
            return CFG + ('\nother=pending' if pending else '')
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


@pytest.mark.parametrize('mode', ['success', 'refused', 'missing', 'hup', 'new_file', 'changed_running', 'without_old_plan'])
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
    # Toujours vérifier qu'aucun accès aux vrais fichiers airOS ne subsiste.
    assert ' /etc' not in script and '=/tmp/' not in script and ' /tmp/' not in script
    outcome = subprocess.run([str(shell)], input=script, text=True, capture_output=True, timeout=20)
    assert (tmp / 'system.cfg').read_text(encoding='utf-8') == CFG + '\n', outcome.stderr
    assert (etc / 'inittab').read_text(encoding='utf-8') == 'old inittab\n', outcome.stderr
    if mode == 'without_old_plan':
        assert not (tmp / 'diff.sh').exists(), outcome.stderr
    else:
        assert (tmp / 'diff.sh').read_text(encoding='utf-8') == 'old plan\n', outcome.stderr
    if mode in ('new_file', 'changed_running'):
        assert outcome.returncode != 0
        assert (tmp / ('fai-review-' + 'a' * 32) / 'etc.tar').exists()
        assert 'Restauration non confirmée' in outcome.stderr
    else:
        assert outcome.returncode == (0 if mode in ('success', 'without_old_plan') else 1), outcome.stderr
        assert not (tmp / ('fai-review-' + 'a' * 32)).exists()
        assert not (tmp / 'fai-frequency-review.lock').exists()
    if mode in ('success', 'without_old_plan'):
        assert outcome.stdout.strip() == PLAN
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
