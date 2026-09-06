# BIB-STORE — Professional Flask E-commerce

A responsive Nigerian e-commerce starter with a secure owner-controlled admin panel.

## Run on Android / Pydroid 3

```bash
cd /storage/emulated/0/BIB-STORE
pip install -r requirements.txt
python app.py
```

Open `http://127.0.0.1:5000` in the browser.

## First-time store owner setup

Open:

`http://127.0.0.1:5000/setup`

Create the first administrator. Once an admin exists, `/setup` is automatically disabled. There is no built-in developer/admin account.

Admin login uses the normal login page. `/admin/login` redirects safely to `/login` and then back to the dashboard.

## Admin dashboard

The dashboard provides website-based access to:
- Overview and live store statistics
- Products, images, pricing and stock
- Orders and order status updates
- Customers
- Store settings
- Responsive navigation/menu controls
- WhatsApp and delivery configuration
- Administrator profile and password change
- View public store

## WhatsApp delivery workflow

The store owner enters the WhatsApp number in **Admin → Store Settings → WhatsApp & delivery**.

After an order is placed, the customer can open a WhatsApp link for the order. The customer can also send the order from the order details page. Admin order details includes a WhatsApp customer button.

WhatsApp numbers should be stored with the country code, e.g. `2348012345678`.

## Security included

- Password hashing with Werkzeug
- CSRF protection with Flask-WTF
- Admin-only route protection
- Secure session cookie configuration
- Safe redirects
- Secure uploaded filenames with UUIDs
- Image extension restrictions and 5 MB request limit
- Inventory re-check during checkout with an immediate transaction
- Security response headers
- Owner-created first admin; no developer account

## Production note

Do not use Flask's development server for a public production deployment. Set a strong random `SECRET_KEY`, use HTTPS, and deploy with a production WSGI server/platform.

## Data

SQLite database: `bib_store.db`

Uploads: `uploads/`


### Mobile product image uploads
Product images are uploaded immediately after selection from the admin product editor. This avoids Android/Chrome temporary-file errors such as `ERR_UPLOAD_FILE_CHANGED` when the final product form is submitted.


## Client-ready installation workflow

Use this project as a clean master copy for each customer. Each customer deployment should have its own folder, `bib_store.db`, and `uploads/` directory. On first launch, open `/setup` and create the store identity plus the first administrator. After setup, customize the logo, brand color, navigation and WhatsApp settings from the admin portal.

## Administrator management

The owner can open **Admin → Administrators** to create separate administrator accounts for trusted staff or remove another administrator. The current administrator cannot remove themselves, and the store always keeps at least one administrator.

## Customer preview

Open **Admin → Customer access** to safely preview the storefront as a registered customer. The original administrator account is preserved and a **Return to Admin** control is shown while previewing.

## Selling multiple copies

Keep one untouched master project and create a separate deployment for every client. Never reuse the same SQLite database or uploads folder between customers.
