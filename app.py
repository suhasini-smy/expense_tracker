
import os
from datetime import datetime, timezone , date
from decimal import Decimal
from sqlalchemy import or_

from dotenv import load_dotenv
from flask import (
    Flask, render_template, request,
    redirect, url_for, flash
)
from flask_sqlalchemy import SQLAlchemy
from flask_login import (
    LoginManager, UserMixin, login_user,
    login_required, logout_user, current_user
)
from flask_wtf.csrf import CSRFProtect
from sqlalchemy.exc import IntegrityError
from werkzeug.security import (
    generate_password_hash, check_password_hash
)


load_dotenv()

app = Flask(__name__)

app.config["SECRET_KEY"] = os.getenv("SECRET_KEY")
if not app.config["SECRET_KEY"]:
    raise RuntimeError("Please set SECRET_KEY in your .env file")

db_user = os.getenv("DB_USER", "root")
db_password = os.getenv("DB_PASSWORD", "")
db_host = os.getenv("DB_HOST", "localhost")
db_port = os.getenv("DB_PORT", "3306")
db_name = os.getenv("DB_NAME", "expense_tracker_db")

from urllib.parse import quote_plus

app.config["SQLALCHEMY_DATABASE_URI"] = (
    f"mysql+pymysql://{quote_plus(db_user)}:"
    f"{quote_plus(db_password)}@{db_host}:{db_port}/{db_name}"
)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = "login"
login_manager.login_message_category = "info"
csrf = CSRFProtect(app)


# Database model: one row for each user
class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(
        db.DateTime, default=lambda: datetime.now(timezone.utc),
        nullable=False
    )

class Expense(db.Model):
    __tablename__ = "expenses"

    id = db.Column(db.Integer, primary_key=True)

    title = db.Column(db.String(150), nullable=False)

    amount = db.Column(db.Numeric(10, 2), nullable=False)

    category = db.Column(
        db.String(100),
        nullable=False,
        default="Other"
    )

    description = db.Column(db.Text, nullable=True)

    expense_date = db.Column(
        db.Date,
        nullable=False,
        default=datetime.utcnow
    )

    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow
    )

    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id"),
        nullable=False,
        index=True
    )

    user = db.relationship("User", backref="expenses")


@login_manager.user_loader
def load_user(user_id):
    try:
        return db.session.get(User, int(user_id))
    except (ValueError, TypeError):
        return None


@app.route("/")
def home():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if not username or not email or not password:
            flash("Please fill in every field.", "danger")
        elif len(username) > 80:
            flash("Username must be 80 characters or fewer.", "danger")
        elif len(email) > 255 or "@" not in email:
            flash("Please enter a valid email address.", "danger")
        elif len(password) < 8:
            flash("Password must be at least 8 characters.", "danger")
        elif len(password) > 128:
            flash("Password is too long.", "danger")
        else:
            user = User(
                username=username,
                email=email,
                password_hash=generate_password_hash(password)
            )
            try:
                db.session.add(user)
                db.session.commit()
                flash("Account created. Please log in.", "success")
                return redirect(url_for("login"))
            except IntegrityError:
                db.session.rollback()
                flash("That username or email is already registered.", "danger")

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = User.query.filter_by(email=email).first()
        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            flash("Welcome back!", "success")
            return redirect(url_for("dashboard"))
        flash("Invalid email or password.", "danger")
    return render_template("login.html")


@app.route("/dashboard")
@login_required
def dashboard():
    from sqlalchemy import func, extract
    expenses = (
                    Expense.query
                    .filter_by(user_id=current_user.id)
                    .order_by(Expense.expense_date.desc(), Expense.id.desc())
                    .all()
               )

    # Calculate total spending
    total_expenses = (
                        db.session.query(func.coalesce(func.sum(Expense.amount), 0))
                        .filter(Expense.user_id == current_user.id)
                        .scalar()
                     )

    # Calculate current month's spending
    today = date.today()

    monthly_expenses = (
        db.session.query(func.coalesce(func.sum(Expense.amount), 0))
                  .filter(
                            Expense.user_id == current_user.id,
                            extract("year", Expense.expense_date) == today.year,
                            extract("month", Expense.expense_date) == today.month
                         )
                  .scalar()
    )

    # Count expense records
    expense_count = len(expenses)

    # Show the latest 5 expenses
    recent_expenses = expenses[:5]

    #return render_template("dashboard.html")
    return render_template(
                                "dashboard.html",
                                expenses=expenses,
                                recent_expenses=recent_expenses,
                                total_expenses=total_expenses,
                                monthly_expenses=monthly_expenses,
                                expense_count=expense_count
                           )


