#!/usr/bin/env python3
"""Generic URL normalization, validation, fetching, and product extraction."""

from __future__ import annotations

import ipaddress
import json
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from dataclasses import dataclass
from html import unescape
from typing import Any

from woolworths_scraper import ProductSnapshot


USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/135.0.0.0 Safari/537.36"
)
CRAWLER_USER_AGENT = "PriceWatchBot/1.0"
TRACKING_QUERY_PARAM_PREFIXES = (
    "utm_",
    "fbclid",
    "gclid",
    "mc_",
    "mkt_",
)
TRACKING_QUERY_PARAM_NAMES = {
    "ref",
    "ref_",
    "source",
    "src",
    "campaign",
    "cmpid",
    "spm",
    "si",
}
JSON_LD_RE = re.compile(
    r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>\s*(.*?)\s*</script>',
    re.DOTALL | re.IGNORECASE,
)
META_TAG_RE = re.compile(
    r"<meta\s+[^>]*(?:property|name)=['\"]([^'\"]+)['\"][^>]*content=['\"]([^'\"]*)['\"][^>]*>",
    re.IGNORECASE,
)
TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.DOTALL | re.IGNORECASE)
ITEMPROP_PRICE_RE = re.compile(
    r'(?:itemprop=["\']price["\'][^>]*content=["\']|content=["\'])([0-9]+(?:\.[0-9]+)?)',
    re.IGNORECASE,
)
PRICE_AMOUNT_RE = re.compile(r'"priceAmount"\s*:\s*"?([0-9]+(?:\.[0-9]+)?)"?')
PRICE_LABEL_RE = re.compile(r"\$([0-9]+(?:\.[0-9]{2})?)")
SKU_RE = re.compile(
    r'(?:itemprop=["\']sku["\'][^>]*content=["\']|["\']sku["\']\s*:\s*["\'])([^"\']+)',
    re.IGNORECASE,
)
PRODUCT_SIGNALS = (
    "add to cart",
    "buy now",
    "in stock",
    "out of stock",
    "sku",
    "product details",
)
EMBEDDED_STATE_GLOBALS = (
    "__PRELOADED_STATE__",
    "__INITIAL_STATE__",
    "__NUXT__",
)
PRODUCT_ID_HINT_RE = re.compile(r"[A-Z]?\d{4,}(?:-\d+)+|[A-Z]?\d{5,}")


class ProductPageValidationError(ValueError):
    """Raised when a user-provided product URL fails validation."""


class ProductExtractionError(ValueError):
    """Raised when a page fetch succeeds but no product can be extracted."""


@dataclass
class NormalizedTarget:
    original_url: str
    normalized_url: str
    domain: str


@dataclass
class FetchedProductPage:
    original_url: str
    normalized_url: str
    final_url: str
    domain: str
    content_type: str | None
    html: str


def normalize_target_url(target: str) -> NormalizedTarget:
    raw_target = (target or "").strip()
    if not raw_target:
        raise ProductPageValidationError("A product URL is required.")

    if raw_target.isdigit():
        canonical = f"https://www.woolworths.com.au/shop/productdetails/{raw_target}"
        return NormalizedTarget(
            original_url=raw_target,
            normalized_url=canonical,
            domain="woolworths.com.au",
        )

    parsed = urllib.parse.urlparse(raw_target)
    if parsed.scheme not in {"http", "https"}:
        raise ProductPageValidationError("Target must be an HTTP or HTTPS URL.")
    if parsed.scheme != "https":
        raise ProductPageValidationError("Only HTTPS product URLs are supported.")

    hostname = (parsed.hostname or "").strip().lower()
    if not hostname:
        raise ProductPageValidationError("The URL is missing a valid hostname.")
    _validate_public_hostname(hostname)

    cleaned_query = urllib.parse.urlencode(
        [
            (key, value)
            for key, value in urllib.parse.parse_qsl(
                parsed.query,
                keep_blank_values=False,
            )
            if not _is_tracking_query_param(key)
        ],
        doseq=True,
    )
    normalized_url = urllib.parse.urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path or "/",
            "",
            cleaned_query,
            "",
        )
    )
    return NormalizedTarget(
        original_url=raw_target,
        normalized_url=normalized_url,
        domain=hostname,
    )


