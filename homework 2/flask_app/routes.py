
from flask import current_app as app
from flask import Blueprint, render_template

main = Blueprint('main', __name__)


@main.route('/')
def home():
    return render_template('home.html')


@main.route('/resume')
def resume():
    resume_data = app.db.getResumeData()
    return render_template('resume.html', resume=resume_data)
