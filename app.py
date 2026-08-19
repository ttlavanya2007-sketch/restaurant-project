import json
import os
from datetime import date
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory, session
from supabase import Client, create_client
from werkzeug.utils import secure_filename

# =========================================================
# THE FLAVOUR - RESTAURANT BACKEND (SUPABASE VERSION)
# =========================================================
# Keep app.py in the SAME folder as your HTML/CSS/JS files.
# Data is stored in Supabase Postgres, not in restaurant.db.
# =========================================================

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_FOLDER = Path("/tmp/theflavour_uploads")
UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-only-change-me")
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = os.environ.get("VERCEL", "").lower() == "1"

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").strip()
SUPABASE_SECRET_KEY = os.environ.get("SUPABASE_SECRET_KEY", "").strip()
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin").strip()
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "").strip()

if not SUPABASE_URL or not SUPABASE_SECRET_KEY:
    raise RuntimeError("SUPABASE_URL and SUPABASE_SECRET_KEY environment variables are required.")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_SECRET_KEY)


def rows(response):
    """Return response data as a normal list."""
    return list(response.data or [])


def one(response):
    data = rows(response)
    return data[0] if data else None


# =========================================================
# INITIALIZATION
# =========================================================

def init_admin():
    """Create/update the single owner login from environment variables."""
    if not ADMIN_PASSWORD:
        # We can still run the public site until the admin password is set.
        return

    existing = one(
        supabase.table("admins")
        .select("id,username")
        .eq("username", ADMIN_USERNAME)
        .limit(1)
        .execute()
    )

    if existing:
        supabase.table("admins").update({
            "password": ADMIN_PASSWORD
        }).eq("id", existing["id"]).execute()
    else:
        supabase.table("admins").insert({
            "username": ADMIN_USERNAME,
            "password": ADMIN_PASSWORD
        }).execute()


try:
    init_admin()
except Exception as exc:
    # Keep startup failures visible in logs without making the public site unreadable.
    print(f"Admin initialization warning: {exc}")


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
        "customers.html",
    }
    path = request.path.lstrip("/")
    if path in protected_pages and "admin_id" not in session:
        return send_from_directory(BASE_DIR, "admin_login.html")


@app.route("/<path:filename>")
def serve_file(filename):
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
    try:
        supabase.table("admins").select("id").limit(1).execute()
        db_status = "connected"
    except Exception as exc:
        return jsonify({
            "success": False,
            "message": "Supabase connection failed.",
            "error": str(exc)
        }), 500

    return jsonify({
        "success": True,
        "message": "The Flavour backend is running.",
        "database": "Supabase PostgreSQL",
        "status": db_status,
    })


# =========================================================
# IMAGE UPLOAD API
# =========================================================

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


@app.post("/api/upload-image")
def upload_image():
    if "image" not in request.files:
        return jsonify({"success": False, "error": "No image file received."}), 400

    file = request.files["image"]
    if not file or not file.filename:
        return jsonify({"success": False, "error": "Please select an image."}), 400

    if not allowed_file(file.filename):
        return jsonify({
            "success": False,
            "error": "Only PNG, JPG, JPEG and WEBP images are allowed."
        }), 400

    # Local fallback for development. On Vercel, use Supabase Storage for permanent images.
    extension = file.filename.rsplit(".", 1)[1].lower()
    safe_name = secure_filename(f"{os.urandom(12).hex()}.{extension}")
    file_path = UPLOAD_FOLDER / safe_name
    file.save(file_path)

    return jsonify({
        "success": True,
        "message": "Image uploaded successfully.",
        "image_url": f"/uploads/{safe_name}",
    }), 201


# =========================================================
# ADMIN AUTHENTICATION
# =========================================================