def fetch_product_page(target: str) -> FetchedProductPage:
    normalized = normalize_target_url(target)
    _assert_allowed_by_robots(normalized.normalized_url)

    request = urllib.request.Request(
        normalized.normalized_url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-AU,en;q=0.9",
        },
    )
    opener = _build_url_opener(context=None)

    try:
        with opener.open(request, timeout=20) as response:
            final_url = response.geturl()
            content_type = response.headers.get("Content-Type")
            html = response.read().decode("utf-8", errors="replace")
    except ssl.SSLCertVerificationError:
        fallback_context = ssl._create_unverified_context()
        opener = _build_url_opener(context=fallback_context)
        with opener.open(request, timeout=20) as response:
            final_url = response.geturl()
            content_type = response.headers.get("Content-Type")
            html = response.read().decode("utf-8", errors="replace")
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", None)
        if not _is_ssl_cert_verify_error(reason):
            raise
        fallback_context = ssl._create_unverified_context()
        opener = _build_url_opener(context=fallback_context)
        with opener.open(request, timeout=20) as response:
            final_url = response.geturl()
            content_type = response.headers.get("Content-Type")
            html = response.read().decode("utf-8", errors="replace")

    final_hostname = (urllib.parse.urlparse(final_url).hostname or normalized.domain).lower()
    _validate_public_hostname(final_hostname)

    return FetchedProductPage(
        original_url=normalized.original_url,
        normalized_url=normalized.normalized_url,
        final_url=final_url,
        domain=final_hostname,
        content_type=content_type,
        html=html,
    )


def extract_generic_product_snapshot(page: FetchedProductPage) -> ProductSnapshot:
    content_type = (page.content_type or "").lower()
    if content_type and "html" not in content_type:
        raise ProductExtractionError("The target URL did not return an HTML page.")

    try:
        product = _extract_json_ld_product(page.html)
    except ProductExtractionError:
        product = None

    if product is not None:
        snapshot = _build_snapshot_from_structured_data(page, product)
        if snapshot.name and snapshot.price is not None:
            return snapshot

    embedded_state_snapshot = _extract_embedded_state_snapshot(page)
    if embedded_state_snapshot is not None:
        return embedded_state_snapshot

    snapshot = _build_snapshot_from_page_signals(page)
    if snapshot.name and snapshot.price is not None:
        return snapshot

    raise ProductExtractionError("Could not generically identify a product on this page.")


def _build_snapshot_from_structured_data(
    page: FetchedProductPage,
    product: dict[str, Any],
) -> ProductSnapshot:
    offers = _pick_offer(product.get("offers"))
    price_spec = offers.get("priceSpecification") if isinstance(offers, dict) else {}
    if not isinstance(price_spec, dict):
        price_spec = {}

    price = _coerce_float(_first_non_empty(
        offers.get("price"),
        product.get("price"),
        product.get("offers", {}).get("price") if isinstance(product.get("offers"), dict) else None,
    ))
    was_price = _coerce_float(_first_non_empty(
        price_spec.get("price"),
        price_spec.get("value"),
    ))
    if was_price is not None and price is not None and was_price <= price:
        was_price = None

    availability = _first_non_empty(
        offers.get("availability"),
        product.get("availability"),
    )
    canonical_url = _first_non_empty(
        offers.get("url"),
        product.get("url"),
        page.final_url,
    )
    raw_product_id = _first_non_empty(
        product.get("sku"),
        product.get("productID"),
        product.get("gtin13"),
        product.get("gtin"),
        _extract_product_id_hint_from_url(page.final_url),
        _slug_from_path(urllib.parse.urlparse(page.final_url).path),
    )
    if raw_product_id is None:
        raw_product_id = _slug_from_path(urllib.parse.urlparse(page.final_url).path) or page.domain

    return ProductSnapshot(
        product_id=f"{_domain_slug(page.domain)}:{raw_product_id}",
        name=_first_non_empty(product.get("name")),
        brand=_normalise_brand(product.get("brand")),
        price=price,
        was_price=was_price,
        cup_price=None,
        in_stock=_coerce_stock_flag(availability),
        availability=availability,
        image_url=_normalise_image(product.get("image")),
        canonical_url=canonical_url,
        currency=_first_non_empty(
            offers.get("priceCurrency"),
            price_spec.get("priceCurrency"),
            product.get("priceCurrency"),
        ),
        original_url=page.original_url,
        extraction_source="generic:structured",
        extraction_confidence=0.95,
    )


