# app.py
# Interview app (Flask + SQLite) with:
# - candidate form + resume upload
# - HOD self-registration -> created inactive
# - HR account created at startup (password from env)
# - HR approves HODs (is_active=True) -> only then HOD can login
# - Excel export and email notifications via Gmail
#
# Requirements:
# pip install flask sqlalchemy openpyxl werkzeug

from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file, abort
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from datetime import datetime
from openpyxl import Workbook
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import io

# ------------------ CONFIG ------------------
app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET", "change_this_now")

# DB (single sqlite file)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///interview_app.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# Uploads
UPLOAD_FOLDER = os.path.join('static', 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
ALLOWED_EXTENSIONS = {'pdf', 'doc', 'docx'}
MAX_MB = 5
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = MAX_MB * 1024 * 1024

# Email config (use env vars)
EMAIL_SENDER = os.environ.get('EMAIL_SENDER', 'warulesuraj12@gmail.com')
HR_EMAIL = os.environ.get('HR_EMAIL', 'hr@accordhospitals.com')
EMAIL_PASSWORD = os.environ.get('EMAIL_PASSWORD') # gmail app password
HR_INIT_PASSWORD = os.environ.get('HR_INIT_PASSWORD', 'hr123') # initial HR password (change ASAP)

# ------------------ MODELS ------------------
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(180), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(20), nullable=False) # 'HR' or 'HOD'
    is_active = db.Column(db.Boolean, default=False) # HOD must be approved by HR to login
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Application(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    email = db.Column(db.String(200))
    dob = db.Column(db.String(50))
    phone = db.Column(db.String(20))
    current_address = db.Column(db.String(500))
    permanent_address = db.Column(db.String(500))
    position = db.Column(db.String(200))
    experience_summary = db.Column(db.String(200))
    notice_period = db.Column(db.String(50))
    last_salary = db.Column(db.String(50))
    expected_salary = db.Column(db.String(50))
    family_details_text = db.Column(db.Text)
    experience_details_text = db.Column(db.Text)
    resume_filename = db.Column(db.String(300))
    hod_remarks = db.Column(db.Text)
    hr_decision = db.Column(db.String(50))
    date_submitted = db.Column(db.DateTime, default=datetime.utcnow)

# ------------------ UTIL: Email ------------------
def send_email(to_email, subject, html_body):
    """Send an HTML email via Gmail using EMAIL_SENDER and EMAIL_PASSWORD env var."""
    if not EMAIL_PASSWORD:
        print("⚠️ EMAIL_PASSWORD not set. Email skipped.")
        return False
    try:
        msg = MIMEMultipart()
        msg['From'] = EMAIL_SENDER
        msg['To'] = to_email
        msg['Subject'] = subject
        msg.attach(MIMEText(html_body, 'html'))
        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.starttls()
            server.login(EMAIL_SENDER, EMAIL_PASSWORD)
            server.send_message(msg)
        print(f"✅ Email sent to {to_email}")
        return True
    except Exception as e:
        print("❌ Email error:", e)
        return False

# ------------------ HELPERS ------------------
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def create_tables_and_default_hr():
    """Create DB tables and ensure default HR user exists (is_active=True)."""
    db.create_all()
    hr = User.query.filter_by(role='HR').first()
    if hr is None:
        hashed = generate_password_hash(HR_INIT_PASSWORD)
        hr = User(email=HR_EMAIL, password_hash=hashed, role='HR', is_active=True)
        db.session.add(hr)
        db.session.commit()
        print(f"Created default HR user: {HR_EMAIL} (password from env or 'hr123')")

# ------------------ ROUTES ------------------
@app.route('/')
def candidate_form():
    return render_template('candidate_form.html')

@app.route('/submit', methods=['POST'])
def submit_application():
    form = request.form
    name = form.get('name','').strip()
    candidate_email = form.get('email','').strip()
    phone = form.get('phone','').strip()
    position = form.get('position','').strip()

    errors = []
    if not name: errors.append('Name is required.')
    if not candidate_email: errors.append('Email is required.')
    if not phone: errors.append('Phone is required.')
    if not position: errors.append('Position is required.')
    if phone and (not phone.isdigit() or len(phone) != 10): errors.append('Phone must be 10 digits.')

    resume = request.files.get('resume')
    if not resume or resume.filename == '':
        errors.append('Resume is required.')
    else:
        if not allowed_file(resume.filename):
            errors.append('Resume must be PDF, DOC or DOCX.')

    if errors:
        flash(' ; '.join(errors), 'error')
        return render_template('candidate_form.html', form_data=form, errors=errors)

    # optional fields
    dob = form.get('dob','').strip()
    current_address = form.get('current_address','').strip()
    permanent_address = form.get('permanent_address','').strip()
    experience_summary = form.get('experience','').strip()
    notice_period = form.get('notice_period','').strip()
    last_salary = form.get('last_salary','').strip()
    expected_salary = form.get('expected_salary','').strip()

    # family details
    fam_lines = []
    for i in range(1,4):
        n = form.get(f'family_name_{i}','').strip()
        rel = form.get(f'relationship_{i}','').strip()
        occ = form.get(f'occupation_{i}','').strip()
        other = form.get(f'other_{i}','').strip()
        if n or rel or occ or other:
            fam_lines.append(f"{i}. {n} | {rel} | {occ} | other: {other}")
    fam_text = "\n".join(fam_lines)

    # experience details
    exp_lines = []
    for i in range(1,4):
        org = form.get(f'org_{i}','').strip()
        role = form.get(f'role_{i}','').strip()
        tenure = form.get(f'tenure_{i}','').strip()
        reason = form.get(f'reason_{i}','').strip()
        if org or role or tenure or reason:
            exp_lines.append(f"{i}. {org} | {role} | {tenure} | reason: {reason}")
    exp_text = "\n".join(exp_lines)

    # save resume
    filename = secure_filename(resume.filename)
    prefix = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    save_name = f"{prefix}_{filename}"
    save_path = os.path.join(app.config['UPLOAD_FOLDER'], save_name)
    resume.save(save_path)

    app_row = Application(
        name=name, email=candidate_email, dob=dob, phone=phone,
        current_address=current_address, permanent_address=permanent_address,
        position=position, experience_summary=experience_summary,
        notice_period=notice_period, last_salary=last_salary, expected_salary=expected_salary,
        family_details_text=fam_text, experience_details_text=exp_text,
        resume_filename=save_name, hr_decision="Pending"
    )
    db.session.add(app_row)
    db.session.commit()

    # notify HR of new application
    hr_msg = f"<p>New application: <b>{name}</b> for <b>{position}</b>.</p><p>Login to HR dashboard to view resume and details.</p>"
    send_email(HR_EMAIL, f"New application: {name}", hr_msg)

    # ack candidate
    if candidate_email:
        body = f"<p>Dear {name},</p><p>Thank you for applying for <strong>{position}</strong>. We received your application on {app_row.date_submitted.strftime('%Y-%m-%d %H:%M')}.</p><p>Regards,<br>HR</p>"
        send_email(candidate_email, "Application Received - Accord Hospitals", body)

    return render_template('submitted.html', name=name)

# ------------------ Authentication ------------------
@app.route('/register', methods=['GET','POST'])
def register():
    # HOD self registration -> created inactive, HR must approve
    if request.method == 'POST':
        email = request.form.get('email','').strip().lower()
        password = request.form.get('password','').strip()
        if not email or not password:
            return "Email and password required", 400
        existing = User.query.filter_by(email=email).first()
        if existing:
            return "Account with this email already exists. Please login.", 400
        hashed = generate_password_hash(password)
        hod = User(email=email, password_hash=hashed, role='HOD', is_active=False)
        db.session.add(hod)
        db.session.commit()
        # notify HR about new HOD registration
        send_email(HR_EMAIL, "New HOD registration pending", f"<p>New HOD registered with email: {email}. Please review and approve in HR dashboard.</p>")
        return "Registration received. Await HR approval. Please wait for confirmation."
    return render_template('register.html')

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email','').strip().lower()
        password = request.form.get('password','').strip()
        user = User.query.filter_by(email=email).first()
        if not user or not user.check_password(password):
            return render_template('login.html', error="Invalid credentials.")
        # role check and activation
        if user.role == 'HOD' and not user.is_active:
            return render_template('login.html', error="Your account is awaiting HR approval. Please wait.")
        # login success
        session['user_email'] = user.email
        session['user_role'] = user.role
        if user.role == 'HR':
            return redirect(url_for('hr_dashboard'))
        else:
            return redirect(url_for('hod_dashboard'))
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# ------------------ HOD dashboard ------------------
@app.route('/hod', methods=['GET','POST'])
def hod_dashboard():
    if 'user_email' not in session or session.get('user_role') != 'HOD':
        return redirect(url_for('login'))
    if request.method == 'POST':
        candidate_name = request.form.get('candidate_name')
        remarks = request.form.get('remarks','').strip()
        update_success = False
        if candidate_name:
            update_success = update_hod_remarks(candidate_name, remarks, session.get('user_email'))
        if update_success:
            flash("Remarks saved.", "success")
        else:
            flash("Candidate not found.", "error")
        return redirect(url_for('hod_dashboard'))

    apps = Application.query.order_by(Application.date_submitted.desc()).all()
    candidates = []
    for a in apps:
        candidates.append({
            'name': a.name, 'position': a.position, 'phone': a.phone,
            'remarks': a.hod_remarks or '', 'resume_filename': a.resume_filename or '',
            'date': a.date_submitted.strftime('%Y-%m-%d')
        })
    return render_template('hod_dashboard.html', candidates=candidates, email=session.get('user_email'))

def update_hod_remarks(candidate_name, remarks, hod_email):
    a = Application.query.filter_by(name=candidate_name).first()
    if not a:
        return False
    timestamped = f"{remarks} (by {hod_email} at {datetime.utcnow().strftime('%Y-%m-%d %H:%M')})"
    a.hod_remarks = timestamped
    db.session.commit()
    send_email(HR_EMAIL, f"HOD Remarks added for {candidate_name}", f"<p>{timestamped}</p>")
    return True

# ------------------ HR dashboard ------------------
@app.route('/hr', methods=['GET','POST'])
def hr_dashboard():
    if 'user_email' not in session or session.get('user_role') != 'HR':
        return redirect(url_for('login'))

    # Handle HR actions: approve HOD or make decision on candidate
    if request.method == 'POST':
        # Approve HOD
        if 'approve_hod_email' in request.form:
            hod_email = request.form.get('approve_hod_email').strip().lower()
            user = User.query.filter_by(email=hod_email, role='HOD').first()
            if user:
                user.is_active = True
                db.session.commit()
                send_email(hod_email, "HOD account approved", f"<p>Your HOD account ({hod_email}) has been approved by HR. You can now login.</p>")
                flash(f"Approved HOD {hod_email}", "success")
            else:
                flash("HOD not found", "error")
            return redirect(url_for('hr_dashboard'))

        # HR decision on candidate
        if 'candidate_name' in request.form:
            candidate_name = request.form.get('candidate_name')
            decision = request.form.get('decision')
            if candidate_name and decision:
                update_hr_decision(candidate_name, decision)
            return redirect(url_for('hr_dashboard'))

    # Prepare lists
    apps = Application.query.order_by(Application.date_submitted.desc()).all()
    candidates = []
    for a in apps:
        candidates.append({
            'name': a.name, 'position': a.position, 'phone': a.phone,
            'remarks': a.hod_remarks or '', 'decision': a.hr_decision or 'Pending',
            'resume_filename': a.resume_filename or '', 'email': a.email or '', 'date': a.date_submitted.strftime('%Y-%m-%d')
        })

    pending_hods = User.query.filter_by(role='HOD', is_active=False).order_by(User.created_at.desc()).all()

    return render_template('hr_dashboard.html', candidates=candidates, pending_hods=pending_hods, email=session.get('user_email'))

def update_hr_decision(candidate_name, decision):
    a = Application.query.filter_by(name=candidate_name).first()
    if not a:
        return False
    a.hr_decision = decision
    db.session.commit()
    # notify candidate if email exists
    if a.email:
        if decision.lower() == 'approve':
            subj = "Accord Hospitals — Selected"
            body = f"<p>Dear {a.name},</p><p>Congratulations — you are selected. Please contact HR at {EMAIL_SENDER}.</p>"
        elif decision.lower() == 'reject':
            subj = "Accord Hospitals — Application Update"
            body = f"<p>Dear {a.name},</p><p>We regret to inform you that you were not selected.</p>"
        else:
            subj = "Accord Hospitals — Application On Hold"
            body = f"<p>Dear {a.name},</p><p>Your application is on hold. We will update you soon.</p>"
        send_email(a.email, subj, body)
    return True

# ------------------ Reset HOD password (HR only) ------------------
@app.route('/reset_password', methods=['POST'])
def reset_password():
    if 'user_email' not in session or session.get('user_role') != 'HR':
        return redirect(url_for('login'))
    email = request.form.get('email','').strip().lower()
    new_password = request.form.get('new_password','').strip()
    if not email or not new_password:
        return "Email and new password required", 400
    user = User.query.filter_by(email=email).first()
    if not user:
        return "User not found", 404
    user.password_hash = generate_password_hash(new_password)
    db.session.commit()
    return "Password updated successfully"

# ------------------ Export to Excel ------------------
@app.route('/export')
def export_excel():
    apps = Application.query.order_by(Application.date_submitted.desc()).all()
    wb = Workbook()
    ws = wb.active
    ws.title = "Applications"
    ws.append([
        "Name","Email","DOB","Phone","Current Address","Permanent Address",
        "Position","Experience Summary","Notice Period","Last Salary","Expected Salary",
        "Family Details","Experience Details","Resume Filename","HOD Remarks","HR Decision","Date Submitted"
    ])
    for a in apps:
        ws.append([
            a.name, a.email, a.dob, a.phone, a.current_address, a.permanent_address,
            a.position, a.experience_summary, a.notice_period, a.last_salary, a.expected_salary,
            a.family_details_text, a.experience_details_text, a.resume_filename, a.hod_remarks, a.hr_decision,
            a.date_submitted.strftime('%Y-%m-%d %H:%M')
        ])
    stream = io.BytesIO()
    wb.save(stream)
    stream.seek(0)
    return send_file(stream, as_attachment=True, download_name="interview_data.xlsx", mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

# ------------------ MAIN ------------------
if __name__ == '__main__':
    # create tables and default HR inside app context
    with app.app_context():
        create_tables_and_default_hr()
    # run
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT",5000)))