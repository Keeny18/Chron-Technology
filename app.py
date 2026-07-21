from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, send_file
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3
import re
import os
import secrets
from io import BytesIO
from datetime import datetime
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable, Image

app = Flask(__name__)

# Persistent secret key: reads from env var, then local file, then generates one
_key_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.secret_key')
if 'SECRET_KEY' in os.environ:
    app.secret_key = os.environ['SECRET_KEY']
elif os.path.exists(_key_file):
    with open(_key_file) as _f:
        app.secret_key = _f.read().strip()
else:
    app.secret_key = secrets.token_hex(32)
    with open(_key_file, 'w') as _f:
        _f.write(app.secret_key)

# Session cookie security
app.config['SESSION_COOKIE_HTTPONLY'] = True   # JS cannot access the session cookie
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'  # Blocks cross-site request forgery
# Set SESSION_COOKIE_SECURE = True in production once served over HTTPS

@app.after_request
def set_security_headers(response):
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    return response

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
        password TEXT NOT NULL
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
        important_information TEXT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id)
    )''')

    # Migrate: add important_information column if it doesn't exist
    try:
        cursor.execute('ALTER TABLE conditions ADD COLUMN important_information TEXT NULL')
    except sqlite3.OperationalError:
        pass

    # Migrate: drop date_of_birth if it exists
    try:
        cursor.execute('ALTER TABLE users DROP COLUMN date_of_birth')
    except sqlite3.OperationalError:
        pass

    # Migrate: add email verification columns
    for col in [
        'ALTER TABLE users ADD COLUMN is_verified INTEGER DEFAULT 0',
        'ALTER TABLE users ADD COLUMN verification_token TEXT',
        'ALTER TABLE users ADD COLUMN token_expires_at TIMESTAMP',
    ]:
        try:
            cursor.execute(col)
        except sqlite3.OperationalError:
            pass
    # Mark existing accounts (created before this feature) as already verified
    cursor.execute("UPDATE users SET is_verified = 1 WHERE verification_token IS NULL AND is_verified = 0")


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

    # Junction table linking flare ups to conditions
    cursor.execute('''CREATE TABLE IF NOT EXISTS flare_up_conditions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        flare_up_id INTEGER NOT NULL,
        condition_id INTEGER NOT NULL,
        FOREIGN KEY (flare_up_id) REFERENCES flare_ups(id),
        FOREIGN KEY (condition_id) REFERENCES conditions(id)
    )''')

    # Contact page content table
    cursor.execute('''CREATE TABLE IF NOT EXISTS contact_content (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )''')
    defaults = [
        ('contact_email', 'spoonie.chronic.manager@gmail.com'),
        ('about_name', 'Jackson Keen'),
        ('about_intro', 'I am a solo developer trying to use my programming abilities for good and make a difference.'),
        ('about_mission', 'I have been inspired to focus heavily on developing a chronic condition manager due to the lack of free services available for those with chronic conditions. This has been brought to my attention through the struggles faced by those closest to me and their limited support from software online.')
    ]
    for key, value in defaults:
        cursor.execute('INSERT OR IGNORE INTO contact_content (key, value) VALUES (?, ?)', (key, value))

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

def get_password_error(password):
    if not isinstance(password, str):
        return 'Invalid password.'
    if len(password) < 8:
        return 'Password must be at least 8 characters long.'
    if len(password) > 64:
        return 'Password must be no more than 64 characters long.'
    if not re.search(r'[A-Z]', password):
        return 'Password must contain at least one uppercase letter.'
    if not re.search(r'[a-z]', password):
        return 'Password must contain at least one lowercase letter.'
    if not re.search(r'[0-9]', password):
        return 'Password must contain at least one number.'
    if not re.search(r'[!@#$%^&*()\-_=+\[\]{};:\'",.<>?/\\|`~]', password):
        return 'Password must contain at least one special character (e.g. !@#$%).'
    return None

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
    user_conditions = []
    if session.get('user_id'):
        conn = get_user_conn()
        cursor = conn.cursor()

        # Fetch flare ups
        cursor.execute(
            'SELECT id, begin_time, end_time, flareup_comment FROM flare_ups WHERE user_id = ?',
            (session['user_id'],)
        )
        rows = cursor.fetchall()

        # Fetch which conditions are linked to each flare up
        flare_up_ids = [row[0] for row in rows]
        conditions_name_map = {}
        conditions_id_map = {}
        if flare_up_ids:
            placeholders = ','.join('?' * len(flare_up_ids))
            cursor.execute(f'''
                SELECT fuc.flare_up_id, fuc.condition_id, c.condition_name
                FROM flare_up_conditions fuc
                JOIN conditions c ON c.id = fuc.condition_id
                WHERE fuc.flare_up_id IN ({placeholders})
            ''', flare_up_ids)
            for fup_id, cid, cname in cursor.fetchall():
                conditions_name_map.setdefault(fup_id, []).append(cname)
                conditions_id_map.setdefault(fup_id, []).append(cid)

        user_logs = [(row[0], row[1], row[2], row[3] or '', conditions_name_map.get(row[0], []), conditions_id_map.get(row[0], [])) for row in rows]

        # Fetch user's conditions for the form
        cursor.execute(
            'SELECT id, condition_name FROM conditions WHERE user_id = ?',
            (session['user_id'],)
        )
        user_conditions = cursor.fetchall()
        conn.close()

    return render_template('log.html', user_logs=user_logs, user_conditions=user_conditions)

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

    selected_condition_ids = request.form.getlist('condition_ids')

    conn = get_user_conn()
    cursor = conn.cursor()
    cursor.execute(
        'INSERT INTO flare_ups (user_id, begin_time, end_time, flareup_comment) VALUES (?, ?, ?, ?)',
        (session['user_id'], begin_time, end_time, comment)
    )
    flare_up_id = cursor.lastrowid

    for condition_id in selected_condition_ids:
        cursor.execute(
            'INSERT INTO flare_up_conditions (flare_up_id, condition_id) VALUES (?, ?)',
            (flare_up_id, condition_id)
        )

    conn.commit()
    conn.close()

    flash('Flare up logged successfully!', 'success')
    return redirect('/log')
# _______________________ end log page _______________________




# _____________________ Check-In page _______________________
@app.route('/checkin')
def checkin():
    return render_template('checkin.html')
# _______________________End Check-In page _______________________



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
        'SELECT first_name, last_name, email FROM users WHERE id = ?',
        (session['user_id'],)
    )
    user = cursor.fetchone()
    user_info = {
        'first_name': user[0],
        'last_name': user[1],
        'email': user[2],
    }

    # Get user conditions
    cursor.execute(
        'SELECT condition_name, triggers, important_information, created_at FROM conditions WHERE user_id = ? ORDER BY created_at',
        (session['user_id'],)
    )
    conditions = cursor.fetchall()

    # Get user flare ups
    cursor.execute(
        'SELECT id, begin_time, end_time, flareup_comment, created_at FROM flare_ups WHERE user_id = ? ORDER BY begin_time DESC',
        (session['user_id'],)
    )
    flare_up_rows = cursor.fetchall()

    # Get linked conditions for each flare up
    flare_up_ids = [row[0] for row in flare_up_rows]
    conditions_map = {}
    if flare_up_ids:
        placeholders = ','.join('?' * len(flare_up_ids))
        cursor.execute(f'''
            SELECT fuc.flare_up_id, c.condition_name
            FROM flare_up_conditions fuc
            JOIN conditions c ON c.id = fuc.condition_id
            WHERE fuc.flare_up_id IN ({placeholders})
        ''', flare_up_ids)
        for fup_id, cname in cursor.fetchall():
            conditions_map.setdefault(fup_id, []).append(cname)

    flare_ups = [(row[1], row[2], row[3], ', '.join(conditions_map.get(row[0], []))) for row in flare_up_rows]
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
        'SELECT first_name, last_name, email FROM users WHERE id = ?',
        (session['user_id'],)
    )
    user = cursor.fetchone()

    # Get user conditions
    cursor.execute(
        'SELECT condition_name, triggers, important_information, created_at FROM conditions WHERE user_id = ? ORDER BY created_at',
        (session['user_id'],)
    )
    conditions = cursor.fetchall()

    # Get user flare ups with linked conditions
    cursor.execute(
        'SELECT id, begin_time, end_time, flareup_comment FROM flare_ups WHERE user_id = ? ORDER BY begin_time DESC',
        (session['user_id'],)
    )
    flare_up_rows = cursor.fetchall()

    flare_up_ids = [row[0] for row in flare_up_rows]
    conditions_map = {}
    if flare_up_ids:
        placeholders = ','.join('?' * len(flare_up_ids))
        cursor.execute(f'''
            SELECT fuc.flare_up_id, c.condition_name
            FROM flare_up_conditions fuc
            JOIN conditions c ON c.id = fuc.condition_id
            WHERE fuc.flare_up_id IN ({placeholders})
        ''', flare_up_ids)
        for fup_id, cname in cursor.fetchall():
            conditions_map.setdefault(fup_id, []).append(cname)

    flare_ups = [(row[1], row[2], row[3], ', '.join(conditions_map.get(row[0], []))) for row in flare_up_rows]
    conn.close()

    # Create PDF in memory
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=72, leftMargin=72, topMargin=72, bottomMargin=72)

    # Usable width: 8.5in - 1in left - 1in right = 6.5in
    usable_width = 6.5 * inch

    styles = getSampleStyleSheet()
    heading_style = ParagraphStyle(
        'CustomHeading',
        parent=styles['Heading2'],
        fontSize=14,
        spaceBefore=16,
        spaceAfter=8,
        textColor=colors.HexColor('#1b766c')
    )
    cell_style = ParagraphStyle('Cell', parent=styles['Normal'], fontSize=10, leading=13)
    header_cell_style = ParagraphStyle('HeaderCell', parent=styles['Normal'], fontSize=10,
                                       leading=13, textColor=colors.white, fontName='Helvetica-Bold')
    date_style = ParagraphStyle('Date', parent=styles['Normal'], fontSize=10, alignment=1)
    footer_style = ParagraphStyle('Footer', parent=styles['Normal'], fontSize=9, textColor=colors.gray, alignment=1)

    table_header_bg = colors.HexColor('#1b766c')
    table_row_bg = colors.HexColor('#f0faf8')
    table_alt_bg = colors.white
    table_grid = colors.HexColor('#2BB3A3')

    def make_table_style():
        return TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), table_header_bg),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [table_alt_bg, table_row_bg]),
            ('GRID', (0, 0), (-1, -1), 0.5, table_grid),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('TOPPADDING', (0, 0), (-1, -1), 7),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 7),
            ('LEFTPADDING', (0, 0), (-1, -1), 6),
            ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ])

    elements = []

    # Logo
    logo_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'images', 'spoonie_logo_black.png')
    if os.path.exists(logo_path):
        logo = Image(logo_path, width=2.2*inch, height=0.75*inch)
        logo.hAlign = 'CENTER'
        elements.append(logo)
        elements.append(Spacer(1, 8))

    elements.append(HRFlowable(width="100%", thickness=2, color=colors.HexColor('#1b766c')))
    elements.append(Spacer(1, 6))
    elements.append(Paragraph(f"Health Summary — Generated {datetime.now().strftime('%d %B %Y')}", date_style))
    elements.append(Spacer(1, 16))

    # Personal Information
    elements.append(Paragraph("Personal Information", heading_style))
    user_data = [
        [Paragraph('<b>Name</b>', cell_style), Paragraph(f"{user[0]} {user[1]}", cell_style)],
        [Paragraph('<b>Email</b>', cell_style), Paragraph(user[2], cell_style)],
    ]
    user_table = Table(user_data, colWidths=[1.5*inch, usable_width - 1.5*inch])
    user_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('LINEBELOW', (0, 0), (-1, -1), 0.5, colors.HexColor('#2BB3A3')),
    ]))
    elements.append(user_table)
    elements.append(Spacer(1, 16))

    # Conditions
    elements.append(Paragraph("My Conditions", heading_style))
    if conditions:
        col_w = [1.4*inch, 1.7*inch, 2.1*inch, 1.3*inch]
        conditions_data = [[
            Paragraph('Condition', header_cell_style),
            Paragraph('Triggers', header_cell_style),
            Paragraph('Important Information', header_cell_style),
            Paragraph('Added On', header_cell_style),
        ]]
        for c in conditions:
            conditions_data.append([
                Paragraph(c[0] or '-', cell_style),
                Paragraph(c[1] or '-', cell_style),
                Paragraph(c[2] or '-', cell_style),
                Paragraph(c[3][:10] if c[3] else '-', cell_style),
            ])
        conditions_table = Table(conditions_data, colWidths=col_w)
        conditions_table.setStyle(make_table_style())
        elements.append(conditions_table)
    else:
        elements.append(Paragraph("No conditions recorded yet.", cell_style))
    elements.append(Spacer(1, 16))

    # Flare Up Log
    elements.append(Paragraph("Flare Up Log", heading_style))
    if flare_ups:
        col_w = [1.6*inch, 1.5*inch, 1.5*inch, 1.9*inch]
        flareup_data = [[
            Paragraph('Conditions', header_cell_style),
            Paragraph('Start Time', header_cell_style),
            Paragraph('End Time', header_cell_style),
            Paragraph('Notes', header_cell_style),
        ]]
        for f in flare_ups:
            flareup_data.append([
                Paragraph(f[3] or '-', cell_style),
                Paragraph(f[0].replace('T', ' ') if f[0] else '-', cell_style),
                Paragraph(f[1].replace('T', ' ') if f[1] else '-', cell_style),
                Paragraph(f[2] or '-', cell_style),
            ])
        flareup_table = Table(flareup_data, colWidths=col_w)
        flareup_table.setStyle(make_table_style())
        elements.append(flareup_table)
    else:
        elements.append(Paragraph("No flare ups logged yet.", cell_style))

    # Footer
    elements.append(Spacer(1, 30))
    elements.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor('#2BB3A3')))
    elements.append(Spacer(1, 8))
    elements.append(Paragraph("Generated by Spoonie", footer_style))

    doc.build(elements)
    buffer.seek(0)

    filename = f"health_summary_{user[0]}_{user[1]}_{datetime.now().strftime('%Y%m%d')}.pdf"
    return send_file(buffer, as_attachment=True, download_name=filename, mimetype='application/pdf')
# _______________________ End Summary Page _______________________


# _______________________ contact page _______________________
ADMIN_EMAIL = 'spoonie.chronic.manager@gmail.com'

@app.route('/contact')
def contact():
    conn = get_user_conn()
    cursor = conn.cursor()
    cursor.execute('SELECT key, value FROM contact_content')
    content = dict(cursor.fetchall())
    conn.close()
    is_admin = session.get('email') == ADMIN_EMAIL
    return render_template('contact.html', content=content, is_admin=is_admin)


@app.route('/update_contact', methods=['POST'])
def update_contact():
    if session.get('email') != ADMIN_EMAIL:
        flash('Unauthorised.', 'error')
        return redirect('/contact')

    conn = get_user_conn()
    cursor = conn.cursor()
    for key in ['contact_email', 'about_name', 'about_intro', 'about_mission']:
        value = request.form.get(key, '').strip()
        if value:
            cursor.execute('UPDATE contact_content SET value = ? WHERE key = ?', (value, key))
    conn.commit()
    conn.close()
    flash('Contact page updated.', 'success')
    return redirect('/contact')
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
                trigger_text = request.form.get(f'trigger_{condition}', '')
                important_info_text = request.form.get(f'important_info_{condition}', '')

                # Check if user already has this condition
                cursor.execute(
                    'SELECT id FROM conditions WHERE user_id = ? AND condition_name = ?',
                    (session['user_id'], condition)
                )
                if not cursor.fetchone():
                    cursor.execute(
                        'INSERT INTO conditions (user_id, condition_name, triggers, important_information) VALUES (?, ?, ?, ?)',
                        (session['user_id'], condition, trigger_text, important_info_text)
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
            'SELECT id, condition_name, triggers, important_information FROM conditions WHERE user_id = ?',
            (session['user_id'],)
        )
        rows = cursor.fetchall()
        user_conditions = [(row[0], row[1], row[2] or '', row[3] or '') for row in rows]  # (id, name, triggers, important_info)
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
    cursor.execute("DELETE FROM conditions WHERE id = ? AND user_id = ?", (item_id, session['user_id']))
    conn.commit()
    conn.close()
    flash('Condition deleted.', 'success')
    return redirect(url_for('conditions'))


@app.route('/edit_condition/<int:item_id>', methods=['POST'])
def edit_condition(item_id):
    if not session.get('user_id'):
        return redirect('/signin')

    triggers = request.form.get('triggers', '')
    important_info = request.form.get('important_info', '')

    conn = get_user_conn()
    cursor = conn.cursor()
    cursor.execute(
        'UPDATE conditions SET triggers = ?, important_information = ? WHERE id = ? AND user_id = ?',
        (triggers, important_info, item_id, session['user_id'])
    )
    conn.commit()
    conn.close()
    flash('Condition updated.', 'success')
    return redirect('/conditions')


@app.route('/edit_flareup/<int:item_id>', methods=['POST'])
def edit_flareup(item_id):
    if not session.get('user_id'):
        return redirect('/signin')

    begin_time = request.form.get('flare_up_begun')
    end_time = request.form.get('flare_up_end')
    comment = request.form.get('flareup_information', '')
    selected_condition_ids = request.form.getlist('condition_ids')

    conn = get_user_conn()
    cursor = conn.cursor()
    cursor.execute(
        'UPDATE flare_ups SET begin_time = ?, end_time = ?, flareup_comment = ? WHERE id = ? AND user_id = ?',
        (begin_time, end_time, comment, item_id, session['user_id'])
    )
    cursor.execute('DELETE FROM flare_up_conditions WHERE flare_up_id = ?', (item_id,))
    for condition_id in selected_condition_ids:
        cursor.execute(
            'INSERT INTO flare_up_conditions (flare_up_id, condition_id) VALUES (?, ?)',
            (item_id, condition_id)
        )
    conn.commit()
    conn.close()
    flash('Flare up updated.', 'success')
    return redirect('/log')


@app.route('/delete_flareup/<int:item_id>', methods=['POST'])
def delete_flareup(item_id):
    if not session.get('user_id'):
        return redirect('/signin')

    conn = get_user_conn()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM flare_up_conditions WHERE flare_up_id = ?', (item_id,))
    cursor.execute('DELETE FROM flare_ups WHERE id = ? AND user_id = ?', (item_id, session['user_id']))
    conn.commit()
    conn.close()
    flash('Flare up deleted.', 'success')
    return redirect('/log')
# _______________________ end conditions page _______________________



# _______________________ sign in page _______________________
@app.route('/signin', methods=['GET', 'POST'])
def signin():
    if request.method == 'POST':
        email = request.form['email'].lower().strip()
        password = request.form['password']

        conn = get_user_conn()
        cursor = conn.cursor()
        cursor.execute(
            'SELECT id, first_name, last_name, email, password FROM users WHERE email = ?',
            (email,)
        )
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
        password_error = get_password_error(password)
        if password_error:
            flash(password_error, 'error')
            return redirect('/signup')
        if user_exists:
            flash('An account with this email already exists.', 'error')
        else:
            cursor.execute(
                'INSERT INTO users (first_name, last_name, email, password, is_verified) VALUES (?, ?, ?, ?, 1)',
                (first_name.strip(), last_name.strip(), email, hashed_password)
            )
            conn.commit()
            user_id = cursor.lastrowid
            conn.close()
            session['user_id'] = user_id
            session['first_name'] = first_name.strip()
            session['email'] = email
            flash('Welcome to Spoonie!', 'success')
            return redirect('/')
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
    if not session.get('user_id'):
        return redirect('/signin')

    conn = get_user_conn()
    cursor = conn.cursor()
    cursor.execute(
        'SELECT first_name, last_name, email FROM users WHERE id = ?',
        (session['user_id'],)
    )
    user = cursor.fetchone()
    conn.close()
    user_info = {'first_name': user[0], 'last_name': user[1], 'email': user[2]}
    return render_template('account.html', user_info=user_info)


@app.route('/update_account', methods=['POST'])
def update_account():
    if not session.get('user_id'):
        return redirect('/signin')

    first_name = request.form.get('first_name', '').strip()
    last_name = request.form.get('last_name', '').strip()
    email = request.form.get('email', '').lower().strip()
    new_password = request.form.get('new_password', '')

    if not is_valid_name(first_name) or not is_valid_name(last_name):
        flash('Please enter a valid name.', 'error')
        return redirect('/account')
    if not is_valid_email(email):
        flash('Please enter a valid email address.', 'error')
        return redirect('/account')

    conn = get_user_conn()
    cursor = conn.cursor()

    if new_password:
        password_error = get_password_error(new_password)
        if password_error:
            flash(password_error, 'error')
            conn.close()
            return redirect('/account')
        cursor.execute(
            'UPDATE users SET first_name=?, last_name=?, email=?, password=? WHERE id=?',
            (first_name, last_name, email, generate_password_hash(new_password), session['user_id'])
        )
    else:
        cursor.execute(
            'UPDATE users SET first_name=?, last_name=?, email=? WHERE id=?',
            (first_name, last_name, email, session['user_id'])
        )

    conn.commit()
    conn.close()
    session['first_name'] = first_name
    flash('Account updated successfully.', 'success')
    return redirect('/account')
# _______________________ end account page _______________________


# Admin-only: manually verify an account by email
@app.route('/admin/verify_user', methods=['POST'])
def admin_verify_user():
    if session.get('email') != ADMIN_EMAIL:
        flash('Unauthorised.', 'error')
        return redirect('/')
    email = request.form.get('email', '').lower().strip()
    conn = get_user_conn()
    cursor = conn.cursor()
    cursor.execute(
        'UPDATE users SET is_verified = 1, verification_token = NULL, token_expires_at = NULL WHERE email = ?',
        (email,)
    )
    conn.commit()
    conn.close()
    flash(f'{email} has been manually verified.', 'success')
    return redirect('/contact')


if __name__ == '__main__':
    debug = os.environ.get('FLASK_DEBUG', 'false').lower() == 'true'
    app.run(debug=debug)
