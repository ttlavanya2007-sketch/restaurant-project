from flask import Flask, jsonify, request, send_from_directory, session
from pathlib import Path
import sqlite3
import json
import uuid
from werkzeug.utils import secure_filename

# =========================================================
# THE FLAVOUR - RESTAURANT BACKEND
# =========================================================
# Keep app.py in the SAME folder as all your HTML/CSS/JS files.
# SQLite stores the restaurant data in restaurant.db.
#
# This version supports:
# - Table bookings
# - Online food orders
# - Customers
# - Menu management
# - Image uploads
# - Reviews
# - Admin dashboard data APIs
# =========================================================

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "restaurant.db"
UPLOAD_FOLDER = BASE_DIR / "uploads"
UPLOAD_FOLDER.mkdir(exist_ok=True)

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}

app = Flask(__name__)
app.secret_key = "CHANGE_THIS_TO_A_LONG_RANDOM_SECRET_KEY"
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"


# =========================================================
# DATABASE HELPERS
# =========================================================

def get_db():
    """Return a SQLite connection with dictionary-like rows."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create all required tables without deleting existing data."""
    conn = get_db()

    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS admins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS menu_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            category TEXT NOT NULL,
            price REAL NOT NULL,
            description TEXT DEFAULT '',
            image_url TEXT DEFAULT '',
            available INTEGER NOT NULL DEFAULT 1,
            popular INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_name TEXT NOT NULL,
            phone TEXT NOT NULL,
            items_json TEXT NOT NULL,
            total REAL NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_name TEXT NOT NULL,
            phone TEXT NOT NULL,
            booking_date TEXT NOT NULL,
            booking_time TEXT NOT NULL,
            guests INTEGER NOT NULL DEFAULT 1,
            occasion TEXT DEFAULT '',
            special_request TEXT DEFAULT '',
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS customers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            phone TEXT UNIQUE NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_name TEXT NOT NULL,
            rating INTEGER NOT NULL,
            review_text TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
    )

    # Demo admin account for local testing.
    # IMPORTANT: replace this with proper authentication/password hashing
    # before production deployment.
    existing_admin = conn.execute(
        "SELECT id FROM admins WHERE username = ?",
        ("admin",),
    ).fetchone()

    if not existing_admin:
        conn.execute(
            "INSERT INTO admins (username, password) VALUES (?, ?)",
            ("admin", "C-RESTAURANT-QSG72-J"),
        )
    else:
        # Keep the existing local admin account in sync with the configured password.
        conn.execute(
            "UPDATE admins SET password = ? WHERE username = ?",
            ("C-RESTAURANT-QSG72-J", "admin"),
        )

    conn.commit()
    conn.close()


# Initialize database when the Flask app is imported as well as when run directly.
init_db()


# =========================================================
# FILE SERVING
# =========================================================

@app.route("/")
def home():
    return send_from_directory(BASE_DIR, "index.html")


@app.route("/uploads/<path:filename>")
def uploaded_file(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)


@app.before_request
def protect_admin_pages():
    protected_pages = {
        "admin_dashboard.html",
        "menu_management.html",
        "orders.html",
        "bookings.html",
        "customers.html"
    }
    path = request.path.lstrip("/")
    if path in protected_pages and "admin_id" not in session:
        return send_from_directory(BASE_DIR, "admin_login.html")


@app.route("/<path:filename>")
def serve_file(filename):
    """Serve HTML/CSS/JS/image files from the project root."""
    requested = BASE_DIR / filename

    try:
        requested.resolve().relative_to(BASE_DIR.resolve())
    except ValueError:
        return jsonify({"success": False, "error": "Invalid file path"}), 400

    if requested.is_file():
        return send_from_directory(BASE_DIR, filename)

    return jsonify({"success": False, "error": "File not found"}), 404


# =========================================================
# HEALTH CHECK
# =========================================================

@app.get("/api/health")
def health():
    return jsonify(
        {
            "success": True,
            "message": "The Flavour backend is running.",
            "database": str(DB_PATH.name),
        }
    )


# =========================================================
# IMAGE UPLOAD API
# =========================================================

def allowed_file(filename):
    return (
        "." in filename
        and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS
    )