def _build_snapshot_from_page_signals(page: FetchedProductPage) -> ProductSnapshot:
    html = page.html
    lower_html = html.lower()
    if not any(signal in lower_html for signal in PRODUCT_SIGNALS):
        raise ProductExtractionError("The page does not look like a product page.")

    meta = _extract_meta_tags(html)
    title = _first_non_empty(
        meta.get("og:title"),
        meta.get("twitter:title"),
        _extract_title_tag(html),
    )
    image_url = _first_non_empty(
        meta.get("og:image"),
        meta.get("twitter:image"),
    )
    price = _coerce_float(_first_non_empty(
        meta.get("product:price:amount"),
        meta.get("og:price:amount"),
        _first_regex_group(ITEMPROP_PRICE_RE, html),
        _first_regex_group(PRICE_AMOUNT_RE, html),
        _first_regex_group(PRICE_LABEL_RE, html),
    ))
    availability = _first_non_empty(
        meta.get("product:availability"),
        "In stock" if "in stock" in lower_html else None,
        "Out of stock" if "out of stock" in lower_html else None,
    )
    raw_product_id = _first_non_empty(
        _first_regex_group(SKU_RE, html),
        _extract_product_id_hint_from_url(page.final_url),
        _slug_from_path(urllib.parse.urlparse(page.final_url).path),
    )

    return ProductSnapshot(
        product_id=f"{_domain_slug(page.domain)}:{raw_product_id or page.domain}",
        name=_clean_product_title(title),
        brand=None,
        price=price,
        was_price=None,
        cup_price=None,
        in_stock=_coerce_stock_flag(availability),
        availability=availability,
        image_url=image_url,
        canonical_url=page.final_url,
        currency=_first_non_empty(
            meta.get("product:price:currency"),
            meta.get("og:price:currency"),
        ),
        original_url=page.original_url,
        extraction_source="generic:heuristic",
        extraction_confidence=0.6,
    )


def _extract_embedded_state_snapshot(page: FetchedProductPage) -> ProductSnapshot | None:
    payload = _extract_embedded_state_payload(page.html)
    if payload is None:
        return None

    product = _find_embedded_state_product(payload, page.final_url)
    if product is None:
        return None

    meta = _extract_meta_tags(page.html)
    title = _first_non_empty(
        product.get("name"),
        product.get("productName"),
        meta.get("og:title"),
        meta.get("twitter:title"),
        _extract_title_tag(page.html),
    )
    prices = product.get("prices") if isinstance(product.get("prices"), dict) else {}
    base_price = _coerce_float(_deep_get(prices, "base", "value"))
    promo_price = _coerce_float(_deep_get(prices, "promo", "value"))
    current_price = promo_price if promo_price is not None else base_price
    was_price = base_price if promo_price is not None and base_price is not None and base_price > promo_price else None
    currency = _first_non_empty(
        _deep_get(prices, "promo", "currency", "code"),
        _deep_get(prices, "base", "currency", "code"),
        meta.get("product:price:currency"),
        meta.get("og:price:currency"),
    )
    availability = _first_non_empty(
        product.get("availability"),
        "In stock" if _coerce_stock_flag(_deep_get(product, "representative", "searchInStoresAvailable")) else None,
    )
    image_url = _first_non_empty(
        _extract_image_from_embedded_product(product),
        meta.get("og:image"),
        meta.get("twitter:image"),
    )
    raw_product_id = _first_non_empty(
        product.get("productId"),
        product.get("id"),
        product.get("sku"),
        _extract_product_id_hint_from_url(page.final_url),
        _slug_from_path(urllib.parse.urlparse(page.final_url).path),
    )

    if current_price is None:
        return None

    return ProductSnapshot(
        product_id=f"{_domain_slug(page.domain)}:{raw_product_id or page.domain}",
        name=_clean_product_title(title),
        brand=_normalise_brand(product.get("brand")),
        price=current_price,
        was_price=was_price,
        cup_price=None,
        in_stock=_coerce_stock_flag(availability),
        availability=availability,
        image_url=image_url,
        canonical_url=_first_non_empty(meta.get("og:url"), page.final_url),
        currency=currency,
        original_url=page.original_url,
        extraction_source="generic:embedded-state",
        extraction_confidence=0.85,
    )


def _extract_json_ld_product(html: str) -> dict[str, Any]:
    for raw_json in JSON_LD_RE.findall(html):
        try:
            payload = json.loads(unescape(raw_json))
        except json.JSONDecodeError:
            continue

        product = _find_product_node(payload)
        if product is not None:
            return product

    raise ProductExtractionError("Could not find structured product metadata on the page.")