@app.route("/reports")
@login_required
def reports():
    from sqlalchemy import func, extract

    today = date.today()

    # Prepare labels and totals for the last 6 months
    monthly_labels = []
    monthly_totals = []

    for offset in range(5, -1, -1):
        month_index = today.year * 12 + (today.month - 1) - offset
        year = month_index // 12
        month = month_index % 12 + 1
        monthly_labels.append(date(year, month, 1).strftime("%b %Y"))

        total = (
            db.session.query(
                func.coalesce(func.sum(Expense.amount), 0)
            )
            .filter(
                Expense.user_id == current_user.id,
                extract("year", Expense.expense_date) == year,
                extract("month", Expense.expense_date) == month
            )
            .scalar()
        )

        monthly_totals.append(float(total or 0))

    # Calculate spending grouped by category
    category_rows = (
        db.session.query(
            Expense.category,
            func.sum(Expense.amount)
        )
        .filter(Expense.user_id == current_user.id)
        .group_by(Expense.category)
        .order_by(func.sum(Expense.amount).desc())
        .all()
    )

    category_labels = [row[0] for row in category_rows]
    category_totals = [float(row[1] or 0) for row in category_rows]

    return render_template(
                                "reports.html",
                                monthly_labels=monthly_labels,
                                monthly_totals=monthly_totals,
                                category_labels=category_labels,
                                category_totals=category_totals
                          )

@app.route("/add-expense", methods=["GET", "POST"])
@login_required
def add_expense():
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        amount_text = request.form.get("amount", "").strip()
        category = request.form.get("category", "").strip()
        description = request.form.get("description", "").strip()
        expense_date_text = request.form.get("expense_date", "").strip()

        if not title or not amount_text or not category or not expense_date_text:
            flash("Please fill in all required fields.", "danger")
            return render_template("add_expense.html")

        if len(title) > 150 or len(category) > 100:
            flash("Title or category is too long.", "danger")
            return render_template("add_expense.html")

        if len(description) > 5000:
            flash("Description is too long.", "danger")
            return render_template("add_expense.html")

        try:
            amount = Decimal(amount_text)
            parsed_date = date.fromisoformat(expense_date_text)

            if not amount.is_finite() or amount <= 0:
                raise ValueError

            if amount >= Decimal("100000000"):
                raise ValueError

        except (ValueError, ArithmeticError):
            flash("Enter a valid positive amount and date.", "danger")
            return render_template("add_expense.html")

        expense = Expense(
                            title=title,
                            amount=amount,
                            category=category,
                            description=description or None,
                            expense_date=parsed_date,
                            user_id=current_user.id
                        )

        try:
            db.session.add(expense)
            db.session.commit()
            flash("Expense added successfully!", "success")
            return redirect(url_for("dashboard"))

        except Exception:
            db.session.rollback()
            app.logger.exception("Failed to save expense")
            flash("Could not save the expense. Please try again.", "danger")
    return render_template("add_expense.html")


@app.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("login"))




@app.route("/edit-expense/<int:expense_id>", methods=["GET", "POST"])
@login_required
def edit_expense(expense_id):
    expense = Expense.query.filter_by(
                                        id=expense_id,
                                        user_id=current_user.id
                                     ).first_or_404()

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        amount_text = request.form.get("amount", "").strip()
        category = request.form.get("category", "").strip()
        description = request.form.get("description", "").strip()
        expense_date_text = request.form.get("expense_date", "").strip()

        # Validate required fields.
        if not title or not amount_text or not category or not expense_date_text:
            flash("Please fill in all required fields.", "danger")
            return render_template("edit_expense.html", expense=expense)

        if len(title) > 150 or len(category) > 100:
            flash("Title or category is too long.", "danger")
            return render_template("edit_expense.html", expense=expense)

        if len(description) > 5000:
            flash("Description must be 5000 characters or fewer.", "danger")
            return render_template("edit_expense.html", expense=expense)

        # Validate amount and date.
        try:
            amount = Decimal(amount_text)
            parsed_date = date.fromisoformat(expense_date_text)

            if not amount.is_finite():
                raise ValueError("Amount must be finite.")

            if amount <= 0 or amount >= Decimal("100000000"):
                raise ValueError("Amount is outside the allowed range.")

            # Numeric(10, 2) supports two decimal places.
            if amount.as_tuple().exponent < -2:
                raise ValueError("Amount can have at most two decimal places.")

        except (InvalidOperation, ValueError, OverflowError):
            flash(
                "Enter a valid amount (maximum two decimal places) "
                "and a valid date.",
                "danger"
            )
            return render_template("edit_expense.html", expense=expense)

        # Update the existing record.
        expense.title = title
        expense.amount = amount
        expense.category = category
        expense.description = description or None
        expense.expense_date = parsed_date

        try:
            db.session.commit()
            flash("Expense updated successfully!", "success")
            return redirect(url_for("dashboard"))
        except Exception:
            db.session.rollback()
            app.logger.exception("Failed to update expense")
            flash("Could not update the expense. Please try again.", "danger")
    return render_template("edit_expense.html", expense=expense)


@app.route("/delete-expense/<int:expense_id>", methods=["POST"])
@login_required
def delete_expense(expense_id):
    expense = Expense.query.filter_by(
        id=expense_id,
        user_id=current_user.id
    ).first_or_404()

    try:
        db.session.delete(expense)
        db.session.commit()

        flash("Expense deleted successfully.", "success")

    except Exception:
        db.session.rollback()
        app.logger.exception("Failed to delete expense")
        flash("Could not delete the expense. Please try again.", "danger")

    return redirect(url_for("dashboard"))


if __name__ == "__main__":
    with app.app_context():
        db.create_all()

    app.run(debug=True)
