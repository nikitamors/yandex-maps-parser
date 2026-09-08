"""Парсер Яндекс.Карт: ищет организации по сфере и городу."""
import asyncio
import re
from urllib.parse import quote
from playwright.async_api import async_playwright, TimeoutError as PWTimeoutError


SEARCH_URL = "https://yandex.ru/maps/?mode=search&text={query}"

CARD_SELECTOR = ".search-snippet-view"
TITLE_SELECTOR = ".search-business-snippet-view__title, [class*='search-business-snippet-view__title']"
ADDR_SELECTOR = ".search-business-snippet-view__address, [class*='search-business-snippet-view__address']"

PHONE_SELECTORS = [
    "[class*='orgpage-phones-view__phone-number']",
    "[class*='orgpage-phones-view__phone']",
    "[class*='phones-view__phone-number']",
    "a[href^='tel:']",
]
SITE_SELECTORS = [
    "a[class*='business-urls-view__text']",
    "[class*='business-urls-view'] a",
    "a[class*='action-button-view'][href^='http']:not([href*='yandex.'])",
]

PHONE_RE = re.compile(r"[+\d][\d\s\-()]{8,}\d")
EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")


def _clean_phone(raw):
    """У Яндекса номер телефона иногда идёт одной строкой с текстом кнопки
    ('...\\nПоказать телефон') — вырезаем сам номер регуляркой, а не берём текст как есть."""
    if not raw:
        return ""
    m = PHONE_RE.search(raw)
    return m.group(0).strip() if m else raw.splitlines()[0].strip()


async def _extract_card_detail(page, idx, log, retries=2):
    """Кликает на карточку с индексом idx (0-based) и собирает данные из боковой панели.

    Карточка адресуется через Locator, а не через ранее сохранённый ElementHandle:
    Яндекс.Карты периодически перерисовывают список результатов (виртуализация/реакт-рендер),
    из-за чего снятые заранее хендлы отваливаются с 'Element is not attached to the DOM'.
    Locator при каждом действии сам находит актуальный элемент в текущем DOM.
    """
    last_error = None
    for attempt in range(1, retries + 1):
        try:
            card = page.locator(CARD_SELECTOR).nth(idx)
            title_el = card.locator(TITLE_SELECTOR).first
            if await title_el.count() == 0:
                return None
            name = (await title_el.inner_text()).strip()

            addr_el = card.locator(ADDR_SELECTOR).first
            address = (await addr_el.inner_text()).strip() if await addr_el.count() else ""

            await title_el.scroll_into_view_if_needed(timeout=5000)
            await title_el.click(timeout=5000)
            await page.wait_for_timeout(900)

            phone = ""
            for sel in PHONE_SELECTORS:
                el = page.locator(sel).first
                if await el.count():
                    txt = (await el.inner_text()).strip()
                    if not txt:
                        txt = (await el.get_attribute("href") or "").replace("tel:", "")
                    if txt:
                        phone = _clean_phone(txt)
                        break

            site = ""
            for sel in SITE_SELECTORS:
                el = page.locator(sel).first
                if await el.count():
                    href = await el.get_attribute("href") or ""
                    text = (await el.inner_text()).strip()
                    site = href or text
                    if site:
                        break

            # Почта у Яндекс.Карт не штатное поле карточки (в отличие от телефона/сайта) —
            # проверено вживую на полусотне организаций в разных городах и сферах, mailto:
            # практически никогда не встречается. Оставляем два способа поймать её на всякий
            # случай: явную mailto:-ссылку и запасной вариант — поиск email-паттерна в тексте
            # самой панели (вдруг где-то Яндекс покажет её просто текстом, без ссылки).
            email = ""
            email_el = page.locator("a[href^='mailto:']").first
            if await email_el.count():
                href = await email_el.get_attribute("href") or ""
                email = href.replace("mailto:", "").split("?")[0].strip()
            if not email:
                try:
                    panel_text = await page.locator("[class*='card-title-view'], [class*='orgpage']").first.locator("..").inner_text()
                except Exception:
                    panel_text = ""
                for m in EMAIL_RE.findall(panel_text):
                    if "yandex." not in m.lower() and "ya.ru" not in m.lower():
                        email = m
                        break

            return {
                "name": name,
                "address": address,
                "phone": phone,
                "email": email,
                "site": site,
                "has_site": bool(site),
            }
        except Exception as e:
            last_error = e
            if attempt < retries:
                await page.wait_for_timeout(500)
                continue
            log(f"[{idx + 1}] ошибка карточки: {last_error}")
            return None


