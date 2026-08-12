"""
Village Motors -> Meta (Facebook) Vehicle Feed Bridge
=====================================================
Reads the live inventory on villagemotorsautos.com and writes feed.csv
in Meta's Automotive Inventory Ads (vehicles catalog) format.

Runs automatically every day via GitHub Actions (see .github/workflows/).
No manual data entry required.

Rules:
- Vehicles WITHOUT a listed Retail Price or WITHOUT photos are skipped
  (Meta requires both). They join the feed automatically once the
  website listing has a price and at least one photo.
"""

import csv
import re
import sys
import time
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

# ----------------------------------------------------------------------
# Dealership constants
# ----------------------------------------------------------------------
SITE = "https://villagemotorsautos.com"
INVENTORY_URL = f"{SITE}/inventory?clearall=1&pagesize=100"
DEALER_NAME = "Village Motors"
ADDR1 = "260 West Pike Street"
CITY = "South Lebanon"
REGION = "OH"
POSTAL = "45065"
COUNTRY = "US"
LATITUDE = "39.3735708"
LONGITUDE = "-84.216369"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; VillageMotorsFeedBot/1.0; "
        "+https://villagemotorsautos.com) inventory feed for our own Meta ads"
    )
}

TWO_WORD_MAKES = ["Land Rover", "Alfa Romeo", "Aston Martin", "Rolls Royce"]

BODY_STYLE_MAP = {
    # model keyword (lowercase) -> Meta body_style enum
    "silverado": "TRUCK", "f-150": "TRUCK", "f150": "TRUCK", "tundra": "TRUCK",
    "ram": "TRUCK", "sierra": "TRUCK",
    "equinox": "SUV", "murano": "SUV", "patriot": "SUV", "discovery": "SUV",
    "defender": "SUV", "explorer": "SUV", "escape": "SUV",
    "grand caravan": "MINIVAN", "caravan": "MINIVAN", "odyssey": "MINIVAN",
    "sienna": "MINIVAN",
    "chimaera": "CONVERTIBLE",
    "insight": "HATCHBACK",
    "focus": "SEDAN", "malibu": "SEDAN", "impala": "SEDAN", "taurus": "SEDAN",
    "accord": "SEDAN", "es 330": "SEDAN", "ls 460": "SEDAN",
    "e-class": "SEDAN", "camry": "SEDAN", "civic": "SEDAN",
}


def fetch(url, tries=3):
    """GET a page with simple retries."""
    for attempt in range(tries):
        try:
            r = requests.get(url, headers=HEADERS, timeout=30)
            if r.status_code == 200:
                return r.text
        except requests.RequestException as exc:
            print(f"  fetch error ({attempt + 1}/{tries}) {url}: {exc}")
        time.sleep(3)
    return None


def get_vdp_urls():
    """Collect every vehicle-detail-page URL from the inventory listing."""
    html = fetch(INVENTORY_URL)
    if not html:
        sys.exit("FATAL: could not load the inventory page.")
    urls = re.findall(r'href="(/vdp/\d+/[^"]+)"', html)
    # normalize + dedupe, drop querystring variants (?mode=photos etc.)
    seen, out = set(), []
    for u in urls:
        u = u.split("?")[0]
        m = re.match(r"/vdp/(\d+)/", u)
        if not m:
            continue
        vid = m.group(1)
        if vid not in seen:
            seen.add(vid)
            out.append((vid, SITE + u))
    print(f"Found {len(out)} vehicles on the inventory page.")
    return out


def parse_title(title):
    """'2011 Chevrolet Equinox LS 2WD' -> (year, make, model)."""
    title = title.strip()
    m = re.match(r"^(\d{4})\s+(.*)$", title)
    if not m:
        return None, None, title
    year, rest = m.group(1), m.group(2)
    make = None
    for tw in TWO_WORD_MAKES:
        if rest.startswith(tw):
            make = tw
            rest = rest[len(tw):].strip()
            break
    if make is None:
        parts = rest.split(" ", 1)
        make = parts[0]
        rest = parts[1].strip() if len(parts) > 1 else ""
    model = rest if rest else make
    return year, make, model


def guess_body_style(title):
    t = title.lower()
    for key, style in BODY_STYLE_MAP.items():
        if key in t:
            return style
    return "OTHER"


def label_value(text, label):
    """Find 'Label:  value' pairs in the flattened page text."""
    m = re.search(rf"{re.escape(label)}\s*:?\s*\n\s*([^\n]+)", text)
    if m:
        val = m.group(1).strip()
        if val and not val.endswith(":"):
            return val
    return ""