@app.post("/api/admin/login")
def admin_login():
    data = request.get_json(silent=True) or {}
    username = str(data.get("username", "")).strip()
    password = str(data.get("password", ""))

    if not username or not password:
        return jsonify({
            "success": False,
            "error": "Username and password are required."
        }), 400

    admin = one(
        supabase.table("admins")
        .select("id,username,password")
        .eq("username", username)
        .limit(1)
        .execute()
    )

    if not admin or admin.get("password") != password:
        return jsonify({
            "success": False,
            "error": "Invalid username or password."
        }), 401

    session["admin_id"] = admin["id"]
    session["admin_username"] = admin["username"]

    return jsonify({
        "success": True,
        "message": "Login successful.",
        "redirect": "admin_dashboard.html"
    })


@app.get("/api/admin/me")
def admin_me():
    if "admin_id" not in session:
        return jsonify({"success": False, "authenticated": False}), 401

    return jsonify({
        "success": True,
        "authenticated": True,
        "username": session.get("admin_username", "")
    })


@app.post("/api/admin/logout")
def admin_logout():
    session.clear()
    return jsonify({"success": True, "message": "Logged out successfully."})


def require_admin_api():
    if "admin_id" not in session:
        return jsonify({"success": False, "error": "Admin login required."}), 401
    return None


# =========================================================
# MENU API
# =========================================================

@app.get("/api/menu")
def get_menu():
    response = (
        supabase.table("menu_items")
        .select("id,name,category,price,description,image_url,available,popular,created_at")
        .order("id", desc=True)
        .execute()
    )
    return jsonify(rows(response))


@app.post("/api/menu")
def create_menu_item():
    auth_error = require_admin_api()
    if auth_error:
        return auth_error

    data = request.get_json(silent=True) or {}
    name = str(data.get("name", "")).strip()
    category = str(data.get("category", "")).strip()
    description = str(data.get("description", "")).strip()
    image_url = str(data.get("image_url", "")).strip()

    try:
        price = float(data.get("price", 0))
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "Invalid price."}), 400

    available = bool(data.get("available", True))
    popular = bool(data.get("popular", False))

    if not name or not category or price < 0:
        return jsonify({
            "success": False,
            "error": "Name, category and valid price are required."
        }), 400

    response = supabase.table("menu_items").insert({
        "name": name,
        "category": category,
        "price": price,
        "description": description,
        "image_url": image_url,
        "available": available,
        "popular": popular,
    }).execute()

    item = one(response)
    return jsonify({
        "success": True,
        "message": "Menu item created.",
        "id": item["id"] if item else None,
    }), 201


@app.patch("/api/menu/<int:item_id>")
def update_menu_item(item_id):
    auth_error = require_admin_api()
    if auth_error:
        return auth_error

    data = request.get_json(silent=True) or {}
    allowed_fields = {
        "name", "category", "price", "description",
        "image_url", "available", "popular"
    }
    payload = {}

    for field, value in data.items():
        if field not in allowed_fields:
            continue
        if field in {"available", "popular"}:
            payload[field] = bool(value)
        elif field == "price":
            try:
                payload[field] = float(value)
            except (TypeError, ValueError):
                return jsonify({"success": False, "error": "Invalid price."}), 400
        else:
            payload[field] = str(value).strip()

    if not payload:
        return jsonify({"success": False, "error": "Nothing to update."}), 400

    response = supabase.table("menu_items").update(payload).eq("id", item_id).execute()
    if not rows(response):
        return jsonify({"success": False, "error": "Menu item not found."}), 404

    return jsonify({"success": True, "message": "Menu item updated."})


@app.delete("/api/menu/<int:item_id>")
def delete_menu_item(item_id):
    auth_error = require_admin_api()
    if auth_error:
        return auth_error

    response = supabase.table("menu_items").delete().eq("id", item_id).execute()
    if not rows(response):
        return jsonify({"success": False, "error": "Menu item not found."}), 404

    return jsonify({"success": True, "message": "Menu item deleted."})


# =========================================================
# CUSTOMER HELPER
# =========================================================