def _extract_embedded_state_payload(html: str) -> Any:
    decoder = json.JSONDecoder()
    for global_name in EMBEDDED_STATE_GLOBALS:
        marker = f"window.{global_name}"
        index = html.find(marker)
        if index == -1:
            continue
        brace_index = html.find("{", index)
        if brace_index == -1:
            continue
        try:
            payload, _ = decoder.raw_decode(html[brace_index:])
        except json.JSONDecodeError:
            continue
        return payload
    return None


def _find_embedded_state_product(payload: Any, url: str) -> dict[str, Any] | None:
    candidate_ids = {
        match.group(0)
        for match in PRODUCT_ID_HINT_RE.finditer(url)
    }
    best_score = -1
    best_node: dict[str, Any] | None = None

    for node in _iter_dict_nodes(payload):
        score = _score_embedded_product_node(node, candidate_ids)
        if score > best_score:
            best_score = score
            best_node = node

    if best_score < 4:
        return None
    return best_node


def _iter_dict_nodes(payload: Any):
    stack = [payload]
    seen: set[int] = set()
    inspected = 0
    while stack and inspected < 4000:
        current = stack.pop()
        inspected += 1
        if isinstance(current, dict):
            object_id = id(current)
            if object_id in seen:
                continue
            seen.add(object_id)
            yield current
            stack.extend(current.values())
        elif isinstance(current, list):
            stack.extend(current)


def _score_embedded_product_node(node: dict[str, Any], candidate_ids: set[str]) -> int:
    score = 0
    prices = node.get("prices")
    if isinstance(prices, dict):
        if _coerce_float(_deep_get(prices, "promo", "value")) is not None:
            score += 4
        if _coerce_float(_deep_get(prices, "base", "value")) is not None:
            score += 3
    if isinstance(node.get("name"), str) or isinstance(node.get("productName"), str):
        score += 1
    if isinstance(node.get("images"), dict) or node.get("image"):
        score += 1

    for key in ("productId", "id", "sku"):
        value = node.get(key)
        if isinstance(value, str):
            if value in candidate_ids:
                score += 4
            elif any(candidate in value for candidate in candidate_ids):
                score += 2

    representative = node.get("representative")
    if isinstance(representative, dict) and isinstance(representative.get("flags"), dict):
        score += 1

    return score


def _find_product_node(payload: Any) -> dict[str, Any] | None:
    if isinstance(payload, dict):
        node_type = payload.get("@type")
        if _type_matches_product(node_type):
            return payload

        graph = payload.get("@graph")
        if graph is not None:
            found = _find_product_node(graph)
            if found is not None:
                return found

        for value in payload.values():
            found = _find_product_node(value)
            if found is not None:
                return found

    if isinstance(payload, list):
        for item in payload:
            found = _find_product_node(item)
            if found is not None:
                return found

    return None


def _type_matches_product(node_type: Any) -> bool:
    if isinstance(node_type, str):
        return node_type.lower() == "product"
    if isinstance(node_type, list):
        return any(isinstance(item, str) and item.lower() == "product" for item in node_type)
    return False


def _extract_meta_tags(html: str) -> dict[str, str]:
    meta: dict[str, str] = {}
    for key, value in META_TAG_RE.findall(html):
        lowered = key.strip().lower()
        if lowered and lowered not in meta:
            meta[lowered] = unescape(value.strip())
    return meta


def _extract_title_tag(html: str) -> str | None:
    match = TITLE_RE.search(html)
    if not match:
        return None
    return _clean_html_text(match.group(1))


def _first_regex_group(pattern: re.Pattern[str], value: str) -> str | None:
    match = pattern.search(value)
    if not match:
        return None
    return match.group(1)


