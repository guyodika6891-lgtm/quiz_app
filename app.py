import os
from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_bcrypt import Bcrypt
from models import db, User, Quiz, Question, Attempt
from datetime import datetime
from functools import wraps
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-fallback-key-change-me')

app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///quiz.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)
bcrypt = Bcrypt(app)

with app.app_context():
    db.create_all()
    print("✅ Quiz App database created successfully!")


# ============================================
# DECORATORS
# ============================================
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            flash('Please login to access this page.', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function


def teacher_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            flash('Please login to access this page.', 'warning')
            return redirect(url_for('login'))
        if session.get('role') != 'teacher':
            flash('Only teachers can access this page.', 'error')
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function


def student_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            flash('Please login to access this page.', 'warning')
            return redirect(url_for('login'))
        if session.get('role') != 'student':
            flash('Only students can access this page.', 'error')
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function


# ============================================
# HELPER FUNCTIONS
# ============================================
def get_quiz_status(quiz):
    """
    Returns quiz status:
    - 'upcoming': before start_time
    - 'available': within time window
    - 'expired': after end_time
    - 'no_time_limit': if no start/end time set (open forever)
    """
    now = datetime.now()

    if not quiz.start_time and not quiz.end_time:
        return 'no_time_limit'

    if quiz.start_time and now < quiz.start_time:
        return 'upcoming'

    if quiz.end_time and now > quiz.end_time:
        return 'expired'

    return 'available'


def parse_quiz_time_form(form):
    """
    Parse and validate quiz time fields from the form.
    Returns (start_time, end_time, duration_minutes, errors)
    """
    start_time_str = form.get('start_time', '').strip()
    end_time_str = form.get('end_time', '').strip()
    duration_str = form.get('duration_minutes', '').strip()

    errors = []
    start_time = None
    end_time = None
    duration_minutes = None

    # Require both times
    if not start_time_str:
        errors.append('Opens At time is required')
    if not end_time_str:
        errors.append('Closes At time is required')

    if start_time_str and end_time_str:
        try:
            start_time = datetime.strptime(start_time_str, '%Y-%m-%dT%H:%M')
            end_time = datetime.strptime(end_time_str, '%Y-%m-%dT%H:%M')

            if start_time >= end_time:
                errors.append('End time must be after start time')
            else:
                # Compute window in minutes
                window_minutes = int((end_time - start_time).total_seconds() / 60)

                # Handle duration from hidden field
                if duration_str:
                    try:
                        duration_minutes = int(duration_str)
                        if duration_minutes <= 0:
                            errors.append('Duration must be greater than 0')
                            duration_minutes = None
                        elif duration_minutes > window_minutes:
                            errors.append(f'Duration cannot exceed the window ({window_minutes} minutes)')
                            duration_minutes = None
                    except ValueError:
                        errors.append('Invalid duration value')
                        duration_minutes = None
                else:
                    # No duration = no time limit (full window)
                    duration_minutes = None
        except ValueError:
            errors.append('Invalid date/time format')

    return start_time, end_time, duration_minutes, errors


# ============================================
# HOME ROUTE
# ============================================
@app.route('/')
def index():
    if not session.get('logged_in'):
        return render_template('index.html', role=None)

    role = session.get('role')

    if role == 'teacher':
        quizzes = Quiz.query.filter_by(teacher_id=session['user_id']).order_by(
            Quiz.created_at.desc()
        ).all()

        # Compute stats in Python
        total_questions = sum(len(q.questions) for q in quizzes)
        total_submissions = sum(len(q.attempts) for q in quizzes)

        return render_template(
            'index.html',
            role='teacher',
            quizzes=quizzes,
            total_questions=total_questions,
            total_submissions=total_submissions
        )
    else:
        attempts = Attempt.query.filter_by(student_id=session['user_id']).order_by(
            Attempt.submitted_at.desc()
        ).limit(5).all()
        return render_template('index.html', role='student', attempts=attempts)


# ============================================
# AUTHENTICATION ROUTES
# ============================================
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '').strip()
        confirm_password = request.form.get('confirm_password', '').strip()
        role = request.form.get('role', 'student').strip()

        if role not in ['teacher', 'student']:
            role = 'student'

        errors = []
        if not username or len(username) < 3:
            errors.append('Username must be at least 3 characters')
        elif User.query.filter_by(username=username).first():
            errors.append('This username is already taken')

        if not email or '@' not in email or '.' not in email:
            errors.append('Please enter a valid email')
        elif User.query.filter_by(email=email).first():
            errors.append('This email is already registered')

        if not password or len(password) < 6:
            errors.append('Password must be at least 6 characters')

        if password != confirm_password:
            errors.append('Passwords do not match')

        if errors:
            for error in errors:
                flash(error, 'error')
            return render_template('register.html', username=username, email=email, role=role)

        hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')
        new_user = User(
            username=username,
            email=email,
            password_hash=hashed_password,
            role=role
        )
        db.session.add(new_user)
        db.session.commit()

        flash(f'Registration successful! You registered as a {role}.', 'success')
        return redirect(url_for('login'))

    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()

        user = User.query.filter_by(username=username).first()

        if user and bcrypt.check_password_hash(user.password_hash, password):
            session['user_id'] = user.id
            session['username'] = user.username
            session['role'] = user.role
            session['logged_in'] = True

            flash(f'Welcome back, {username}! ({user.role.capitalize()})', 'success')
            return redirect(url_for('index'))
        else:
            flash('Invalid username or password', 'error')
            return redirect(url_for('login'))

    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('index'))


