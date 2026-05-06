from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, send_file
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3
import re
from io import BytesIO
from datetime import datetime
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable

app = Flask(__name__)
app.secret_key = 'admin'

USER_DB = 'users.db'



# Predefined list of chronic conditions
CHRONIC_CONDITIONS = [
    "Arthritis",
    "Asthma",
    "Celiac Disease",
    "Chronic Fatigue Syndrome",
    "Chronic Kidney Disease",
    "Chronic Pain Syndrome",
    "COPD",
    "Crohn's Disease",
    "Cystic Fibrosis",
    "Diabetes Type 1",
    "Diabetes Type 2",
    "Ehlers-Danlos Syndrome",
    "Endometriosis",
    "Epilepsy",
    "Fibromyalgia",
    "GERD",
    "Hashimoto's Thyroiditis",
    "Heart Disease",
    "Hepatitis",
    "HIV/AIDS",
    "Hypertension",
    "Inflammatory Bowel Disease",
    "Interstitial Cystitis",
    "Lupus",
    "Lyme Disease",
    "Migraines",
    "Multiple Sclerosis",
    "Myasthenia Gravis",
    "Osteoporosis",
    "Parkinson's Disease",
    "PCOS",
    "Psoriasis",
    "Raynaud's Disease",
    "Rheumatoid Arthritis",
    "Scleroderma",
    "Sickle Cell Disease",
    "Sjögren's Syndrome",
    "Sleep Apnea",
    "Ulcerative Colitis"
]



