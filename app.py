import os
from datetime import datetime
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
    SECRET_KEY=os.environ.get("SECRET_KEY", "local-development-key-change-before-deploying"),
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
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


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
        password = request.form.get("password", "")
        if not business_name or len(business_name) > 120:
            flash("Enter a business name (up to 120 characters).", "error")
        elif not email or len(email) > 255 or "@" not in email:
            flash("Enter a valid email address.", "error")
        elif len(password) < 10:
            flash("Use a password with at least 10 characters.", "error")
        elif User.query.filter_by(email=email).first():
            flash("An account with that email already exists. Please sign in.", "error")
        else:
            user = User(business_name=business_name, email=email)
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


if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG", "false").lower() == "true")
