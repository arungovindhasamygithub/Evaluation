from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session, send_file
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
import openpyxl
from openpyxl import Workbook
import qrcode
from io import BytesIO
import base64
import json
from datetime import datetime
import os
import urllib.parse

app = Flask(__name__)

# Use your secret key
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', '5f4dcc3b5aa765d61d8327deb882cf992b95990a9151374abd3e4357b8fa88b2')

# Database configuration with better error handling
def get_database_url():
    # Check for Neon PostgreSQL URL (preferred for deployment)
    database_url = os.environ.get('DATABASE_URL') or os.environ.get('POSTGRES_URL') or os.environ.get('NEON_DATABASE_URL')
    
    if database_url:
        # Parse the URL and ensure it's properly formatted
        parsed_url = urllib.parse.urlparse(database_url)
        
        # For Neon/PostgreSQL, we need to use postgresql:// instead of postgres://
        if parsed_url.scheme == 'postgres':
            database_url = database_url.replace('postgres://', 'postgresql://', 1)
        
        print(f"Using PostgreSQL database: {parsed_url.hostname}")
        return database_url
    
    # Fallback to SQLite for local development with proper file path
    print("Using SQLite database for local development")
    # Use a writable directory
    db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'instance', 'database.db')
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    return f'sqlite:///{db_path}'

app.config['SQLALCHEMY_DATABASE_URI'] = get_database_url()
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Configure SQLAlchemy engine options
if 'postgresql' in app.config['SQLALCHEMY_DATABASE_URI']:
    # PostgreSQL/Neon specific settings
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'pool_recycle': 300,
        'pool_pre_ping': True,
        'connect_args': {
            'sslmode': 'require'
        }
    }
    print("Configured for PostgreSQL with SSL")
else:
    # SQLite specific settings
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'pool_recycle': 300,
        'pool_pre_ping': True,
        'connect_args': {
            'check_same_thread': False  # Allow multiple threads to use the same connection
        }
    }
    print("Configured for SQLite")

db = SQLAlchemy(app)

# Models - Updated for PostgreSQL compatibility
class Admin(db.Model):
    __tablename__ = 'admin'
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)

class Staff(db.Model):
    __tablename__ = 'staff'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    category = db.Column(db.String(50), nullable=False)  # robo_race, robo_sumo, working_model
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Student(db.Model):
    __tablename__ = 'student'
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.String(50), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    college = db.Column(db.String(100))
    phone = db.Column(db.String(20))
    category = db.Column(db.String(50))  # robo_race, robo_sumo, working_model
    qr_code = db.Column(db.Text)  # Base64 encoded QR code

class Evaluation(db.Model):
    __tablename__ = 'evaluation'
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.String(50), nullable=False)
    staff_id = db.Column(db.Integer, nullable=False)
    category = db.Column(db.String(50), nullable=False)
    score = db.Column(db.Float, nullable=False)
    max_score = db.Column(db.Float, nullable=False)
    criteria_scores = db.Column(db.Text)  # JSON string for criteria scores
    comments = db.Column(db.Text)
    evaluated_at = db.Column(db.DateTime, default=datetime.utcnow)

# Helper function for Excel validation
def validate_excel_data(row):
    """Validate and clean Excel row data"""
    if len(row) < 2:  # At least ID and Name
        return None
    
    # Clean data
    student_id = str(row[0]).strip() if row[0] else None
    name = str(row[1]).strip() if len(row) > 1 and row[1] else None
    
    # Validate required fields
    if not student_id or not name:
        return None
    
    # Check for invalid IDs
    if student_id.lower() in ['none', 'null', 'nan', '', 'id', 'student id']:
        return None
    
    # Clean other fields
    college = str(row[2]).strip() if len(row) > 2 and row[2] else ""
    phone = str(row[3]).strip() if len(row) > 3 and row[3] else ""
    
    # Process category
    category = None
    if len(row) > 4 and row[4]:
        cat_str = str(row[4]).strip().lower().replace(' ', '_')
        if cat_str in ['robo_race', 'robo_sumo', 'working_model']:
            category = cat_str
        elif 'race' in cat_str:
            category = 'robo_race'
        elif 'sumo' in cat_str:
            category = 'robo_sumo'
        elif 'working' in cat_str or 'model' in cat_str:
            category = 'working_model'
    
    return {
        'student_id': student_id,
        'name': name,
        'college': college,
        'phone': phone,
        'category': category
    }

