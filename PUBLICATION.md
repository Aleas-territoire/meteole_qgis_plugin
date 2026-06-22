# Publier Meteole v2 sur GitHub

Dépôt cible : <https://github.com/Aleas-territoire/meteole_qgis_plugin>

Tu disposes de trois livrables :

| Fichier | Usage |
|---|---|
| `meteole_v2_repo.tar.gz` | Le dépôt complet (avec historique git + tag `v1.4.0`) — à extraire et pousser |
| `meteole_v2_repo.bundle` | Variante : un *git bundle* clonable (même contenu) |
| `meteole_v2.zip` | L'extension installable directement dans QGIS / asset de release |

---

## Option A — À partir de l'archive `tar.gz` (le plus simple)

```bash
# 1. Extraire l'archive (elle contient déjà le dépôt git initialisé)
mkdir meteole_v2_repo && tar -xzf meteole_v2_repo.tar.gz -C meteole_v2_repo
cd meteole_v2_repo

# 2. Relier au dépôt GitHub existant
git remote add origin https://github.com/Aleas-territoire/meteole_qgis_plugin.git

# 3a. RECOMMANDÉ : pousser sur une branche « v2 » (ne touche pas à main)
git branch -m v2
git push -u origin v2
git push origin v1.4.0        # le tag

# 3b. OU remplacer la branche principale (écrase l'arbo v1 ; conserve l'historique)
#     git branch -m main
#     git push origin main
#     git push origin v1.4.0
```

Ensuite, sur GitHub : créer la **Release** depuis le tag `v1.4.0`
(le workflow Actions construira et attachera `meteole_v2.zip` automatiquement,
ou tu peux téléverser le `meteole_v2.zip` fourni).

---

## Option B — À partir du *git bundle*

```bash
git clone meteole_v2_repo.bundle meteole_qgis_plugin
cd meteole_qgis_plugin
git remote set-url origin https://github.com/Aleas-territoire/meteole_qgis_plugin.git
git push -u origin v2          # ou main
git push origin v1.4.0
```

---

## Déclencher la release automatique

Le workflow [`.github/workflows/release.yml`](.github/workflows/release.yml)
se déclenche au push d'un tag `v*` :

```bash
git push origin v1.4.0
```

Il construit `dist/meteole_v2.zip` via `build_zip.sh` et l'attache à la Release.

---

## Remarques

- L'arborescence v2 place le plugin dans le sous-dossier **`meteole_v2/`**
  (c'est lui qui devient le dossier d'installation dans QGIS). Les fichiers de
  présentation (README, CHANGELOG, LICENSE, CI) sont à la racine du dépôt.
- Si tu préfères conserver la v1 accessible, garde-la sur une branche `v1`
  avant de pousser la v2 :
  ```bash
  # depuis un clone à jour de l'ancien dépôt
  git checkout main && git branch v1 && git push origin v1
  ```
- Authentification GitHub : utilise un *Personal Access Token* (HTTPS) ou une
  clé SSH. Je ne peux pas pousser à ta place (pas d'accès à tes identifiants).
