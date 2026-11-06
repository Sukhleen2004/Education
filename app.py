import os
import re
from datetime import date
from functools import wraps

import mysql.connector
from flask import (
    Flask, render_template, request, redirect,
    url_for, flash, session
)
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get(
    "FLASK_SECRET_KEY",
    "replace-this-with-a-long-random-secret-key"
)

DB_CONFIG = {
    "host": "localhost",
    "user": "root",
    "password": "abc@123",
    "database": "travel_tour"
}


def get_db():
    return mysql.connector.connect(**DB_CONFIG)


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            flash("Please log in first.", "warning")
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


@app.route("/")
@login_required
def home():
    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT p.package_id, p.package_name, p.duration,
               p.price, p.description,
               d.name AS destination, d.country
        FROM tour_packages p
        JOIN destinations d
          ON p.destination_id = d.destination_id
        ORDER BY d.name, p.package_name
    """)
    packages = cursor.fetchall()

    cursor.execute("SELECT * FROM destinations ORDER BY name")
    destinations = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template(
        "index.html",
        packages=packages,
        destinations=destinations,
        today=date.today().isoformat()
    )


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if "user_id" in session:
        return redirect(url_for("home"))

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")

        if not all([name, email, password, confirm]):
            flash("Please fill in every field.", "error")
        elif not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
            flash("Enter a valid email address.", "error")
        elif len(password) < 8:
            flash("Password must be at least 8 characters.", "error")
        elif password != confirm:
            flash("Passwords do not match.", "error")
        else:
            conn = get_db()
            cursor = conn.cursor()
            try:
                cursor.execute("""
                    INSERT INTO users (name, email, password_hash)
                    VALUES (%s, %s, %s)
                """, (name, email, generate_password_hash(password)))
                conn.commit()
                flash("Account created. Please log in.", "success")
                return redirect(url_for("login"))
            except mysql.connector.IntegrityError:
                conn.rollback()
                flash("This email is already registered.", "error")
            finally:
                cursor.close()
                conn.close()

    return render_template("signup.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if "user_id" in session:
        return redirect(url_for("home"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT * FROM users WHERE email = %s", (email,)
        )
        user = cursor.fetchone()
        cursor.close()
        conn.close()

        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session["user_id"] = user["user_id"]
            session["user_name"] = user["name"]
            session["user_email"] = user["email"]
            return redirect(url_for("home"))

        flash("Invalid email or password.", "error")

    return render_template("login.html")


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    flash("You have logged out.", "success")
    return redirect(url_for("login"))


@app.route("/book", methods=["POST"])
@login_required
def book():
    package_id = request.form.get("package_id", type=int)
    travel_date = request.form.get("travel_date", "")
    persons = request.form.get("persons", type=int)
    phone = request.form.get("phone", "").strip()
    payment_method = request.form.get("payment_method", "")

    if not package_id or not persons or persons < 1 or not phone:
        flash("Please complete all booking fields.", "error")
        return redirect(url_for("home") + "#booking")

    try:
        selected_date = date.fromisoformat(travel_date)
        if selected_date < date.today():
            flash("Travel date cannot be in the past.", "error")
            return redirect(url_for("home") + "#booking")
    except ValueError:
        flash("Please select a valid travel date.", "error")
        return redirect(url_for("home") + "#booking")

    if payment_method not in {"UPI", "Card", "Net Banking", "Cash"}:
        flash("Please select a payment method.", "error")
        return redirect(url_for("home") + "#booking")

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    try:
        cursor.execute(
            "SELECT user_id, name, email FROM users WHERE user_id = %s",
            (session["user_id"],)
        )
        user = cursor.fetchone()

        if not user:
            session.clear()
            flash("Please log in again.", "error")
            return redirect(url_for("login"))

        cursor.execute(
            "SELECT price FROM tour_packages WHERE package_id = %s",
            (package_id,)
        )
        package = cursor.fetchone()

        if not package:
            flash("Selected package does not exist.", "error")
            return redirect(url_for("home") + "#booking")

        total = package["price"] * persons

        cursor.execute(
            "SELECT customer_id FROM customers WHERE user_id = %s",
            (user["user_id"],)
        )
        customer = cursor.fetchone()

        if customer:
            customer_id = customer["customer_id"]
            cursor.execute("""
                UPDATE customers
                SET name = %s, email = %s, phone = %s
                WHERE customer_id = %s
            """, (user["name"], user["email"], phone, customer_id))
        else:
            cursor.execute("""
                INSERT INTO customers (user_id, name, email, phone)
                VALUES (%s, %s, %s, %s)
            """, (user["user_id"], user["name"], user["email"], phone))
            customer_id = cursor.lastrowid

        cursor.execute("""
            INSERT INTO bookings
                (customer_id, package_id, travel_date,
                 persons, total_amount, status)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (
            customer_id, package_id, travel_date,
            persons, total, "Confirmed"
        ))
        booking_id = cursor.lastrowid

        # Demo record only: no real money is collected.
        cursor.execute("""
            INSERT INTO payments
                (booking_id, amount, payment_method, payment_status)
            VALUES (%s, %s, %s, %s)
        """, (booking_id, total, payment_method, "Pending"))

        conn.commit()
        flash(
            f"Booking #{booking_id} submitted successfully.",
            "success"
        )
        return redirect(url_for("my_bookings"))

    except Exception:
        conn.rollback()
        app.logger.exception("Booking could not be saved")
        flash("Booking failed. Please try again.", "error")
        return redirect(url_for("home") + "#booking")
    finally:
        cursor.close()
        conn.close()