# Create tables and admin user with better error handling
def init_database():
    with app.app_context():
        try:
            print(f"Initializing database: {app.config['SQLALCHEMY_DATABASE_URI'][:50]}...")
            db.create_all()
            
            # Test database connection
            db.session.execute('SELECT 1')
            print("Database connection successful!")
            
            # Create default admin if not exists
            if not Admin.query.first():
                admin = Admin(
                    email="admin@robotica.com",
                    password=generate_password_hash("admin123")
                )
                db.session.add(admin)
                db.session.commit()
                print("Default admin user created!")
                
        except Exception as e:
            print(f"Database initialization error: {e}")
            print("This might be normal if the database already exists.")
            db.session.rollback()
            try:
                # Try to create admin separately
                if not Admin.query.first():
                    admin = Admin(
                        email="admin@robotica.com",
                        password=generate_password_hash("admin123")
                    )
                    db.session.add(admin)
                    db.session.commit()
                    print("Default admin user created in separate transaction!")
            except Exception as e2:
                print(f"Could not create admin user: {e2}")

# Initialize database on startup
init_database()

# Routes
@app.route('/')
def home():
    if 'user_type' in session:
        if session['user_type'] == 'admin':
            return redirect(url_for('admin_dashboard'))
        else:
            return redirect(url_for('staff_dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        
        try:
            # Check admin
            admin = Admin.query.filter_by(email=email).first()
            if admin and check_password_hash(admin.password, password):
                session['user_id'] = admin.id
                session['user_type'] = 'admin'
                session['email'] = admin.email
                flash('Login successful!', 'success')
                return redirect(url_for('admin_dashboard'))
            
            # Check staff
            staff = Staff.query.filter_by(email=email).first()
            if staff and check_password_hash(staff.password, password):
                session['user_id'] = staff.id
                session['user_type'] = 'staff'
                session['email'] = staff.email
                session['category'] = staff.category
                flash('Login successful!', 'success')
                return redirect(url_for('staff_dashboard'))
            
            flash('Invalid credentials!', 'danger')
        except Exception as e:
            flash(f'Login error: {str(e)}', 'danger')
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('Logged out successfully!', 'info')
    return redirect(url_for('login'))

# Admin Routes
@app.route('/admin/dashboard')
def admin_dashboard():
    if 'user_type' not in session or session['user_type'] != 'admin':
        return redirect(url_for('login'))
    
    try:
        # Statistics
        total_students = Student.query.count()
        total_staff = Staff.query.count()
        total_evaluations = Evaluation.query.count()
        
        # Category-wise counts
        categories = ['robo_race', 'robo_sumo', 'working_model']
        category_counts = {}
        for cat in categories:
            category_counts[cat] = {
                'students': Student.query.filter_by(category=cat).count(),
                'staff': Staff.query.filter_by(category=cat).count(),
                'evaluations': Evaluation.query.filter_by(category=cat).count()
            }
    except Exception as e:
        flash(f'Error loading statistics: {str(e)}', 'danger')
        return render_template('admin_dashboard.html', 
                             total_students=0,
                             total_staff=0,
                             total_evaluations=0,
                             category_counts={})
    
    return render_template('admin_dashboard.html', 
                         total_students=total_students,
                         total_staff=total_staff,
                         total_evaluations=total_evaluations,
                         category_counts=category_counts)

@app.route('/admin/staff', methods=['GET', 'POST'])
def admin_staff():
    if 'user_type' not in session or session['user_type'] != 'admin':
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        try:
            name = request.form['name']
            email = request.form['email']
            password = request.form['password']
            category = request.form['category']
            
            if Staff.query.filter_by(email=email).first():
                flash('Staff email already exists!', 'danger')
            else:
                staff = Staff(
                    name=name,
                    email=email,
                    password=generate_password_hash(password),
                    category=category
                )
                db.session.add(staff)
                db.session.commit()
                flash('Staff created successfully!', 'success')
        except Exception as e:
            flash(f'Error creating staff: {str(e)}', 'danger')
    
    try:
        staff_list = Staff.query.all()
    except:
        staff_list = []
    
    return render_template('admin_staff.html', staff_list=staff_list)

@app.route('/admin/delete_staff/<int:id>')
def delete_staff(id):
    if 'user_type' not in session or session['user_type'] != 'admin':
        return redirect(url_for('login'))
    
    try:
        staff = Staff.query.get_or_404(id)
        db.session.delete(staff)
        db.session.commit()
        flash('Staff deleted successfully!', 'success')
    except Exception as e:
        flash(f'Error deleting staff: {str(e)}', 'danger')
    
    return redirect(url_for('admin_staff'))

@app.route('/admin/students', methods=['GET', 'POST'])
def admin_students():
    if 'user_type' not in session or session['user_type'] != 'admin':
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        if 'excel_file' in request.files:
            file = request.files['excel_file']
            if file.filename.endswith(('.xlsx', '.xls')):
                try:
                    workbook = openpyxl.load_workbook(file, data_only=True)
                    sheet = workbook.active
                    
                    added = 0
                    skipped = 0
                    duplicates = 0
                    errors = 0
                    
                    for idx, row in enumerate(sheet.iter_rows(min_row=2, values_only=True), start=2):
                        try:
                            # Skip empty rows
                            if not any(row):
                                skipped += 1
                                continue
                            
                            # Validate data
                            data = validate_excel_data(row)
                            if not data:
                                skipped += 1
                                continue
                            
                            # Check if student already exists
                            existing = Student.query.filter_by(student_id=data['student_id']).first()
                            if existing:
                                duplicates += 1
                                continue
                            
                            # Generate QR code
                            qr = qrcode.QRCode(
                                version=1,
                                error_correction=qrcode.constants.ERROR_CORRECT_L,
                                box_size=10,
                                border=4,
                            )
                            qr.add_data(data['student_id'])
                            qr.make(fit=True)
                            
                            img = qr.make_image(fill_color="black", back_color="white")
                            buffered = BytesIO()
                            img.save(buffered, format="PNG")
                            qr_base64 = base64.b64encode(buffered.getvalue()).decode()
                            
                            # Create student record
                            student = Student(
                                student_id=data['student_id'],
                                name=data['name'],
                                college=data['college'],
                                phone=data['phone'],
                                category=data['category'],
                                qr_code=qr_base64
                            )
                            
                            db.session.add(student)
                            added += 1
                            
                            # Commit in batches to avoid large transactions
                            if added % 50 == 0:
                                db.session.commit()
                                
                        except Exception as e:
                            errors += 1
                            print(f"Error processing row {idx}: {e}")
                            continue
                    
                    # Final commit
                    db.session.commit()
                    
                    flash(f'Successfully imported {added} students! {skipped} rows skipped. {duplicates} duplicates skipped. {errors} errors.', 'success')
                    
                except Exception as e:
                    db.session.rollback()
                    print(f"Import error details: {e}")
                    flash(f'Error importing file: {str(e)}', 'danger')
            else:
                flash('Please upload a valid Excel file (.xlsx or .xls)', 'warning')
    
    try:
        students = Student.query.order_by(Student.student_id).all()
    except Exception as e:
        students = []
        print(f"Error loading students: {e}")
    
    return render_template('admin_students.html', students=students)






@app.route('/admin/delete_student/<int:id>')
def delete_student(id):
    if 'user_type' not in session or session['user_type'] != 'admin':
        return redirect(url_for('login'))
    
    try:
        student = Student.query.get_or_404(id)
        db.session.delete(student)
        db.session.commit()
        flash('Student deleted successfully!', 'success')
    except Exception as e:
        flash(f'Error deleting student: {str(e)}', 'danger')
    
    return redirect(url_for('admin_students'))

@app.route('/admin/reports')
def admin_reports():
    if 'user_type' not in session or session['user_type'] != 'admin':
        return redirect(url_for('login'))
    
    category = request.args.get('category', 'all')
    
    try:
        # Get evaluations
        if category == 'all':
            evaluations = Evaluation.query.all()
        else:
            evaluations = Evaluation.query.filter_by(category=category).all()
        
        # Calculate statistics
        categories = ['robo_race', 'robo_sumo', 'working_model']
        stats = {}
        for cat in categories:
            cat_evals = Evaluation.query.filter_by(category=cat).all()
            if cat_evals:
                scores = [e.score for e in cat_evals]
                stats[cat] = {
                    'count': len(cat_evals),
                    'avg': sum(scores) / len(scores),
                    'max': max(scores),
                    'min': min(scores)
                }
            else:
                stats[cat] = {
                    'count': 0,
                    'avg': 0,
                    'max': 0,
                    'min': 0
                }
    except Exception as e:
        evaluations = []
        stats = {}
        flash(f'Error loading reports: {str(e)}', 'danger')
    
    return render_template('admin_reports.html', 
                         evaluations=evaluations,
                         category=category,
                         stats=stats)

@app.route('/admin/export')
def export_reports():
    if 'user_type' not in session or session['user_type'] != 'admin':
        return redirect(url_for('login'))
    
    category = request.args.get('category', 'all')
    
    try:
        if category == 'all':
            evaluations = Evaluation.query.all()
        else:
            evaluations = Evaluation.query.filter_by(category=category).all()
        
        # Create Excel workbook
        wb = Workbook()
        ws = wb.active
        ws.title = f"Evaluations_{category}"
        
        # Headers
        headers = ['Student ID', 'Staff ID', 'Category', 'Score', 'Max Score', 'Comments', 'Evaluated At']
        ws.append(headers)
        
        # Data
        for eval in evaluations:
            ws.append([
                eval.student_id,
                eval.staff_id,
                eval.category.replace('_', ' ').title(),
                eval.score,
                eval.max_score,
                eval.comments,
                eval.evaluated_at.strftime('%Y-%m-%d %H:%M:%S')
            ])
        
        # Save to BytesIO
        buffer = BytesIO()
        wb.save(buffer)
        buffer.seek(0)
        
        filename = f"robotica_evaluations_{category}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        return send_file(buffer, as_attachment=True, download_name=filename)
    except Exception as e:
        flash(f'Error exporting reports: {str(e)}', 'danger')
        return redirect(url_for('admin_reports'))

# Staff Routes
@app.route('/staff/dashboard')
def staff_dashboard():
    if 'user_type' not in session or session['user_type'] != 'staff':
        return redirect(url_for('login'))
    
    try:
        staff_id = session['user_id']
        category = session['category']
        
        # Get staff's evaluations
        evaluations = Evaluation.query.filter_by(staff_id=staff_id).all()
        total_evaluated = len(evaluations)
        
        # Get students in this category
        students_in_category = Student.query.filter_by(category=category).count()
    except Exception as e:
        evaluations = []
        total_evaluated = 0
        students_in_category = 0
        flash(f'Error loading dashboard: {str(e)}', 'danger')
    
    return render_template('staff_dashboard.html',
                         category=category,
                         total_evaluated=total_evaluated,
                         students_in_category=students_in_category,
                         evaluations=evaluations)

@app.route('/staff/evaluate', methods=['GET', 'POST'])
def staff_evaluate():
    if 'user_type' not in session or session['user_type'] != 'staff':
        return redirect(url_for('login'))
    
    staff_id = session['user_id']
    category = session['category']
    
    if request.method == 'POST':
        try:
            student_id = request.form['student_id']
            criteria_data = request.form.get('criteria_data', '{}')
            
            # Parse criteria data
            criteria = json.loads(criteria_data)
            total_score = sum(float(criteria[key]) for key in criteria)
            max_score = len(criteria) * 10  # Assuming each criteria max 10
            
            # Check if student exists in this category
            student = Student.query.filter_by(student_id=student_id).first()
            if not student:
                flash('Student not found!', 'danger')
                return redirect(url_for('staff_evaluate'))
            
            # Check if student belongs to staff's category
            if student.category != category:
                flash(f'Student belongs to {student.category.replace("_", " ").title()} category, not your assigned category!', 'danger')
                return redirect(url_for('staff_evaluate'))
            
            # Check if already evaluated by ANY staff (not just this staff)
            existing = Evaluation.query.filter_by(
                student_id=student_id,
                category=category
            ).first()
            
            if existing:
                flash('Student already evaluated! Re-evaluation is not allowed.', 'warning')
                return redirect(url_for('staff_evaluate'))
            
            evaluation = Evaluation(
                student_id=student_id,
                staff_id=staff_id,
                category=category,
                score=total_score,
                max_score=max_score,
                criteria_scores=criteria_data,
                comments=request.form.get('comments', '')
            )
            db.session.add(evaluation)
            db.session.commit()
            flash('Evaluation submitted successfully!', 'success')
        except Exception as e:
            flash(f'Error submitting evaluation: {str(e)}', 'danger')
        
        return redirect(url_for('staff_evaluate'))
    
    return render_template('staff_evaluate.html', category=category)

@app.route('/get_student/<student_id>')
def get_student(student_id):
    if 'user_type' not in session or session['user_type'] != 'staff':
        return jsonify({'exists': False})
    
    try:
        staff_category = session['category']
        student = Student.query.filter_by(student_id=student_id).first()
        
        if student:
            # Check if student belongs to staff's category
            if student.category != staff_category:
                return jsonify({
                    'exists': True,
                    'wrong_category': True,
                    'student_category': student.category.replace('_', ' ').title(),
                    'staff_category': staff_category.replace('_', ' ').title()
                })
            
            # Check if already evaluated
            evaluated = Evaluation.query.filter_by(
                student_id=student_id,
                category=staff_category
            ).first()
            
            return jsonify({
                'exists': True,
                'wrong_category': False,
                'name': student.name,
                'college': student.college,
                'phone': student.phone,
                'category': student.category,
                'already_evaluated': evaluated is not None
            })
    except Exception as e:
        return jsonify({'error': str(e), 'exists': False})
    
    return jsonify({'exists': False})

@app.route('/scanner')
def scanner():
    if 'user_type' not in session or session['user_type'] != 'staff':
        return redirect(url_for('login'))
    
    return render_template('scanner.html')

# Database test endpoint
@app.route('/test-db')
def test_db():
    try:
        # Test connection
        db.session.execute('SELECT 1')
        
        # Get counts
        admin_count = Admin.query.count()
        staff_count = Staff.query.count()
        student_count = Student.query.count()
        eval_count = Evaluation.query.count()
        
        return jsonify({
            'status': 'connected',
            'database': app.config['SQLALCHEMY_DATABASE_URI'][:50] + '...',
            'counts': {
                'admins': admin_count,
                'staff': staff_count,
                'students': student_count,
                'evaluations': eval_count
            }
        })
    except Exception as e:
        return jsonify({
            'status': 'error',
            'error': str(e),
            'database': app.config['SQLALCHEMY_DATABASE_URI'][:50] + '...'
        })

# Health check
@app.route('/health')
def health():
    try:
        db.session.execute('SELECT 1')
        db_status = 'connected'
    except Exception as e:
        db_status = f'error: {str(e)}'
    
    return jsonify({
        'status': 'ok', 
        'timestamp': datetime.now().isoformat(),
        'database': db_status
    })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'
    app.run(host='0.0.0.0', port=port, debug=debug)