@app.route('/profile')
@login_required
def profile():
    user = User.query.get(session['user_id'])
    return render_template('profile.html', user=user)


@app.route('/quizzes')
@login_required
def quizzes():
    all_quizzes = Quiz.query.order_by(Quiz.created_at.desc()).all()
    quiz_statuses = {quiz.id: get_quiz_status(quiz) for quiz in all_quizzes}
    return render_template('quizzes.html', quizzes=all_quizzes, quiz_statuses=quiz_statuses)


# ============================================
# TEACHER ROUTES
# ============================================
@app.route('/quiz/new', methods=['GET', 'POST'])
@teacher_required
def new_quiz():
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()

        # Parse and validate time fields using helper
        start_time, end_time, duration_minutes, errors = parse_quiz_time_form(request.form)

        if not title:
            errors.insert(0, 'Title is required')

        if errors:
            for error in errors:
                flash(error, 'error')
            return render_template('new_quiz.html',
                                 title=title,
                                 description=description,
                                 start_time=request.form.get('start_time', ''),
                                 end_time=request.form.get('end_time', ''),
                                 duration_minutes=request.form.get('duration_minutes', ''))

        quiz = Quiz(
            title=title,
            description=description,
            start_time=start_time,
            end_time=end_time,
            duration_minutes=duration_minutes,
            teacher_id=session['user_id']
        )
        db.session.add(quiz)
        db.session.commit()

        flash('Quiz created! Now add questions.', 'success')
        return redirect(url_for('add_question', quiz_id=quiz.id))

    return render_template('new_quiz.html')


@app.route('/quiz/<int:quiz_id>/edit', methods=['GET', 'POST'])
@teacher_required
def edit_quiz(quiz_id):
    quiz = Quiz.query.get_or_404(quiz_id)

    if quiz.teacher_id != session['user_id']:
        flash('You can only edit your own quizzes.', 'error')
        return redirect(url_for('index'))

    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()

        # Parse and validate time fields using helper
        start_time, end_time, duration_minutes, errors = parse_quiz_time_form(request.form)

        if not title:
            errors.insert(0, 'Title is required')

        if errors:
            for error in errors:
                flash(error, 'error')
            return render_template('edit_quiz.html', quiz=quiz)

        quiz.title = title
        quiz.description = description
        quiz.start_time = start_time
        quiz.end_time = end_time
        quiz.duration_minutes = duration_minutes
        db.session.commit()

        flash('Quiz updated successfully!', 'success')
        return redirect(url_for('view_quiz', quiz_id=quiz.id))

    return render_template('edit_quiz.html', quiz=quiz)


@app.route('/quiz/<int:quiz_id>/delete', methods=['POST'])
@teacher_required
def delete_quiz(quiz_id):
    quiz = Quiz.query.get_or_404(quiz_id)

    if quiz.teacher_id != session['user_id']:
        flash('You can only delete your own quizzes.', 'error')
        return redirect(url_for('index'))

    db.session.delete(quiz)
    db.session.commit()

    flash('Quiz deleted successfully!', 'info')
    return redirect(url_for('index'))


@app.route('/quiz/<int:quiz_id>/add_question', methods=['GET', 'POST'])
@teacher_required
def add_question(quiz_id):
    quiz = Quiz.query.get_or_404(quiz_id)

    if quiz.teacher_id != session['user_id']:
        flash('You can only add questions to your own quizzes.', 'error')
        return redirect(url_for('index'))

    if request.method == 'POST':
        question_text = request.form.get('question_text', '').strip()
        option_a = request.form.get('option_a', '').strip()
        option_b = request.form.get('option_b', '').strip()
        option_c = request.form.get('option_c', '').strip()
        option_d = request.form.get('option_d', '').strip()
        correct_answer = request.form.get('correct_answer', '').strip().upper()

        errors = []
        if not question_text:
            errors.append('Question text is required')
        if not option_a or not option_b or not option_c or not option_d:
            errors.append('All four options are required')
        if correct_answer not in ['A', 'B', 'C', 'D']:
            errors.append('Please select the correct answer')

        if errors:
            for error in errors:
                flash(error, 'error')
            return render_template('add_question.html', quiz=quiz)

        question = Question(
            question_text=question_text,
            option_a=option_a,
            option_b=option_b,
            option_c=option_c,
            option_d=option_d,
            correct_answer=correct_answer,
            quiz_id=quiz.id
        )
        db.session.add(question)
        db.session.commit()

        flash('Question added!', 'success')

        if request.form.get('add_another'):
            return redirect(url_for('add_question', quiz_id=quiz.id))

        return redirect(url_for('view_quiz', quiz_id=quiz.id))

    return render_template('add_question.html', quiz=quiz)


