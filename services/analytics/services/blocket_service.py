"""
Blocket.se integration service.

Fetches dealer shop statistics from the blocket-api.se hosted REST API.
Requires no extra dependencies beyond the standard library — uses urllib.request
with a Firefox User-Agent header (the API returns HTTP 403 otherwise).
"""

import json
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from statistics import mean, median

_BASE_URL = "https://blocket-api.se/v1/search"
_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"
)
_TIMEOUT = 10  # seconds per request


def _get(url: str) -> dict | None:
    """Perform a GET request and return parsed JSON, or None on error."""
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError):
        return None


def _parse_date(date_str: str) -> datetime | None:
    """Parse ISO-8601 datetime string safely."""
    if not date_str:
        return None
    try:
        return datetime.fromisoformat(date_str.replace('Z', '+00:00'))
    except (ValueError, TypeError):
        return None


def _calculate_days_published(created_at: str) -> int:
    """Calculate days since listing was created."""
    created = _parse_date(created_at)
    if not created:
        return 0
    now = datetime.now(tz=timezone.utc)
    # Make created_at aware if it's naive
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    delta = now - created
    return max(0, delta.days)


def _calculate_days_published_from_timestamp(timestamp: int | None) -> int:
    """Calculate days since listing was created using Unix timestamp (milliseconds)."""
    if not timestamp:
        return 0
    try:
        # Blocket API provides timestamps in milliseconds
        created = datetime.fromtimestamp(timestamp / 1000.0, tz=timezone.utc)
        now = datetime.now(tz=timezone.utc)
        delta = now - created
        return max(0, delta.days)
    except (ValueError, TypeError, OSError):
        return 0


def _calculate_price_rank(price: int | None, car_year: int | None,
                          mileage: int | None, all_cars: list) -> str:
    """
    Compare price against similar vehicles.

    Matching criteria:
      - Same make + model (exact, case-insensitive)
      - Year within ±1 of target
      - Mileage within ±15 000 km of target
      - If the listing has a recognisable package keyword (e.g. "M-Sport",
        "S-Line"), prefer comparables that share the same package keyword.
        Falls back to all model-matched comparables when fewer than 3
        package-matched ones exist.

    Returns 'low' / 'competitive' / 'high' / 'unknown'
    """
    # Called with a raw doc, not the processed listing dict
    return "unknown"  # placeholder – the real work is in _calculate_price_rank_for_doc


def _extract_package_keywords(model_specification: str | None) -> list[str]:
    """
    Return a list of lowercased trim/package keywords found in model_specification.
    These are used to narrow comparables to truly equivalent trims.
    """
    if not model_specification:
        return []
    spec = model_specification.lower()
    # Ordered from most-specific to least-specific so longer matches win
    known = [
        "m-sport", "m sport", "msport",
        "m competition", "competition",
        "s-line", "s line", "sline",
        "r-line", "r line",
        "amg-line", "amg line",
        "black edition", "white edition", "sport edition",
        "executive", "exclusive", "elegance", "luxury", "prestige",
        "inscription", "r-design", "r design",
        "sport", "premium", "plus", "pro",
    ]
    return [kw for kw in known if kw in spec]


def _calculate_price_rank_for_doc(
    price: int | None,
    car_year: int | None,
    mileage: int | None,
    make: str | None,
    model: str | None,
    model_specification: str | None,
    all_cars: list,
) -> str:
    """
    Compare *price* against other listings in *all_cars* that are genuinely
    comparable.  Returns 'low' / 'competitive' / 'high' / 'unknown'.
    """
    if price is None or car_year is None or not make or not model:
        return "unknown"

    package_keywords = _extract_package_keywords(model_specification)
    make_l = make.lower()
    model_l = model.lower()

    all_comparable: list[int] = []
    package_comparable: list[int] = []

    for car in all_cars:
        try:
            c_price_obj = car.get("price", {})
            c_price = c_price_obj.get("amount") if isinstance(c_price_obj, dict) else c_price_obj
            c_year = car.get("year")
            c_mileage = car.get("mileage")
            c_make = (car.get("make") or "").lower()
            c_model = (car.get("model") or "").lower()
            c_spec = (car.get("model_specification") or "").lower()

            if c_price is None or c_year is None:
                continue
            # Must be same make + model
            if c_make != make_l or c_model != model_l:
                continue
            # Year ±1
            if abs(c_year - car_year) > 1:
                continue
            # Mileage ±15 000 km (skip mileage filter if data missing)
            if mileage is not None and c_mileage is not None:
                if abs(c_mileage - mileage) > 15_000:
                    continue

            all_comparable.append(c_price)

            # Track package-level comparables
            if package_keywords and all(kw in c_spec for kw in package_keywords):
                package_comparable.append(c_price)

        except (KeyError, TypeError):
            continue

    # Prefer package-matched pool, fall back to generic when too small
    pool = package_comparable if len(package_comparable) >= 3 else all_comparable

    if len(pool) < 2:
        return "unknown"

    ref_price = median(pool)
    if ref_price <= 0:
        return "unknown"

    ratio = price / ref_price
    if ratio < 0.90:
        return "low"
    elif ratio > 1.10:
        return "high"
    else:
        return "competitive"



