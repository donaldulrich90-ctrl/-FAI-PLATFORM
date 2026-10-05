from datetime import timedelta
from types import SimpleNamespace as Obj
from unittest.mock import patch, MagicMock

import pytest
from django.utils import timezone
from django.test import override_settings

from apps.monitoring.frequency_policy import (
    persistent_interference, choose_candidate, verified_improvement,
)
from apps.monitoring.services.snmp_ubiquiti import UbiquitiFullMetrics


def samples(freq=5180, noise=-95, snr=10, age_hours=0):
    now = timezone.now()
    return [Obj(freq_mhz=freq, noise_floor_dbm=noise, snr=snr,
                measured_at=now - timedelta(hours=age_hours, minutes=i * 5)) for i in range(3)]


def test_requires_three_spaced_poor_observations():
    data = samples()
    assert persistent_interference(data, 5180, timezone.now(), 15)
    assert not persistent_interference(data[:1], 5180, timezone.now(), 15)
    data[1].snr = 20
    assert not persistent_interference(data, 5180, timezone.now(), 15)


@pytest.mark.parametrize('change', ['stale', 'wrong_freq', 'missing', 'duplicate', 'nan'])
def test_unreliable_measurements_do_not_trigger(change):
    data = samples()
    if change == 'stale': data[2].measured_at -= timedelta(hours=1)
    if change == 'wrong_freq': data[2].freq_mhz = 5200
    if change == 'missing': data[2].snr = None
    if change == 'duplicate': data[1].measured_at = data[0].measured_at
    if change == 'nan': data[2].snr = float('nan')
    assert not persistent_interference(data, 5180, timezone.now(), 15)


def test_preferences_only_among_measured_better_channels():
    data = samples(5200, -95) + samples(5220, -100)
    assert choose_candidate([5180, 5200, 5220], data, 5180, -85, timezone.now())[0] == 5200
    assert choose_candidate([5180, 5220, 5200], data, 5180, -85, timezone.now())[0] == 5220


def test_unknown_stale_and_insufficient_gain_are_excluded():
    assert choose_candidate([5200], [], 5180, -85, timezone.now())[0] is None
    assert choose_candidate([5200], samples(5200, age_hours=25), 5180, -85, timezone.now())[0] is None
    assert choose_candidate([5200], samples(5200, -86), 5180, -85, timezone.now())[0] is None
    assert choose_candidate([5180], samples(), 5180, -85, timezone.now())[0] is None


def metrics(freq=5180, noise=-85, clients=5, online=True):
    return UbiquitiFullMetrics(online=online, freq_mhz=freq, noise_floor_dbm=noise,
                              rssi_dbm=-70, client_count=clients)


@pytest.mark.parametrize('after', [metrics(5200, -95, 4), metrics(5180, -95),
                                  metrics(5200, -86), metrics(5200, -95, online=False)])
def test_command_success_alone_is_not_improvement(after):
    assert not verified_improvement(metrics(), after, 5200)


def test_improvement_requires_clients_frequency_and_snr():
    assert verified_improvement(metrics(), metrics(5200, -95), 5200)


@override_settings(ROUTER_CONTROL_DRY_RUN=False, FREQUENCY_COMMANDS_VERIFIED=True,
                   FREQUENCY_SOFT_APPLY_ALLOWED={"1": [5180, 5200]})
