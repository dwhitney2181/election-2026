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
NBC News (U.S. House, Senate and governor candidates, vote shares and calls), ABC News (cross-check for seats changing party), MultiState Elections (state legislative calls), NCSL (chamber control), the Utah Lieutenant Governor's Office results site (Utah legislative vote counts; Utah News Dispatch's tables before that). Earlier snapshots also drew on AP, CBS News and Fox News. Each item on the page links to its source.

## Feed for the Legislative Atlas

`atlas-feed.json` (state legislatures) and `atlas-federal.json` (U.S. House, U.S. Senate, governors and delegates) are the results files the [Legislative Atlas](https://github.com/dwhitney2181/legislative-atlas) reads. It's built from `leg_all.js` and `results_all.js` by:

```bash
python3 tools/build_atlas_feed.py
```

Re-run it whenever those files change, then commit and push; the atlas picks up the new feed within 10 minutes.

## Automatic updates every 3 hours

`.github/workflows/update-legislatures.yml` ("Update election results") runs on GitHub Actions every 3 hours and refreshes the whole site:

1. `tools/scrape_multistate.py` reads MultiState's results page for each state with legislative races and writes `leg_live.json`.
2. `tools/scrape_utah.py` reads Utah's official results feed (the data behind electionresults.utah.gov) and writes `utah_live.json`: every state House and Senate race with each candidate's votes.
3. `tools/scrape_federal.py` reads NBC News's House, Senate and governor results pages (candidates, votes, share counted, calls) and ABC News's results tables (which seats each network marks as a party gain), and writes `federal_live.json`.
4. `tools/update_site.py` folds all three into `leg_all.js`, `results_all.js` and `flips.js`: vote shares and calls for every race, the list of seats changing party, uncalled-race counts and the page's "as of" time.
5. `tools/build_atlas_feed.py` rebuilds `atlas-feed.json`, `atlas-federal.json` and `atlas-live.json` for the Legislative Atlas.

Files are only committed when a result actually changes. A source that can't be read, or a state page that suddenly parses to far fewer races, keeps its previous data. Rows the automatic sources don't cover (territory governors, non-voting delegates, chamber-control notes) stay as they were.

To change how often it runs, edit the `cron` line in that file (times are UTC). To run it right away, open the repository's Actions tab, pick "Update election results" and press "Run workflow".
