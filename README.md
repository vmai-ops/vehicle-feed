# Village Motors → Facebook Vehicle Feed Bridge

This little robot reads the live inventory on villagemotorsautos.com once a day
and publishes it as `feed.csv` in the exact format Meta (Facebook/Instagram)
needs for Automotive Inventory Ads.

**You never edit anything by hand.** Cars that sell disappear from the feed;
new arrivals appear automatically — as long as the listing on the website has
a Retail Price and at least one photo (Meta requires both).

## What's in this folder

| File | What it does |
|---|---|
| `build_feed.py` | The robot. Reads the website, writes `feed.csv`. |
| `.github/workflows/update-feed.yml` | The schedule. Runs the robot every day at ~4–5 AM Eastern. |
| `feed.csv` | The output Meta reads. Created on the first run. |
| `last_updated.txt` | Timestamp + list of any skipped vehicles, so you can check it ran. |

## One-time setup (about 10 minutes)

1. Create a free account at github.com.
2. Click **+** (top right) → **New repository**. Name it `vehicle-feed`,
   set it to **Public**, and click **Create repository**.
3. Click **uploading an existing file** and drag in `build_feed.py` and
   `README.md`. Commit.
4. Click **Add file → Create new file**. For the filename, type exactly:
   `.github/workflows/update-feed.yml` (the slashes create the folders).
   Paste in the contents of that file. Commit.
5. Go to the **Actions** tab → click **Update vehicle feed** →
   **Run workflow** → green **Run workflow** button. Wait ~2 minutes;
   a green check means it worked and `feed.csv` now exists.
6. Your permanent feed URL is:
   `https://raw.githubusercontent.com/YOUR-USERNAME/vehicle-feed/main/feed.csv`
   Open it in a browser to confirm you see vehicle data.

Give that URL to Claude (or paste it into Meta Commerce Manager as a
scheduled data feed) and the catalog stays in sync daily.

## Things to know

- **Vehicles get skipped** if the website listing has no Retail Price
  ("Get ePrice") or zero photos. Check `last_updated.txt` to see which.
  Add a price + photos on the website and they join the next daily run.
- **If the website is ever redesigned** by Dealer Car Search, the robot may
  stop finding vehicles. The daily run will fail loudly (red X in the Actions
  tab, email from GitHub) rather than silently sending a bad feed. Take the
  error to Claude and it can update `build_feed.py`.
- The schedule runs on GitHub's servers for free. The daily commit of
  `last_updated.txt` keeps the schedule from being paused for inactivity.
