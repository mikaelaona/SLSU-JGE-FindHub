import os
from flask import Flask, request, jsonify
from flask_cors import CORS
from database import db, Item, AdminSetting

app = Flask(_name_)
CORS(app) # Binibigyan ng permiso ang frontend na kumonekta sa backend API

# Kukunin nito ang DATABASE_URL mula sa Render Environment Variables
db_url = os.getenv('DATABASE_URL', 'sqlite:///app.db')
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)

# Initialize Database at Default Admin Password
with app.app_context():
    db.create_all()
    # Mag-set ng default password na "ian2004" kung wala pa
    admin_pass = AdminSetting.query.filter_by(key='password').first()
    if not admin_pass:
        default_pass = AdminSetting(key='password', value='ian2004')
        db.session.add(default_pass)
        db.session.commit()

# --- ROUTES & API ENDPOINTS ---

# 1. Kunin lahat ng items
@app.route('/api/items', methods=['GET'])
def get_items():
    items = Item.query.order_by(Item.id.desc()).all()
    return jsonify([item.to_dict() for item in items]), 200

# 2. Magdagdag ng bagong Loss/Found item
@app.route('/api/items', methods=['POST'])
def add_item():
    data = request.json
    new_item = Item(
        user_role=data.get('userRole'),
        title=data.get('title'),
        item_type=data.get('type'),
        category=data.get('category'),
        location=data.get('location'),
        date=data.get('date'),
        description=data.get('description'),
        contact=data.get('contact'),
        image=data.get('image')
    )
    db.session.add(new_item)
    db.session.commit()
    return jsonify(new_item.to_dict()), 201

# 3. Submit ng Claim Request (Regular User)
@app.route('/api/items/<int:item_id>/claim', methods=['POST'])
def submit_claim(item_id):
    data = request.json
    item = Item.query.get_or_404(item_id)
    
    item.claim_pending = True
    item.claim_contact = data.get('contact')
    item.claim_notes = data.get('notes')
    
    db.session.commit()
    return jsonify(item.to_dict()), 200

# 4. Approve Claim (Admin Only - buburahin ang item bilang resolved)
@app.route('/api/items/<int:item_id>/approve-claim', methods=['DELETE'])
def approve_claim(item_id):
    item = Item.query.get_or_404(item_id)
    db.session.delete(item)
    db.session.commit()
    return jsonify({"message": "Claim approved and item resolved"}), 200

# 5. Reject Claim (Admin Only - ibabalik sa normal state)
@app.route('/api/items/<int:item_id>/reject-claim', methods=['POST'])
def reject_claim(item_id):
    item = Item.query.get_or_404(item_id)
    item.claim_pending = False
    item.claim_contact = None
    item.claim_notes = None
    db.session.commit()
    return jsonify(item.to_dict()), 200

# 6. Direct Delete Item (Admin Only)
@app.route('/api/items/<int:item_id>', methods=['DELETE'])
def delete_item(item_id):
    item = Item.query.get_or_404(item_id)
    db.session.delete(item)
    db.session.commit()
    return jsonify({"message": "Item deleted"}), 200

# 7. Admin Login Check
@app.route('/api/admin/login', methods=['POST'])
def admin_login():
    data = request.json
    entered_password = data.get('password')
    admin_pass = AdminSetting.query.filter_by(key='password').first()
    
    if admin_pass and admin_pass.value == entered_password:
        return jsonify({"success": True, "message": "Login successful"}), 200
    return jsonify({"success": False, "message": "Incorrect password"}), 401

# 8. Change Admin Password
@app.route('/api/admin/change-password', methods=['POST'])
def change_password():
    data = request.json
    curr_pass = data.get('currentPassword')
    new_pass = data.get('newPassword')
    
    admin_pass = AdminSetting.query.filter_by(key='password').first()
    if admin_pass and admin_pass.value == curr_pass:
        admin_pass.value = new_pass
        db.session.commit()
        return jsonify({"success": True, "message": "Password updated successfully"}), 200
    
    return jsonify({"success": False, "message": "Current password incorrect"}), 400

if _name_ == '_main_':
    app.run(debug=True, port=5000)
