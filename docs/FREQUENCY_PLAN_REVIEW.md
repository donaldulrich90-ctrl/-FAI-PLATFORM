# Examiner un plan de fréquence airOS

La commande `review_frequency_plan` prépare le script généré par airOS pour une
fréquence proposée et l'affiche sans l'exécuter. Elle n'active pas le basculement
automatique, n'ajoute pas d'empreinte approuvée et ne valide pas la qualité RF du
canal proposé.

## Préconditions

- Antenne Ubiquiti active avec SSH accessible depuis le conteneur de l'application.
- Configuration radio reconnue en 20 MHz et fréquence configurée égale au canal en service.
- Aucune autre modification de configuration en attente.
- `FREQUENCY_COMMANDS_VERIFIED=False`, `auto_switch=False`, `scan_actif=False`.
- Aucun autre administrateur ne doit appliquer des changements dans airOS pendant l'examen.

Comparer d'abord les candidats dans AirMagic. Une fréquence disponible dans
l'interface ou dans les listes de recherche des clients ne prouve pas que son
utilisation est autorisée pour l'installation. Confirmer cette autorisation
avant un essai qui émet sur le nouveau canal.

## Utilisation

Dans le conteneur de l'application, pour l'exemple Central-6 :

```sh
python manage.py review_frequency_plan --device 9 --target 5895
```

La commande écrit **temporairement** la fréquence proposée dans
`/tmp/system.cfg` et appelle uniquement le préparateur `ubntconf -p`. Ce n'est
donc pas une opération en lecture seule. Elle sauvegarde auparavant les
configurations et `/etc`, puis les restaure ; le piège shell de restauration
s'exécute aussi après un échec ou un signal HUP/INT/TERM.

Elle n'exécute ni `/tmp/diff.sh`, ni `chsw`, ni un signal à init, ni
`rc.softrestart`, ni `cfgmtd`. À la fin, elle relit la configuration, le canal en
service et le boot_id. La sortie indique si le script contient encore des
commandes bloquées par les contrôles actuels. Le blocage de `kill` reste actif.

Le verrou `/tmp/fai-frequency-review.lock` empêche deux examens simultanés de
cette application. Il ne remplace pas la coordination avec les administrateurs
qui utilisent l'interface airOS.

## En cas d'échec

Si une différence subsiste après restauration, la commande échoue et conserve
les archives dans un répertoire `/tmp/fai-review-<identifiant>`, ainsi que le
verrou. Elle ne supprime pas automatiquement des fichiers nouvellement apparus
dans `/etc` et n'écrase pas une configuration `running.cfg` modifiée en parallèle.

Ne pas relancer ni activer l'automatisation avant d'avoir vérifié la
configuration et la liaison. Une perte de SSH peut empêcher de confirmer la
restauration, même si le piège shell a été exécuté. Une coupure électrique,
SIGKILL ou panne du système peut empêcher le piège de s'exécuter.

Un plan préparé et un boot_id inchangé ne prouvent pas encore qu'un changement
réel de fréquence fonctionnera sans redémarrage. Un essai distinct, avec canal
autorisé, contrôles du retour des clients et du SNR, reste nécessaire.