async def _fetch_email_from_site(context, url, timeout=6000):
    """Заходит на сайт организации (если он есть) и ищет почту на главной странице.
    Короткий таймаут и try/except — один медленный или битый сайт не должен
    останавливать парсинг остальных организаций."""
    if not url or not url.startswith("http"):
        return ""
    page2 = await context.new_page()
    try:
        await page2.goto(url, wait_until="domcontentloaded", timeout=timeout)
        mailto = page2.locator("a[href^='mailto:']").first
        if await mailto.count():
            href = await mailto.get_attribute("href") or ""
            found = href.replace("mailto:", "").split("?")[0].strip()
            if found:
                return found
        body_text = await page2.locator("body").inner_text(timeout=timeout)
        skip_markers = (".png", ".jpg", ".jpeg", ".svg", ".gif", ".webp", "sentry", "wixpress", "example.")
        for m in EMAIL_RE.findall(body_text):
            if not any(bad in m.lower() for bad in skip_markers):
                return m
    except Exception:
        pass
    finally:
        try:
            await page2.close()
        except Exception:
            pass
    return ""


async def search_async(category, city, max_results=80, headless=True,
                       only_without_site=True, log=print, on_result=None,
                       stop_flag=None):
    """Основная корутина парсинга."""
    query = f"{category} {city}".strip()
    url = SEARCH_URL.format(query=quote(query))
    log(f"Запрос: {query}")
    log(f"URL: {url}")

    results = []
    async with async_playwright() as p:
        # channel="chromium" — принудительно использовать полный браузер Chromium,
        # а не отдельный бинарник chromium_headless_shell, который Playwright 1.45+
        # по умолчанию подставляет при headless=True. В .exe зашит только полный
        # chromium (headless_shell вырезан для уменьшения размера), поэтому без
        # явного channel headless-запуск падал с "Executable doesn't exist".
        browser = await p.chromium.launch(headless=headless, channel="chromium")
        context = await browser.new_context(
            locale="ru-RU",
            viewport={"width": 1400, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/121.0.0.0 Safari/537.36"
            ),
        )
        page = await context.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            log(f"Не удалось открыть страницу: {e}")
            await browser.close()
            return results

        try:
            await page.wait_for_selector(CARD_SELECTOR, timeout=15000)
        except Exception:
            log("Карточки не найдены — возможно, изменилась вёрстка или капча.")
            await browser.close()
            return results

        # Прокрутка для подгрузки карточек
        log("Прокручиваю список результатов...")
        card_locator = page.locator(CARD_SELECTOR)
        prev = 0
        stable = 0
        while True:
            if stop_flag and stop_flag():
                log("Остановлено пользователем (прокрутка).")
                break
            cur = await card_locator.count()
            log(f"Найдено карточек: {cur}")
            if cur >= max_results:
                break
            if cur == prev:
                stable += 1
                if stable >= 3:
                    break
            else:
                stable = 0
            prev = cur
            if cur:
                try:
                    await card_locator.last.scroll_into_view_if_needed(timeout=5000)
                except Exception:
                    pass
            await page.wait_for_timeout(1500)

        # Даём странице спокойно домонтировать DOM после последней прокрутки —
        # именно резкий клик сразу после scroll чаще всего ловит 'not attached to DOM'.
        await page.wait_for_timeout(700)

        total = min(await card_locator.count(), max_results)
        log(f"Обрабатываю {total} карточек...")

        for i in range(total):
            if stop_flag and stop_flag():
                log("Остановлено пользователем.")
                break
            data = await _extract_card_detail(page, i, log)
            if not data:
                continue
            data["category"] = category
            data["city"] = city
            if only_without_site and data["has_site"]:
                log(f"[{i + 1}/{total}] {data['name']} — есть сайт, пропуск")
                continue
            # У Яндекс.Карт нет своего поля "почта" — если сайт есть, единственный
            # реальный шанс найти email — заглянуть на сам сайт организации.
            if not data["email"] and data["site"]:
                data["email"] = await _fetch_email_from_site(context, data["site"])
                if data["email"]:
                    log(f"   ↳ почта с сайта: {data['email']}")
            results.append(data)
            log(f"[{i + 1}/{total}] + {data['name']}")
            if on_result:
                on_result(data)

        await browser.close()
    log(f"Готово. Итого: {len(results)} организаций.")
    return results


def search(category, city, **kwargs):
    """Синхронная обёртка над search_async."""
    return asyncio.run(search_async(category, city, **kwargs))
