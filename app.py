"""
Flask Dashboard — веб-панель управления лидами.
"""

from flask import Flask, render_template, request, jsonify, Response
import csv
import io
from database import Database
from personalizer import Personalizer
from config import DAILY_MESSAGE_LIMIT

app = Flask(__name__)
db = Database()
personalizer = Personalizer()


# ──────────────────────────────────────
# Pages
# ──────────────────────────────────────

@app.route("/")
def dashboard():
    stats = db.get_stats()
    today_count = db.get_today_messaged_count()
    return render_template(
        "dashboard.html",
        stats=stats,
        today_count=today_count,
        daily_limit=DAILY_MESSAGE_LIMIT,
    )


# ──────────────────────────────────────
# API endpoints
# ──────────────────────────────────────

@app.route("/api/businesses")
def api_businesses():
    """Get businesses with filters."""
    city = request.args.get("city", "")
    category = request.args.get("category", "")
    status = request.args.get("status", "")
    has_website = request.args.get("has_website", "")
    search = request.args.get("search", "")
    min_reviews = request.args.get("min_reviews", "")
    page = int(request.args.get("page", 1))

    has_ws = None
    if has_website == "0":
        has_ws = False
    elif has_website == "1":
        has_ws = True

    min_revs = None
    if min_reviews:
        try:
            min_revs = int(min_reviews)
        except ValueError:
            pass

    businesses = db.get_businesses(
        city=city or None,
        category=category or None,
        status=status or None,
        has_website=has_ws,
        search=search or None,
        min_reviews=min_revs,
        page=page,
    )

    total = db.get_total_count(
        city=city or None,
        category=category or None,
        status=status or None,
        has_website=has_ws,
        search=search or None,
        min_reviews=min_revs,
    )

    return jsonify({
        "businesses": businesses,
        "total": total,
        "page": page,
        "pages": max(1, (total + 49) // 50),
    })


@app.route("/api/generate-message/<int:business_id>", methods=["POST"])
def api_generate_message(business_id):
    """Generate a personalized WhatsApp message."""
    force = request.json.get("force", False) if request.is_json else False

    if force:
        result = personalizer.regenerate_message(business_id)
    else:
        result = personalizer.process_business(business_id)

    if result:
        return jsonify({
            "success": True,
            "message": result["message"],
            "wa_link": result["wa_link"],
            "cached": result.get("cached", False),
        })
    return jsonify({"success": False, "error": "Не удалось создать сообщение"}), 400


@app.route("/api/update-status/<int:business_id>", methods=["POST"])
def api_update_status(business_id):
    """Update business outreach status."""
    data = request.get_json()
    status = data.get("status")
    valid = ("new", "messaged", "replied", "converted", "rejected")
    if status in valid:
        db.update_status(business_id, status)
        return jsonify({"success": True})
    return jsonify({"success": False, "error": "Неверный статус"}), 400


@app.route("/api/update-notes/<int:business_id>", methods=["POST"])
def api_update_notes(business_id):
    """Update business notes."""
    data = request.get_json()
    notes = data.get("notes", "")
    db.update_notes(business_id, notes)
    return jsonify({"success": True})


@app.route("/api/stats")
def api_stats():
    """Get dashboard statistics."""
    stats = db.get_stats()
    today_count = db.get_today_messaged_count()
    return jsonify({**stats, "today_messaged": today_count})


# ──────────────────────────────────────
# Export
# ──────────────────────────────────────

@app.route("/export")
def export_csv():
    """Export all businesses to CSV."""
    businesses = db.get_all_businesses_for_export()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Название", "Телефон (межд.)", "Телефон", "Адрес",
        "Город", "Категория", "Рейтинг", "Отзывы",
        "Сайт", "Статус", "Заметки", "Добавлен"
    ])

    for biz in businesses:
        writer.writerow([
            biz["name"],
            biz["international_phone"] or "",
            biz["phone"] or "",
            biz["address"] or "",
            biz["city"] or "",
            biz["category"] or "",
            biz["rating"] or "",
            biz["reviews_count"] or 0,
            biz["website"] or "",
            biz["status"] or "",
            biz["notes"] or "",
            biz["created_at"] or "",
        ])

    return Response(
        "\ufeff" + output.getvalue(),  # BOM for Excel UTF-8
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=leads_export.csv"},
    )


if __name__ == "__main__":
    print("=" * 50)
    print("🚀 Dashboard запущен!")
    print("   Открой: http://localhost:5000")
    print("=" * 50)
    app.run(debug=True, port=5000, host="0.0.0.0")