def fetch_blocket_shop_stats(org_id: int) -> dict:
    """
    Fetch published vehicle statistics for a Blocket dealer shop.

    Args:
        org_id: the dealer's Blocket organisation numeric ID (from the shop URL,
                e.g. https://www.blocket.se/mobility/search/car?orgId=<org_id>)

    Returns:
        dict with:
          published_cars     – total published cars
          published_mc       – total published motorcycles/mopeds
          published_boats    – total published boats
          total_published    – sum of the above
          total_views        – sum of views across all car listings
          total_saves        – sum of saves/likes across all car listings
          avg_days_published – average days listings have been published
          price_stats        – dict with min, max, avg price of published cars
          sample_ads         – list of up to 5 car ads with detailed analytics
          store_url          – link to the dealer's car listing on blocket.se
          fetched_at         – ISO-8601 timestamp of the fetch
          error              – None on success, error message string on partial failure
    """
    store_url = f"https://www.blocket.se/mobility/search/car?orgId={org_id}"
    fetched_at = datetime.now(tz=timezone.utc).isoformat()

    car_data = _get(f"{_BASE_URL}/car?org_id={org_id}")
    mc_data = _get(f"{_BASE_URL}/mc?org_id={org_id}")
    boat_data = _get(f"{_BASE_URL}/boat?org_id={org_id}")

    error = None
    published_cars = 0
    published_mc = 0
    published_boats = 0
    sample_ads = []
    total_views = 0
    total_saves = 0
    all_days_published = []
    all_prices = []

    if car_data is None:
        error = "Could not reach blocket-api.se"
    else:
        try:
            published_cars = (
                car_data.get("metadata", {})
                .get("result_size", {})
                .get("match_count", 0)
            )
        except (AttributeError, TypeError):
            published_cars = 0

        # Extract all cars first for price comparison
        all_docs = car_data.get("docs", [])

        # Build sample ads list (up to 5 items) with enhanced analytics
        for doc in all_docs[:5]:
            price_amount = None
            try:
                price_obj = doc.get("price", {})
                if isinstance(price_obj, dict):
                    price_amount = price_obj.get("amount")
                else:
                    price_amount = price_obj
            except (KeyError, TypeError):
                pass

            car_year = doc.get("year")
            # Views and saves not available in search API
            views = 0
            saves = 0
            mileage = doc.get("mileage")
            # Use timestamp to calculate days published
            timestamp = doc.get("timestamp")
            days_published = _calculate_days_published_from_timestamp(timestamp) if timestamp else 0

            # Track statistics (will be 0 for search results)
            total_views += views
            total_saves += saves
            if days_published > 0:
                all_days_published.append(days_published)
            if price_amount:
                all_prices.append(price_amount)

            model_spec = doc.get("model_specification") or ""
            make = doc.get("make", "")
            model = doc.get("model", "")

            # Calculate price rank: same make+model, year ±1, mileage ±15 000 km, package match
            price_rank = _calculate_price_rank_for_doc(
                price_amount, car_year, mileage, make, model, model_spec, all_docs
            )

            # Extract registration number from 'regno' field
            registration_number = doc.get("regno") or ""
            
            # Extract first photo URL from 'image' object
            photo_url = None
            image = doc.get("image")
            if image and isinstance(image, dict):
                photo_url = image.get("url")

            sample_ads.append(
                {
                    "heading": doc.get("heading", ""),
                    "make": make,
                    "model": model,
                    "model_specification": model_spec,
                    "year": car_year,
                    "mileage": mileage,
                    "price": price_amount,
                    "views": views,
                    "saves": saves,
                    "days_published": days_published,
                    "body_type": doc.get("body_type", ""),
                    "fuel_type": doc.get("fuel_type", ""),
                    "transmission": doc.get("transmission", ""),
                    "price_rank": price_rank,
                    "registration_number": registration_number,
                    "photo_url": photo_url,
                    "url": doc.get("canonical_url", ""),
                }
            )

    if mc_data is not None:
        try:
            published_mc = (
                mc_data.get("metadata", {})
                .get("result_size", {})
                .get("match_count", 0)
            )
        except (AttributeError, TypeError):
            published_mc = 0

    if boat_data is not None:
        try:
            published_boats = (
                boat_data.get("metadata", {})
                .get("result_size", {})
                .get("match_count", 0)
            )
        except (AttributeError, TypeError):
            published_boats = 0

    # Calculate aggregate statistics
    avg_days_published = round(mean(all_days_published)) if all_days_published else 0
    price_stats = {}
    if all_prices:
        price_stats = {
            "min": min(all_prices),
            "max": max(all_prices),
            "avg": round(mean(all_prices)),
            "median": round(median(all_prices)),
        }

    return {
        "published_cars": published_cars,
        "published_mc": published_mc,
        "published_boats": published_boats,
        "total_published": published_cars + published_mc + published_boats,
        "total_views": total_views,
        "total_saves": total_saves,
        "avg_days_published": avg_days_published,
        "price_stats": price_stats,
        "sample_ads": sample_ads,
        "store_url": store_url,
        "fetched_at": fetched_at,
        "error": error,
    }


