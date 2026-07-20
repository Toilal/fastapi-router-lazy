# AI implementation notes

Ce dossier contient des notes d'implémentation produites par l'IA pendant le traitement d'un ticket. Chaque fichier correspond à une issue / une MR et capture :

- **Design decisions** : choix faits par l'IA quand le spec était ambigu
- **Deviations** : départs intentionnels par rapport au spec
- **Tradeoffs** : alternatives considérées et pourquoi le choix retenu
- **Open questions** : ce qui reste à valider par un humain

## Convention de nommage

`<YYYY-MM-DD>-<issue_iid>-<slug>.md`

Exemple : `2026-05-19-1234-validate-acceptance-criteria.md`

## Lecture

- Les Open questions marquées 🔴 sont à traiter avant le merge
- Les 🟡 sont à valider, l'IA a procédé sous hypothèse documentée
- Les 🟢 sont informatives, pas d'action requise

## Followup tickets

Pour créer des followup issues à partir des Open questions :

```bash
pysae-ai-tools glab issue-from-ai-note docs/ai-notes/<fichier>.md
```
