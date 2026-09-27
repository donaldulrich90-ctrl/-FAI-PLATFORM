# Conception du bonus fidélité

## Règle

- Cinq tickets **payés et confirmés du même forfait** donnent un ticket bonus du même forfait.
- Les compteurs sont séparés par adresse MAC de l'appareil et par code de forfait.
- Un ticket bonus ne compte pas comme un achat et ne fait donc pas progresser le compteur.
- `3 × 500 F + 2 × 200 F` ne déclenche aucun bonus : les progressions restent `3/5` et `2/5`.
- `5 × 500 F` déclenche un ticket bonus à 500 F, puis remet ce compteur à `0/5`.

## Fonctionnement actuel de la maquette

La page captive est en mode démonstration. Les compteurs sont conservés localement dans le navigateur avec l'adresse MAC fournie par `$(mac)` sur le MikroTik. En prévisualisation locale, une identité d'appareil fictive est utilisée. Cette donnée locale ne doit pas être utilisée en production, car elle pourrait être modifiée par le client.

## Flux de production prévu

```text
Paiement mobile confirmé ou ticket cash activé sur le MikroTik
              |
              v
Enregistrement unique de la transaction
              |
              v
Compteur (adresse MAC + forfait) + 1
              |
       compteur atteint 5 ?
          /             \
        non             oui
        |                |
 progression        compteur = 0
 enregistrée        + ticket bonus
```

## Données à enregistrer côté Django

1. Achat : adresse MAC normalisée, forfait, montant, moyen de paiement, référence unique et statut.
2. Progression fidélité : adresse MAC normalisée, forfait et compteur entre 0 et 4.
3. Attribution bonus : achat déclencheur et ticket offert, tous deux uniques.

Dans le fonctionnement actuel, un ticket cash vendu par un revendeur est crédité lors de sa première activation : le MikroTik fournit alors la MAC réelle de l'appareil et Django rattache automatiquement l'achat au bon compteur. Cela évite d'obliger le vendeur à recopier une MAC. Un futur parcours « demande cash » depuis le portail pourra aussi permettre une validation immédiate par le vendeur, car la page connaît déjà `$(mac)`.

Le traitement du retour de paiement ou de la validation cash devra être atomique et idempotent : une même opération répétée ne devra compter l'achat qu'une seule fois ni générer plusieurs bonus.

## Limite de l'identification MAC

Les téléphones modernes utilisent souvent une adresse MAC privée propre à chaque réseau Wi-Fi. Elle reste généralement stable pour le même SSID, mais le client peut la réinitialiser ou désactiver l'adresse privée. La MAC peut aussi être copiée techniquement. Pour récupérer un compte perdu, il est recommandé de conserver le numéro de téléphone comme information facultative, sans l'utiliser pour mélanger les compteurs.

## Évolution future

Si le volume augmente, la progression pourra être calculée à partir d'un journal immuable des achats. Pour le lancement, un compteur verrouillé en base lors de chaque paiement confirmé reste plus simple et suffisamment fiable.