def fetch_blocket_listings(org_id: int, make_filter: str = None,
                          min_price: int = None, max_price: int = None) -> dict:
    """
    Fetch all Blocket car listings for a dealer with optional filtering.

    Args:
        org_id: the dealer's Blocket organisation numeric ID
        make_filter: optional car brand/make to filter by (case-insensitive)
        min_price: optional minimum price filter (in SEK)
        max_price: optional maximum price filter (in SEK)

    Returns:
        dict with:
          listings      – list of all car listings, optionally filtered
          total_count   – total number of listings (before filtering)
          filtered_count – number of listings after filtering
          makes          – list of all unique makes/brands in the shop
          error          – None on success, error message on failure
    """
    car_data = _get(f"{_BASE_URL}/car?org_id={org_id}")

    if car_data is None:
        return {
            "listings": [],
            "total_count": 0,
            "filtered_count": 0,
            "makes": [],
            "error": "Could not reach blocket-api.se",
        }

    all_docs = car_data.get("docs", [])
    
    try:
        total_count = (
            car_data.get("metadata", {})
            .get("result_size", {})
            .get("match_count", 0)
        )
    except (AttributeError, TypeError):
        total_count = len(all_docs)

    # Extract all unique makes
    makes_set = set()
    all_prices = []  # Track all prices for statistics
    for doc in all_docs:
        make = doc.get("make")
        if make:
            makes_set.add(make)
        # Collect prices
        try:
            price_obj = doc.get("price", {})
            if isinstance(price_obj, dict):
                price_amount = price_obj.get("amount")
            else:
                price_amount = price_obj
            if price_amount:
                all_prices.append(price_amount)
        except (KeyError, TypeError):
            pass
    
    makes = sorted(list(makes_set))

    # Build full listings list and apply filters
    listings = []
    for doc in all_docs:
        price_amount = None
        try:
            price_obj = doc.get("price", {})
            if isinstance(price_obj, dict):
                price_amount = price_obj.get("amount")
            else:
                price_amount = price_obj
        except (KeyError, TypeError):
            pass

        car_year = doc.get("year")
        mileage = doc.get("mileage")
        make = doc.get("make", "")

        # Apply make filter
        if make_filter and make.lower() != make_filter.lower():
            continue

        # Apply price filters
        if price_amount is not None:
            if min_price is not None and price_amount < min_price:
                continue
            if max_price is not None and price_amount > max_price:
                continue

        # Views and saves not available in search API
        views = 0
        saves = 0
        timestamp = doc.get("timestamp")
        days_published = _calculate_days_published_from_timestamp(timestamp) if timestamp else 0
        model = doc.get("model", "")
        model_spec = doc.get("model_specification") or ""

        # Calculate price rank: same make+model, year ±1, mileage ±15 000 km, package match
        price_rank = _calculate_price_rank_for_doc(
            price_amount, car_year, mileage, make, model, model_spec, all_docs
        )
        
        # Extract registration number from 'regno' field
        registration_number = doc.get("regno") or ""
        
        # Extract first photo URL from 'image' object
        photo_url = None
        image = doc.get("image")
        if image and isinstance(image, dict):
            photo_url = image.get("url")

        listings.append(
            {
                "id": doc.get("id", ""),
                "heading": doc.get("heading", ""),
                "make": make,
                "model": model,
                "model_specification": model_spec,
                "year": car_year,
                "mileage": mileage,
                "price": price_amount,
                "views": views,
                "saves": saves,
                "days_published": days_published,
                "body_type": doc.get("body_type", ""),
                "fuel_type": doc.get("fuel_type", ""),
                "transmission": doc.get("transmission", ""),
                "price_rank": price_rank,
                "registration_number": registration_number,
                "photo_url": photo_url,
                "url": doc.get("canonical_url", ""),
            }
        )

    # Calculate price statistics
    price_stats = {}
    if all_prices:
        price_stats = {
            "min": min(all_prices),
            "max": max(all_prices),
            "avg": round(mean(all_prices)),
            "median": round(median(all_prices)),
        }

    return {
        "listings": listings,
        "total_count": total_count,
        "filtered_count": len(listings),
        "makes": makes,
        "price_stats": price_stats,
        "error": None,
    }