def save_customer(name, phone):
    """Create customer if the phone number does not already exist."""
    existing = one(
        supabase.table("customers")
        .select("id")
        .eq("phone", phone)
        .limit(1)
        .execute()
    )
    if not existing:
        supabase.table("customers").insert({"name": name, "phone": phone}).execute()


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
    occasion = str(data.get("occasion", "")).strip()
    special_request = str(data.get("special_request", data.get("request", ""))).strip()

    raw_guests = data.get("guests", 1)
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
        return jsonify({
            "success": False,
            "message": "Name, phone, date, time and guests are required."
        }), 400

    try:
        save_customer(name, phone)
        response = supabase.table("bookings").insert({
            "customer_name": name,
            "phone": phone,
            "booking_date": booking_date,
            "booking_time": booking_time,
            "guests": guests,
            "occasion": occasion,
            "special_request": special_request,
            "status": "pending",
        }).execute()
        booking = one(response)
    except Exception as exc:
        return jsonify({
            "success": False,
            "message": f"Could not save booking: {exc}"
        }), 500

    return jsonify({
        "success": True,
        "message": "Booking received successfully.",
        "booking_id": booking["id"] if booking else None,
    }), 201


@app.get("/api/bookings")
def get_bookings():
    auth_error = require_admin_api()
    if auth_error:
        return auth_error

    response = (
        supabase.table("bookings")
        .select("id,customer_name,phone,booking_date,booking_time,guests,occasion,special_request,status,created_at")
        .order("id", desc=True)
        .execute()
    )
    return jsonify(rows(response))


@app.patch("/api/bookings/<int:booking_id>")
def update_booking(booking_id):
    auth_error = require_admin_api()
    if auth_error:
        return auth_error

    data = request.get_json(silent=True) or {}
    status = str(data.get("status", "")).strip().lower()
    allowed = {"pending", "confirmed", "seated", "completed", "cancelled"}

    if status not in allowed:
        return jsonify({"success": False, "error": "Invalid booking status."}), 400

    response = supabase.table("bookings").update({"status": status}).eq("id", booking_id).execute()
    if not rows(response):
        return jsonify({"success": False, "error": "Booking not found."}), 404

    return jsonify({"success": True, "message": "Booking status updated."})


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
        return jsonify({
            "success": False,
            "message": "Customer details and order items are required."
        }), 400

    try:
        save_customer(name, phone)
        response = supabase.table("orders").insert({
            "customer_name": name,
            "phone": phone,
            "items_json": json.dumps(items, ensure_ascii=False),
            "total": total,
            "status": "pending",
        }).execute()
        order = one(response)
    except Exception as exc:
        return jsonify({
            "success": False,
            "message": f"Could not save order: {exc}"
        }), 500

    return jsonify({
        "success": True,
        "message": "Order received successfully.",
        "order_id": order["id"] if order else None,
    }), 201


@app.get("/api/orders")
def get_orders():
    auth_error = require_admin_api()
    if auth_error:
        return auth_error

    response = (
        supabase.table("orders")
        .select("id,customer_name,phone,items_json,total,status,created_at")
        .order("id", desc=True)
        .execute()
    )

    result = []
    for row in rows(response):
        item = dict(row)
        try:
            item["items"] = json.loads(item.pop("items_json"))
        except (TypeError, ValueError, json.JSONDecodeError):
            item["items"] = []
            item.pop("items_json", None)
        result.append(item)

    return jsonify(result)


@app.patch("/api/orders/<int:order_id>")
def update_order(order_id):
    auth_error = require_admin_api()
    if auth_error:
        return auth_error

    data = request.get_json(silent=True) or {}
    status = str(data.get("status", "")).strip().lower()
    allowed = {"pending", "confirmed", "preparing", "ready", "completed", "cancelled"}

    if status not in allowed:
        return jsonify({"success": False, "error": "Invalid order status."}), 400

    response = supabase.table("orders").update({"status": status}).eq("id", order_id).execute()
    if not rows(response):
        return jsonify({"success": False, "error": "Order not found."}), 404

    return jsonify({"success": True, "message": "Order status updated."})


# =========================================================
# DASHBOARD API
# =========================================================

