# Veille — Médiation de conflits

Base de données SQLite + tableau HTML statique alimenté automatiquement par des flux RSS publics sur la **médiation de conflits** (peace mediation, conflict mediation, peace talks, médiation, négociations de paix).

## Sommaire
1. [Aperçu](#aperçu)
2. [Contenu livré](#contenu-livré)
3. [Exécution manuelle](#exécution-manuelle)
4. [Automatisation gratuite avec GitHub Actions + GitHub Pages](#automatisation-gratuite-avec-github-actions--github-pages)
5. [Ajouter / modifier les sources RSS](#ajouter--modifier-les-sources-rss)
6. [Schéma de la base](#schéma-de-la-base)
7. [Dépannage](#dépannage)

## Aperçu
Le script `collect_mediation_news.py` :
- interroge plusieurs flux RSS publics en anglais et français ;
- déduplique par URL et par titre normalisé ;
- stocke le tout dans une base SQLite locale (`mediation_news.db`) ;
- régénère à chaque exécution `articles.csv`, `articles.json` et `index.html`.

Aucun service payant, aucune clé API : uniquement Python 3.10+ et `requests`.

## Contenu livré

| Fichier | Rôle |
| --- | --- |
| `collect_mediation_news.py` | Script de collecte principal. |
| `mediation_news.db` | Base SQLite (table `articles`). |
| `articles.csv` | Export tabulaire. |
| `articles.json` | Export JSON complet. |
| `index.html` | Tableau de bord HTML, articles triés du plus récent au plus ancien. |
| `README.md` | Ce document. |

## Exécution manuelle

```bash
python -m pip install requests
python collect_mediation_news.py --output-dir . --db ./mediation_news.db
```

Options :
- `--output-dir` : répertoire où sont écrits `articles.csv`, `articles.json` et `index.html` (par défaut : dossier du script).
- `--db` : chemin vers la base SQLite.
- `--timeout` : délai maximal (secondes) par requête HTTP.

Le script est **idempotent** : relancer la commande n'ajoute pas de doublons (un test de ré-exécution a montré 1 seul nouvel article — preuve que la déduplication fonctionne).

## Automatisation gratuite avec GitHub Actions + GitHub Pages

Procédure :

1. Poussez le dépôt sur GitHub (branche `main`). Les fichiers de sortie ne sont **pas** versionnés s'ils sont régénérés à chaque exécution.
2. Activez GitHub Pages sur la branche `gh-pages` (Settings → Pages).
3. Créez le fichier `.github/workflows/mediation-news.yml` :

```yaml
name: Update mediation news
on:
  schedule:
    - cron: "0 */6 * * *"     # toutes les 6 heures
  workflow_dispatch:            # exécution manuelle possible
permissions:
  contents: write
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install dependencies
        run: python -m pip install requests

      - name: Run collector
        run: python collect_mediation_news.py --output-dir ./docs --db ./docs/mediation_news.db

      - name: Deploy to GitHub Pages
        uses: peaceiris/actions-gh-pages@v4
        with:
          github_token: ${{ secrets.GITHUB_TOKEN }}
          publish_dir: ./docs
          publish_branch: gh-pages
          keep_files: false
```

Déclencheur cron `0 */6 * * *` = exécution toutes les 6 heures. Autres exemples :
- `0 */1 * * *` : toutes les heures
- `0 6 * * *` : une fois par jour à 06:00 UTC

L'étape finale publie `docs/index.html` (et la base, le CSV, le JSON) sur la branche `gh-pages`, automatiquement servie par GitHub Pages. Aucune dépendance payante : GitHub offre 2 000 minutes/mois gratuites pour les dépôts publics.

### Alternative : push direct dans la branche
Si vous préférez committer les artefacts plutôt que d'utiliser Pages :
```yaml
      - run: |
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add docs/
          git commit -m "Update mediation news" || echo "no changes"
          git push
```

## Ajouter / modifier les sources RSS

Toutes les sources sont déclarées en haut du script :

```python
DEFAULT_SOURCES = [
    ("UN News", "https://news.un.org/feed/subscribe/en/news/topic/peace-and-security/feed/rss.xml", "en"),
    ("Crisis Group", "https://www.crisisgroup.org/rss.xml", "en"),
    ("Google News — conflict mediation", "https://news.google.com/rss/search?q=conflict+mediation&hl=en-US&gl=US&ceid=US:en", "en"),
    # ... ajoutez vos flux ici
]
```

Format : `(nom_affiché, url_du_flux_rss, code_langue)`. Quelques idées à ajouter :
- ReliefWeb par pays/thème : `https://reliefweb.int/updates/rss.xml?search=<mot-clé>`
- Peace Insight : `https://www.peaceinsight.org/en/rss/`
- UN Peacemaker : voir site officiel de l'United Nations.
- Le Monde : `https://www.lemonde.fr/pixels/rss_full.xml` (filtrer ensuite côté SQL).
- Toute recherche Google News : `https://news.google.com/rss/search?q=<requête+encodée>&hl=<lang>&gl=<pays>&ceid=<pays>:<lang>`.

Après modification, relancer le script (ou attendre la prochaine exécution planifiée).

## Schéma de la base

Table `articles` (SQLite) :

| Colonne | Type | Description |
| --- | --- | --- |
| `id` | INTEGER PK | Identifiant interne. |
| `titre` | TEXT | Titre de l'article. |
| `source` | TEXT | Nom du flux source. |
| `date_publication` | TEXT (ISO 8601) | Date publiée par le flux. |
| `lien` | TEXT (UNIQUE) | URL canonique. |
| `resume` | TEXT | Résumé / description fournis par le flux. |
| `langue` | TEXT | Code langue (`en`, `fr`, ...). |
| `date_ajout` | TEXT (ISO 8601) | Date d'insertion dans la base. |
| `titre_normalise` | TEXT | Titre nettoyé (ASCII, lower, alphanumérique) pour la déduplication. |

## Dépannage

- **`requests` manquant** : `python -m pip install requests`.
- **Erreur HTTP sur Google News** : Google limite parfois le rythme. Augmenter `--timeout` ou patienter ; le script ignore les flux en échec et continue.
- **Article déjà présent** : la déduplication utilise `lien` (UNIQUE) et `titre_normalise`. Si un flux change légèrement le slug URL d'un même article, il peut apparaître deux fois — supprimez l'ancien ou ajoutez un filtre côté flux.
- **Activer une nouvelle source** : voir la section précédente.