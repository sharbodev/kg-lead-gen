"""
Database module — SQLite хранилище для лидов.
Дедупликация по source_id, отслеживание статусов, статистика.
"""

import sqlite3
import os
from datetime import datetime
from config import DB_PATH


class Database:
    def __init__(self, db_path=None):
        self.db_path = db_path or DB_PATH
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self.init_db()

    def get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self):
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS businesses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id TEXT UNIQUE,
                name TEXT NOT NULL,
                phone TEXT,
                international_phone TEXT,
                address TEXT,
                city TEXT,
                category TEXT,
                rating REAL,
                reviews_count INTEGER DEFAULT 0,
                website TEXT,
                has_website BOOLEAN DEFAULT 0,
                status TEXT DEFAULT 'new',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                messaged_at TIMESTAMP,
                notes TEXT
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                business_id INTEGER,
                message_text TEXT,
                wa_link TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                sent_at TIMESTAMP,
                FOREIGN KEY (business_id) REFERENCES businesses(id)
            )
        """)

        # Indexes for fast filtering
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_businesses_city ON businesses(city)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_businesses_category ON businesses(category)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_businesses_status ON businesses(status)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_businesses_has_website ON businesses(has_website)")

        conn.commit()
        conn.close()

    # ──────────────────────────────────────
    # CRUD Operations
    # ──────────────────────────────────────

    def add_business(self, data):
        """Add a business to the database. Returns row id or None if duplicate."""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("""
                INSERT OR IGNORE INTO businesses
                (source_id, name, phone, international_phone, address,
                 city, category, rating, reviews_count, website, has_website)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                data.get("source_id"),
                data.get("name"),
                data.get("phone"),
                data.get("international_phone"),
                data.get("address"),
                data.get("city"),
                data.get("category"),
                data.get("rating"),
                data.get("reviews_count", 0),
                data.get("website"),
                1 if data.get("website") else 0,
            ))
            conn.commit()
            return cursor.lastrowid if cursor.rowcount > 0 else None
        except Exception as e:
            print(f"  ⚠ Ошибка при добавлении: {e}")
            return None
        finally:
            conn.close()

    def get_business(self, business_id):
        """Get a single business by ID."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM businesses WHERE id = ?", (business_id,))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None

    def get_businesses(self, city=None, category=None, status=None,
                       has_website=None, search=None, min_reviews=None, page=1, per_page=50):
        """Get businesses with optional filters and pagination."""
        conn = self.get_connection()
        cursor = conn.cursor()

        query = "SELECT * FROM businesses WHERE phone IS NOT NULL AND phone != ''"
        params = []

        if city:
            query += " AND city = ?"
            params.append(city)
        if category:
            query += " AND category = ?"
            params.append(category)
        if status:
            query += " AND status = ?"
            params.append(status)
        if has_website is not None:
            query += " AND has_website = ?"
            params.append(1 if has_website else 0)
        if min_reviews is not None:
            query += " AND reviews_count >= ?"
            params.append(min_reviews)
        if search:
            query += " AND (name LIKE ? OR address LIKE ? OR phone LIKE ?)"
            s = f"%{search}%"
            params.extend([s, s, s])

        # Businesses without website first (priority leads), then by rating
        query += " ORDER BY has_website ASC, rating DESC NULLS LAST"
        query += " LIMIT ? OFFSET ?"
        params.extend([per_page, (page - 1) * per_page])

        cursor.execute(query, params)
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]

    def get_total_count(self, city=None, category=None, status=None,
                        has_website=None, search=None, min_reviews=None):
        """Get total count with the same filters."""
        conn = self.get_connection()
        cursor = conn.cursor()

        query = "SELECT COUNT(*) as count FROM businesses WHERE phone IS NOT NULL AND phone != ''"
        params = []

        if city:
            query += " AND city = ?"
            params.append(city)
        if category:
            query += " AND category = ?"
            params.append(category)
        if status:
            query += " AND status = ?"
            params.append(status)
        if has_website is not None:
            query += " AND has_website = ?"
            params.append(1 if has_website else 0)
        if min_reviews is not None:
            query += " AND reviews_count >= ?"
            params.append(min_reviews)
        if search:
            query += " AND (name LIKE ? OR address LIKE ? OR phone LIKE ?)"
            s = f"%{search}%"
            params.extend([s, s, s])

        cursor.execute(query, params)
        count = cursor.fetchone()["count"]
        conn.close()
        return count

    # ──────────────────────────────────────
    # Status Management
    # ──────────────────────────────────────

    def update_status(self, business_id, status):
        """Update the outreach status of a business."""
        conn = self.get_connection()
        cursor = conn.cursor()
        if status == "messaged":
            cursor.execute(
                "UPDATE businesses SET status = ?, messaged_at = ? WHERE id = ?",
                (status, datetime.now().isoformat(), business_id),
            )
        else:
            cursor.execute(
                "UPDATE businesses SET status = ? WHERE id = ?",
                (status, business_id),
            )
        conn.commit()
        conn.close()

    def update_notes(self, business_id, notes):
        """Update notes for a business."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE businesses SET notes = ? WHERE id = ?",
            (notes, business_id),
        )
        conn.commit()
        conn.close()

    # ──────────────────────────────────────
    # Messages
    # ──────────────────────────────────────

    def save_message(self, business_id, message_text, wa_link):
        """Save a generated message for a business."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO messages (business_id, message_text, wa_link)
            VALUES (?, ?, ?)
        """, (business_id, message_text, wa_link))
        conn.commit()
        msg_id = cursor.lastrowid
        conn.close()
        return msg_id

    def get_message(self, business_id):
        """Get the latest message for a business."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM messages WHERE business_id = ? ORDER BY created_at DESC LIMIT 1",
            (business_id,),
        )
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None

    # ──────────────────────────────────────
    # Statistics
    # ──────────────────────────────────────

    def get_stats(self):
        """Get dashboard statistics."""
        conn = self.get_connection()
        cursor = conn.cursor()

        stats = {}

        cursor.execute("SELECT COUNT(*) as c FROM businesses")
        stats["total"] = cursor.fetchone()["c"]

        cursor.execute("SELECT COUNT(*) as c FROM businesses WHERE phone IS NOT NULL AND phone != ''")
        stats["with_phone"] = cursor.fetchone()["c"]

        for s in ("new", "messaged", "replied", "converted", "rejected"):
            cursor.execute(f"SELECT COUNT(*) as c FROM businesses WHERE status = ?", (s,))
            stats[s] = cursor.fetchone()["c"]

        cursor.execute("SELECT COUNT(*) as c FROM businesses WHERE has_website = 0 AND phone IS NOT NULL AND phone != ''")
        stats["no_website"] = cursor.fetchone()["c"]

        cursor.execute("SELECT DISTINCT city FROM businesses WHERE city IS NOT NULL ORDER BY city")
        stats["cities"] = [row["city"] for row in cursor.fetchall()]

        cursor.execute("SELECT DISTINCT category FROM businesses WHERE category IS NOT NULL ORDER BY category")
        stats["categories"] = [row["category"] for row in cursor.fetchall()]

        conn.close()
        return stats

    def get_today_messaged_count(self):
        """Count messages sent today."""
        conn = self.get_connection()
        cursor = conn.cursor()
        today = datetime.now().strftime("%Y-%m-%d")
        cursor.execute(
            "SELECT COUNT(*) as c FROM businesses WHERE messaged_at LIKE ?",
            (f"{today}%",),
        )
        count = cursor.fetchone()["c"]
        conn.close()
        return count

    def get_all_businesses_for_export(self):
        """Get all businesses for CSV export."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT name, international_phone, phone, address, city,
                   category, rating, reviews_count, website, status, notes, created_at
            FROM businesses
            WHERE phone IS NOT NULL AND phone != ''
            ORDER BY city, category, name
        """)
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]