@pytest.mark.parametrize('improved,restored', [(True, True), (False, True), (False, False)])
def test_change_verification_and_rollback(improved, restored):
    from apps.monitoring.frequency_decision import execute_frequency_change
    device = Obj(pk=1, name='central')
    cfg = Obj(freq_principale=5180, auto_switch=True, save=MagicMock())
    after = metrics(5200, -95, 5 if improved else 4)
    returned = metrics(5180, -85, 5 if restored else 0)
    with patch('apps.core.models.PtPLink.objects') as links, \
         patch('apps.monitoring.models.HistoriqueFrequence.objects') as history, \
         patch('apps.monitoring.services.ubiquiti_ssh.read_current_frequency', return_value={'ok':True,'freq_mhz':5180}), \
         patch('apps.monitoring.services.ubiquiti_ssh.set_frequency', return_value={'ok':True}) as setter, \
         patch('apps.monitoring.services.frequency_metrics.fetch_frequency_metrics') as service, \
         patch('apps.monitoring.frequency_scanner.record_measurement'), \
         patch('apps.notifications.whatsapp.send_admin_alert'), patch('time.sleep'):
        links.filter.return_value.first.return_value = None
        service.side_effect = [after, returned]
        ok = execute_frequency_change(device, cfg, 5200, baseline=metrics())
        assert ok == improved
        assert [call.args[1] for call in setter.call_args_list] == ([5200] if improved else [5200, 5180])
        assert history.create.call_args.kwargs['resultat'] == ('ameliore' if improved else 'degrade')
        assert cfg.auto_switch == (improved or restored)


@override_settings(ROUTER_CONTROL_DRY_RUN=True)
def test_dry_run_never_sends_commands_or_reports_improvement():
    from apps.monitoring.frequency_decision import execute_frequency_change
    cfg = Obj(freq_principale=5180, save=MagicMock())
    with patch('apps.core.models.PtPLink.objects') as links, \
         patch('apps.monitoring.models.HistoriqueFrequence.objects') as history, \
         patch('apps.monitoring.services.ubiquiti_ssh.read_current_frequency', return_value={'ok':True,'freq_mhz':5180}), \
         patch('apps.monitoring.services.ubiquiti_ssh.set_frequency') as setter, \
         patch('apps.notifications.whatsapp.send_admin_alert'):
        links.filter.return_value.first.return_value = None
        assert execute_frequency_change(Obj(name='central'), cfg, 5200)
        setter.assert_not_called()
        assert history.create.call_args.kwargs['resultat'] == 'neutre'


def test_active_probe_is_non_disruptive():
    from apps.monitoring.frequency_scanner import probe_best_frequency
    with patch('apps.monitoring.services.ubiquiti_ssh.set_frequency') as setter:
        assert not probe_best_frequency(None, None)['ok']
        setter.assert_not_called()


@override_settings(ROUTER_CONTROL_DRY_RUN=False, FREQUENCY_COMMANDS_VERIFIED=False)
def test_unvalidated_commands_block_real_automation():
    from apps.monitoring.frequency_decision import should_change_frequency
    assert not should_change_frequency(None, Obj(auto_switch=True))


@override_settings(ROUTER_CONTROL_DRY_RUN=False)
def test_unsupported_original_frequency_blocks_change():
    from apps.monitoring.frequency_decision import execute_frequency_change
    with patch('apps.core.models.PtPLink.objects') as links, \
         patch('apps.monitoring.services.ubiquiti_ssh.read_current_frequency', return_value={'ok':True,'freq_mhz':5120}), \
         patch('apps.monitoring.services.ubiquiti_ssh.set_frequency') as setter:
        links.filter.return_value.first.return_value = None
        assert not execute_frequency_change(Obj(name='central'), Obj(freq_principale=5120), 5200,
                                            baseline=metrics(5120))
        setter.assert_not_called()


@override_settings(ROUTER_CONTROL_DRY_RUN=False)
def test_frequency_change_never_connects_or_reboots():
    from apps.monitoring.services.ubiquiti_ssh import set_frequency
    with patch('apps.monitoring.services.ubiquiti_ssh._connect') as connect:
        result = set_frequency(None, 5200)
        assert not result['ok'] and result['blocked']
        connect.assert_not_called()


@override_settings(ROUTER_CONTROL_DRY_RUN=True)
def test_frequency_simulation_does_not_connect():
    from apps.monitoring.services.ubiquiti_ssh import set_frequency
    with patch('apps.monitoring.services.ubiquiti_ssh._connect') as connect:
        assert set_frequency(None, 5200)['ok']
        connect.assert_not_called()
