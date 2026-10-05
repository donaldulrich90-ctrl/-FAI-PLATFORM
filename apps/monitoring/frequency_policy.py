"""Décisions RF sans accès réseau : aucune commande n'est exécutée ici."""
from datetime import timedelta
import math


def valid_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def persistent_interference(samples, current_freq, now, snr_min, count=3, max_age_minutes=20):
    """Exige plusieurs observations récentes, consécutives, sur le canal courant."""
    if len(samples) < count:
        return False
    cutoff = now - timedelta(minutes=max_age_minutes)
    for sample in samples[:count]:
        if (sample.freq_mhz != current_freq or sample.measured_at < cutoff
                or sample.measured_at > now or not valid_number(sample.snr)
                or not valid_number(sample.noise_floor_dbm) or sample.snr >= snr_min):
            return False
    # Une exécution doublée du worker ne compte pas comme plusieurs observations.
    times = sorted(s.measured_at for s in samples[:count])
    return all((b - a).total_seconds() >= 240 for a, b in zip(times, times[1:]))


def choose_candidate(candidates, measurements, current_freq, current_noise, now,
                     min_gain_db=3, max_age_hours=24, min_samples=3):
    """Préférence = ordre configuré, parmi les canaux mesurés assez meilleurs."""
    if not valid_number(current_noise):
        return None, 0.0
    cutoff = now - timedelta(hours=max_age_hours)
    for freq in dict.fromkeys(candidates):
        if not freq or freq == current_freq:
            continue
        samples = [m for m in measurements if m.freq_mhz == freq
                   and cutoff <= m.measured_at <= now and valid_number(m.noise_floor_dbm)
                   and valid_number(m.snr)]
        # Plusieurs points espacés ; une rafale de doublons n'est pas une preuve.
        spaced = []
        for sample in sorted(samples, key=lambda m: m.measured_at):
            if not spaced or (sample.measured_at - spaced[-1].measured_at).total_seconds() >= 240:
                spaced.append(sample)
        if len(spaced) < min_samples:
            continue
        noise = sum(m.noise_floor_dbm for m in spaced) / len(spaced)
        if current_noise - noise >= min_gain_db:
            return freq, min(1.0, (current_noise - noise) / 20)
    return None, 0.0


def verified_improvement(before, after, target_freq, min_gain_db=3):
    """La fréquence, le SNR et le nombre de clients doivent être vérifiables."""
    if (not after.online or after.freq_mhz != target_freq or after.error
            or not valid_number(before.rssi_dbm) or not valid_number(before.noise_floor_dbm)
            or not valid_number(after.rssi_dbm) or not valid_number(after.noise_floor_dbm)
            or before.client_count is None or before.client_count <= 0
            or after.client_count is None or after.client_count < before.client_count):
        return False
    return ((after.rssi_dbm - after.noise_floor_dbm)
            - (before.rssi_dbm - before.noise_floor_dbm)) >= min_gain_db
