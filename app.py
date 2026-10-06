import os
from functools import wraps

from flask import Flask, request, jsonify, session
from flask_cors import CORS
from database import db, Item, AdminSetting


app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-this-secret-key")

# Use DATABASE_URL when provided; otherwise use a local SQLite database.
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
    "DATABASE_URL",
    "sqlite:///findhub.db",
)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

# Allows the frontend to call this backend.
# For production, restrict origins to your real frontend URL.
CORS(app, supports_credentials=True)

db.init_app(app)


# ---------------------------------------------------------
# DATABASE INITIALIZATION
# ---------------------------------------------------------

def init_database():
    with app.app_context():
        db.create_all()

        admin_pass = AdminSetting.query.filter_by(key="password").first()
        if not admin_pass:
            default_password = os.environ.get("ADMIN_PASSWORD", "ian2004")
            db.session.add(
                AdminSetting(key="password", value=default_password)
            )
            db.session.commit()


init_database()


# ---------------------------------------------------------
# HELPERS
# ---------------------------------------------------------

def get_json_data():
    """Safely return JSON request data as a dictionary."""
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def admin_required(view):
    """Protect admin-only endpoints."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("is_admin"):
            return jsonify({
                "success": False,
                "message": "Admin authentication required.",
            }), 401
        return view(*args, **kwargs)

    return wrapped


# ---------------------------------------------------------
# ITEMS
# ---------------------------------------------------------

@app.route("/api/items", methods=["GET"])
def get_items():
    try:
        items = Item.query.order_by(Item.id.desc()).all()
        return jsonify([item.to_dict() for item in items]), 200
    except Exception:
        app.logger.exception("Unable to load items")
        return jsonify({
            "success": False,
            "message": "Unable to load items.",
        }), 500


@app.route("/api/items", methods=["POST"])
def add_item():
    # Supports both application/json and multipart/form-data.
    if request.is_json:
        data = get_json_data()
    else:
        data = request.form.to_dict()

    required = [
        "userRole",
        "title",
        "type",
        "category",
        "location",
        "date",
        "description",
        "contact",
    ]

    missing = [
        field for field in required
        if not str(data.get(field, "")).strip()
    ]

    if missing:
        return jsonify({
            "success": False,
            "message": "Please complete all required fields.",
            "missing": missing,
        }), 400

    item_type = str(data["type"]).strip().upper()
    if item_type not in {"LOST", "FOUND"}:
        return jsonify({
            "success": False,
            "message": "Item type must be LOST or FOUND.",
        }), 400

    image_value = data.get("image")
    if not image_value and "image" in request.files:
        # The current model expects an image field. This accepts a filename
        # when using multipart uploads; real file storage can be added later.
        image_file = request.files["image"]
        if image_file and image_file.filename:
            image_value = image_file.filename

    try:
        new_item = Item(
            user_role=str(data["userRole"]).strip(),
            title=str(data["title"]).strip(),
            item_type=item_type,
            category=str(data["category"]).strip(),
            location=str(data["location"]).strip(),
            date=str(data["date"]).strip(),
            description=str(data["description"]).strip(),
            contact=str(data["contact"]).strip(),
            image=image_value,
        )

        # Optional model fields. These won't break if your Item model does
        # not contain them.
        if hasattr(new_item, "turnover_location"):
            new_item.turnover_location = (
                data.get("turnoverLocation")
                or data.get("turnover_location")
            )

        if hasattr(new_item, "secret_question"):
            new_item.secret_question = (
                data.get("secretQuestion")
                or data.get("secret_question")
            )

        db.session.add(new_item)
        db.session.commit()

        return jsonify(new_item.to_dict()), 201

    except Exception:
        db.session.rollback()
        app.logger.exception("Unable to add item")
        return jsonify({
            "success": False,
            "message": "Unable to save the item.",
        }), 500


# ---------------------------------------------------------
# CLAIMS
# ---------------------------------------------------------

@app.route("/api/items/<int:item_id>/claim", methods=["POST"])
def submit_claim(item_id):
    data = get_json_data()
    item = Item.query.get(item_id)

    if not item:
        return jsonify({
            "success": False,
            "message": "Item not found.",
        }), 404

    if str(getattr(item, "item_type", "")).upper() != "FOUND":
        return jsonify({
            "success": False,
            "message": "Only found items can be claimed.",
        }), 400

    contact = str(data.get("contact", "")).strip()
    notes = str(data.get("notes", "")).strip()

    if not contact:
        return jsonify({
            "success": False,
            "message": "Contact information is required.",
        }), 400

    try:
        item.claim_pending = True
        item.claim_contact = contact
        item.claim_notes = notes
        db.session.commit()

        return jsonify(item.to_dict()), 200
    except Exception:
        db.session.rollback()
        app.logger.exception("Unable to submit claim")
        return jsonify({
            "success": False,
            "message": "Unable to submit claim.",
        }), 500


@app.route("/api/items/<int:item_id>/approve-claim", methods=["DELETE"])
@admin_required
def approve_claim(item_id):
    item = Item.query.get(item_id)

    if not item:
        return jsonify({
            "success": False,
            "message": "Item not found.",
        }), 404

    if not getattr(item, "claim_pending", False):
        return jsonify({
            "success": False,
            "message": "There is no pending claim for this item.",
        }), 400

    try:
        db.session.delete(item)
        db.session.commit()
        return jsonify({
            "success": True,
            "message": "Claim approved and item resolved.",
        }), 200
    except Exception:
        db.session.rollback()
        app.logger.exception("Unable to approve claim")
        return jsonify({
            "success": False,
            "message": "Unable to approve claim.",
        }), 500


@app.route("/api/items/<int:item_id>/reject-claim", methods=["POST"])
@admin_required
def reject_claim(item_id):
    item = Item.query.get(item_id)

    if not item:
        return jsonify({
            "success": False,
            "message": "Item not found.",
        }), 404

    try:
        item.claim_pending = False
        item.claim_contact = None
        item.claim_notes = None
        db.session.commit()
        return jsonify(item.to_dict()), 200
    except Exception:
        db.session.rollback()
        app.logger.exception("Unable to reject claim")
        return jsonify({
            "success": False,
            "message": "Unable to reject claim.",
        }), 500


@app.route("/api/items/<int:item_id>", methods=["DELETE"])
@admin_required
def delete_item(item_id):
    item = Item.query.get(item_id)

    if not item:
        return jsonify({
            "success": False,
            "message": "Item not found.",
        }), 404

    try:
        db.session.delete(item)
        db.session.commit()
        return jsonify({
            "success": True,
            "message": "Item deleted.",
        }), 200
    except Exception:
        db.session.rollback()
        app.logger.exception("Unable to delete item")
        return jsonify({
            "success": False,
            "message": "Unable to delete item.",
        }), 500


# ---------------------------------------------------------
# ADMIN AUTHENTICATION
# ---------------------------------------------------------

@app.route("/api/admin/login", methods=["POST"])
@app.route("/api/admin/verify", methods=["POST"])
def admin_login():
    data = get_json_data()
    entered_password = str(data.get("password", ""))

    admin_pass = AdminSetting.query.filter_by(key="password").first()

    if admin_pass and admin_pass.value == entered_password:
        session["is_admin"] = True
        return jsonify({
            "success": True,
            "message": "Login successful.",
        }), 200

    session.pop("is_admin", None)
    return jsonify({
        "success": False,
        "message": "Incorrect password.",
    }), 401


@app.route("/api/admin/change-password", methods=["POST"])
@admin_required
def change_password():
    data = get_json_data()

    current_password = str(data.get("currentPassword", ""))
    new_password = str(data.get("newPassword", ""))

    if not new_password:
        return jsonify({
            "success": False,
            "message": "New password is required.",
        }), 400

    if len(new_password) < 6:
        return jsonify({
            "success": False,
            "message": "New password must be at least 6 characters.",
        }), 400

    admin_pass = AdminSetting.query.filter_by(key="password").first()

    if not admin_pass:
        return jsonify({
            "success": False,
            "message": "Admin password setting was not found.",
        }), 500

    if admin_pass.value != current_password:
        return jsonify({
            "success": False,
            "message": "Current password is incorrect.",
        }), 400

    try:
        admin_pass.value = new_password
        db.session.commit()
        return jsonify({
            "success": True,
            "message": "Password updated successfully.",
        }), 200
    except Exception:
        db.session.rollback()
        app.logger.exception("Unable to change admin password")
        return jsonify({
            "success": False,
            "message": "Unable to update password.",
        }), 500


@app.route("/api/admin/logout", methods=["POST"])
def admin_logout():
    session.pop("is_admin", None)
    return jsonify({
        "success": True,
        "message": "Admin logged out.",
    }), 200


# ---------------------------------------------------------
# HEALTH CHECK
# ---------------------------------------------------------

@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({
        "success": True,
        "message": "SLSU FindHub API is running.",
    }), 200


# ---------------------------------------------------------
# ERROR HANDLERS
# ---------------------------------------------------------

@app.errorhandler(404)
def not_found(_error):
    return jsonify({
        "success": False,
        "message": "Endpoint or item not found.",
    }), 404


@app.errorhandler(413)
def too_large(_error):
    return jsonify({
        "success": False,
        "message": "Uploaded file is too large. Maximum size is 5 MB.",
    }), 413


@app.errorhandler(500)
def internal_error(_error):
    try:
        db.session.rollback()
    except Exception:
        pass

    return jsonify({
        "success": False,
        "message": "Internal server error.",
    }), 500


# ---------------------------------------------------------
# START SERVER
# ---------------------------------------------------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
