# Page captive Faso ISP pour MikroTik

Ce dossier contient une nouvelle page captive autonome, conçue pour RouterOS 6/7. Elle n'écrase pas la page actuellement installée sur le routeur.

La page est livrée en **mode test** (`data-payment-mode="demo"`). Dans ce mode, Orange Money, Moov Money, Wave et Telecel Money sont simulés : aucun débit réel et aucun appel externe ne sont effectués.

## Bonus fidélité

- 5 tickets payés du même forfait donnent droit à 1 ticket bonus du même forfait.
- Chaque forfait possède son propre compteur, associé à l'adresse MAC fournie par le MikroTik.
- Exemple non éligible : 3 tickets à 500 F + 2 tickets à 200 F.
- Exemple éligible : 5 tickets à 500 F donnent 1 ticket à 500 F offert.
- Les tickets vendus en espèces sont crédités à leur première activation, lorsque le MikroTik remonte la MAC de l'appareil.
- En mode test, la progression est conservée dans le navigateur. En production, le compteur devra être géré côté Django uniquement après confirmation du paiement mobile ou validation cash, avec un identifiant unique pour éviter les doublons.

La conception de la version serveur est détaillée dans `BONUS_FIDELITE.md`.

## Contenu

- `login.html` : connexion par ticket et parcours d'achat Orange Money, Moov Money, Wave et Telecel Money ;
- `films.html` : catalogue local de démonstration relié à l’onglet Films ;
- `css/portal.css` : apparence responsive, sans bibliothèque externe ;
- `js/portal.js` : onglets, carrousel, lecteur multimédia et redirection vers le paiement ;
- `js/media-config.js` : liste des images, vidéos, audios et liens visibles dans l’onglet Médias ;
- `img/` : visuels légers stockés localement sur le routeur ;
- `media/` : emplacement optionnel de la vidéo promotionnelle.

## Réglages obligatoires avant mise en ligne

1. Dans `login.html`, modifier `data-payment-url` si l'adresse de la future page de paiement est différente.
2. Modifier les forfaits, les durées et les prix dans la section `plans` de `login.html`.
3. Remplacer `+22600000000` par le numéro réel d'assistance.
4. Pour afficher une vidéo ou un audio, copier le fichier dans `media/`, puis activer son entrée dans `js/media-config.js`.

Ne remplacer `data-payment-mode="demo"` par `data-payment-mode="live"` qu'après développement et validation du module de paiement Django.

La redirection d'achat pointe actuellement vers :

`https://faestfai.duckdns.org/wifi/acheter/`

Cette adresse doit être reliée au futur module de paiement Django. Tant que cette route et les appels Orange Money, Moov Money, Wave et Telecel Money ne sont pas développés, le bouton d'achat ne peut pas encaisser un paiement réel.

## Installation sur MikroTik

1. Faire une sauvegarde du dossier Hotspot actuel du routeur.
2. Copier le contenu de ce dossier dans le dossier Hotspot utilisé par le profil (`html-directory`).
3. Conserver le fichier `md5.js` généré par MikroTik : `login.html` l'utilise pour la connexion CHAP.
4. Tester d'abord avec un ticket sur un téléphone Android et un iPhone.

## Accès avant authentification

Les images, styles et scripts sont locaux : ils s'affichent donc sans règle Walled Garden supplémentaire. Pour l'achat, ajouter au Walled Garden le domaine Faso ISP et les domaines communiqués par l'agrégateur de paiement choisi. Ne pas autoriser des domaines plus larges que nécessaire.

## Personnalisation des médias

L’onglet **Médias** est disponible avant la connexion et fonctionne avec des fichiers locaux. Les trois visuels livrés sont déjà affichés.

Pour ajouter un contenu :

1. copier l’image, la vidéo ou l’audio dans `img/` ou `media/` ;
2. ouvrir `js/media-config.js` ;
3. ajouter ou modifier une entrée avec le type `image`, `video`, `audio` ou `link` ;
4. mettre `enabled: true` ;
5. recopier le dossier complet sur le MikroTik.

Pour une bonne expérience mobile, viser moins de 250 Ko par image, moins de 5 Mo par vidéo et moins de 2 Mo par audio. Les fichiers locaux ne demandent aucune règle Walled Garden supplémentaire.

## Lien vers les films abonnés

Le bouton de l’onglet **Films** utilise actuellement `data-films-url="films.html"` dans `login.html`. Il ouvre un catalogue local de démonstration.

Lorsque le serveur de films sera prêt, remplacer seulement cette valeur par son adresse, par exemple `http://media.wifizone.local/`. La page du serveur devra vérifier le ticket actif et la MAC avant d’autoriser la lecture ; le simple fait de masquer un bouton dans la page captive ne protège pas les films.
