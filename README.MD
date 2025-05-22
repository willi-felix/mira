# MiraURL - Open Source Link Shortener

**MiraURL** is a modern, open-source, self-hosted link shortener for individuals, teams, and organizations. It provides secure, easy, and powerful link management with a beautiful dashboard and advanced features.

![MiraURL Dashboard Screenshot](https://i.ibb.co/gh3sZrq/Mira-URL-1-1.png)

## Features

- **Admin & User Management**: Role-based, with API key support.
- **Custom or Random Short Links**: Choose your own alias or let the system generate one.
- **Password Protection, Expiry, One-time Links**: Secure and control access to your links.
- **Personal & Admin Dashboards**: Manage and analyze your links and users.
- **RESTful Async API**: For automation and integration.
- **Google Safe Browsing**: Automatic checks to protect from malicious targets.
- **Domain Blacklist**: Prevent unwanted or dangerous domains from being shortened.
- **Email Notifications**: For account creation and password reset.
- **Beautiful Modern UI**: Built with Tailwind CSS.
- **Easy PostgreSQL Setup**: Configure everything with a simple `.env` file.

## Quick Start

1. **Clone the repository**
    ```bash
    git clone https://github.com/your-org/miraurl.git
    cd miraurl
    ```

2. **Install dependencies**
    ```bash
    pip install -r requirements.txt
    ```

3. **Configure environment variables**

    Copy the example file and edit as needed:
    ```bash
    cp .env.example .env
    ```

    Set up:
    - Database (`DATABASE_URL`)
    - Secret key (`SECRET_KEY`)
    - Google Safe Browsing API (`GOOGLE_SAFE_BROWSING_API`)
    - Resend email API and sender (`RESEND_API`, `RESEND_EMAIL`)
    - `SITE_NAME` (your team/org/brand)

4. **Initialize the database**

    The database is auto-initialized on first run.

5. **Run the app**
    ```bash
    python app.py
    ```

6. **Setup the first admin**

    On first launch, you will be redirected to `/setup` to create your admin account.

7. **Login & Shorten URLs!**

    After logging in, you can create short links, manage users (if admin), and more.

## Screenshots

> Add your screenshots here!

## Folder Structure

- `app.py` - Main Flask application
- `models.py` - Database models
- `templates/` - All HTML templates (Jinja2 + Tailwind CSS)
- `static/` - Static assets (logo, screenshots, etc.)
- `utils.py` - Helper functions
- `mailer.py` - Email logic for user notification
- `auth.py` - Authentication logic

## Security

- Passwords are securely hashed (bcrypt).
- All user actions and critical data are protected by authentication.
- Links can be protected with passwords, expiration, or one-time access.
- Malicious/phishing links are blocked with Google Safe Browsing and custom blacklist.

## License

GNU General Public License v3.0. See [LICENSE](LICENSE).

> **Note:** The GPL license allows you to use, modify, and deploy MiraURL for private/internal purposes without any requirement to distribute your modifications. You are only required to make source code available if you distribute MiraURL (or a derivative work) to others outside your organization/private use.

---

**MiraURL** is open source and maintained by the community.  
Feel free to contribute or submit an issue!
