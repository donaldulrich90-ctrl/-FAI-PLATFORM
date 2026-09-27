# Paiement en ligne des tickets Wi‑Fi Zone (CinetPay)

Ce document explique comment activer le **paiement mobile money réel** (Orange
Money, Moov Money, Wave, Telecel, carte) depuis le portail captif, pour **toutes
les zones** (Central, Saaba, Boassa, Ziniaré… et toute zone future).

Un **seul compte CinetPay** et un **seul backend Django** servent toutes les
zones. Le code est identique partout ; seule une ligne du `login.html` change
d'un routeur à l'autre (le code de la zone).

---

## 1. Comment ça marche

```
Client sur le hotspot (ex. SAABA)
        │  choisit un forfait + opérateur, valide
        ▼
GET /wifi/acheter/?plan=1d&provider=orange_money&site_code=SAABA&mac=…&login_url=…
        │  Django : lit le tarif OFFICIEL (jamais le prix du client),
        │  crée une transaction, ouvre le guichet CinetPay
        ▼
Guichet CinetPay (le client paie sur son téléphone)
        │
        ├── Webhook  POST /wifi/paiement/notify/   (serveur → serveur)
        │       Django revérifie le statut via l'API CinetPay (CHECK)
        │
        ▼  paiement ACCEPTÉ
Django crée le ticket SUR LE SITE SAABA
        │  puis provision_wifi_zone_hotspot_for_ticket()
        ▼  pousse l'utilisateur sur LE MikroTik de Saaba (chemin déjà éprouvé)
Page de retour : affiche le CODE + bouton « Se connecter au Wi‑Fi »
```

Le ticket est délivré comme un ticket revendeur vendu : **la recette et
l'expiration ne démarrent qu'à la première connexion** du client.

---

## 2. Pré‑requis (déjà en place chez FAEST)

Chaque zone doit exister comme **Site** dans Django, avec son **MikroTik lié**
(champ *Routeur Hotspot Wi‑Fi Zone* du Site, ou premier MikroTik actif du site).
C'est déjà ainsi que les tickets revendeurs sont poussés — le paiement réutilise
exactement ce mécanisme.

Le `site_id` du Site (ex. `SAABA`) est ce qui relie le portail à la zone.

---

## 3. Configuration PAR ROUTEUR (`login.html`)

Dans le `<body>` de `login.html` copié sur chaque MikroTik :

| Attribut | Valeur | Remarque |
|---|---|---|
| `data-site-code` | `CENTRAL` / `SAABA` / `BOASSA` / `ZINIARE` | **doit correspondre au `site_id` du Site** dans Django |
| `data-payment-mode` | `live` | `demo` = aucun paiement réel (par défaut) |
| `data-payment-url` | `https://faestfai.duckdns.org/wifi/acheter/` | inchangé |

> ⚠️ La seule chose à changer d'un routeur à l'autre est **`data-site-code`**.
> Le reste du dossier `mikrotik_hotspot/` est identique sur tous les routeurs.

Nouvelle zone plus tard = copier le même dossier, mettre son `data-site-code`,
créer le Site + tarifs dans Django. Rien d'autre à coder.

---

## 4. Configuration Django (variables d'environnement `.env`)

```
CINETPAY_API_KEY=<clé API du compte marchand CinetPay>
CINETPAY_SITE_ID=<site_id CinetPay>
CINETPAY_MODE=PRODUCTION            # TEST tant que le compte n'est pas validé
PUBLIC_BASE_URL=https://faestfai.duckdns.org
```

Tant que `CINETPAY_API_KEY`/`SITE_ID` sont vides, le bouton d'achat affiche
« paiement pas encore activé » (aucune erreur brutale).

### Tableau de bord CinetPay
Renseigner l'**URL de notification** :

```
https://faestfai.duckdns.org/wifi/paiement/notify/
```

(elle est aussi envoyée à chaque transaction, mais la définir dans le tableau de
bord évite les surprises.)

---

## 5. Walled Garden (sur CHAQUE MikroTik)

Autoriser, **avant authentification**, les domaines du paiement :

```
/ip hotspot walled-garden
add dst-host=faestfai.duckdns.org
add dst-host=*.cinetpay.com
add dst-host=api-checkout.cinetpay.com
add dst-host=checkout.cinetpay.com
add dst-host=secure.cinetpay.com
```

Selon l'opérateur choisi, CinetPay peut rediriger vers une page Orange Money /
Moov / Wave : ajoutez au besoin les domaines signalés par CinetPay (ex.
`*.orange.bf`, `*.wave.com`). N'autorisez pas plus large que nécessaire.

---

## 6. Tarifs (source de vérité serveur)

Les prix affichés par le portail sont **revalidés côté serveur** : le client ne
peut jamais imposer son prix. La grille est gérée dans l'admin Django :

**Admin → Wi‑Fi Zone → Tarifs Wi‑Fi Zone**

Des tarifs **globaux** sont créés automatiquement (3 h = 100, 24 h = 200,
5 j = 500, 7 j = 700, 30 j = 2 500 F). Pour un prix différent sur une zone,
ajoutez un tarif avec le Site renseigné (il prime sur le tarif global).

---

## 7. Déploiement

Depuis le PC (le push GitHub reste manuel) :

```bash
git add -A
git commit -m "feat(wifi): paiement mobile money en ligne via CinetPay (toutes zones)"
git push origin main
```

Puis sur le serveur (Coolify → redeploy), et dans le conteneur :

```bash
python manage.py migrate
```

(applique `0016_wifipurchase_wifizonetarif` : tables paiement + tarifs par défaut.)

---

## 8. Test de bout en bout

1. `CINETPAY_MODE=TEST`, `data-payment-mode="live"`, `data-site-code` correct.
2. Sur un téléphone connecté au hotspot : onglet **Acheter**, choisir un forfait
   + opérateur, valider → redirection vers le guichet CinetPay (sandbox).
3. Payer en sandbox → retour sur la page « Paiement réussi » avec le **code**.
4. Vérifier dans l'admin : **Achats Wi‑Fi Zone** = `Payée`, un **Ticket** créé,
   `hotspot_synced_at` renseigné (poussé sur le bon MikroTik).
5. Se connecter avec le code.
6. Une fois le compte validé : `CINETPAY_MODE=PRODUCTION` + clés réelles.

---

## 9. Fichiers ajoutés / modifiés

**Backend**
- `apps/wifi_zone/models.py` — modèles `WifiZoneTarif`, `WifiPurchase`.
- `apps/wifi_zone/migrations/0016_wifipurchase_wifizonetarif.py`.
- `apps/wifi_zone/services/payments/cinetpay.py` — client CinetPay (init/check).
- `apps/wifi_zone/services/purchase.py` — orchestration (tarif, ticket, MikroTik, fidélité).
- `apps/wifi_zone/views.py` — `wifi_acheter`, `wifi_paiement_retour`, `wifi_paiement_notify`, `wifi_paiement_statut`.
- `apps/wifi_zone/urls.py` — routes publiques `/wifi/acheter/`, `/wifi/paiement/…`.
- `apps/wifi_zone/admin.py` — admin des tarifs et des achats.
- `faso_isp_manager/settings.py`, `.env.example` — `PUBLIC_BASE_URL`, `CINETPAY_API_BASE`.

**Portail captif**
- `mikrotik_hotspot/login.html` — attribut `data-site-code`.
- `mikrotik_hotspot/js/portal.js` — transmission de `site_code` en mode réel.