@app.route("/my-bookings")
@login_required
def my_bookings():
    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT b.booking_id, p.package_name,
               d.name AS destination, b.booking_date,
               b.travel_date, b.persons, b.total_amount,
               b.status, pay.payment_method, pay.payment_status
        FROM bookings b
        JOIN customers c ON b.customer_id = c.customer_id
        JOIN tour_packages p ON b.package_id = p.package_id
        JOIN destinations d ON p.destination_id = d.destination_id
        LEFT JOIN payments pay ON b.booking_id = pay.booking_id
        WHERE c.user_id = %s
        ORDER BY b.booking_id DESC
    """, (session["user_id"],))

    bookings = cursor.fetchall()
    cursor.close()
    conn.close()

    return render_template("my_bookings.html", bookings=bookings)


@app.route("/admin")
@login_required
def admin():
    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT b.booking_id, u.name AS customer_name, u.email,
               c.phone, p.package_name, d.name AS destination,
               b.travel_date, b.persons, b.total_amount, b.status,
               pay.payment_method, pay.payment_status
        FROM bookings b
        JOIN customers c ON b.customer_id = c.customer_id
        JOIN users u ON c.user_id = u.user_id
        JOIN tour_packages p ON b.package_id = p.package_id
        JOIN destinations d ON p.destination_id = d.destination_id
        LEFT JOIN payments pay ON b.booking_id = pay.booking_id
        ORDER BY b.booking_id DESC
    """)
    bookings = cursor.fetchall()

    cursor.execute("SELECT COUNT(*) AS n FROM users")
    total_users = cursor.fetchone()["n"]

    cursor.execute("SELECT COUNT(*) AS n FROM bookings")
    total_bookings = cursor.fetchone()["n"]

    cursor.execute("SELECT COUNT(*) AS n FROM destinations")
    total_destinations = cursor.fetchone()["n"]

    cursor.execute("SELECT COUNT(*) AS n FROM tour_packages")
    total_packages = cursor.fetchone()["n"]

    cursor.close()
    conn.close()

    return render_template(
        "admin.html",
        bookings=bookings,
        total_users=total_users,
        total_bookings=total_bookings,
        total_destinations=total_destinations,
        total_packages=total_packages
    )


if __name__ == "__main__":
    app.run(debug=True)
