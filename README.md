# Faso ISP Manager

Plateforme de gestion WISP (Wireless Internet Service Provider) pour l'Afrique de l'Ouest.

## Fonctionnalités

- Gestion des abonnés WiFi et PPPoE
- Contrôle RouterOS (MikroTik) via API librouteros
- Surveillance des antennes Ubiquiti airMAX via SNMP/SSH
- **Gestion intelligente des fréquences** (auto-basculement SNR)
- Dashboard financier avec export CSV/Excel
- Tickets plainte avec réponse WhatsApp CallMeBot
- Carte réseau 3D satellite Mapbox GL JS
- Multi-tenant SaaS avec rôles (admin, technicien, revendeur)

---

## Configuration des variables d'environnement

Copier `.env.example` en `.env` et renseigner les variables :

```bash
cp .env.example .env
```

### Mapbox (carte 3D satellite)

```env
MAPBOX_ACCESS_TOKEN=pk.eyJ1IjoiLi4uIn0...
```

Obtenez un token sur [mapbox.com](https://mapbox.com). Le plan gratuit (50 000 chargements/mois) est suffisant pour un usage interne. Sans token, la carte affiche un message de substitution.

### WhatsApp via CallMeBot

```env
WHATSAPP_CALLMEBOT_APIKEY=votre_apikey_callmebot
WHATSAPP_DRY_RUN=0          # Mettre à 0 en production (1 = simulation)
WHATSAPP_ADMIN_NUMBER=+226XXXXXXXXX   # Numéro admin pour alertes fréquences
```

**Activation CallMeBot :**
1. Envoyez `I allow callmebot to send me messages` au numéro WhatsApp +34 644 91 44 55
2. Vous recevrez une API key par message
3. Renseignez cette key dans `WHATSAPP_CALLMEBOT_APIKEY`

### Gestion intelligente des fréquences Ubiquiti

```env
FREQUENCY_AUTO_SWITCH=1              # 0 pour désactiver globalement
FREQUENCY_MIN_SNR=15                 # SNR minimum acceptable (dB)
FREQUENCY_MIN_SIGNAL=-75             # Signal minimum acceptable (dBm)
FREQUENCY_CHANGE_COOLDOWN_MINUTES=15 # Délai minimum entre deux changements
FREQUENCY_MAX_CHANGES_PER_HOUR=3    # Limite anti-oscillation par heure
```

**Fonctionnement :**
- La tâche `monitor_frequencies` s'exécute toutes les 5 minutes via django-q2
- Elle classe chaque antenne en état NORMAL / DÉGRADÉ / CRITIQUE / URGENCE
- Si l'état se dégrade et que les gardes anti-oscillation sont respectées, la fréquence bascule automatiquement vers la fréquence de secours configurée
- Un historique complet est disponible sur `/monitoring/antennes/frequences/`
- Une alerte WhatsApp est envoyée à `WHATSAPP_ADMIN_NUMBER` à chaque changement

**Configuration par antenne :** Via l'interface `/monitoring/antennes/frequences/` → bouton "Configurer" pour définir la fréquence principale, jusqu'à 3 fréquences de secours, et les seuils SNR/signal.

**Mode test :** Définir `ROUTER_CONTROL_DRY_RUN=1` pour simuler tous les changements sans envoyer de commandes SSH réelles.

---

## Installation

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser
python manage.py setup_schedules  # Enregistre les tâches planifiées
python manage.py runserver
```

**Démarrer le worker django-q2 :**

```bash
python manage.py qcluster
```

---

## Structure des apps

| App | R��le |
|-----|------|
| `apps.tenants` | Multi-tenant middleware |
| `apps.accounts` | Authentification, rôles |
| `apps.core` | Sites, équipements réseau, PtPLink |
| `apps.monitoring` | Dashboard, antennes Ubiquiti, fr��quences |
| `apps.wifi_zone` | Abonnés WiFi, tickets plainte, hotspot |
| `apps.finance` | Caisse, rapports revendeurs |
| `apps.notifications` | WhatsApp CallMeBot |