@app.route('/quiz/<int:quiz_id>/submissions')
@teacher_required
def submissions(quiz_id):
    quiz = Quiz.query.get_or_404(quiz_id)

    if quiz.teacher_id != session['user_id']:
        flash('You can only view submissions for your own quizzes.', 'error')
        return redirect(url_for('index'))

    attempts = Attempt.query.filter_by(quiz_id=quiz_id).order_by(
        Attempt.submitted_at.desc()
    ).all()

    return render_template('submissions.html', quiz=quiz, attempts=attempts)


# ============================================
# SHARED / VIEW ROUTES
# ============================================
@app.route('/quiz/<int:quiz_id>')
@login_required
def view_quiz(quiz_id):
    quiz = Quiz.query.get_or_404(quiz_id)
    status = get_quiz_status(quiz)

    already_attempted = False
    existing_attempt = None
    if session.get('role') == 'student':
        existing_attempt = Attempt.query.filter_by(
            student_id=session['user_id'],
            quiz_id=quiz_id
        ).first()
        already_attempted = existing_attempt is not None

    return render_template(
        'view_quiz.html',
        quiz=quiz,
        status=status,
        already_attempted=already_attempted,
        existing_attempt=existing_attempt
    )


# ============================================
# STUDENT ROUTES
# ============================================
@app.route('/quiz/<int:quiz_id>/take', methods=['GET', 'POST'])
@student_required
def take_quiz(quiz_id):
    quiz = Quiz.query.get_or_404(quiz_id)

    # RULE 1: Quiz must have questions
    if not quiz.questions:
        flash('This quiz has no questions yet.', 'warning')
        return redirect(url_for('view_quiz', quiz_id=quiz.id))

    # RULE 2: Quiz must be currently available (time window)
    status = get_quiz_status(quiz)
    if status == 'upcoming':
        flash(f'This quiz opens on {quiz.start_time.strftime("%b %d, %Y at %H:%M")}.', 'warning')
        return redirect(url_for('view_quiz', quiz_id=quiz.id))
    if status == 'expired':
        flash('This quiz has already closed.', 'error')
        return redirect(url_for('view_quiz', quiz_id=quiz.id))

    # RULE 3: Student can only take it once
    existing_attempt = Attempt.query.filter_by(
        student_id=session['user_id'],
        quiz_id=quiz_id
    ).first()

    if existing_attempt:
        flash('You have already taken this quiz. You cannot retake it.', 'error')
        return redirect(url_for('quiz_results', attempt_id=existing_attempt.id))

    if request.method == 'POST':
        score = 0
        total = len(quiz.questions)

        for question in quiz.questions:
            student_answer = request.form.get(f'question_{question.id}', '').strip().upper()
            if student_answer == question.correct_answer:
                score += 1

        attempt = Attempt(
            score=score,
            total_questions=total,
            student_id=session['user_id'],
            quiz_id=quiz_id
        )
        db.session.add(attempt)
        db.session.commit()

        flash(f'Quiz submitted! You scored {score}/{total}.', 'success')
        return redirect(url_for('quiz_results', attempt_id=attempt.id))

    return render_template('take_quiz.html', quiz=quiz)


@app.route('/quiz/results/<int:attempt_id>')
@student_required
def quiz_results(attempt_id):
    attempt = Attempt.query.get_or_404(attempt_id)

    if attempt.student_id != session['user_id']:
        flash('You can only view your own results.', 'error')
        return redirect(url_for('index'))

    return render_template('quiz_results.html', attempt=attempt)


@app.route('/my_attempts')
@student_required
def my_attempts():
    attempts = Attempt.query.filter_by(student_id=session['user_id']).order_by(
        Attempt.submitted_at.desc()
    ).all()
    return render_template('my_attempts.html', attempts=attempts)


# ============================================
# ERROR HANDLERS
# ============================================
@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html'), 404


@app.errorhandler(500)
def internal_server_error(e):
    return render_template('500.html'), 500


if __name__ == '__main__':
    app.run(debug=True)