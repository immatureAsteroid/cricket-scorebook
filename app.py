from google.oauth2 import id_token
from google.auth.transport import requests as google_requests
# Baaki purane imports waise hi rehne dein

from flask import Flask, render_template, request, jsonify, session, send_file, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta
import json, os, uuid, io
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, HRFlowable
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'cricket-scorebook-secret-2026')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///cricket.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# ─── Models ───────────────────────────────────────────────────────────────────

class User(db.Model):
    id = db.Column(db.String(100), primary_key=True)
    email = db.Column(db.String(200), unique=True)
    name = db.Column(db.String(200))
    picture = db.Column(db.String(500))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    matches = db.relationship('Match', backref='user', lazy=True)

class Match(db.Model):
    id = db.Column(db.String(50), primary_key=True, default=lambda: str(uuid.uuid4())[:8].upper())
    user_id = db.Column(db.String(100), db.ForeignKey('user.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    match_date = db.Column(db.String(20))
    data = db.Column(db.Text)  # JSON blob of entire match

    def is_expired(self):
        return datetime.utcnow() - self.created_at > timedelta(hours=48)

# ─── DB Init ──────────────────────────────────────────────────────────────────

with app.app_context():
    db.create_all()

# ─── Cleanup old matches ───────────────────────────────────────────────────────

def cleanup_old_matches():
    cutoff = datetime.utcnow() - timedelta(hours=48)
    Match.query.filter(Match.created_at < cutoff, Match.user_id.isnot(None)).delete()
    db.session.commit()

# ─── Routes ───────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/score')
def score():
    return render_template('score.html')

# Mock Google OAuth (replace with real in production)
@app.route('/auth/google/mock', methods=['POST'])
def mock_google_login():
    data = request.json
    # In production, verify Google token here
    user_id = data.get('sub', 'mock_' + str(uuid.uuid4())[:8])
    email = data.get('email', 'user@example.com')
    name = data.get('name', 'Cricket Fan')
    picture = data.get('picture', '')

    user = User.query.get(user_id)
    if not user:
        user = User(id=user_id, email=email, name=name, picture=picture)
        db.session.add(user)
        db.session.commit()

    session['user_id'] = user_id
    session['user_name'] = name
    session['user_email'] = email
    session['user_picture'] = picture
    return jsonify({'success': True, 'name': name, 'email': email, 'picture': picture})

@app.route('/auth/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({'success': True})

@app.route('/auth/status')
def auth_status():
    if 'user_id' in session:
        return jsonify({
            'logged_in': True,
            'name': session.get('user_name'),
            'email': session.get('user_email'),
            'picture': session.get('user_picture')
        })
    return jsonify({'logged_in': False})

# Save match to DB (for logged-in users)
@app.route('/api/match/save', methods=['POST'])
def save_match():
    cleanup_old_matches()
    data = request.json
    match_data = data.get('match')
    match_id = data.get('match_id')

    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'})

    user_id = session['user_id']
    today = datetime.utcnow().strftime('%Y/%m/%d')

    existing = Match.query.get(match_id) if match_id else None
    if existing and existing.user_id == user_id:
        existing.data = json.dumps(match_data)
        existing.match_date = today
    else:
        m = Match(
            id=match_id or str(uuid.uuid4())[:8].upper(),
            user_id=user_id,
            match_date=today,
            data=json.dumps(match_data)
        )
        db.session.add(m)
        match_id = m.id

    db.session.commit()
    return jsonify({'success': True, 'match_id': match_id})

# Get user's match history
@app.route('/api/matches/history')
def match_history():
    if 'user_id' not in session:
        return jsonify({'matches': []})

    cleanup_old_matches()
    user_id = session['user_id']
    matches = Match.query.filter_by(user_id=user_id).order_by(Match.created_at.desc()).all()

    result = {}
    for m in matches:
        date = m.match_date or m.created_at.strftime('%Y/%m/%d')
        if date not in result:
            result[date] = []
        try:
            mdata = json.loads(m.data) if m.data else {}
            result[date].append({
                'id': m.id,
                'created_at': m.created_at.isoformat(),
                'team1': mdata.get('setup', {}).get('team1Name', 'Team 1'),
                'team2': mdata.get('setup', {}).get('team2Name', 'Team 2'),
                'status': mdata.get('status', 'ongoing'),
                'result': mdata.get('result', ''),
                'date': date
            })
        except:
            pass

    return jsonify({'matches': result})

# Download single match PDF
@app.route('/api/match/<match_id>/pdf')
def download_match_pdf(match_id):
    match = Match.query.get(match_id)
    if not match:
        return jsonify({'error': 'Match not found'}), 404

    if match.user_id and match.user_id != session.get('user_id'):
        return jsonify({'error': 'Unauthorized'}), 403

    try:
        match_data = json.loads(match.data)
        pdf_buf = generate_pdf(match_data)
        return send_file(
            pdf_buf,
            mimetype='application/pdf',
            as_attachment=True,
            download_name=f"match_{match_id}.pdf"
        )
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# Generate PDF from posted match data (for guest users)
@app.route('/api/match/pdf', methods=['POST'])
def generate_match_pdf():
    try:
        match_data = request.json
        pdf_buf = generate_pdf(match_data)
        return send_file(
            pdf_buf,
            mimetype='application/pdf',
            as_attachment=True,
            download_name='cricket_scorecard.pdf'
        )
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# Download all matches for a day
@app.route('/api/matches/day/<date_str>/pdf')
def download_day_pdf(date_str):
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401

    # date_str format: 2026-04-27
    user_id = session['user_id']
    formatted_date = date_str.replace('-', '/')
    matches = Match.query.filter_by(user_id=user_id, match_date=formatted_date).all()

    if not matches:
        return jsonify({'error': 'No matches found'}), 404

    try:
        all_data = [json.loads(m.data) for m in matches if m.data]
        pdf_buf = generate_multi_match_pdf(all_data, formatted_date)
        return send_file(
            pdf_buf,
            mimetype='application/pdf',
            as_attachment=True,
            download_name=f"matches_{date_str}.pdf"
        )
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ─── PDF Generator ────────────────────────────────────────────────────────────

def generate_pdf(match_data):
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            leftMargin=1.5*cm, rightMargin=1.5*cm,
                            topMargin=2*cm, bottomMargin=2*cm)

    styles = getSampleStyleSheet()
    cream = colors.HexColor('#F5F0E8')
    forest = colors.HexColor('#2D5016')
    gold = colors.HexColor('#C9A227')
    dark = colors.HexColor('#1A1A1A')

    title_style = ParagraphStyle('Title', fontSize=22, textColor=forest,
                                  fontName='Helvetica-Bold', alignment=TA_CENTER, spaceAfter=6)
    sub_style = ParagraphStyle('Sub', fontSize=11, textColor=dark,
                                fontName='Helvetica', alignment=TA_CENTER, spaceAfter=4)
    section_style = ParagraphStyle('Section', fontSize=13, textColor=forest,
                                    fontName='Helvetica-Bold', spaceBefore=12, spaceAfter=6)
    body_style = ParagraphStyle('Body', fontSize=10, textColor=dark,
                                 fontName='Helvetica', spaceAfter=4)

    story = []
    setup = match_data.get('setup', {})
    innings_list = match_data.get('innings', [])
    result = match_data.get('result', '')
    toss = match_data.get('toss', {})

    # Header
    story.append(Paragraph("🏏 CRICKET SCORECARD", title_style))
    story.append(Paragraph(f"{setup.get('team1Name','Team 1')}  vs  {setup.get('team2Name','Team 2')}", sub_style))
    story.append(Paragraph(f"Overs: {setup.get('overs','N/A')}  |  Date: {match_data.get('matchDate', datetime.utcnow().strftime('%d %b %Y'))}", sub_style))

    if toss:
        story.append(Paragraph(f"Toss: {toss.get('winner','')} won & chose to {toss.get('choice','bat')}", sub_style))

    story.append(HRFlowable(width="100%", thickness=2, color=forest, spaceAfter=10))

    if result:
        result_style = ParagraphStyle('Result', fontSize=14, textColor=gold,
                                       fontName='Helvetica-Bold', alignment=TA_CENTER,
                                       spaceBefore=4, spaceAfter=12)
        story.append(Paragraph(f"RESULT: {result}", result_style))

    # Each innings
    for idx, inn in enumerate(innings_list):
        batting_team = inn.get('battingTeam', f'Team {idx+1}')
        bowling_team = inn.get('bowlingTeam', '')
        runs = inn.get('runs', 0)
        wickets = inn.get('wickets', 0)
        balls = inn.get('balls', 0)
        overs_str = f"{balls//6}.{balls%6}"
        extras = inn.get('extras', {})
        total_extras = sum(extras.values())

        story.append(Paragraph(f"INNINGS {idx+1}: {batting_team}", section_style))
        story.append(Paragraph(f"Score: {runs}/{wickets}  ({overs_str} overs)  |  Extras: {total_extras}", body_style))

        # Batting table
        batsmen = inn.get('batsmen', [])
        if batsmen:
            story.append(Paragraph("Batting", ParagraphStyle('BH', fontSize=11, fontName='Helvetica-Bold',
                                                               textColor=forest, spaceBefore=6, spaceAfter=3)))
            bat_data = [['Batsman', 'R', 'B', '4s', '6s', 'SR', 'How Out']]
            for b in batsmen:
                balls_faced = b.get('balls', 0)
                sr = round((b.get('runs',0)/balls_faced)*100, 1) if balls_faced > 0 else 0
                bat_data.append([
                    b.get('name', '?'),
                    str(b.get('runs', 0)),
                    str(balls_faced),
                    str(b.get('fours', 0)),
                    str(b.get('sixes', 0)),
                    str(sr),
                    b.get('dismissal', 'not out')
                ])
            bat_table = Table(bat_data, colWidths=[4.5*cm,1.2*cm,1.2*cm,1.2*cm,1.2*cm,1.5*cm,4.5*cm])
            bat_table.setStyle(TableStyle([
                ('BACKGROUND', (0,0), (-1,0), forest),
                ('TEXTCOLOR', (0,0), (-1,0), colors.white),
                ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
                ('FONTSIZE', (0,0), (-1,-1), 9),
                ('ROWBACKGROUNDS', (0,1), (-1,-1), [cream, colors.white]),
                ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#CCCCCC')),
                ('ALIGN', (1,0), (-1,-1), 'CENTER'),
            ]))
            story.append(bat_table)

        # Extras breakdown
        ext_parts = []
        for k, v in extras.items():
            if v > 0:
                ext_parts.append(f"{k.upper()}: {v}")
        if ext_parts:
            story.append(Paragraph(f"Extras: {', '.join(ext_parts)}  (Total: {total_extras})", body_style))

        # Bowling table
        bowlers = inn.get('bowlers', [])
        if bowlers:
            story.append(Paragraph("Bowling", ParagraphStyle('BWH', fontSize=11, fontName='Helvetica-Bold',
                                                               textColor=forest, spaceBefore=6, spaceAfter=3)))
            bowl_data = [['Bowler', 'O', 'M', 'R', 'W', 'Econ', 'WD', 'NB']]
            for bw in bowlers:
                b_balls = bw.get('balls', 0)
                overs_bowled = f"{b_balls//6}.{b_balls%6}"
                econ = round((bw.get('runs',0)/(b_balls/6)), 2) if b_balls > 0 else 0
                maiden = bw.get('maidens', 0)
                bowl_data.append([
                    bw.get('name', '?'),
                    overs_bowled,
                    str(maiden),
                    str(bw.get('runs', 0)),
                    str(bw.get('wickets', 0)),
                    str(econ),
                    str(bw.get('wides', 0)),
                    str(bw.get('noballs', 0)),
                ])
            bowl_table = Table(bowl_data, colWidths=[4.5*cm,1.2*cm,1.2*cm,1.2*cm,1.2*cm,1.5*cm,1.2*cm,1.2*cm])
            bowl_table.setStyle(TableStyle([
                ('BACKGROUND', (0,0), (-1,0), forest),
                ('TEXTCOLOR', (0,0), (-1,0), colors.white),
                ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
                ('FONTSIZE', (0,0), (-1,-1), 9),
                ('ROWBACKGROUNDS', (0,1), (-1,-1), [cream, colors.white]),
                ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#CCCCCC')),
                ('ALIGN', (1,0), (-1,-1), 'CENTER'),
            ]))
            story.append(bowl_table)

        # Fall of wickets
        fow = inn.get('fallOfWickets', [])
        if fow:
            fow_str = '  |  '.join([f"{f['wicket']}-{f['runs']} ({f['batsman']}, {f['over']}ov)" for f in fow])
            story.append(Paragraph(f"Fall of Wickets: {fow_str}", body_style))

        story.append(Spacer(1, 0.5*cm))

    # Match Summary
    story.append(HRFlowable(width="100%", thickness=1, color=forest, spaceAfter=6))
    story.append(Paragraph("MATCH SUMMARY", section_style))

    summary = match_data.get('summary', {})
    if summary:
        for k, v in summary.items():
            story.append(Paragraph(f"• {k}: {v}", body_style))

    story.append(Spacer(1, 0.5*cm))
    story.append(Paragraph("Generated by Cricket Scorebook App", 
                             ParagraphStyle('Footer', fontSize=8, textColor=colors.grey, alignment=TA_CENTER)))

    doc.build(story)
    buf.seek(0)
    return buf

def generate_multi_match_pdf(all_data, date_str):
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            leftMargin=1.5*cm, rightMargin=1.5*cm,
                            topMargin=2*cm, bottomMargin=2*cm)

    styles = getSampleStyleSheet()
    forest = colors.HexColor('#2D5016')
    title_style = ParagraphStyle('Title', fontSize=20, textColor=forest,
                                  fontName='Helvetica-Bold', alignment=TA_CENTER, spaceAfter=8)
    story = [Paragraph(f"🏏 All Matches — {date_str}", title_style),
             HRFlowable(width="100%", thickness=2, color=forest, spaceAfter=16)]

    for i, match_data in enumerate(all_data):
        setup = match_data.get('setup', {})
        result = match_data.get('result', 'Ongoing')
        sub = ParagraphStyle('Sub', fontSize=12, fontName='Helvetica-Bold',
                              textColor=forest, spaceAfter=4, spaceBefore=12)
        story.append(Paragraph(f"Match {i+1}: {setup.get('team1Name','T1')} vs {setup.get('team2Name','T2')}", sub))
        story.append(Paragraph(f"Result: {result}", ParagraphStyle('R', fontSize=10, fontName='Helvetica',
                                                                     textColor=colors.HexColor('#1A1A1A'), spaceAfter=6)))

        for inn in match_data.get('innings', []):
            runs = inn.get('runs', 0)
            wkts = inn.get('wickets', 0)
            balls = inn.get('balls', 0)
            story.append(Paragraph(
                f"  {inn.get('battingTeam','')}: {runs}/{wkts} ({balls//6}.{balls%6} ov)",
                ParagraphStyle('Inn', fontSize=10, fontName='Helvetica', spaceAfter=3)
            ))

        story.append(HRFlowable(width="80%", thickness=0.5, color=colors.grey, spaceAfter=4))

    story.append(Spacer(1, 1*cm))
    story.append(Paragraph("Generated by Cricket Scorebook App",
                             ParagraphStyle('Footer', fontSize=8, textColor=colors.grey, alignment=TA_CENTER)))
    doc.build(story)
    buf.seek(0)
    return buf

if __name__ == '__main__':
    app.run(debug=True, port=5000)
