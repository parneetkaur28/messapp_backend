# app.py

from flask import Flask, render_template, request, redirect, session, flash, jsonify, url_for
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from flask_dance.contrib.google import make_google_blueprint, google
from sqlalchemy import extract
from datetime import datetime
import qrcode
import io
import base64
import os
from dotenv import load_dotenv
from calendar import monthrange

load_dotenv()

print("Connecting to DB:", os.getenv("DATABASE_URL"))

app = Flask(__name__)
from flask_cors import CORS
CORS(app, supports_credentials=True)
app.secret_key = os.getenv("SECRET_KEY")
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv("DATABASE_URL")
db = SQLAlchemy(app)

# ------------------ DATABASE MODELS ------------------
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100))
    email = db.Column(db.String(100), unique=True)
    password = db.Column(db.String(100))
    phone = db.Column(db.String(20))
    hostel_rollno = db.Column(db.String(50))
    role = db.Column(db.String(10))

class MealLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    meal_type = db.Column(db.String(10))
    date_time = db.Column(db.DateTime, default=datetime.utcnow)
    token = db.Column(db.String(300))

class Feedback(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    message = db.Column(db.Text)
    submitted_at = db.Column(db.DateTime, default=datetime.utcnow)

class Complaint(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    message = db.Column(db.Text)
    submitted_at = db.Column(db.DateTime, default=datetime.utcnow)

# ------------------ GOOGLE OAUTH ------------------
google_bp = make_google_blueprint(
    client_id=os.getenv("GOOGLE_CLIENT_ID"),
    client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
    scope=["profile", "email"],
    redirect_url="/google_login"
)
app.register_blueprint(google_bp, url_prefix="/login")

@app.route("/google_login")
def google_login():
    if not google.authorized:
        return redirect(url_for("google.login"))

    resp = google.get("/oauth2/v2/userinfo")
    assert resp.ok, resp.text
    info = resp.json()
    email = info["email"]
    name = info["name"]
    user = User.query.filter_by(email=email).first()
    if not user:
        user = User(name=name, email=email, password="", phone="", role="student")
        db.session.add(user)
        db.session.commit()
    session["user_id"] = user.id
    session["role"] = user.role
    return redirect("/dashboard")

@app.route('/')
def home():
    return redirect('/login')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        role = request.form['role']
        name = request.form['name']
        email = request.form['email']
        password = request.form['password']
        phone = request.form['phone']
        hostel_rollno = request.form['hostel_rollno']
        user = User(role=role, name=name, email=email, password=password, phone=phone ,hostel_rollno=hostel_rollno)
        db.session.add(user)
        db.session.commit()
        print("Saving user to DB:", name, email)
        return redirect('/login')
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        user = User.query.filter_by(email=email, password=password).first()
        if user:
            session['user_id'] = user.id
            session['role'] = user.role
            if user.role == 'student':
                return redirect('/student_home')
            else:
                return redirect('/dashboard')
        flash('Invalid credentials')
    return render_template('login.html')

@app.route('/student_home')
def student_home():
    if 'user_id' not in session or session['role'] != 'student':
        return redirect('/login')
    user = User.query.get(session['user_id'])
    return render_template('home_student.html', user=user)

@app.route('/dashboard')
def dashboard():
    user = User.query.get(session['user_id'])
    role = session.get('role')

    selected_month = request.args.get("month")
    now = datetime.now()
    if selected_month:
        year, month = map(int, selected_month.split('-'))
    else:
        year, month = now.year, now.month
        selected_month = f"{year}-{month:02}"

    if role == 'student':
        meals = MealLog.query.filter(
            MealLog.user_id == user.id,
            extract('year', MealLog.date_time) == year,
            extract('month', MealLog.date_time) == month
        ).all()

        complaints = Complaint.query.filter_by(user_id=user.id).order_by(Complaint.submitted_at.desc()).all()
        meal_map = {}
        bill = 0
        for meal in meals:
            day_str = meal.date_time.strftime("%Y-%m-%d")
            weekday = meal.date_time.weekday()  # Monday=0 ... Sunday=6
            if day_str not in meal_map:
                meal_map[day_str] = []
            meal_map[day_str].append(meal.meal_type)

            if meal.meal_type == 'dinner' and weekday in [1, 2, 3]:  # Tue, Wed, Thu
                bill += 47
            else:
                bill += 41

        days = monthrange(year, month)[1]

        return render_template('student_dashboard.html',
                               user=user,
                               selected_month=selected_month,
                               meals=meals,
                               bill=bill,
                               meal_map=meal_map,
                               year=year,
                               month=month,
                               days=days,
                               datetime=datetime,
                               complaints=complaints)
    else:
        students = User.query.filter_by(role='student').all()
        student_data = []

        for student in students:
            meals = MealLog.query.filter_by(user_id=student.id).filter(
                extract('month', MealLog.date_time) == month,
                extract('year', MealLog.date_time) == year
            ).all()

            count = len(meals)
            bill = 0
            for meal in meals:
                weekday = meal.date_time.weekday()  # Monday=0, Tuesday=1, ...
                if meal.meal_type == 'dinner' and weekday in [1, 2, 3]:  # Tue, Wed, Thu
                    bill += 47
                else:
                    bill += 41

            student_data.append({
                "name": student.name,
                "hostel_rollno": student.hostel_rollno,
                "count": count,
                "bill": bill
            })


        return render_template(
            'admin_dashboard.html',
            student_data=student_data,
            selected_month=f"{year}-{month:02}"
        )


@app.route('/add_meal/<meal_type>')
def add_meal(meal_type):
    user = User.query.get(session['user_id'])
    now = datetime.now()
    token_data = {
        "name": user.name,
        "phone": user.phone,
        "meal": meal_type,
        "date": now.strftime("%Y-%m-%d"),
        "time": now.strftime("%H:%M:%S")
    }
    qr_content = '|'.join(f"{k}:{v}" for k, v in token_data.items())
    qr = qrcode.make(qr_content)
    buf = io.BytesIO()
    qr.save(buf)
    image_base64 = base64.b64encode(buf.getvalue()).decode("ascii")

    meal_log = MealLog(user_id=user.id, meal_type=meal_type, date_time=now, token=qr_content)
    db.session.add(meal_log)
    db.session.commit()

    return render_template('qr_display.html', qr_code=image_base64, token=token_data)



@app.route('/validate_qr', methods=['POST'])
def validate_qr():
    content = request.json.get('qr_data')

    existing = MealLog.query.filter_by(token=content).first()
    if existing:
        user = User.query.get(existing.user_id)
        return jsonify({
            "status": "duplicate",
            "message": "Meal already logged.",
            "role": user.role if user else None
        })

    try:
        token_parts = dict(part.split(":", 1) for part in content.split("|"))
        phone = token_parts.get("phone")
        meal_type = token_parts.get("meal")
        date = token_parts.get("date")
        time = token_parts.get("time")
    except:
        return jsonify({"status": "invalid", "message": "Invalid QR structure."})

    user = User.query.filter_by(phone=phone).first()
    if not user:
        return jsonify({"status": "invalid", "message": "User not found."})

    dt_obj = datetime.strptime(f"{date} {time}", "%Y-%m-%d %H:%M:%S")
    new_log = MealLog(user_id=user.id, meal_type=meal_type, date_time=dt_obj, token=content)
    db.session.add(new_log)
    db.session.commit()

    return jsonify({
        "status": "valid",
        "message": f"Meal logged for {user.name}",
        "name": user.name,
        "meal": meal_type,
        "datetime": dt_obj.strftime("%Y-%m-%d %H:%M:%S"),
        "role": user.role
    })


@app.route('/qr_scanner')
def qr_scanner():
    if session.get('role') != 'admin':
        return redirect('/login')
    return render_template('qr_scanner.html')

@app.route('/feedback', methods=['GET', 'POST'])
def feedback():
    if request.method == 'POST':
        fb = Feedback(user_id=session['user_id'], message=request.form['message'])
        db.session.add(fb)
        db.session.commit()
        flash("Feedback submitted")
        return redirect('/dashboard')
    return render_template('feedback.html')

@app.route('/complaints', methods=['GET', 'POST'])
def complaints():
    if request.method == 'POST':
        comp = Complaint(user_id=session['user_id'], message=request.form['message'])
        db.session.add(comp)
        db.session.commit()
        flash("Complaint submitted")
        return redirect('/dashboard')
    return render_template('complaints.html')

@app.route('/admin/feedbacks')
def admin_feedbacks():
    feedbacks = Feedback.query.order_by(Feedback.submitted_at.desc()).all()
    return render_template('admin_feedbacks.html', feedbacks=feedbacks)

@app.route('/admin/complaints')
def admin_complaints():
    complaints = Complaint.query.order_by(Complaint.submitted_at.desc()).all()
    return render_template('admin_complaints.html', complaints=complaints)


if __name__ == "__main__":
    app.run(debug=True)