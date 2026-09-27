(function () {
  "use strict";

  /*
   * CATALOGUE DE FILMS — WiFi Zone Faso Équipements Store
   * ------------------------------------------------------
   * Ce fichier sera copié sur le SERVEUR LOCAL (le PC qui stocke les films).
   *
   * Pour AJOUTER un film : copiez un bloc { ... } et modifiez-le.
   * Pour CLASSER un film : mettez le nom de la catégorie dans "category".
   *   -> Les catégories s'affichent toutes seules en haut de la page.
   * Pour MASQUER un film sans le supprimer : mettez "enabled": false.
   *
   * Champs d'un film :
   *   title       : titre affiché
   *   category    : catégorie (ex. "Action", "Comédie", "Séries"...)
   *   duree       : durée affichée (ex. "1h52") — optionnel
   *   description : petit résumé — optionnel
   *   poster      : affiche dans img/ (ex. "img/opera-sahel.jpg") — optionnel
   *   src         : fichier vidéo dans videos/ (ex. "videos/opera-sahel.mp4")
   *                 -> si vide "", le film s'affiche mais n'est pas encore lisible
   *   enabled     : true pour afficher, false pour masquer
   *
   * IMPORTANT : les vidéos doivent être en MP4 (H.264) pour être lues sur
   * tous les téléphones. Placez les fichiers .mp4 dans le dossier videos/.
   */
  window.WifiZoneFilms = [
    {
      title: "Opération Sahel",
      category: "Action",
      duree: "1h52",
      description: "Un thriller local plein de suspense.",
      poster: "",
      src: "videos/operation-sahel.mp4",
      enabled: true
    },
    {
      title: "Le Convoi",
      category: "Action",
      duree: "1h38",
      description: "Ajoutez ici le résumé de votre film d'action.",
      poster: "",
      src: "videos/le-convoi.mp4",
      enabled: true
    },
    {
      title: "Taxi Ouaga",
      category: "Comédie",
      duree: "1h25",
      description: "Une comédie qui fait rire toute la famille.",
      poster: "",
      src: "videos/taxi-ouaga.mp4",
      enabled: true
    },
    {
      title: "Les Voisins",
      category: "Comédie",
      duree: "1h10",
      description: "Exemple de film de catégorie Comédie.",
      poster: "",
      src: "",
      enabled: true
    },
    {
      title: "Kadi Jolie",
      category: "Séries",
      duree: "Saison 1",
      description: "Vos séries préférées, épisode par épisode.",
      poster: "",
      src: "videos/kadi-jolie-s01e01.mp4",
      enabled: true
    },
    {
      title: "Les Bobodiouf",
      category: "Séries",
      duree: "Saison 1",
      description: "Exemple de série à ajouter à votre catalogue.",
      poster: "",
      src: "",
      enabled: true
    },
    {
      title: "Kirikou",
      category: "Dessins animés",
      duree: "1h11",
      description: "Pour les enfants — dessins animés.",
      poster: "",
      src: "videos/kirikou.mp4",
      enabled: true
    },
    {
      title: "Faso Nature",
      category: "Documentaires",
      duree: "48 min",
      description: "Découvertes et documentaires.",
      poster: "",
      src: "",
      enabled: true
    }
  ];
})();
