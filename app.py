import os
import re
import uuid
from decimal import Decimal, InvalidOperation
from functools import wraps
from pathlib import Path
from urllib.parse import quote

from flask import Flask, abort, flash, g, redirect, render_template, request, session, url_for, send_from_directory
from flask_wtf import CSRFProtect
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

from config import Config
from database import fetch_all, fetch_one, get_connection, get_settings, init_db, update_settings

app = Flask(__name__)
app.config.from_object(Config)
csrf = CSRFProtect(app)
init_db()

STATUS_OPTIONS = ['Pending', 'Processing', 'Shipped', 'Delivered', 'Cancelled']
HEX_RE = re.compile(r'^#[0-9a-fA-F]{6}$')


def get_store():
    return get_settings()


def whatsapp_number(raw):
    return re.sub(r'\D', '', raw or '')


def wa_link(message):
    number = whatsapp_number(get_store().get('whatsapp'))
    if not number:
        return ''
    return f'https://wa.me/{number}?text={quote(message)}'


def build_order_whatsapp(order, prefix='Hello'):
    store = get_store()
    message = store.get('whatsapp_message', '').replace('{{store_name}}', store.get('store_name', 'BIB-STORE'))
    message = message.replace('{{order_id}}', str(order['id']))
    if message == store.get('whatsapp_message', ''):
        message = f'{prefix} {store.get("store_name", "BIB-STORE")}, I need help with order #{order["id"]}.'
    return message


@app.context_processor
def inject_globals():
    cart = session.get('cart', {})
    cart_count = sum(int(q) for q in cart.values())
    store = get_store()
    return {
        'store': store,
        'cart_count': cart_count,
        'categories': Config.CATEGORIES,
        'status_options': STATUS_OPTIONS,
        'whatsapp_url': wa_link(f'Hello {store.get("store_name", "BIB-STORE")}, I need assistance.'),
        'admin_exists': bool(fetch_one('SELECT id FROM users WHERE is_admin=1 LIMIT 1')),
        'current_year': __import__('datetime').datetime.now().year,
        'is_impersonating': bool(session.get('impersonating_admin_id')),
    }


@app.before_request
def load_user():
    g.user = None
    user_id = session.get('user_id')
    if user_id:
        g.user = fetch_one('SELECT id, name, email, is_admin, created_at FROM users WHERE id = ?', (user_id,))
        if not g.user:
            session.clear()


@app.after_request
def security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'SAMEORIGIN'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    response.headers['Permissions-Policy'] = 'camera=(), microphone=(), geolocation=()'
    return response


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not g.user:
            flash('Please log in to continue.', 'warning')
            return redirect(url_for('login', next=request.path))
        return view(*args, **kwargs)
    return wrapped


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not g.user:
            flash('Please log in as an administrator.', 'warning')
            return redirect(url_for('login', next=request.path))
        if not g.user['is_admin']:
            abort(403)
        return view(*args, **kwargs)
    return wrapped


def valid_email(email):
    return '@' in email and '.' in email.rsplit('@', 1)[-1]


def parse_price(raw):
    try:
        value = Decimal(str(raw).replace(',', '').strip())
        if value < 0:
            raise ValueError
        return float(value)
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError('Invalid price.')


def parse_stock(raw):
    try:
        value = int(raw)
        if value < 0:
            raise ValueError
        return value
    except (ValueError, TypeError):
        raise ValueError('Stock must be a non-negative whole number.')


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']


def save_upload(file):
    if not file or not file.filename:
        return None
    if not allowed_file(file.filename):
        raise ValueError('Only JPG, JPEG, PNG and WEBP images are allowed.')
    safe_name = secure_filename(file.filename)
    if not safe_name or '.' not in safe_name:
        raise ValueError('Invalid image filename.')
    ext = safe_name.rsplit('.', 1)[-1].lower()
    filename = f'{uuid.uuid4().hex}.{ext}'
    file.save(Path(app.config['UPLOAD_FOLDER']) / filename)
    return filename


def delete_upload(filename):
    if not filename:
        return
    path = Path(app.config['UPLOAD_FOLDER']) / Path(filename).name
    try:
        if path.exists():
            path.unlink()
    except OSError:
        pass