@app.post("/api/upload-image")
def upload_image():
    if "image" not in request.files:
        return jsonify({"success": False, "error": "No image file received."}), 400

    file = request.files["image"]

    if not file or not file.filename:
        return jsonify({"success": False, "error": "Please select an image."}), 400

    if not allowed_file(file.filename):
        return jsonify(
            {
                "success": False,
                "error": "Only PNG, JPG, JPEG and WEBP images are allowed.",
            }
        ), 400

    extension = file.filename.rsplit(".", 1)[1].lower()
    safe_name = secure_filename(f"{uuid.uuid4().hex}.{extension}")
    file_path = UPLOAD_FOLDER / safe_name
    file.save(file_path)

    return jsonify(
        {
            "success": True,
            "message": "Image uploaded successfully.",
            "image_url": f"/uploads/{safe_name}",
        }
    ), 201


# =========================================================
# ADMIN AUTHENTICATION
# =========================================================

@app.post("/api/admin/login")
def admin_login():
    data = request.get_json(silent=True) or {}
    username = str(data.get("username", "")).strip()
    password = str(data.get("password", ""))

    if not username or not password:
        return jsonify({"success": False, "error": "Username and password are required."}), 400

    conn = get_db()
    admin = conn.execute(
        "SELECT id, username, password FROM admins WHERE username = ?",
        (username,)
    ).fetchone()
    conn.close()

    if not admin or admin["password"] != password:
        return jsonify({"success": False, "error": "Invalid username or password."}), 401

    session["admin_id"] = admin["id"]
    session["admin_username"] = admin["username"]

    return jsonify({"success": True, "message": "Login successful.", "redirect": "admin_dashboard.html"})


@app.get("/api/admin/me")
def admin_me():
    if "admin_id" not in session:
        return jsonify({"success": False, "authenticated": False}), 401
    return jsonify({"success": True, "authenticated": True, "username": session.get("admin_username", "")})


@app.post("/api/admin/logout")
def admin_logout():
    session.clear()
    return jsonify({"success": True, "message": "Logged out successfully."})


# =========================================================
# MENU API
# =========================================================

@app.get("/api/menu")
def get_menu():
    conn = get_db()
    rows = conn.execute(
        """
        SELECT id, name, category, price, description,
               image_url, available, popular, created_at
        FROM menu_items
        ORDER BY id DESC
        """
    ).fetchall()
    conn.close()

    return jsonify([dict(row) for row in rows])


