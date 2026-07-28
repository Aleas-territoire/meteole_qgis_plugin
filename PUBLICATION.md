# Publier une nouvelle version

Dépôt : <https://github.com/Aleas-territoire/meteole_qgis_plugin>

Le plugin est versionné sur la branche `v2`. Une release (et son ZIP
installable `meteole_v2.zip`) est produite automatiquement par GitHub Actions
au push d'un tag `v*`.

## Procédure

Depuis un clone à jour du dépôt, sur la branche `v2` :

```bash
# 1. Monter le numéro de version dans le plugin
#    (fichier meteole_v2/metadata.txt, ligne version=X.Y.Z)

# 2. Mettre à jour le CHANGELOG (racine et meteole_v2/), puis committer
git add -A
git commit -m "vX.Y.Z : description"
git push origin v2

# 3. Taguer la version : cela declenche la release automatique
git tag -a vX.Y.Z -m "Meteole v2 - version X.Y.Z"
git push origin vX.Y.Z
```

Le workflow [`.github/workflows/release.yml`](.github/workflows/release.yml)
exécute `build_zip.sh`, qui empaquette le dossier `meteole_v2/` en
`dist/meteole_v2.zip`, puis attache ce ZIP à la release du tag.

## Synchroniser main

La page d'accueil du dépôt affiche la branche `main`. Pour qu'elle reflète la
dernière version, fusionner `v2` dans `main`, de préférence via une Pull Request
sur GitHub (base `main`, comparaison `v2`), puis Merge.

## Structure du dépôt

* `meteole_v2/` : le plugin (dossier d'installation dans QGIS)
* fichiers de présentation à la racine : README, CHANGELOG, LICENSE,
  CONTRIBUTING, ce guide, et la CI dans `.github/`

## Authentification

Au push HTTPS, utiliser son identifiant GitHub et un jeton d'accès personnel
(Personal Access Token) avec la portee `repo`, ou une clé SSH.