def safe_next_url(target):
    if not target:
        return url_for('dashboard') if g.user else url_for('index')
    if target.startswith('/') and not target.startswith('//'):
        return target
    return url_for('dashboard') if g.user else url_for('index')


def product_query():
    q = request.args.get('q', '').strip()
    category = request.args.get('category', '').strip()
    min_price = request.args.get('min_price', '').strip()
    max_price = request.args.get('max_price', '').strip()
    sort = request.args.get('sort', 'newest')
    clauses, params = [], []
    if q:
        clauses.append('(name LIKE ? OR category LIKE ? OR description LIKE ?)')
        like = f'%{q}%'
        params += [like, like, like]
    if category in Config.CATEGORIES:
        clauses.append('category = ?')
        params.append(category)
    try:
        if min_price:
            clauses.append('price >= ?')
            params.append(float(min_price))
        if max_price:
            clauses.append('price <= ?')
            params.append(float(max_price))
    except ValueError:
        pass
    order_map = {
        'price_low': 'price ASC', 'price_high': 'price DESC', 'name': 'name COLLATE NOCASE ASC',
        'oldest': 'created_at ASC', 'newest': 'created_at DESC'
    }
    where = (' WHERE ' + ' AND '.join(clauses)) if clauses else ''
    return fetch_all(f'SELECT * FROM products{where} ORDER BY {order_map.get(sort, "created_at DESC")}', params)


@app.route('/')
def index():
    featured = fetch_all('SELECT * FROM products WHERE stock > 0 ORDER BY created_at DESC LIMIT 8')
    popular = fetch_all('''SELECT p.*, COALESCE(SUM(oi.quantity),0) AS sold FROM products p
                           LEFT JOIN order_items oi ON oi.product_id=p.id GROUP BY p.id
                           ORDER BY sold DESC, p.created_at DESC LIMIT 8''')
    return render_template('index.html', featured=featured, popular=popular)


@app.route('/shop')
def shop():
    return render_template('shop.html', products=product_query())


@app.route('/categories')
def categories():
    counts = {row['category']: row['count'] for row in fetch_all('SELECT category, COUNT(*) AS count FROM products GROUP BY category')}
    return render_template('categories.html', counts=counts)


@app.route('/product/<int:product_id>')
def product(product_id):
    item = fetch_one('SELECT * FROM products WHERE id = ?', (product_id,))
    if not item:
        abort(404)
    related = fetch_all('SELECT * FROM products WHERE category = ? AND id != ? ORDER BY created_at DESC LIMIT 4', (item['category'], product_id))
    return render_template('product.html', product=item, related=related)