@app.post("/api/menu")
def create_menu_item():
    data = request.get_json(silent=True) or {}

    name = str(data.get("name", "")).strip()
    category = str(data.get("category", "")).strip()
    description = str(data.get("description", "")).strip()
    image_url = str(data.get("image_url", "")).strip()

    try:
        price = float(data.get("price", 0))
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "Invalid price."}), 400

    available = 1 if bool(data.get("available", True)) else 0
    popular = 1 if bool(data.get("popular", False)) else 0

    if not name or not category or price < 0:
        return jsonify(
            {
                "success": False,
                "error": "Name, category and valid price are required.",
            }
        ), 400

    conn = get_db()
    cursor = conn.execute(
        """
        INSERT INTO menu_items
        (name, category, price, description, image_url, available, popular)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (name, category, price, description, image_url, available, popular),
    )
    conn.commit()
    item_id = cursor.lastrowid
    conn.close()

    return jsonify(
        {
            "success": True,
            "message": "Menu item created.",
            "id": item_id,
        }
    ), 201


@app.patch("/api/menu/<int:item_id>")
def update_menu_item(item_id):
    data = request.get_json(silent=True) or {}

    allowed_fields = {
        "name",
        "category",
        "price",
        "description",
        "image_url",
        "available",
        "popular",
    }

    fields = []
    values = []

    for field, value in data.items():
        if field not in allowed_fields:
            continue

        fields.append(f"{field} = ?")

        if field in {"available", "popular"}:
            values.append(1 if bool(value) else 0)
        elif field == "price":
            try:
                values.append(float(value))
            except (TypeError, ValueError):
                return jsonify({"success": False, "error": "Invalid price."}), 400
        else:
            values.append(str(value).strip())

    if not fields:
        return jsonify({"success": False, "error": "Nothing to update."}), 400

    values.append(item_id)

    conn = get_db()
    cursor = conn.execute(
        f"UPDATE menu_items SET {', '.join(fields)} WHERE id = ?",
        values,
    )
    conn.commit()
    conn.close()

    if cursor.rowcount == 0:
        return jsonify({"success": False, "error": "Menu item not found."}), 404

    return jsonify({"success": True, "message": "Menu item updated."})


@app.delete("/api/menu/<int:item_id>")
def delete_menu_item(item_id):
    conn = get_db()
    cursor = conn.execute(
        "DELETE FROM menu_items WHERE id = ?",
        (item_id,),
    )
    conn.commit()
    conn.close()

    if cursor.rowcount == 0:
        return jsonify({"success": False, "error": "Menu item not found."}), 404

    return jsonify({"success": True, "message": "Menu item deleted."})


# =========================================================
# CUSTOMER HELPER
# =========================================================

def save_customer(conn, name, phone):
    """Create customer if the phone number does not already exist."""
    conn.execute(
        """
        INSERT OR IGNORE INTO customers (name, phone)
        VALUES (?, ?)
        """,
        (name, phone),
    )


# =========================================================
# BOOKING API
# =========================================================

@app.post("/api/bookings")
def create_booking():
    data = request.get_json(silent=True) or {}

    name = str(data.get("name", "")).strip()
    phone = str(data.get("phone", "")).strip()
    booking_date = str(data.get("date", "")).strip()
    booking_time = str(data.get("time", "")).strip()

    # Support both names so your existing booking form works:
    # "request" and "special_request".
    occasion = str(data.get("occasion", "")).strip()
    special_request = str(
        data.get("special_request", data.get("request", ""))
    ).strip()

    raw_guests = data.get("guests", 1)

    # Convert values such as:
    # 4 -> 4
    # "4" -> 4
    # "4 Guests" -> 4
    # "6+ Guests" -> 6
    try:
        if isinstance(raw_guests, int):
            guests = raw_guests
        else:
            guest_text = str(raw_guests).strip()
            digits = "".join(ch for ch in guest_text if ch.isdigit())
            guests = int(digits) if digits else 0
    except (TypeError, ValueError):
        guests = 0

    if not name or not phone or not booking_date or not booking_time or guests < 1:
        return jsonify(
            {
                "success": False,
                "message": "Name, phone, date, time and guests are required.",
            }
        ), 400

    conn = get_db()

    try:
        save_customer(conn, name, phone)

        cursor = conn.execute(
            """
            INSERT INTO bookings
            (
                customer_name,
                phone,
                booking_date,
                booking_time,
                guests,
                occasion,
                special_request,
                status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, 'pending')
            """,
            (
                name,
                phone,
                booking_date,
                booking_time,
                guests,
                occasion,
                special_request,
            ),
        )

        conn.commit()
        booking_id = cursor.lastrowid

    except sqlite3.Error as exc:
        conn.rollback()
        return jsonify(
            {
                "success": False,
                "message": f"Could not save booking: {exc}",
            }
        ), 500

    finally:
        conn.close()

    return jsonify(
        {
            "success": True,
            "message": "Booking received successfully.",
            "booking_id": booking_id,
        }
    ), 201


@app.get("/api/bookings")
def get_bookings():
    conn = get_db()

    rows = conn.execute(
        """
        SELECT id,
               customer_name,
               phone,
               booking_date,
               booking_time,
               guests,
               occasion,
               special_request,
               status,
               created_at
        FROM bookings
        ORDER BY id DESC
        """
    ).fetchall()

    conn.close()

    return jsonify([dict(row) for row in rows])


@app.patch("/api/bookings/<int:booking_id>")
def update_booking(booking_id):
    data = request.get_json(silent=True) or {}
    status = str(data.get("status", "")).strip().lower()

    allowed = {
        "pending",
        "confirmed",
        "seated",
        "completed",
        "cancelled",
    }

    if status not in allowed:
        return jsonify({"success": False, "error": "Invalid booking status."}), 400

    conn = get_db()

    cursor = conn.execute(
        """
        UPDATE bookings
        SET status = ?
        WHERE id = ?
        """,
        (status, booking_id),
    )

    conn.commit()
    conn.close()

    if cursor.rowcount == 0:
        return jsonify({"success": False, "error": "Booking not found."}), 404

    return jsonify(
        {
            "success": True,
            "message": "Booking status updated.",
        }
    )


# =========================================================
# ORDER API
# =========================================================

@app.post("/api/orders")
def create_order():
    data = request.get_json(silent=True) or {}

    name = str(data.get("name", data.get("customer_name", ""))).strip()
    phone = str(data.get("phone", "")).strip()
    items = data.get("items", [])

    try:
        total = float(data.get("total", 0))
    except (TypeError, ValueError):
        total = 0

    if not name or not phone or not isinstance(items, list) or not items:
        return jsonify(
            {
                "success": False,
                "message": "Customer details and order items are required.",
            }
        ), 400

    conn = get_db()

    try:
        save_customer(conn, name, phone)

        cursor = conn.execute(
            """
            INSERT INTO orders
            (customer_name, phone, items_json, total, status)
            VALUES (?, ?, ?, ?, 'pending')
            """,
            (
                name,
                phone,
                json.dumps(items, ensure_ascii=False),
                total,
            ),
        )

        conn.commit()
        order_id = cursor.lastrowid

    except sqlite3.Error as exc:
        conn.rollback()
        return jsonify(
            {
                "success": False,
                "message": f"Could not save order: {exc}",
            }
        ), 500

    finally:
        conn.close()

    return jsonify(
        {
            "success": True,
            "message": "Order received successfully.",
            "order_id": order_id,
        }
    ), 201


@app.get("/api/orders")
def get_orders():
    conn = get_db()

    rows = conn.execute(
        """
        SELECT id,
               customer_name,
               phone,
               items_json,
               total,
               status,
               created_at
        FROM orders
        ORDER BY id DESC
        """
    ).fetchall()

    conn.close()

    result = []

    for row in rows:
        data = dict(row)

        try:
            data["items"] = json.loads(data.pop("items_json"))
        except (TypeError, ValueError, json.JSONDecodeError):
            data["items"] = []
            data.pop("items_json", None)

        result.append(data)

    return jsonify(result)


@app.patch("/api/orders/<int:order_id>")
def update_order(order_id):
    data = request.get_json(silent=True) or {}
    status = str(data.get("status", "")).strip().lower()

    allowed = {
        "pending",
        "confirmed",
        "preparing",
        "ready",
        "completed",
        "cancelled",
    }

    if status not in allowed:
        return jsonify({"success": False, "error": "Invalid order status."}), 400

    conn = get_db()

    cursor = conn.execute(
        """
        UPDATE orders
        SET status = ?
        WHERE id = ?
        """,
        (status, order_id),
    )

    conn.commit()
    conn.close()

    if cursor.rowcount == 0:
        return jsonify({"success": False, "error": "Order not found."}), 404

    return jsonify(
        {
            "success": True,
            "message": "Order status updated.",
        }
    )


# =========================================================
# DASHBOARD API
# =========================================================
# Your admin dashboard can use these endpoints to replace
# hard-coded/sample numbers with live database data.

@app.get("/api/dashboard")
def dashboard_data():
    conn = get_db()

    today_bookings = conn.execute(
        """
        SELECT COUNT(*)
        FROM bookings
        WHERE booking_date = date('now', 'localtime')
        """
    ).fetchone()[0]

    pending_bookings = conn.execute(
        """
        SELECT COUNT(*)
        FROM bookings
        WHERE status = 'pending'
        """
    ).fetchone()[0]

    total_bookings = conn.execute(
        "SELECT COUNT(*) FROM bookings"
    ).fetchone()[0]

    new_orders = conn.execute(
        """
        SELECT COUNT(*)
        FROM orders
        WHERE status = 'pending'
        """
    ).fetchone()[0]

    total_orders = conn.execute(
        "SELECT COUNT(*) FROM orders"
    ).fetchone()[0]

    total_customers = conn.execute(
        "SELECT COUNT(*) FROM customers"
    ).fetchone()[0]

    total_menu_items = conn.execute(
        "SELECT COUNT(*) FROM menu_items"
    ).fetchone()[0]

    available_menu_items = conn.execute(
        "SELECT COUNT(*) FROM menu_items WHERE available = 1"
    ).fetchone()[0]

    recent_bookings = conn.execute(
        """
        SELECT id,
               customer_name,
               phone,
               booking_date,
               booking_time,
               guests,
               occasion,
               special_request,
               status,
               created_at
        FROM bookings
        ORDER BY id DESC
        LIMIT 10
        """
    ).fetchall()

    recent_orders = conn.execute(
        """
        SELECT id,
               customer_name,
               phone,
               items_json,
               total,
               status,
               created_at
        FROM orders
        ORDER BY id DESC
        LIMIT 10
        """
    ).fetchall()

    conn.close()

    orders_list = []

    for row in recent_orders:
        item = dict(row)

        try:
            item["items"] = json.loads(item.pop("items_json"))
        except (TypeError, ValueError, json.JSONDecodeError):
            item["items"] = []
            item.pop("items_json", None)

        orders_list.append(item)

    return jsonify(
        {
            "success": True,
            "stats": {
                "today_bookings": today_bookings,
                "pending_bookings": pending_bookings,
                "total_bookings": total_bookings,
                "new_orders": new_orders,
                "total_orders": total_orders,
                "total_customers": total_customers,
                "total_menu_items": total_menu_items,
                "available_menu_items": available_menu_items,
            },
            "recent_bookings": [dict(row) for row in recent_bookings],
            "recent_orders": orders_list,
        }
    )


# =========================================================
# CUSTOMERS API
# =========================================================

@app.get("/api/customers")
def get_customers():
    conn = get_db()

    rows = conn.execute(
        """
        SELECT
            c.id,
            c.name,
            c.phone,
            COUNT(DISTINCT o.id) AS orders_count,
            COUNT(DISTINCT b.id) AS bookings_count,
            COALESCE(SUM(o.total), 0) AS total_spend,
            MAX(
                CASE
                    WHEN o.created_at IS NOT NULL THEN o.created_at
                    ELSE b.created_at
                END
            ) AS last_activity
        FROM customers c
        LEFT JOIN orders o ON o.phone = c.phone
        LEFT JOIN bookings b ON b.phone = c.phone
        GROUP BY c.id, c.name, c.phone
        ORDER BY c.id DESC
        """
    ).fetchall()

    conn.close()

    return jsonify([dict(row) for row in rows])


# =========================================================
# REVIEWS API
# =========================================================

@app.get("/api/reviews")
def get_reviews():
    conn = get_db()

    rows = conn.execute(
        """
        SELECT id, customer_name, rating, review_text, created_at
        FROM reviews
        ORDER BY id DESC
        """
    ).fetchall()

    conn.close()

    return jsonify([dict(row) for row in rows])


@app.post("/api/reviews")
def create_review():
    data = request.get_json(silent=True) or {}

    name = str(data.get("name", "")).strip()
    review_text = str(data.get("review", "")).strip()

    try:
        rating = int(data.get("rating", 0))
    except (TypeError, ValueError):
        rating = 0

    if not name or not review_text or rating not in range(1, 6):
        return jsonify(
            {
                "success": False,
                "error": "Name, review and rating from 1 to 5 are required.",
            }
        ), 400

    conn = get_db()

    cursor = conn.execute(
        """
        INSERT INTO reviews
        (customer_name, rating, review_text)
        VALUES (?, ?, ?)
        """,
        (name, rating, review_text),
    )

    conn.commit()
    review_id = cursor.lastrowid
    conn.close()

    return jsonify(
        {
            "success": True,
            "message": "Review added successfully.",
            "review_id": review_id,
        }
    ), 201


# =========================================================
# START SERVER
# =========================================================

if __name__ == "__main__":
    print("")
    print("==============================================")
    print(" The Flavour - Flask backend is running")
    print("==============================================")
    print(" Website   : http://127.0.0.1:5000")
    print(" Health    : http://127.0.0.1:5000/api/health")
    print(" Admin     : http://127.0.0.1:5000/admin_login.html")
    print(" Dashboard : http://127.0.0.1:5000/admin_dashboard.html")
    print(" DB        : restaurant.db")
    print("==============================================")
    print("")

    app.run(debug=True)
