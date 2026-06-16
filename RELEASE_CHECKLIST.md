# Release Checklist

Before tagging a release, verify:

## Pre-release

- [ ] `python -m pytest` — all tests pass
- [ ] `python -m src.main doctor` — no FAIL
- [ ] `python -m src.main version` — version correct
- [ ] `python -m src.main auth-check` — API access OK (if token configured)
- [ ] `python -m src.main search --dry-run --mode smoke` — estimate shown
- [ ] `python -m src.main sample-export` — sample DB created
- [ ] `python -m src.main export` — exports created
- [ ] `python -m src.main db backup` — backup created
- [ ] `.env` is NOT tracked (`git status` shows no .env)
- [ ] No tokens in logs, README, or committed files
- [ ] `README.md` updated with new features
- [ ] `CHANGELOG.md` updated

## Post-release

- [ ] Git tag created: `git tag vX.Y.Z`
- [ ] `git push --tags`
- [ ] Release notes on GitHub

## Rollback

If release fails:
1. `git checkout <previous-tag>`
2. Restore DB from `backups/`
3. Verify with `python -m pytest`
