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

Les outils nécessaires sont contrôlés par SSH en lecture seule, puis à nouveau
au début du script, avant de créer les sauvegardes. La comparaison utilise
`diff`, sans dépendre de `cmp` qui peut être absent de BusyBox. Si un outil manque,
la préparation est refusée ; aucun outil n'est installé sur l'antenne.

Le contrôle de `/etc` compare les empreintes des fichiers ainsi que les chemins,
destinations des liens, permissions et identifiants des propriétaires/groupes.
Les dates sont exclues : le tar de certaines versions airOS recrée les liens
symboliques avec la date courante sans changer leur destination. Une erreur
d'inventaire fait échouer le contrôle, même si `find` ou `sort` termine normalement.

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

Pour contrôler une sauvegarde conservée, sans aucune écriture :

```sh
python manage.py check_frequency_review --device 9 --archive /tmp/fai-review-<identifiant>
```

Ce contrôle compare l'état actuel aux sauvegardes, en ignorant uniquement les
dates des anciens inventaires de liens. Il ne restaure aucun fichier et ne
supprime aucune archive. Il accepte aussi le format d'inventaire historique.
Les anciens inventaires contiennent les empreintes des fichiers et les
métadonnées des liens, sans permissions/propriétaires des fichiers ordinaires.
Le contrôle historique reste limité aux éléments effectivement sauvegardés.
Après un contrôle réussi et en l'absence d'un autre administrateur appliquant
des changements, la même commande avec `--release-lock` permet de libérer le
seul verrou vide. Elle recontrôle les fichiers radio, les marqueurs d'application
et les processus de préparation ; toute différence ou erreur conserve le verrou.
Ne pas effacer manuellement le verrou pour contourner un refus.

Un plan préparé et un boot_id inchangé ne prouvent pas encore qu'un changement
réel de fréquence fonctionnera sans redémarrage. Un essai distinct, avec canal
autorisé, contrôles du retour des clients et du SNR, reste nécessaire.

## Interpréter les arguments de chsw

Le rapport lit `/bin/chsw` en octets avant toute préparation et calcule son
SHA256 sans l'exécuter. Une copie de 637 octets fournie depuis Central-6,
WA.v8.7.25, a été analysée statiquement :

```text
bd13756a7734ffa4dc918c07a94bcea948b5e11aefde22a42a8170451949f0d9
```

Il s'agit d'un programme Lua 5.1 avec constantes entières LNUM. Le décodage
complet des 72 instructions et des trois fonctions confirme que les deux
arguments sont `center`, puis `control`. Pour un appel à deux arguments, le
programme convertit ceux-ci en nombres et effectue, dans cet ordre :

```text
iwconfig ath0 center1 <center>M
iwconfig ath0 freq <control>M
```

Le statut de la première commande est ignoré ; le résultat retourné par
`os.execute` pour la seconde est transmis à `os.exit`. Il ne comporte aucune
commande de redémarrage. Cela décrit le
programme inspecté, sans établir le comportement des commandes du pilote.

Le résultat de `chsw` n'est pas une preuve suffisante de succès. En particulier,
la bibliothèque [Lua 5.1 standard](https://www.lua.org/source/5.1/loslib.c.html)
transmet le résultat brut de `system()` à `os.execute`, puis l'entier à `exit()`.
Le bytecode ne permet pas d'établir si le firmware modifie ce comportement.
Le canal effectivement en service doit donc toujours être relu séparément.

Avec cette empreinte, `/bin/chsw -1 5895` vise donc bien 5895 MHz pour la fréquence
de contrôle. `-1` est transmis tel quel à `center1` ; il n'est pas interprété par
ce programme comme une fréquence automatique. Son acceptation et son effet sur
le canal de 20 MHz restent à vérifier sur le pilote et le matériel. Le rapport
signale cette limite séparément de la correspondance de la cible.

Une autre empreinte rend l'interprétation indéterminée. Aucun programme n'est
reconnu uniquement par son nom, la version affichée du firmware ou des chaînes
de caractères ressemblantes. Un appel multiple, calculé ou non reconnu ne
confirme pas non plus la cible. Cette reconnaissance ne crée aucune approbation
de plan, ne lève pas le blocage de `kill` et n'active aucune commande réelle.

Format consulté pour l'analyse : [instructions Lua 5.1](https://www.lua.org/source/5.1/lopcodes.h.html),
[chargement Lua 5.1](https://www.lua.org/source/5.1/lundump.c.html) et
[modifications LNUM](https://github.com/LuaDist/lualnum/blob/master/lua514-lnum-20090417-custom.patch).
