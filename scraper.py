"""
2GIS Scraper — поиск бизнесов Кыргызстана через 2GIS Catalog API.
Собирает: название, телефон, адрес, рейтинг, сайт.
"""

import requests
import time
import argparse
import sys
from config import TWOGIS_API_KEY, TWOGIS_BASE_URL, CITIES, CATEGORIES, REQUEST_DELAY
from database import Database


class TwoGisScraper:
    def __init__(self):
        if not TWOGIS_API_KEY or TWOGIS_API_KEY == "your_2gis_api_key_here":
            print("❌ Ошибка: укажи TWOGIS_API_KEY в файле .env")
            print("   Получи ключ бесплатно на https://dev.2gis.com/")
            sys.exit(1)

        self.api_key = TWOGIS_API_KEY
        self.base_url = TWOGIS_BASE_URL
        self.db = Database()
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "KG-LeadGen/1.0",
            "Accept": "application/json",
        })

    # ──────────────────────────────────────
    # API calls
    # ──────────────────────────────────────

    def search_businesses(self, query, page=1, page_size=10):
        """Search for businesses in 2GIS Catalog API."""
        url = f"{self.base_url}/items"
        params = {
            "q": query,
            "key": self.api_key,
            "type": "branch",
            "page": page,
            "page_size": page_size,
            "fields": "items.contact_groups,items.reviews,items.external_content,items.org",
            "locale": "ru_KG",
        }

        try:
            response = self.session.get(url, params=params, timeout=15)
            response.raise_for_status()
            data = response.json()

            # Check for API errors
            meta = data.get("meta", {})
            if meta.get("code") and meta["code"] != 200:
                error_msg = meta.get("error", {}).get("message", "Unknown error")
                print(f"  ⚠ API ошибка: {error_msg}")
                return None

            return data
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 403:
                print(f"  ❌ API ключ невалидный или лимит исчерпан")
            elif e.response.status_code == 429:
                print(f"  ⏳ Слишком много запросов, жду 5 сек...")
                time.sleep(5)
            else:
                print(f"  ❌ HTTP ошибка {e.response.status_code}: {e}")
            return None
        except requests.exceptions.RequestException as e:
            print(f"  ❌ Ошибка сети: {e}")
            return None

    # ──────────────────────────────────────
    # Data extraction helpers
    # ──────────────────────────────────────

    def _extract_phones(self, item):
        """Extract all phone numbers from a 2GIS item."""
        phones = []

        # From contact_groups
        for group in item.get("contact_groups", []):
            for contact in group.get("contacts", []):
                if contact.get("type") == "phone":
                    value = contact.get("value", "")
                    if value and value not in phones:
                        phones.append(value)

        # From org.contact_groups
        org = item.get("org", {})
        if org:
            for group in org.get("contact_groups", []):
                for contact in group.get("contacts", []):
                    if contact.get("type") == "phone":
                        value = contact.get("value", "")
                        if value and value not in phones:
                            phones.append(value)

        return phones

    def _format_international(self, phone):
        """Format phone to international format +996XXXXXXXXX."""
        if not phone:
            return None

        # Clean: keep only digits and +
        cleaned = "".join(c for c in phone if c.isdigit() or c == "+")

        if cleaned.startswith("+996"):
            return cleaned
        if cleaned.startswith("996") and len(cleaned) >= 12:
            return f"+{cleaned}"
        if cleaned.startswith("0") and len(cleaned) >= 10:
            return f"+996{cleaned[1:]}"
        if len(cleaned) == 9 and cleaned[0] in "2579":
            # Local mobile: 2XX, 5XX, 7XX, 9XX
            return f"+996{cleaned}"

        # Return with +996 prefix as best guess
        return phone

    def _extract_website(self, item):
        """Extract website URL from a 2GIS item."""
        for group in item.get("contact_groups", []):
            for contact in group.get("contacts", []):
                if contact.get("type") == "website":
                    return contact.get("value")

        # Check external_content
        for ext in item.get("external_content", []):
            if ext.get("type") == "website":
                return ext.get("main_page_url")

        return None

    def _extract_rating(self, item):
        """Extract rating from reviews section."""
        reviews = item.get("reviews", {})
        return reviews.get("general_rating")

    def _extract_review_count(self, item):
        """Extract review count."""
        reviews = item.get("reviews", {})
        return reviews.get("general_review_count", 0)

    # ──────────────────────────────────────
    # Processing
    # ──────────────────────────────────────

    def process_item(self, item, city, category):
        """Process a single 2GIS result into our format."""
        phones = self._extract_phones(item)
        primary_phone = phones[0] if phones else None
        intl_phone = self._format_international(primary_phone)
        website = self._extract_website(item)

        return {
            "source_id": str(item.get("id", "")),
            "name": item.get("name", "Без названия"),
            "phone": primary_phone,
            "international_phone": intl_phone,
            "address": item.get("address_name", ""),
            "city": city,
            "category": category,
            "rating": self._extract_rating(item),
            "reviews_count": self._extract_review_count(item),
            "website": website,
        }

    def scrape_query(self, category, city):
        """Scrape all results for a category+city combination."""
        query = f"{category} {city}"
        print(f"  🔍 «{category}» в {city}...", end=" ", flush=True)

        total_found = 0
        total_saved = 0
        page = 1
        max_pages = 5  # Safety limit (250 results per query)

        while page <= max_pages:
            result = self.search_businesses(query, page=page)

            if not result or "result" not in result:
                break

            items = result["result"].get("items", [])
            if not items:
                break

            for item in items:
                data = self.process_item(item, city, category)
                total_found += 1

                if data["phone"]:  # Only save if has phone
                    row_id = self.db.add_business(data)
                    if row_id:
                        total_saved += 1

            # Check if there are more pages
            total_available = result["result"].get("total", 0)
            if page * 10 >= total_available:
                break

            page += 1
            time.sleep(REQUEST_DELAY)

        print(f"найдено: {total_found}, новых: {total_saved}")
        return total_found, total_saved

    # ──────────────────────────────────────
    # Main runner
    # ──────────────────────────────────────

    def run(self, cities=None, categories=None, test=False):
        """Run the full scraping process."""
        cities = cities or CITIES
        categories = categories or CATEGORIES

        if test:
            cities = cities[:1]
            categories = categories[:2]
            print("🧪 ТЕСТОВЫЙ РЕЖИМ: 1 город × 2 категории\n")

        total_queries = len(cities) * len(categories)
        print("=" * 60)
        print("🚀 Запуск сбора данных из 2GIS")
        print(f"   Города:      {len(cities)}")
        print(f"   Категории:   {len(categories)}")
        print(f"   Запросов:    ~{total_queries}")
        print(f"   Ожидание:    ~{total_queries * 2} сек")
        print("=" * 60)

        grand_total = 0
        grand_saved = 0
        query_num = 0

        for city in cities:
            print(f"\n📍 {city}")
            print("-" * 40)

            for category in categories:
                query_num += 1
                found, saved = self.scrape_query(category, city)
                grand_total += found
                grand_saved += saved
                time.sleep(REQUEST_DELAY)

        # Final stats
        stats = self.db.get_stats()
        print("\n" + "=" * 60)
        print("✅ СБОР ЗАВЕРШЁН!")
        print(f"   Обработано запросов:  {query_num}")
        print(f"   Найдено всего:       {grand_total}")
        print(f"   Сохранено новых:     {grand_saved}")
        print(f"   Всего в базе:        {stats['total']}")
        print(f"   С телефоном:         {stats['with_phone']}")
        print(f"   Без сайта:           {stats['no_website']} 🎯 (приоритет!)")
        print("=" * 60)
        print(f"\n💡 Запусти Dashboard: python app.py")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="2GIS Scraper — поиск бизнесов Кыргызстана"
    )
    parser.add_argument(
        "--test", action="store_true",
        help="Тестовый режим (1 город, 2 категории)"
    )
    parser.add_argument(
        "--city", type=str,
        help="Поиск в конкретном городе (напр: Бишкек)"
    )
    parser.add_argument(
        "--category", type=str,
        help="Поиск по конкретной категории (напр: 'салон красоты')"
    )
    args = parser.parse_args()

    scraper = TwoGisScraper()

    cities = [args.city] if args.city else None
    categories = [args.category] if args.category else None

    scraper.run(cities=cities, categories=categories, test=args.test)