@app.get("/api/dashboard")
def dashboard_data():
    auth_error = require_admin_api()
    if auth_error:
        return auth_error

    bookings = rows(
        supabase.table("bookings")
        .select("id,customer_name,phone,booking_date,booking_time,guests,occasion,special_request,status,created_at")
        .order("id", desc=True)
        .execute()
    )
    orders = rows(
        supabase.table("orders")
        .select("id,customer_name,phone,items_json,total,status,created_at")
        .order("id", desc=True)
        .execute()
    )
    customers = rows(supabase.table("customers").select("id").execute())
    menu_items = rows(supabase.table("menu_items").select("id,available").execute())

    today = date.today().isoformat()
    today_bookings = [b for b in bookings if b.get("booking_date") == today]
    pending_bookings = [b for b in bookings if b.get("status") == "pending"]
    new_orders = [o for o in orders if o.get("status") == "pending"]
    available_menu_items = [m for m in menu_items if m.get("available") is True]

    recent_orders = []
    for row in orders[:10]:
        item = dict(row)
        try:
            item["items"] = json.loads(item.pop("items_json"))
        except (TypeError, ValueError, json.JSONDecodeError):
            item["items"] = []
            item.pop("items_json", None)
        recent_orders.append(item)

    return jsonify({
        "success": True,
        "stats": {
            "today_bookings": len(today_bookings),
            "pending_bookings": len(pending_bookings),
            "total_bookings": len(bookings),
            "new_orders": len(new_orders),
            "total_orders": len(orders),
            "total_customers": len(customers),
            "total_menu_items": len(menu_items),
            "available_menu_items": len(available_menu_items),
        },
        "recent_bookings": bookings[:10],
        "recent_orders": recent_orders,
    })


# =========================================================
# CUSTOMERS API
# =========================================================

@app.get("/api/customers")
def get_customers():
    auth_error = require_admin_api()
    if auth_error:
        return auth_error

    customers = rows(
        supabase.table("customers")
        .select("id,name,phone,created_at")
        .order("id", desc=True)
        .execute()
    )
    orders = rows(
        supabase.table("orders")
        .select("id,phone,total,created_at")
        .execute()
    )
    bookings = rows(
        supabase.table("bookings")
        .select("id,phone,created_at")
        .execute()
    )

    result = []
    for customer in customers:
        phone = customer.get("phone")
        customer_orders = [o for o in orders if o.get("phone") == phone]
        customer_bookings = [b for b in bookings if b.get("phone") == phone]
        activities = [x.get("created_at") for x in customer_orders + customer_bookings if x.get("created_at")]
        result.append({
            "id": customer["id"],
            "name": customer["name"],
            "phone": phone,
            "orders_count": len(customer_orders),
            "bookings_count": len(customer_bookings),
            "total_spend": sum(float(o.get("total") or 0) for o in customer_orders),
            "last_activity": max(activities) if activities else customer.get("created_at"),
        })

    return jsonify(result)


# =========================================================
# REVIEWS API
# =========================================================

@app.get("/api/reviews")
def get_reviews():
    response = (
        supabase.table("reviews")
        .select("id,customer_name,rating,review_text,created_at")
        .order("id", desc=True)
        .execute()
    )
    return jsonify(rows(response))


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
        return jsonify({
            "success": False,
            "error": "Name, review and rating from 1 to 5 are required."
        }), 400

    response = supabase.table("reviews").insert({
        "customer_name": name,
        "rating": rating,
        "review_text": review_text,
    }).execute()
    review = one(response)

    return jsonify({
        "success": True,
        "message": "Review added successfully.",
        "review_id": review["id"] if review else None,
    }), 201


# =========================================================
# START SERVER
# =========================================================

if __name__ == "__main__":
    print("==============================================")
    print(" The Flavour - Flask backend is running")
    print("==============================================")
    print(" Website   : http://127.0.0.1:5000")
    print(" Health    : http://127.0.0.1:5000/api/health")
    print(" Admin     : http://127.0.0.1:5000/admin_login.html")
    print(" Dashboard : http://127.0.0.1:5000/admin_dashboard.html")
    print(" Database  : Supabase PostgreSQL")
    print("==============================================")
    app.run(debug=True)