def parse_vdp(vid, url):
    """Extract one vehicle's data from its detail page."""
    html = fetch(url)
    if not html:
        return None, "page failed to load"

    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text("\n")

    # Title
    og_title = soup.find("meta", property="og:title")
    title = og_title["content"].strip() if og_title and og_title.get("content") else ""
    if not title:
        m = re.search(r"/vdp/\d+/Used-([^/]+)-for-sale", url)
        title = m.group(1).replace("-", " ") if m else f"Vehicle {vid}"
    year, make, model = parse_title(title)
    if not year:
        return None, "could not read year/make/model"

    # Price — Retail Price $X,XXX.XX (required by Meta)
    pm = re.search(r"Retail Price\s*\$\s*([\d,]+(?:\.\d{2})?)", text)
    if not pm:
        return None, "no Retail Price listed (Get ePrice vehicle)"
    price_num = pm.group(1).replace(",", "")
    price = f"{float(price_num):.2f} USD"

    # Images (required by Meta) — capped at 20 per Meta's limit
    imgs = re.findall(
        r'https://imagescdn\.dealercarsearch\.com/Media/\d+/%s/[^"\'\s\)>]+\.jpg' % vid,
        html,
    )
    images = list(dict.fromkeys(imgs))[:20]
    if not images:
        return None, "no photos on the listing"

    # VIN — most reliably present in the Carfax link
    vin = ""
    vm_ = re.search(r"vin=([A-HJ-NPR-Z0-9]{17})", html)
    if vm_:
        vin = vm_.group(1)
    else:
        vm2 = re.search(r"\b([A-HJ-NPR-Z0-9]{17})\b", text)
        vin = vm2.group(1) if vm2 else ""

    # Mileage — "169,189 miles" appears in the summary line
    mileage = ""
    mm = re.search(r"([\d,]+)\s+miles", text)
    if mm:
        mileage = mm.group(1).replace(",", "")
    else:
        lv = label_value(text, "Mileage")
        if lv:
            digits = re.sub(r"[^\d]", "", lv)
            mileage = digits or ""
    if not mileage:
        mileage = "1"  # Meta requires a value; site sometimes shows 1 for new arrivals

    stock = label_value(text, "Stock #") or vid
    color = label_value(text, "Color") or "Not Specified"
    if color.lower() in ("", "not specified"):
        color = "Not Specified"
    transmission_raw = label_value(text, "Transmission").upper()
    transmission = (
        "MANUAL" if "MANUAL" in transmission_raw
        else "AUTOMATIC" if transmission_raw else ""
    )
    drive_raw = label_value(text, "Drive Train").upper()
    drivetrain = ""
    for cand in ("4WD", "AWD", "FWD", "RWD"):
        if cand in drive_raw:
            drivetrain = cand
            break
    if drive_raw.strip() == "4":
        drivetrain = "4WD"

    description = (
        f"Used {year} {make} {model} with {int(mileage):,} miles. "
        f"Stock #{stock}. Buy Here Pay Here financing available at "
        f"{DEALER_NAME} in {CITY}, {REGION} — no credit check, no interest, "
        f"no dealer fees. Call 283-203-8763 or visit us at {ADDR1}."
    )

    row = {
        "vehicle_id": stock,
        "title": title,
        "description": description,
        "url": url,
        "make": make,
        "model": model,
        "year": year,
        "mileage.value": mileage,
        "mileage.unit": "MI",
        "vin": vin,
        "price": price,
        "state_of_vehicle": "USED",
        "condition": "GOOD",
        "availability": "AVAILABLE",
        "exterior_color": color,
        "body_style": guess_body_style(title),
        "transmission": transmission,
        "drivetrain": drivetrain,
        "fuel_type": "GASOLINE",
        "dealer_name": DEALER_NAME,
        "address": (
            '{"addr1":"%s","city":"%s","region":"%s","postal_code":"%s","country":"%s"}'
            % (ADDR1, CITY, REGION, POSTAL, COUNTRY)
        ),
        "latitude": LATITUDE,
        "longitude": LONGITUDE,
        "image[0].url": images[0] if len(images) > 0 else "",
    }
    for i, img in enumerate(images[1:], start=1):
        row[f"image[{i}].url"] = img
    return row, None


def main():
    vehicles = []
    skipped = []
    for vid, url in get_vdp_urls():
        row, reason = parse_vdp(vid, url)
        if row:
            vehicles.append(row)
            print(f"  OK   {row['title']}  ({row['price']}, "
                  f"{sum(1 for k in row if k.startswith('image'))} photos)")
        else:
            skipped.append((url, reason))
            print(f"  SKIP {url} -> {reason}")
        time.sleep(1)  # be polite to our own site

    if not vehicles:
        sys.exit("FATAL: zero vehicles made it into the feed; not overwriting.")

    # Column order: fixed fields first, then as many image columns as needed
    max_imgs = max(
        sum(1 for k in v if re.match(r"image\[\d+\]\.url", k)) for v in vehicles
    )
    base_cols = [
        "vehicle_id", "title", "description", "url", "make", "model", "year",
        "mileage.value", "mileage.unit", "vin", "price", "state_of_vehicle",
        "condition", "availability", "exterior_color", "body_style",
        "transmission", "drivetrain", "fuel_type", "dealer_name", "address",
        "latitude", "longitude",
    ]
    img_cols = [f"image[{i}].url" for i in range(max_imgs)]

    with open("feed.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=base_cols + img_cols, extrasaction="ignore")
        w.writeheader()
        for v in vehicles:
            w.writerow(v)

    # Heartbeat file: guarantees a daily commit so the schedule never
    # gets auto-disabled for inactivity, and shows when the feed last ran.
    with open("last_updated.txt", "w") as f:
        f.write(datetime.now(timezone.utc).isoformat() + "\n")
        f.write(f"vehicles_in_feed: {len(vehicles)}\n")
        for url, reason in skipped:
            f.write(f"skipped: {url} ({reason})\n")

    print(f"\nWrote feed.csv with {len(vehicles)} vehicles "
          f"({len(skipped)} skipped).")


if __name__ == "__main__":
    main()