def _pick_offer(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                return item
    return {}


def _normalise_brand(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        name = value.get("name")
        if isinstance(name, str):
            return name
    return None


def _normalise_image(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        for item in value:
            if isinstance(item, str):
                return item
    return None


def _extract_image_from_embedded_product(product: dict[str, Any]) -> str | None:
    images = product.get("images")
    if isinstance(images, dict):
        for preferred_key in ("main", "hero", "primary", "default", "gallery", "images"):
            value = images.get(preferred_key)
            image = _extract_first_image_url(value)
            if image is not None:
                return image
        for value in images.values():
            image = _extract_first_image_url(value)
            if image is not None:
                return image
    return _normalise_image(product.get("image"))


def _extract_first_image_url(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        for item in value:
            image = _extract_first_image_url(item)
            if image is not None:
                return image
    if isinstance(value, dict):
        direct = _first_non_empty(
            value.get("image"),
            value.get("imageUrl"),
            value.get("src"),
            value.get("url"),
        )
        if isinstance(direct, str):
            return direct
        for nested in value.values():
            image = _extract_first_image_url(nested)
            if image is not None:
                return image
    return None


def _deep_get(value: Any, *path: str) -> Any:
    current = value
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _coerce_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = value.strip().replace("$", "").replace(",", "")
        if not cleaned:
            return None
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None


def _coerce_stock_flag(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if not lowered:
            return None
        if any(token in lowered for token in ("instock", "in stock", "available")):
            return True
        if any(token in lowered for token in ("outofstock", "out of stock", "soldout", "sold out", "unavailable")):
            return False
    return None


def _clean_html_text(value: str) -> str:
    cleaned = unescape(re.sub(r"<[^>]+>", "", value))
    return re.sub(r"\s+", " ", cleaned).strip()


def _clean_product_title(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    if " | " in cleaned:
        cleaned = cleaned.split(" | ", 1)[0].strip()
    return cleaned or None


def _domain_slug(domain: str) -> str:
    parts = [part for part in domain.split(".") if part not in {"www", "com", "au", "net", "org"}]
    if not parts:
        return domain.replace(".", "-")
    return parts[0]


def _slug_from_path(path: str) -> str | None:
    parts = [part for part in path.split("/") if part]
    if not parts:
        return None
    return parts[-1]


def _extract_product_id_hint_from_url(url: str) -> str | None:
    parsed = urllib.parse.urlparse(url)
    candidates = []
    for segment in parsed.path.split("/"):
        if not segment:
            continue
        match = PRODUCT_ID_HINT_RE.search(segment)
        if match:
            candidates.append(match.group(0))
    if not candidates:
        return None
    candidates.sort(key=len, reverse=True)
    return candidates[0]


def _first_non_empty(*values: Any) -> Any:
    for value in values:
        if value not in (None, "", [], {}):
            return value
    return None


def _is_tracking_query_param(name: str) -> bool:
    lowered = name.strip().lower()
    if not lowered:
        return False
    if lowered in TRACKING_QUERY_PARAM_NAMES:
        return True
    return any(lowered.startswith(prefix) for prefix in TRACKING_QUERY_PARAM_PREFIXES)


def _validate_public_hostname(hostname: str) -> None:
    lowered = hostname.lower()
    if lowered in {"localhost", "127.0.0.1", "::1"}:
        raise ProductPageValidationError("Localhost URLs are not allowed.")

    try:
        ip = ipaddress.ip_address(lowered)
    except ValueError:
        ip = None

    if ip is not None and (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
    ):
        raise ProductPageValidationError("Private or local network URLs are not allowed.")


def _assert_allowed_by_robots(url: str) -> None:
    parsed = urllib.parse.urlparse(url)
    robots_url = urllib.parse.urlunparse(
        (parsed.scheme, parsed.netloc, "/robots.txt", "", "", "")
    )
    parser = urllib.robotparser.RobotFileParser()
    parser.set_url(robots_url)
    try:
        request = urllib.request.Request(
            robots_url,
            headers={"User-Agent": CRAWLER_USER_AGENT},
        )
        opener = _build_url_opener(context=None)
        with opener.open(request, timeout=5) as response:
            robots_text = response.read().decode("utf-8", errors="replace")
        parser.parse(robots_text.splitlines())
    except Exception:
        return
    if not parser.can_fetch(CRAWLER_USER_AGENT, url):
        raise ProductPageValidationError(
            "This site disallows crawling that product URL via robots.txt."
        )


def _build_url_opener(*, context: ssl.SSLContext | None) -> urllib.request.OpenerDirector:
    handlers: list[Any] = [urllib.request.ProxyHandler({})]
    if context is not None:
        handlers.append(urllib.request.HTTPSHandler(context=context))
    return urllib.request.build_opener(*handlers)


def _is_ssl_cert_verify_error(reason: Any) -> bool:
    if isinstance(reason, ssl.SSLCertVerificationError):
        return True
    if isinstance(reason, ssl.SSLError):
        return "CERTIFICATE_VERIFY_FAILED" in str(reason)
    return "CERTIFICATE_VERIFY_FAILED" in str(reason)
