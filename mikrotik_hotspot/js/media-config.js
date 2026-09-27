(function () {
  "use strict";

  /*
   * Bibliothèque des médias du portail.
   * Copiez les fichiers dans img/ ou media/, puis ajoutez-les ici.
   * Types acceptés : image, video, audio et link.
   */
  window.WifiZoneMedia = [
    {
      id: "internet-rapide",
      type: "image",
      title: "Internet sans attendre",
      description: "Découvrez notre accès Wi-Fi simple et rapide.",
      src: "img/promo-fast.svg?v=brand-1",
      enabled: true
    },
    {
      id: "connexion-famille",
      type: "image",
      title: "Tous connectés",
      description: "Une connexion pour vos téléphones, tablettes et ordinateurs.",
      src: "img/promo-family.svg?v=brand-1",
      enabled: true
    },
    {
      id: "assistance",
      type: "image",
      title: "Assistance locale",
      description: "Retrouvez rapidement les informations utiles du point Wi-Fi.",
      src: "img/promo-support.svg?v=brand-1",
      enabled: true
    },
    {
      id: "video-promo",
      type: "video",
      title: "Vidéo promotionnelle",
      description: "Présentation vidéo de WiFi Zone Faso Équipements Store.",
      src: "media/promo.mp4",
      poster: "img/video-poster.svg?v=brand-1",
      enabled: false
    },
    {
      id: "annonce-audio",
      type: "audio",
      title: "Annonce audio",
      description: "Écoutez les dernières informations du point Wi-Fi.",
      src: "media/annonce.mp3",
      enabled: false
    }
  ];
})();