# Initialize the database
def init_databases():
    conn = sqlite3.connect(USER_DB)
    cursor = conn.cursor()

    # Users table
    cursor.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        first_name TEXT NOT NULL,
        last_name TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        date_of_birth DATE NOT NULL
    )''')

    # Migrate: rename illnesses table to conditions if it exists
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='illnesses'")
    if cursor.fetchone():
        cursor.execute('ALTER TABLE illnesses RENAME TO conditions')
        cursor.execute('ALTER TABLE conditions RENAME COLUMN illness_name TO condition_name')

    # Conditions table
    cursor.execute('''CREATE TABLE IF NOT EXISTS conditions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        condition_name TEXT NOT NULL,
        triggers TEXT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id)
    )''')


    # Flare Ups table
    cursor.execute('''CREATE TABLE IF NOT EXISTS flare_ups (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        begin_time DATETIME NOT NULL,
        end_time DATETIME NOT NULL,
        flareup_comment TEXT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id)
    )''')

    conn.commit()
    conn.close()
init_databases()





# Helper functions for database connections
def get_user_conn():
    return sqlite3.connect(USER_DB)


#_______________________ checks if the users personal information is valid _______________________
def is_valid_email(email):
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return isinstance(email, str) and re.match(pattern, email)

def is_valid_password(password):
    return isinstance(password, str) and len(password) >= 8 and re.search(r"[a-zA-Z]", password) and re.search(r"[0-9]", password)

def is_valid_name(name):
    return isinstance(name, str) and len(name.strip()) >= 1
#_______________________ end valid personal information _______________________




#_______________________ index page _______________________
@app.route('/')
def index():
    first_name = session.get('first_name')
    return render_template('index.html', first_name=first_name)
#_______________________ end index page _______________________




# _____________________ Log page _______________________
@app.route('/log')
def log():
    user_logs = []
    if session.get('user_id'):
        conn = get_user_conn()
        cursor = conn.cursor()
        cursor.execute(
            'SELECT id, begin_time, end_time, flareup_comment FROM flare_ups WHERE user_id = ?',
            (session['user_id'],)
        )
        rows = cursor.fetchall()
        user_logs = [(row[0], row[1], row[2], row[3] or '') for row in rows]
        conn.close()
    return render_template('log.html', user_logs=user_logs)

# handles the flare up logs into the database
@app.route('/log_flareups', methods=['POST'])
def log_flareups():
    if not session.get('user_id'):
        flash('Please sign in to log flare ups.', 'error')
        return redirect('/signup')

    begin_time = request.form.get('flare_up_begun')
    end_time = request.form.get('flare_up_end')
    comment = request.form.get('flareup_information', '')

    if not begin_time or not end_time:
        flash('Please provide both start and end times.', 'error')
        return redirect('/log')

    conn = get_user_conn()
    cursor = conn.cursor()
    cursor.execute(
        'INSERT INTO flare_ups (user_id, begin_time, end_time, flareup_comment) VALUES (?, ?, ?, ?)',
        (session['user_id'], begin_time, end_time, comment)
    )
    conn.commit()
    conn.close()

    flash('Flare up logged successfully!', 'success')
    return redirect('/log')
# _______________________ end log page _______________________



# _______________________ Summary page _______________________
@app.route('/summary')
def summary():
    if not session.get('user_id'):
        flash('Please sign in to view your summary.', 'error')
        return redirect('/signin')

    conn = get_user_conn()
    cursor = conn.cursor()

    # Get user info (excluding password)
    cursor.execute(
        'SELECT first_name, last_name, email, date_of_birth FROM users WHERE id = ?',
        (session['user_id'],)
    )
    user = cursor.fetchone()
    user_info = {
        'first_name': user[0],
        'last_name': user[1],
        'email': user[2],
        'date_of_birth': user[3]
    }

    # Get user conditions
    cursor.execute(
        'SELECT condition_name, triggers, created_at FROM conditions WHERE user_id = ? ORDER BY created_at',
        (session['user_id'],)
    )
    conditions = cursor.fetchall()

    # Get user flare ups
    cursor.execute(
        'SELECT begin_time, end_time, flareup_comment, created_at FROM flare_ups WHERE user_id = ? ORDER BY begin_time DESC',
        (session['user_id'],)
    )
    flare_ups = cursor.fetchall()
    conn.close()

    return render_template('summary.html', user_info=user_info, conditions=conditions, flare_ups=flare_ups)


@app.route('/download_summary')
def download_summary():
    if not session.get('user_id'):
        flash('Please sign in to download your summary.', 'error')
        return redirect('/signin')

    conn = get_user_conn()
    cursor = conn.cursor()

    # Get user info (excluding password)
    cursor.execute(
        'SELECT first_name, last_name, email, date_of_birth FROM users WHERE id = ?',
        (session['user_id'],)
    )
    user = cursor.fetchone()

    # Get user conditions
    cursor.execute(
        'SELECT condition_name, triggers, created_at FROM conditions WHERE user_id = ? ORDER BY created_at',
        (session['user_id'],)
    )
    conditions = cursor.fetchall()

    # Get user flare ups
    cursor.execute(
        'SELECT begin_time, end_time, flareup_comment FROM flare_ups WHERE user_id = ? ORDER BY begin_time DESC',
        (session['user_id'],)
    )
    flare_ups = cursor.fetchall()
    conn.close()

    # Create PDF in memory
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=72, leftMargin=72, topMargin=72, bottomMargin=72)

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=24,
        spaceAfter=30,
        alignment=1,
        textColor=colors.HexColor('#333333')
    )
    heading_style = ParagraphStyle(
        'CustomHeading',
        parent=styles['Heading2'],
        fontSize=16,
        spaceBefore=20,
        spaceAfter=10,
        textColor=colors.HexColor('#2c5282')
    )
    normal_style = styles['Normal']

    elements = []

    # Title
    elements.append(Paragraph("Health Summary Report", title_style))
    elements.append(Paragraph(f"Generated on {datetime.now().strftime('%B %d, %Y')}", styles['Normal']))
    elements.append(Spacer(1, 20))
    elements.append(HRFlowable(width="100%", thickness=2, color=colors.HexColor('#2c5282')))
    elements.append(Spacer(1, 20))

    # User Information Section
    elements.append(Paragraph("Personal Information", heading_style))
    user_data = [
        ['Name:', f"{user[0]} {user[1]}"],
        ['Email:', user[2]],
        ['Date of Birth:', user[3]]
    ]
    user_table = Table(user_data, colWidths=[1.5*inch, 4*inch])
    user_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTNAME', (1, 0), (1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 11),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
    ]))
    elements.append(user_table)
    elements.append(Spacer(1, 20))

    # Conditions Section
    elements.append(Paragraph("My Conditions", heading_style))
    if conditions:
        conditions_data = [['Condition', 'Triggers/Notes', 'Added On']]
        for condition in conditions:
            conditions_data.append([
                condition[0],
                condition[1] if condition[1] else '-',
                condition[2][:10] if condition[2] else '-'
            ])
        conditions_table = Table(conditions_data, colWidths=[2*inch, 2.5*inch, 1.2*inch])
        conditions_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2c5282')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 11),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#f7fafc')),
            ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 1), (-1, -1), 10),
            ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#e2e8f0')),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('BOTTOMPADDING', (0, 1), (-1, -1), 8),
            ('TOPPADDING', (0, 1), (-1, -1), 8),
        ]))
        elements.append(conditions_table)
    else:
        elements.append(Paragraph("No conditions recorded yet.", normal_style))
    elements.append(Spacer(1, 20))

    # Flare Ups Section
    elements.append(Paragraph("Flare Up Log", heading_style))
    if flare_ups:
        flareup_data = [['Start Time', 'End Time', 'Notes']]
        for flare in flare_ups:
            flareup_data.append([
                flare[0].replace('T', ' ') if flare[0] else '-',
                flare[1].replace('T', ' ') if flare[1] else '-',
                flare[2] if flare[2] else '-'
            ])
        flareup_table = Table(flareup_data, colWidths=[1.8*inch, 1.8*inch, 2.1*inch])
        flareup_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2c5282')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 11),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#f7fafc')),
            ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 1), (-1, -1), 10),
            ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#e2e8f0')),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('BOTTOMPADDING', (0, 1), (-1, -1), 8),
            ('TOPPADDING', (0, 1), (-1, -1), 8),
        ]))
        elements.append(flareup_table)
    else:
        elements.append(Paragraph("No flare ups logged yet.", normal_style))

    # Footer
    elements.append(Spacer(1, 40))
    elements.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor('#e2e8f0')))
    elements.append(Spacer(1, 10))
    footer_style = ParagraphStyle('Footer', parent=styles['Normal'], fontSize=9, textColor=colors.gray, alignment=1)
    elements.append(Paragraph("Generated by Chron Technology", footer_style))

    doc.build(elements)
    buffer.seek(0)

    filename = f"health_summary_{user[0]}_{user[1]}_{datetime.now().strftime('%Y%m%d')}.pdf"
    return send_file(buffer, as_attachment=True, download_name=filename, mimetype='application/pdf')
# _______________________ End Summary Page _______________________


# _______________________ contact page _______________________
@app.route('/contact')
def contact():
    return render_template('contact.html')
# _______________________ end contact page _______________________



# _______________________ conditions page _______________________
@app.route('/conditions', methods=['GET', 'POST'])
def conditions():
    if request.method == 'POST':
        if not session.get('user_id'):
            flash('Please sign in to add conditions.', 'error')
            return redirect('/signup')

        selected_conditions = request.form.getlist('conditions')

        if selected_conditions:
            conn = get_user_conn()
            cursor = conn.cursor()

            for condition in selected_conditions:
                # Get the trigger specific to this condition
                trigger_text = request.form.get(f'trigger_{condition}', '')

                # Check if user already has this condition
                cursor.execute(
                    'SELECT id FROM conditions WHERE user_id = ? AND condition_name = ?',
                    (session['user_id'], condition)
                )
                if not cursor.fetchone():
                    cursor.execute(
                        'INSERT INTO conditions (user_id, condition_name, triggers) VALUES (?, ?, ?)',
                        (session['user_id'], condition, trigger_text)
                    )

            conn.commit()
            conn.close()
            flash('Conditions added successfully!', 'success')

    # Get user's existing conditions
    user_conditions = []
    user_condition_names = []
    if session.get('user_id'):
        conn = get_user_conn()
        cursor = conn.cursor()
        cursor.execute(
            'SELECT id, condition_name, triggers FROM conditions WHERE user_id = ?',
            (session['user_id'],)
        )
        rows = cursor.fetchall()
        user_conditions = [(row[0], row[1], row[2] or '') for row in rows]  # (id, name, triggers)
        user_condition_names = [row[1] for row in rows]
        conn.close()

    return render_template(
        'conditions.html',
        all_conditions=CHRONIC_CONDITIONS,
        user_conditions=user_conditions,
        user_condition_names=user_condition_names
    )


@app.route('/delete/<int:item_id>', methods=['POST'])
def delete_item(item_id):
    if not session.get('user_id'):
        flash('Please sign in to delete conditions.', 'error')
        return redirect('/signin')

    conn = get_user_conn()
    cursor = conn.cursor()
    # Only delete if it belongs to the current user
    cursor.execute("DELETE FROM conditions WHERE id = ? AND user_id = ?", (item_id, session['user_id']))
    conn.commit()
    conn.close()
    flash('Condition deleted.', 'success')
    return redirect(url_for('conditions'))
# _______________________ end conditions page _______________________



# _______________________ sign in page _______________________
@app.route('/signin', methods=['GET', 'POST'])
def signin():
    if request.method == 'POST':
        email = request.form['email'].lower().strip()
        password = request.form['password']

        conn = get_user_conn()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM users WHERE email = ?', (email,))
        user = cursor.fetchone()
        conn.close()

        if user and check_password_hash(user[4], password):
            session['user_id'] = user[0]
            session['first_name'] = user[1]
            session['email'] = user[3]
            flash('Signin successful!', 'success')
            return redirect('/')
        flash('Invalid email or password!', 'error')
    return render_template('signin.html')
# _______________________ end sign in page _______________________


# _______________________ sign up page _______________________
@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        first_name = request.form['first_name']
        last_name = request.form['last_name']
        email = request.form['email'].lower().strip()
        password = request.form['password']
        date_of_birth = request.form['date_of_birth']
        hashed_password = generate_password_hash(password)

        conn = get_user_conn()
        cursor = conn.cursor()

        # Check if email already exists
        cursor.execute('SELECT COUNT(*) FROM users WHERE email = ?', (email,))
        user_exists = cursor.fetchone()[0] > 0

        if not is_valid_name(first_name):
            flash('Please enter your first name.', 'error')
            return redirect('/signup')
        if not is_valid_name(last_name):
            flash('Please enter your last name.', 'error')
            return redirect('/signup')
        if not is_valid_email(email):
            flash('Please enter a valid email address.', 'error')
            return redirect('/signup')
        if not is_valid_password(password):
            flash('Invalid password. Ensure it is at least 8 characters long and contains at least one letter and one number.', 'error')
            return redirect('/signup')
        if not date_of_birth:
            flash('Please enter your date of birth.', 'error')
            return redirect('/signup')

        if user_exists:
            flash('An account with this email already exists.', 'error')
        else:
            cursor.execute(
                'INSERT INTO users (first_name, last_name, email, password, date_of_birth) VALUES (?, ?, ?, ?, ?)',
                (first_name.strip(), last_name.strip(), email, hashed_password, date_of_birth)
            )
            conn.commit()
            flash('Registration successful! Please sign in.', 'success')
            conn.close()
            return redirect('/signin')
        conn.close()
    return render_template('signup.html')
# _______________________ end sign up page _______________________



# _______________________ sign out page _______________________
@app.route('/signout')
def signout():
    session.clear()
    flash('You have been signed out.', 'success')
    return redirect('/')
# _______________________ end sign out page _______________________


# _______________________ account page _______________________
@app.route('/account')
def account():
    session.clear()
    return render_template('account.html')
# _______________________ end account page _______________________


if __name__ == '__main__':
    app.run(debug=True)
