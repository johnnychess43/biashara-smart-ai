import os
import hashlib
import secrets
import smtplib
import urllib.parse
import urllib.request
import base64
from email.message import EmailMessage
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from functools import wraps

from flask import Flask, abort, flash, redirect, render_template, request, url_for
from flask_login import (
    LoginManager, UserMixin, current_user, login_required, login_user, logout_user
)
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect
from werkzeug.security import check_password_hash, generate_password_hash

app = Flask(__name__)
os.makedirs(app.instance_path, exist_ok=True)

database_url = os.environ.get("DATABASE_URL", "sqlite:///" + os.path.join(app.instance_path, "biashara.db"))
if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

app.config.update(
    SECRET_KEY=os.environ.get("SECRET_KEY") or "local-development-key-change-before-deploying",
    SQLALCHEMY_DATABASE_URI=database_url,
    SQLALCHEMY_TRACK_MODIFICATIONS=False,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE", "false").lower() == "true",
    REMEMBER_COOKIE_HTTPONLY=True,
    REMEMBER_COOKIE_SECURE=os.environ.get("COOKIE_SECURE", "false").lower() == "true",
)

db = SQLAlchemy(app)
csrf = CSRFProtect(app)
login_manager = LoginManager(app)
login_manager.login_view = "login"
login_manager.login_message = "Please sign in to continue."
login_manager.login_message_category = "info"


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    business_name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    phone = db.Column(db.String(32), unique=True, nullable=True, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class PasswordResetCode(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    code_hash = db.Column(db.String(64), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    used_at = db.Column(db.DateTime, nullable=True)
    attempts = db.Column(db.Integer, nullable=False, default=0)
    user = db.relationship("User")


class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    sku = db.Column(db.String(60), nullable=True)
    quantity = db.Column(db.Integer, nullable=False, default=0)
    cost_price = db.Column(db.Numeric(12, 2), nullable=False)
    selling_price = db.Column(db.Numeric(12, 2), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class Sale(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    product_id = db.Column(db.Integer, db.ForeignKey("product.id"), nullable=False)
    product_name = db.Column(db.String(120), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    unit_price = db.Column(db.Numeric(12, 2), nullable=False)
    unit_cost = db.Column(db.Numeric(12, 2), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    @property
    def revenue(self):
        return self.unit_price * self.quantity

    @property
    def cost_of_goods(self):
        return self.unit_cost * self.quantity

    @property
    def gross_profit(self):
        return self.revenue - self.cost_of_goods


class Expense(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    title = db.Column(db.String(120), nullable=False)
    category = db.Column(db.String(60), nullable=False)
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    notes = db.Column(db.String(500), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


@app.after_request
def add_security_headers(response):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    response.headers.setdefault("Content-Security-Policy", "default-src 'self'; base-uri 'self'; object-src 'none'; frame-ancestors 'none'; form-action 'self';")
    if request.path in {"/login", "/register", "/forgot-password", "/reset-password"}:
        response.headers.setdefault("Cache-Control", "no-store")
    return response


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


def money(value):
    return Decimal(str(value or 0)).quantize(Decimal("0.01"))


def positive_amount(raw, field_name):
    try:
        value = Decimal(raw)
    except (InvalidOperation, TypeError):
        raise ValueError(f"Enter a valid {field_name}.")
    if not value.is_finite() or value <= 0:
        raise ValueError(f"{field_name.capitalize()} must be greater than zero.")
    return value.quantize(Decimal("0.01"))


@app.context_processor
def inject_helpers():
    return {"money": money, "now_year": datetime.utcnow().year}


@app.get("/")
def index():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    return render_template("landing.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        business_name = request.form.get("business_name", "").strip()
        email = request.form.get("email", "").strip().lower()
        phone = request.form.get("phone", "").strip() or None
        password = request.form.get("password", "")
        if not business_name or len(business_name) > 120:
            flash("Enter a business name (up to 120 characters).", "error")
        elif not email or len(email) > 255 or "@" not in email:
            flash("Enter a valid email address.", "error")
        elif phone and (len(phone) > 32 or not phone.startswith("+") or not phone[1:].isdigit()):
            flash("Enter a phone number in international format, e.g. +254712345678.", "error")
        elif phone and User.query.filter_by(phone=phone).first():
            flash("That phone number is already linked to an account.", "error")
        elif len(password) < 10:
            flash("Use a password with at least 10 characters.", "error")
        elif User.query.filter_by(email=email).first():
            flash("An account with that email already exists. Please sign in.", "error")
        else:
            user = User(business_name=business_name, email=email, phone=phone)
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            login_user(user)
            flash("Your business workspace is ready. Let's get started!", "success")
            return redirect(url_for("dashboard"))
    return render_template("auth.html", mode="register")


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = User.query.filter_by(email=email).first()
        if user and user.check_password(password):
            login_user(user)
            return redirect(request.args.get("next") if request.args.get("next", "").startswith("/") and not request.args.get("next", "").startswith("//") else url_for("dashboard"))
        flash("Email or password was incorrect.", "error")
    return render_template("auth.html", mode="login")



def deliver_reset_code(user, code, channel):
    """Send reset codes through configured SMTP or Twilio; never expose them in responses."""
    if channel == "phone" and user.phone:
        sid = os.environ.get("TWILIO_ACCOUNT_SID", "").strip()
        token = os.environ.get("TWILIO_AUTH_TOKEN", "").strip()
        from_number = os.environ.get("TWILIO_FROM_NUMBER", "").strip()
        if not (sid and token and from_number):
            app.logger.warning("Password reset SMS is not configured.")
            return False
        payload = urllib.parse.urlencode({"To": user.phone, "From": from_number,
                                          "Body": f"Your BiasharaSmart password reset code is {code}. It expires in 10 minutes."}).encode()
        auth = base64.b64encode(f"{sid}:{token}".encode()).decode()
        req = urllib.request.Request(
            f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json",
            data=payload, headers={"Authorization": f"Basic {auth}"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                return 200 <= response.status < 300
        except Exception:
            app.logger.exception("Password reset SMS delivery failed.")
            return False
    if channel != "email" or not user.email:
        return False
    host = os.environ.get("SMTP_HOST", "").strip()
    sender = os.environ.get("SMTP_FROM", os.environ.get("SMTP_USERNAME", "")).strip()
    if not (host and sender and user.email):
        app.logger.warning("Password reset email is not configured.")
        return False
    message = EmailMessage()
    message["Subject"] = "Your BiasharaSmart password reset code"
    message["From"] = sender
    message["To"] = user.email
    message.set_content(f"Your password reset code is {code}. It expires in 10 minutes. If you did not request this, ignore this email.")
    try:
        port = int(os.environ.get("SMTP_PORT", "587"))
        with smtplib.SMTP(host, port, timeout=10) as server:
            server.starttls()
            username = os.environ.get("SMTP_USERNAME", "").strip()
            password = os.environ.get("SMTP_PASSWORD", "")
            if username:
                server.login(username, password)
            server.send_message(message)
        return True
    except Exception:
        app.logger.exception("Password reset email delivery failed.")
        return False


@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        identifier = request.form.get("identifier", "").strip()
        user = User.query.filter(
            db.or_(User.email == identifier.lower(), User.phone == identifier)
        ).first() if identifier else None
        channel = "email" if user and user.email == identifier.lower() else "phone"
        now = datetime.utcnow()
        # Keep responses identical for known and unknown accounts.
        if user:
            recent_count = PasswordResetCode.query.filter(
                PasswordResetCode.user_id == user.id,
                PasswordResetCode.created_at >= now - timedelta(hours=1)
            ).count()
            recent_code = PasswordResetCode.query.filter_by(user_id=user.id, used_at=None).order_by(
                PasswordResetCode.created_at.desc()).first()
            if recent_count < 3 and not (recent_code and recent_code.created_at >= now - timedelta(seconds=60)):
                code = f"{secrets.randbelow(1_000_000):06d}"
                reset = PasswordResetCode(
                    user_id=user.id,
                    code_hash=hashlib.sha256(code.encode()).hexdigest(),
                    created_at=now,
                    expires_at=now + timedelta(minutes=10),
                )
                db.session.add(reset)
                db.session.commit()
                if not deliver_reset_code(user, code, channel):
                    # Do not pretend delivery succeeded; keep the public response generic.
                    app.logger.error("A password reset code could not be delivered for user id %s.", user.id)
        flash("If the account matches the details provided, a reset code will be sent using its registered contact. Check your inbox or messages.", "info")
        return redirect(url_for("reset_password"))
    return render_template("forgot_password.html")


@app.route("/reset-password", methods=["GET", "POST"])
def reset_password():
    if request.method == "POST":
        identifier = request.form.get("identifier", "").strip()
        code = request.form.get("code", "").strip()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")
        user = User.query.filter(
            db.or_(User.email == identifier.lower(), User.phone == identifier)
        ).first() if identifier else None
        reset = PasswordResetCode.query.filter_by(user_id=user.id, used_at=None).order_by(
            PasswordResetCode.created_at.desc()).first() if user else None
        valid_code = bool(reset and reset.expires_at >= datetime.utcnow() and reset.attempts < 5 and
                          secrets.compare_digest(reset.code_hash, hashlib.sha256(code.encode()).hexdigest()))
        if reset and not valid_code:
            reset.attempts += 1
            if reset.attempts >= 5:
                reset.used_at = datetime.utcnow()
            db.session.commit()
        if not valid_code:
            flash("The reset details are invalid or expired. Request a new code and try again.", "error")
        elif len(password) < 10 or password != confirm:
            flash("Use a password of at least 10 characters and make sure both password fields match.", "error")
        else:
            user.set_password(password)
            reset.used_at = datetime.utcnow()
            db.session.query(PasswordResetCode).filter(
                PasswordResetCode.user_id == user.id,
                PasswordResetCode.id != reset.id,
                PasswordResetCode.used_at.is_(None)
            ).update({PasswordResetCode.used_at: datetime.utcnow()})
            db.session.commit()
            flash("Your password has been reset. Please sign in with your new password.", "success")
            return redirect(url_for("login"))
    return render_template("reset_password.html")



@app.post("/logout")
@login_required
def logout():
    logout_user()
    flash("You have been signed out.", "success")
    return redirect(url_for("index"))


@app.get("/dashboard")
@login_required
def dashboard():
    products = Product.query.filter_by(user_id=current_user.id).all()
    sales = Sale.query.filter_by(user_id=current_user.id).order_by(Sale.created_at.desc()).limit(6).all()
    expenses = Expense.query.filter_by(user_id=current_user.id).order_by(Expense.created_at.desc()).limit(5).all()
    all_sales = Sale.query.filter_by(user_id=current_user.id).all()
    all_expenses = Expense.query.filter_by(user_id=current_user.id).all()
    revenue = sum((sale.revenue for sale in all_sales), Decimal("0.00"))
    cogs = sum((sale.cost_of_goods for sale in all_sales), Decimal("0.00"))
    expense_total = sum((item.amount for item in all_expenses), Decimal("0.00"))
    low_stock = sum(1 for product in products if product.quantity <= 5)
    return render_template(
        "dashboard.html", products=products, sales=sales, expenses=expenses,
        revenue=revenue, cogs=cogs, gross_profit=revenue-cogs,
        expense_total=expense_total, net_profit=revenue-cogs-expense_total,
        stock_value=sum((p.cost_price * p.quantity for p in products), Decimal("0.00")),
        low_stock=low_stock,
    )


@app.route("/products", methods=["GET", "POST"])
@login_required
def products():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        sku = request.form.get("sku", "").strip()[:60] or None
        try:
            quantity = int(request.form.get("quantity", "0"))
            cost_price = positive_amount(request.form.get("cost_price", ""), "cost price")
            selling_price = positive_amount(request.form.get("selling_price", ""), "selling price")
            if not name or len(name) > 120:
                raise ValueError("Enter a product name (up to 120 characters).")
            if quantity < 0 or quantity > 100000000:
                raise ValueError("Stock quantity cannot be negative.")
            product = Product(user_id=current_user.id, name=name, sku=sku, quantity=quantity,
                              cost_price=cost_price, selling_price=selling_price)
            db.session.add(product)
            db.session.commit()
            flash("Product added to your inventory.", "success")
            return redirect(url_for("products"))
        except (ValueError, TypeError) as exc:
            db.session.rollback()
            flash(str(exc), "error")
    items = Product.query.filter_by(user_id=current_user.id).order_by(Product.name.asc()).all()
    return render_template("products.html", products=items)


@app.route("/sales", methods=["GET", "POST"])
@login_required
def sales():
    if request.method == "POST":
        try:
            product_id = int(request.form.get("product_id", "0"))
            quantity = int(request.form.get("quantity", "0"))
            product = Product.query.filter_by(id=product_id, user_id=current_user.id).first()
            if not product:
                raise ValueError("Choose one of your own products.")
            if quantity <= 0:
                raise ValueError("Quantity must be at least 1.")
            if quantity > product.quantity:
                raise ValueError(f"Only {product.quantity} unit(s) are currently in stock.")
            sale = Sale(user_id=current_user.id, product_id=product.id, product_name=product.name,
                        quantity=quantity, unit_price=product.selling_price, unit_cost=product.cost_price)
            product.quantity -= quantity
            db.session.add(sale)
            db.session.commit()
            flash("Sale recorded and stock updated.", "success")
            return redirect(url_for("sales"))
        except (ValueError, TypeError):
            db.session.rollback()
            flash(str(__import__("sys").exc_info()[1]), "error")
    products_list = Product.query.filter_by(user_id=current_user.id).filter(Product.quantity > 0).order_by(Product.name.asc()).all()
    sales_list = Sale.query.filter_by(user_id=current_user.id).order_by(Sale.created_at.desc()).limit(100).all()
    return render_template("sales.html", products=products_list, sales=sales_list)


@app.route("/expenses", methods=["GET", "POST"])
@login_required
def expenses():
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        category = request.form.get("category", "Other").strip()
        notes = request.form.get("notes", "").strip()[:500] or None
        try:
            amount = positive_amount(request.form.get("amount", ""), "amount")
            if not title or len(title) > 120:
                raise ValueError("Enter an expense description (up to 120 characters).")
            if category not in {"Rent", "Transport", "Utilities", "Wages", "Marketing", "Supplies", "Other"}:
                category = "Other"
            db.session.add(Expense(user_id=current_user.id, title=title, category=category,
                                   amount=amount, notes=notes))
            db.session.commit()
            flash("Expense saved.", "success")
            return redirect(url_for("expenses"))
        except (ValueError, TypeError):
            db.session.rollback()
            flash(str(__import__("sys").exc_info()[1]), "error")
    expenses_list = Expense.query.filter_by(user_id=current_user.id).order_by(Expense.created_at.desc()).limit(100).all()
    return render_template("expenses.html", expenses=expenses_list)


@app.get("/health")
def health():
    return {"status": "ok"}


with app.app_context():
    db.create_all()
    # Add the optional phone column for existing SQLite installations without requiring a data reset.
    inspector = __import__("sqlalchemy").inspect(db.engine)
    if "user" in inspector.get_table_names() and "phone" not in {column["name"] for column in inspector.get_columns("user")}:
        with db.engine.begin() as connection:
            connection.exec_driver_sql("ALTER TABLE user ADD COLUMN phone VARCHAR(32)")
    if "password_reset_code" in inspector.get_table_names() and "attempts" not in {column["name"] for column in inspector.get_columns("password_reset_code")}:
        with db.engine.begin() as connection:
            connection.exec_driver_sql("ALTER TABLE password_reset_code ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0")
    try:
        with db.engine.begin() as connection:
            connection.exec_driver_sql("CREATE UNIQUE INDEX IF NOT EXISTS ix_user_phone ON user (phone)")
    except Exception:
        app.logger.exception("Could not create phone lookup index.")


if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG", "false").lower() == "true")
