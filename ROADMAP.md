# Feuille de route

Chaque phase est utile à elle seule. Aucune promesse de précision n'est faite tant que la phase 3 ne
permet pas de la mesurer.

## Phase 1 : enregistrer l'historique des tests (fondations)

- [x] Lire le JUnit XML de pytest, Vitest et Jest, testé sur de vrais rapports de chacun
- [x] Normaliser l'identité des tests entre dialectes ; fusionner les doublons au sein d'une exécution
- [x] Refuser le XML dangereux (expansion d'entités, références externes)
- [x] Lire les fichiers modifiés depuis git, renommages compris
- [x] Une seule couche de stockage SQL pour SQLite et Postgres, avec une suite de tests de contrat exécutée sur les deux
- [x] Ingestion idempotente : les mêmes rapports pour le même commit ne sont enregistrés qu'une fois
- [x] Rapports : tests instables (réussis et échoués sur un même commit), les plus lents, en échec
- [x] CLI : `ingest`, `report`, `prioritize`, `migrate`
- [x] API HTTP avec authentification par jeton *bearer*, contrôles de vivacité et de disponibilité
- [x] Image Docker, stack Compose, CI (lint, types, tests de Python 3.12 à 3.14 sur Postgres, test de fumée du conteneur), publication sur GHCR
- [x] Un vrai rapport de test pour Go (gotestsum), relances comprises
- [x] Un vrai rapport de test pour JUnit/Surefire (dont `flakyFailure` et `rerunFailure`)
- [x] Un vrai rapport de test pour cargo-nextest
- [x] Enregistrer les relances au sein d'une exécution comme indice d'instabilité ([ADR 0005](docs/adr/0005-retries-within-a-run-are-flakiness-evidence.md))
- [x] Regrouper les insertions par test dans `ingest` (auparavant une requête par test)
- [x] Publier sur PyPI avec la publication de confiance (*trusted publishing*) : [testhunch 0.1.0](https://pypi.org/project/testhunch/0.1.0/)

## Phase 2 : l'utiliser en CI

- [x] Une GitHub Action qui enveloppe `ingest` et `prioritize`
- [ ] **Mode fantôme** : lancer tous les tests, enregistrer ce qui aurait été sauté, publier le vrai taux de tests manqués
- [ ] Produire les sélections au format de chaque lanceur (`pytest -k`, listes de fichiers Jest/Vitest, `go test -run`)
- [ ] Utiliser testhunch sur lui-même : la CI de testhunch conserve son historique d'une exécution à l'autre (l'API hébergée n'arrive qu'en phase 4)

## Phase 3 : le benchmark public

- [ ] Un banc d'essai qui récupère des projets open source à des commits passés, dans des conteneurs figés, et lance leurs suites
- [ ] Des tests de mutation pour créer des échecs réalistes là où l'historique en contient trop peu
- [ ] Évaluer sur RTPTorrent (résultats par classe de test, pas par méthode), avec un découpage temporel pour qu'aucun modèle ne voie le futur : chaque variable (taux d'échec, instabilité, récence) est calculée uniquement à partir des exécutions antérieures à celle qu'on prédit
- [ ] Mesurer le rappel par test et le rappel par changement, ainsi que le temps de test économisé
- [ ] Publier les résultats, y compris là où testhunch s'en sort mal

## Phase 4 : service hébergé

- [ ] Terraform pour un seul serveur : Postgres, API, worker, stockage objet pour les rapports bruts
- [ ] Déploiement continu de `main` vers la préproduction, promotion manuelle en production
- [ ] Métriques (Prometheus) et alertes, dont le taux de tests manqués en mode fantôme comme objectif de niveau de service
- [ ] La CI de testhunch envoie son historique à l'API hébergée
- [ ] Des jetons par dépôt au lieu d'un jeton partagé
- [ ] Partitionner `results` par date quand la table sera assez grosse pour le justifier

## Phase 5 : un modèle appris

- [ ] Variables : échecs conjoints fichiers/tests, distance entre chemins, récence, instabilité, durée des tests
- [ ] Des arbres à gradient boosting comparés au classement de référence de la phase 1, sur le benchmark de la phase 3
- [ ] Ne le livrer que s'il bat la référence ; publier la comparaison dans tous les cas
- [ ] Explorer les indicateurs de prédiction de défauts (fichiers historiquement sujets aux bugs) comme variable supplémentaire

## Références

- Machalica et al., *Predictive Test Selection*, ICSE-SEIP 2019 (Meta)
- Mattis et al., *RTPTorrent: An Open-source Dataset for Evaluating Regression Test Prioritization*, MSR 2020
- *Predicting test failures induced by software defects*, Journal of Systems and Software, 2025 (Nokia 5G)
