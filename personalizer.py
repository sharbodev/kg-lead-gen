"""
AI Personalizer — генерация персонализированных WhatsApp сообщений через Gemini API.
Использует google.genai (новый SDK).
"""

import urllib.parse
from config import GEMINI_API_KEY
from database import Database


def _init_gemini():
    """Initialize Gemini client."""
    if not GEMINI_API_KEY or GEMINI_API_KEY == "your_gemini_api_key_here":
        return None
    try:
        from google import genai
        client = genai.Client(api_key=GEMINI_API_KEY)
        return client
    except Exception as e:
        print(f"  [!] Gemini init error: {e}")
        return None


class Personalizer:
    def __init__(self):
        self.client = _init_gemini()
        if not self.client:
            print("[!] Gemini API key not set. Using template messages.")
        self.db = Database()
        self.model_name = "gemini-2.0-flash"

    # ──────────────────────────────────────
    # Message generation
    # ──────────────────────────────────────

    def generate_message(self, business):
        """Generate a personalized WhatsApp message using Gemini."""
        if not self.client:
            return self._fallback_message(business)

        has_site = business.get("has_website")
        name = business.get("name", "")
        category = business.get("category", "бизнес")
        city = business.get("city", "")
        rating = business.get("rating", "")

        offer_parts = ["Telegram-бот для автоматической записи клиентов"]
        if not has_site:
            offer_parts.append("профессиональный лендинг-сайт")
        offer = " и ".join(offer_parts)

        prompt = f"""Напиши короткое WhatsApp-сообщение (максимум 100 слов) для бизнеса.

Данные:
- Название: {name}
- Категория: {category}
- Город: {city}
- Сайт: {"есть" if has_site else "нет сайта"}
- Рейтинг: {rating if rating else "неизвестен"}

Предлагаем: {offer}

Строгие правила:
1. Начни с приветствия и упомяни название
2. Объясни выгоду в 1-2 предложения (клиенты записываются сами 24/7)
3. {"Мягко предложи также сделать сайт, т.к. у них нет сайта" if not has_site else "НЕ упоминай создание сайта"}
4. Тон: дружелюбный, деловой, НЕ навязчивый, НЕ агрессивный
5. Язык: русский
6. Закончи предложением посмотреть примеры наших работ по ссылке: https://demo-websites-two.vercel.app/
7. Максимум 2 эмодзи
8. НЕ пиши цены и суммы
9. НЕ используй слово «уникальный»
10. Выведи ТОЛЬКО текст сообщения, без кавычек и пояснений"""

        try:
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt,
            )
            text = response.text.strip()
            # Remove wrapping quotes if any
            if text.startswith('"') and text.endswith('"'):
                text = text[1:-1]
            if text.startswith("'") and text.endswith("'"):
                text = text[1:-1]
            return text
        except Exception as e:
            print(f"  [!] Gemini error: {e}")
            return self._fallback_message(business)

    def _fallback_message(self, business):
        """Template message when Gemini is unavailable."""
        name = business.get("name", "вашу компанию")

        msg = f"Здравствуйте! Увидел вашу компанию \"{name}\" в 2GIS."
        msg += "\n\nМы делаем Telegram-ботов для автоматизации записи клиентов."
        msg += " Ваши клиенты смогут записываться сами 24/7 — без звонков и ожидания."

        if not business.get("has_website"):
            msg += "\n\nТакже можем сделать профессиональный сайт-визитку для вашего бизнеса."

        msg += "\n\nПосмотреть примеры наших работ можно по ссылке: https://demo-websites-two.vercel.app/"

        return msg

    # ──────────────────────────────────────
    # WhatsApp link generation
    # ──────────────────────────────────────

    def create_wa_link(self, phone, message):
        """Create a wa.me link with pre-filled message."""
        if not phone:
            return None

        # Clean phone: keep only digits
        clean_phone = "".join(c for c in phone if c.isdigit())

        # Ensure starts with country code 996
        if not clean_phone.startswith("996"):
            if clean_phone.startswith("0"):
                clean_phone = "996" + clean_phone[1:]
            elif len(clean_phone) == 9:
                clean_phone = "996" + clean_phone
            else:
                clean_phone = "996" + clean_phone

        encoded = urllib.parse.quote(message)
        return f"https://wa.me/{clean_phone}?text={encoded}"

    # ──────────────────────────────────────
    # Processing
    # ──────────────────────────────────────

    def process_business(self, business_id):
        """Generate message + wa.me link for a business. Returns dict or None."""
        business = self.db.get_business(business_id)
        if not business:
            return None

        phone = business.get("international_phone") or business.get("phone")
        if not phone:
            return None

        # Check if message already exists
        existing = self.db.get_message(business_id)
        if existing:
            return {
                "message": existing["message_text"],
                "wa_link": existing["wa_link"],
                "business": business,
                "cached": True,
            }

        message = self.generate_message(business)
        wa_link = self.create_wa_link(phone, message)

        self.db.save_message(business_id, message, wa_link)

        return {
            "message": message,
            "wa_link": wa_link,
            "business": business,
            "cached": False,
        }

    def regenerate_message(self, business_id):
        """Force regenerate a message (ignore cache)."""
        business = self.db.get_business(business_id)
        if not business:
            return None

        phone = business.get("international_phone") or business.get("phone")
        if not phone:
            return None

        message = self.generate_message(business)
        wa_link = self.create_wa_link(phone, message)

        self.db.save_message(business_id, message, wa_link)

        return {
            "message": message,
            "wa_link": wa_link,
            "business": business,
            "cached": False,
        }