@app.route('/uploads/<path:filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], Path(filename).name)


@app.route('/register', methods=['GET', 'POST'])
def register():
    if g.user:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        confirm = request.form.get('confirm_password', '')
        if len(name) < 2 or len(name) > 100:
            flash('Please enter a valid name.', 'danger')
        elif not valid_email(email):
            flash('Please enter a valid email address.', 'danger')
        elif len(password) < 8:
            flash('Password must be at least 8 characters.', 'danger')
        elif password != confirm:
            flash('Passwords do not match.', 'danger')
        elif fetch_one('SELECT id FROM users WHERE email = ?', (email,)):
            flash('An account with that email already exists.', 'danger')
        else:
            with get_connection() as conn:
                cur = conn.execute('INSERT INTO users(name,email,password,is_admin) VALUES(?,?,?,0)', (name, email, generate_password_hash(password)))
                user_id = cur.lastrowid
                conn.commit()
            session.clear(); session['user_id'] = user_id; session.permanent = True
            flash('Account created successfully.', 'success')
            return redirect(url_for('dashboard'))
    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if g.user:
        return redirect(url_for('admin_dashboard') if g.user['is_admin'] else url_for('dashboard'))
    next_url = request.args.get('next', '')
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        user = fetch_one('SELECT * FROM users WHERE email = ?', (email,))
        if not user or not check_password_hash(user['password'], password):
            flash('Invalid email or password.', 'danger')
        else:
            session.clear(); session['user_id'] = user['id']; session.permanent = True
            return redirect(safe_next_url(request.form.get('next') or next_url))
    return render_template('login.html', next_url=next_url)


@app.route('/admin/login')
def admin_login():
    if g.user and g.user['is_admin']:
        return redirect(url_for('admin_dashboard'))
    return redirect(url_for('login', next=url_for('admin_dashboard')))

@app.route('/admin/customers/<int:user_id>/login-as', methods=['POST'])
@admin_required
def admin_login_as_customer(user_id):
    customer = fetch_one('SELECT id, name, email, is_admin FROM users WHERE id=? AND is_admin=0', (user_id,))
    if not customer:
        flash('Customer account was not found.', 'danger')
        return redirect(url_for('admin_customers'))
    admin_id = g.user['id']
    session['impersonating_admin_id'] = admin_id
    session['user_id'] = customer['id']
    session.permanent = True
    flash(f"You are now viewing the store as {customer['name']}.", 'success')
    return redirect(url_for('dashboard'))


@app.route('/admin/return-from-customer', methods=['POST'])
def return_from_customer():
    admin_id = session.get('impersonating_admin_id')
    if not admin_id:
        return redirect(url_for('index'))
    admin = fetch_one('SELECT id, is_admin FROM users WHERE id=? AND is_admin=1', (admin_id,))
    if not admin:
        session.clear()
        flash('Admin session could not be restored.', 'danger')
        return redirect(url_for('login'))
    session.pop('impersonating_admin_id', None)
    session['user_id'] = admin['id']
    session.permanent = True
    flash('Returned to the administrator account.', 'success')
    return redirect(url_for('admin_dashboard'))


@app.route('/logout')
def logout():
    session.clear(); flash('You have been logged out.', 'success'); return redirect(url_for('index'))


@app.route('/dashboard')
@login_required
def dashboard():
    orders = fetch_all('SELECT * FROM orders WHERE user_id = ? ORDER BY created_at DESC LIMIT 5', (g.user['id'],))
    return render_template('dashboard.html', orders=orders)


@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        if len(name) < 2:
            flash('Please enter a valid name.', 'danger')
        else:
            with get_connection() as conn:
                conn.execute('UPDATE users SET name=? WHERE id=?', (name, g.user['id'])); conn.commit()
            flash('Profile updated.', 'success'); return redirect(url_for('profile'))
    return render_template('profile.html')


@app.route('/orders')
@login_required
def orders():
    return render_template('orders.html', orders=fetch_all('SELECT * FROM orders WHERE user_id = ? ORDER BY created_at DESC', (g.user['id'],)))


@app.route('/orders/<int:order_id>')
@login_required
def order_details(order_id):
    order = fetch_one('SELECT * FROM orders WHERE id=? AND user_id=?', (order_id, g.user['id']))
    if not order: abort(404)
    items = fetch_all('SELECT * FROM order_items WHERE order_id=? ORDER BY id', (order_id,))
    wa_message = build_order_whatsapp(order)
    return render_template('order_details.html', order=order, items=items, order_whatsapp_url=wa_link(wa_message))


@app.route('/cart')
def cart():
    cart_data = session.get('cart', {}); products = []; subtotal = 0.0; cleaned = {}
    for pid, qty in cart_data.items():
        try: pid_int, qty_int = int(pid), int(qty)
        except (ValueError, TypeError): continue
        if qty_int <= 0: continue
        item = fetch_one('SELECT * FROM products WHERE id=?', (pid_int,))
        if not item or item['stock'] <= 0: continue
        qty_int = min(qty_int, item['stock']); cleaned[str(pid_int)] = qty_int
        line_total = item['price'] * qty_int; subtotal += line_total
        products.append({'product': item, 'quantity': qty_int, 'line_total': line_total})
    if cleaned != cart_data: session['cart'] = cleaned; session.modified = True
    return render_template('cart.html', items=products, subtotal=subtotal)


@app.post('/buy-now/<int:product_id>')
def buy_now(product_id):
    item = fetch_one('SELECT id, name, stock FROM products WHERE id=?', (product_id,))
    if not item: abort(404)
    if item['stock'] <= 0:
        flash('This product is out of stock.', 'danger'); return redirect(url_for('product', product_id=product_id))
    try: quantity = max(1, int(request.form.get('quantity', 1)))
    except ValueError: quantity = 1
    session['cart'] = {str(product_id): min(quantity, item['stock'])}; session.modified = True
    return redirect(url_for('checkout'))


@app.post('/cart/add/<int:product_id>')
def add_to_cart(product_id):
    item = fetch_one('SELECT id, name, stock FROM products WHERE id=?', (product_id,))
    if not item: abort(404)
    if item['stock'] <= 0:
        flash('This product is out of stock.', 'danger'); return redirect(request.referrer or url_for('shop'))
    try: quantity = max(1, int(request.form.get('quantity', 1)))
    except ValueError: quantity = 1
    cart_data = session.get('cart', {}); current = int(cart_data.get(str(product_id), 0))
    cart_data[str(product_id)] = min(current + quantity, item['stock']); session['cart'] = cart_data; session.modified = True
    flash(f'{item["name"]} added to cart.', 'success')
    return redirect(request.form.get('next') or request.referrer or url_for('cart'))


@app.post('/cart/update/<int:product_id>')
def update_cart(product_id):
    item = fetch_one('SELECT stock FROM products WHERE id=?', (product_id,)); cart_data = session.get('cart', {})
    if not item or item['stock'] <= 0: cart_data.pop(str(product_id), None)
    else:
        try: qty = int(request.form.get('quantity', 1))
        except ValueError: qty = 1
        if qty <= 0: cart_data.pop(str(product_id), None)
        else: cart_data[str(product_id)] = min(qty, item['stock'])
    session['cart'] = cart_data; session.modified = True; return redirect(url_for('cart'))


@app.post('/cart/remove/<int:product_id>')
def remove_from_cart(product_id):
    cart_data = session.get('cart', {}); cart_data.pop(str(product_id), None); session['cart'] = cart_data; session.modified = True
    flash('Item removed from cart.', 'success'); return redirect(url_for('cart'))


@app.post('/cart/clear')
def clear_cart():
    session['cart'] = {}; flash('Cart cleared.', 'success'); return redirect(url_for('cart'))


@app.route('/checkout', methods=['GET', 'POST'])
@login_required
def checkout():
    cart_data = session.get('cart', {})
    if not cart_data:
        flash('Your cart is empty.', 'warning'); return redirect(url_for('shop'))
    items = []; total = 0.0
    for pid, qty in cart_data.items():
        item = fetch_one('SELECT * FROM products WHERE id=?', (pid,))
        if not item or item['stock'] < int(qty):
            flash(f'Stock changed for {item["name"] if item else "one of your items"}. Please review your cart.', 'danger'); return redirect(url_for('cart'))
        line = item['price'] * int(qty); total += line; items.append((item, int(qty), line))
    if request.method == 'POST':
        customer_name = request.form.get('customer_name', '').strip(); phone = request.form.get('phone', '').strip()
        address = request.form.get('address', '').strip(); note = request.form.get('note', '').strip()
        if len(customer_name) < 2 or not phone or len(address) < 5:
            flash('Please complete your name, phone number and delivery address.', 'danger'); return render_template('checkout.html', items=items, total=total)
        try:
            with get_connection() as conn:
                conn.execute('BEGIN IMMEDIATE'); verified = []; final_total = 0.0
                for item, qty, _ in items:
                    current = conn.execute('SELECT * FROM products WHERE id=?', (item['id'],)).fetchone()
                    if not current or current['stock'] < qty: raise ValueError(f'Insufficient stock for {item["name"]}.')
                    line = current['price'] * qty; final_total += line; verified.append((current, qty, line))
                cur = conn.execute('INSERT INTO orders(user_id,customer_name,phone,address,note,total,status) VALUES(?,?,?,?,?,?,?)', (g.user['id'], customer_name, phone, address, note, final_total, 'Pending'))
                order_id = cur.lastrowid
                for current, qty, _ in verified:
                    conn.execute('INSERT INTO order_items(order_id,product_id,product_name,price,quantity) VALUES(?,?,?,?,?)', (order_id, current['id'], current['name'], current['price'], qty))
                    conn.execute('UPDATE products SET stock=stock-? WHERE id=? AND stock>=?', (qty, current['id'], qty))
                conn.commit()
            session['cart'] = {}; flash('Order placed successfully.', 'success'); return redirect(url_for('order_confirmation', order_id=order_id))
        except ValueError as exc:
            flash(str(exc), 'danger'); return redirect(url_for('cart'))
    return render_template('checkout.html', items=items, total=total)


@app.route('/order-confirmation/<int:order_id>')
@login_required
def order_confirmation(order_id):
    order = fetch_one('SELECT * FROM orders WHERE id=? AND user_id=?', (order_id, g.user['id'],))
    if not order: abort(404)
    items = fetch_all('SELECT * FROM order_items WHERE order_id=?', (order_id,))
    return render_template('order_confirmation.html', order=order, items=items, order_whatsapp_url=wa_link(build_order_whatsapp(order, 'Hello')))


@app.route('/setup', methods=['GET', 'POST'])
@app.route('/admin/setup', methods=['GET', 'POST'])
def setup():
    if fetch_one('SELECT id FROM users WHERE is_admin=1 LIMIT 1'):
        return render_template('setup.html', completed=True)
    if request.method == 'POST':
        name = request.form.get('name', '').strip(); email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', ''); confirm = request.form.get('confirm_password', '')
        store_name = request.form.get('store_name', '').strip()[:100] or 'BIB-STORE'
        store_email = request.form.get('store_email', '').strip()[:160]
        phone = request.form.get('phone', '').strip()[:50]
        whatsapp = request.form.get('whatsapp', '').strip()[:50]
        address = request.form.get('address', '').strip()[:250]
        description = request.form.get('description', '').strip()[:500]
        if len(name) < 2 or not valid_email(email) or len(password) < 8 or password != confirm:
            flash('Enter a valid name/email and a password of at least 8 characters. Passwords must match.', 'danger'); return render_template('setup.html', completed=False)
        if store_email and not valid_email(store_email):
            flash('Please enter a valid store email address.', 'danger'); return render_template('setup.html', completed=False)
        with get_connection() as conn:
            if conn.execute('SELECT id FROM users WHERE is_admin=1 LIMIT 1').fetchone(): return render_template('setup.html', completed=True)
            cur = conn.execute('INSERT INTO users(name,email,password,is_admin) VALUES(?,?,?,1)', (name, email, generate_password_hash(password))); admin_id = cur.lastrowid
            conn.commit()
        update_settings({'store_name':store_name,'store_email':store_email,'phone':phone,'whatsapp':whatsapp,'address':address,'description':description or get_store().get('description','')})
        session.clear(); session['user_id'] = admin_id; session.permanent = True
        flash('Store setup complete. You are now the store administrator.', 'success'); return redirect(url_for('admin_dashboard'))
    return render_template('setup.html', completed=False)


@app.route('/admin')
@admin_required
def admin_dashboard():
    stats = {
        'products': fetch_one('SELECT COUNT(*) c FROM products')['c'],
        'orders': fetch_one('SELECT COUNT(*) c FROM orders')['c'],
        'customers': fetch_one('SELECT COUNT(*) c FROM users WHERE is_admin=0')['c'],
        'sales': fetch_one("SELECT COALESCE(SUM(total),0) c FROM orders WHERE status != 'Cancelled'")['c'],
        'pending': fetch_one("SELECT COUNT(*) c FROM orders WHERE status='Pending'")['c'],
        'delivered': fetch_one("SELECT COUNT(*) c FROM orders WHERE status='Delivered'")['c'],
        'low_stock': fetch_one('SELECT COUNT(*) c FROM products WHERE stock BETWEEN 1 AND 5')['c'],
    }
    recent_orders = fetch_all('SELECT o.*, u.email FROM orders o JOIN users u ON u.id=o.user_id ORDER BY o.created_at DESC LIMIT 8')
    low_stock = fetch_all('SELECT * FROM products WHERE stock <= 5 ORDER BY stock ASC LIMIT 8')
    top_products = fetch_all('''SELECT p.id,p.name,p.image,COALESCE(SUM(oi.quantity),0) sold,COALESCE(SUM(oi.quantity*oi.price),0) revenue
                               FROM products p LEFT JOIN order_items oi ON oi.product_id=p.id GROUP BY p.id ORDER BY sold DESC LIMIT 5''')
    status_counts = {s: fetch_one('SELECT COUNT(*) c FROM orders WHERE status=?', (s,))['c'] for s in STATUS_OPTIONS}
    recent_customers = fetch_all('SELECT name,email,created_at FROM users WHERE is_admin=0 ORDER BY created_at DESC LIMIT 5')
    return render_template('admin_dashboard.html', stats=stats, recent_orders=recent_orders, low_stock=low_stock, top_products=top_products, status_counts=status_counts, recent_customers=recent_customers)


@app.route('/admin/products')
@admin_required
def admin_products():
    products = fetch_all('SELECT * FROM products ORDER BY created_at DESC')
    return render_template('admin_products.html', products=products)


@app.post('/admin/products/upload-image')
@admin_required
def upload_product_image():
    """Upload a product image immediately after selection.

    Mobile browsers sometimes lose access to temporary files between selecting
    an image and submitting a multipart form (ERR_UPLOAD_FILE_CHANGED).
    Uploading immediately gives the server a stable filename so the final
    product form no longer depends on the temporary browser file handle.
    """
    try:
        uploaded = request.files.get('image')
        filename = save_upload(uploaded)
        if not filename:
            return {'ok': False, 'message': 'Please choose an image.'}, 400
        return {'ok': True, 'filename': filename, 'url': url_for('uploaded_file', filename=filename)}
    except ValueError as exc:
        return {'ok': False, 'message': str(exc)}, 400


@app.route('/admin/products/add', methods=['GET', 'POST'])
@admin_required
def add_product():
    if request.method == 'POST':
        name = request.form.get('name', '').strip(); category = request.form.get('category', '').strip(); description = request.form.get('description', '').strip(); image = None
        try:
            price = parse_price(request.form.get('price', '')); stock = parse_stock(request.form.get('stock', ''))
            if len(name) < 2 or category not in Config.CATEGORIES: raise ValueError('Please provide a valid product name and category.')
            image = request.form.get('uploaded_image', '').strip() or None
            if not image:
                image = save_upload(request.files.get('image'))
            elif Path(image).name != image or not (Path(app.config['UPLOAD_FOLDER']) / image).is_file():
                raise ValueError('The uploaded product image could not be found. Please choose it again.')
            with get_connection() as conn:
                conn.execute('INSERT INTO products(name,category,price,stock,description,image) VALUES(?,?,?,?,?,?)', (name, category, price, stock, description, image)); conn.commit()
            flash('Product added successfully.', 'success'); return redirect(url_for('admin_products'))
        except ValueError as exc:
            if image: delete_upload(image)
            flash(str(exc), 'danger')
    return render_template('add_product.html')


@app.route('/admin/products/<int:product_id>/edit', methods=['GET', 'POST'])
@admin_required
def edit_product(product_id):
    item = fetch_one('SELECT * FROM products WHERE id=?', (product_id,))
    if not item: abort(404)
    if request.method == 'POST':
        name = request.form.get('name', '').strip(); category = request.form.get('category', '').strip(); description = request.form.get('description', '').strip(); new_image = None
        try:
            price = parse_price(request.form.get('price', '')); stock = parse_stock(request.form.get('stock', ''))
            if len(name) < 2 or category not in Config.CATEGORIES: raise ValueError('Please provide a valid product name and category.')
            uploaded_image = request.form.get('uploaded_image', '').strip() or None
            uploaded = request.files.get('image')
            if uploaded_image:
                if Path(uploaded_image).name != uploaded_image or not (Path(app.config['UPLOAD_FOLDER']) / uploaded_image).is_file():
                    raise ValueError('The uploaded product image could not be found. Please choose it again.')
                new_image = uploaded_image
            elif uploaded and uploaded.filename:
                new_image = save_upload(uploaded)
            image = new_image or item['image']
            with get_connection() as conn:
                conn.execute('UPDATE products SET name=?,category=?,price=?,stock=?,description=?,image=? WHERE id=?', (name, category, price, stock, description, image, product_id)); conn.commit()
            if new_image and item['image']: delete_upload(item['image'])
            flash('Product updated successfully.', 'success'); return redirect(url_for('admin_products'))
        except ValueError as exc:
            if new_image: delete_upload(new_image)
            flash(str(exc), 'danger')
    return render_template('edit_product.html', product=item)


@app.post('/admin/products/<int:product_id>/delete')
@admin_required
def delete_product(product_id):
    item = fetch_one('SELECT * FROM products WHERE id=?', (product_id,))
    if not item: abort(404)
    try:
        with get_connection() as conn:
            conn.execute('DELETE FROM products WHERE id=?', (product_id,)); conn.commit()
    except Exception:
        flash('This product is attached to an order. Edit it or set stock to 0 instead.', 'danger'); return redirect(url_for('admin_products'))
    delete_upload(item['image']); flash('Product deleted.', 'success'); return redirect(url_for('admin_products'))


@app.route('/admin/orders')
@admin_required
def admin_orders():
    status = request.args.get('status', '').strip()
    if status in STATUS_OPTIONS:
        orders = fetch_all('SELECT o.*, u.email FROM orders o JOIN users u ON u.id=o.user_id WHERE o.status=? ORDER BY o.created_at DESC', (status,))
    else:
        orders = fetch_all('SELECT o.*, u.email FROM orders o JOIN users u ON u.id=o.user_id ORDER BY o.created_at DESC')
    return render_template('admin_orders.html', orders=orders, selected_status=status)


@app.route('/admin/orders/<int:order_id>', methods=['GET', 'POST'])
@admin_required
def admin_order_details(order_id):
    order = fetch_one('SELECT o.*, u.email FROM orders o JOIN users u ON u.id=o.user_id WHERE o.id=?', (order_id,))
    if not order: abort(404)
    if request.method == 'POST':
        status = request.form.get('status', '')
        if status not in STATUS_OPTIONS: flash('Invalid order status.', 'danger')
        else:
            with get_connection() as conn:
                conn.execute('UPDATE orders SET status=? WHERE id=?', (status, order_id)); conn.commit()
            flash('Order status updated.', 'success'); return redirect(url_for('admin_order_details', order_id=order_id))
    items = fetch_all('SELECT * FROM order_items WHERE order_id=?', (order_id,))
    return render_template('admin_order_details.html', order=order, items=items, order_whatsapp_url=wa_link(build_order_whatsapp(order, 'Hello')))


@app.route('/admin/customers')
@admin_required
def admin_customers():
    customers = fetch_all('''SELECT u.id,u.name,u.email,u.created_at,COUNT(o.id) order_count,
                             COALESCE(SUM(CASE WHEN o.status!='Cancelled' THEN o.total ELSE 0 END),0) spent
                             FROM users u LEFT JOIN orders o ON o.user_id=u.id WHERE u.is_admin=0
                             GROUP BY u.id ORDER BY u.created_at DESC''')
    return render_template('admin_customers.html', customers=customers)


@app.route('/admin/customer-access')
@admin_required
def admin_customer_access():
    customers = fetch_all('''SELECT u.id,u.name,u.email,u.created_at,COUNT(o.id) order_count,
                             COALESCE(SUM(CASE WHEN o.status!='Cancelled' THEN o.total ELSE 0 END),0) spent
                             FROM users u LEFT JOIN orders o ON o.user_id=u.id WHERE u.is_admin=0
                             GROUP BY u.id ORDER BY u.created_at DESC''')
    return render_template('admin_customer_access.html', customers=customers)


@app.post('/admin/settings/upload-logo')
@admin_required
def upload_store_logo():
    """Upload the store logo immediately after selection.

    Android/Chrome can invalidate temporary file handles before the settings
    form is submitted. Saving the file immediately gives the form a stable
    server-side filename, just like product image uploads.
    """
    try:
        uploaded = request.files.get('logo')
        filename = save_upload(uploaded)
        if not filename:
            return {'ok': False, 'message': 'Please choose a logo image.'}, 400
        return {'ok': True, 'filename': filename, 'url': url_for('uploaded_file', filename=filename)}
    except ValueError as exc:
        return {'ok': False, 'message': str(exc)}, 400


@app.route('/admin/settings', methods=['GET', 'POST'])
@admin_required
def admin_settings():
    if request.method == 'POST':
        color = request.form.get('primary_color', '#6d4aff').strip()
        if not HEX_RE.match(color): color = '#6d4aff'
        values = {
            'store_name': request.form.get('store_name', '').strip()[:100] or 'BIB-STORE',
            'store_email': request.form.get('store_email', '').strip()[:160],
            'phone': request.form.get('phone', '').strip()[:50],
            'whatsapp': request.form.get('whatsapp', '').strip()[:50],
            'address': request.form.get('address', '').strip()[:250],
            'currency': request.form.get('currency', '₦').strip()[:5] or '₦',
            'description': request.form.get('description', '').strip()[:500],
            'primary_color': color,
            'announcement_text': request.form.get('announcement_text', '').strip()[:220],
            'show_announcement': '1' if request.form.get('show_announcement') == '1' else '0',
            'show_whatsapp': '1' if request.form.get('show_whatsapp') == '1' else '0',
            'whatsapp_message': request.form.get('whatsapp_message', '').strip()[:500],
            'footer_text': request.form.get('footer_text', '').strip()[:300],
            'nav_home': '1' if request.form.get('nav_home') == '1' else '0',
            'nav_shop': '1' if request.form.get('nav_shop') == '1' else '0',
            'nav_categories': '1' if request.form.get('nav_categories') == '1' else '0',
            'nav_about': '1' if request.form.get('nav_about') == '1' else '0',
            'nav_contact': '1' if request.form.get('nav_contact') == '1' else '0',
        }
        try:
            current_store = get_store()
            uploaded_logo = request.form.get('uploaded_logo', '').strip() or None
            remove_logo = request.form.get('remove_logo') == '1'
            old_logo = current_store.get('logo', '')
            if uploaded_logo:
                if Path(uploaded_logo).name != uploaded_logo or not (Path(app.config['UPLOAD_FOLDER']) / uploaded_logo).is_file():
                    raise ValueError('The uploaded store logo could not be found. Please choose it again.')
                values['logo'] = uploaded_logo
                if old_logo and old_logo != uploaded_logo:
                    delete_upload(old_logo)
            elif remove_logo and old_logo:
                values['logo'] = ''
                delete_upload(old_logo)
            else:
                values['logo'] = old_logo
            update_settings(values); flash('Store settings saved successfully.', 'success')
        except ValueError as exc: flash(str(exc), 'danger')
        return redirect(url_for('admin_settings'))
    return render_template('admin_settings.html')


@app.route('/admin/administrators', methods=['GET', 'POST'])
@admin_required
def admin_administrators():
    # Single-admin mode: there is intentionally no second administrator account.
    flash('BIB-STORE is configured for one administrator account only.', 'info')
    return redirect(url_for('admin_profile'))


@app.route('/admin/profile', methods=['GET', 'POST'])
@admin_required
def admin_profile():
    if request.method == 'POST':
        name = request.form.get('name', '').strip(); current = request.form.get('current_password', '')
        new_password = request.form.get('new_password', ''); confirm = request.form.get('confirm_password', '')
        if len(name) < 2: flash('Please enter a valid name.', 'danger')
        else:
            user = fetch_one('SELECT * FROM users WHERE id=?', (g.user['id'],))
            if new_password:
                if not check_password_hash(user['password'], current): flash('Current password is incorrect.', 'danger'); return render_template('admin_profile.html')
                if len(new_password) < 8 or new_password != confirm: flash('New password must be at least 8 characters and match confirmation.', 'danger'); return render_template('admin_profile.html')
                with get_connection() as conn:
                    conn.execute('UPDATE users SET name=?,password=? WHERE id=?', (name, generate_password_hash(new_password), g.user['id'])); conn.commit()
            else:
                with get_connection() as conn:
                    conn.execute('UPDATE users SET name=? WHERE id=?', (name, g.user['id'])); conn.commit()
            flash('Administrator profile updated.', 'success'); return redirect(url_for('admin_profile'))
    return render_template('admin_profile.html')


@app.errorhandler(403)
def forbidden(error): return render_template('403.html'), 403


@app.errorhandler(404)
def not_found(error): return render_template('404.html'), 404


@app.errorhandler(RequestEntityTooLarge)
def too_large(error): return render_template('error_file_too_large.html'), 413


@app.errorhandler(500)
def server_error(error): return render_template('500.html'), 500


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='127.0.0.1', port=port, debug=os.environ.get('FLASK_DEBUG', '0') == '1')
