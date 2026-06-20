import requests
import json
from config import TWOGIS_API_KEY

key = TWOGIS_API_KEY
url = "https://catalog.api.2gis.com/3.0/items"

# Test Almaty with ru_KG locale
params_kg = {
    "q": "салон красоты Алматы",
    "key": key,
    "type": "branch",
    "page": 1,
    "page_size": 1,
    "fields": "items.contact_groups",
    "locale": "ru_KG",
}

print("Testing Almaty with locale=ru_KG...")
response = requests.get(url, params=params_kg)
data = response.json()
if "result" in data and "items" in data["result"]:
    item = data["result"]["items"][0]
    print("  KG Locale contacts found:", "contact_groups" in item)
else:
    print("  Error/No results:", data)

# Test Almaty with ru_KZ locale
params_kz = params_kg.copy()
params_kz["locale"] = "ru_KZ"

print("\nTesting Almaty with locale=ru_KZ...")
response = requests.get(url, params=params_kz)
data = response.json()
if "result" in data and "items" in data["result"]:
    item = data["result"]["items"][0]
    print("  KZ Locale contacts found:", "contact_groups" in item)
    if "contact_groups" in item:
        print(json.dumps(item["contact_groups"], indent=2, ensure_ascii=False)[:300])
else:
    print("  Error/No results:", data)
