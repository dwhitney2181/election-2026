# 2026 election results and flips

An interactive map of the Nov. 3, 2026 U.S. elections: every seat that changed party, plus results for the U.S. House, U.S. Senate, governors and state legislatures. All results are unofficial until certified.

Open `index.html` in a browser, or view it on GitHub Pages.

## Files
- `index.html` – the page
- `states.js` – U.S. state outlines (from the us-atlas package, U.S. Census Bureau boundaries)
- `flips.js` – seats that changed party, with a source for each
- `results_all.js` – U.S. House, Senate and governor results
- `leg_all.js` – state legislative races by state

## Sources
MultiState Elections (state legislative calls), ABC News and Fox News (House vote shares), AP, NBC News and CBS News (race calls), NCSL (chamber control), Utah News Dispatch (Utah legislative vote shares). Each item on the page links to its source.

## Feed for the Legislative Atlas

`atlas-feed.json` (state legislatures) and `atlas-federal.json` (U.S. House, U.S. Senate, governors and delegates) are the results files the [Legislative Atlas](https://github.com/dwhitney2181/legislative-atlas) reads. It's built from `leg_all.js` and `results_all.js` by:

```bash
python3 tools/build_atlas_feed.py
```

Re-run it whenever those files change, then commit and push; the atlas picks up the new feed within 10 minutes.

## Updates every 30 minutes (state legislatures)

`.github/workflows/update-legislatures.yml` runs `tools/scrape_multistate.py` on GitHub Actions every 30 minutes. It reads MultiState's results pages, writes `leg_live.json`, then `tools/build_atlas_feed.py --leg leg_live.json --out atlas-live.json --no-federal` turns that into `atlas-live.json`, which the atlas loads on top of the daily feed. Files are only committed when results actually change. A state whose page can't be read, or suddenly parses to far fewer races, keeps its previous data.
