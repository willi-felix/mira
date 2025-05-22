import httpx
import os

RESEND_API = os.environ.get("RESEND_API")
RESEND_EMAIL = os.environ.get("RESEND_EMAIL")
SITE_NAME = os.environ.get("SITE_NAME")

async def send_new_user_email(to_email, password, org, site_url):
    subject = f"Your {SITE_NAME} account has been created"
    html_body = f"""
    <h2>{SITE_NAME} - A Link Shortener Open Source</h2>
    <p>An account for <b>{org}</b> has been created for you.</p>
    <ul>
        <li>Email: <b>{to_email}</b></li>
        <li>Password: <b>{password}</b></li>
        <li>Login: <a href="{site_url}/login/">{site_url}/login/</a></li>
    </ul>
    <p>This is your only password and it cannot be changed. Please keep it safe.</p>
    """
    async with httpx.AsyncClient() as client:
        await client.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {RESEND_API}"},
            json={
                "from": RESEND_EMAIL,
                "to": [to_email],
                "subject": subject,
                "html": html_body,
            },
            timeout=10
        )

async def send_reset_password_email(to_email, password, org, site_url):
    subject = f"Your {SITE_NAME} password has been reset"
    html_body = f"""
    <h2>{SITE_NAME} - A Link Shortener Open Source</h2>
    <p>Your password for <b>{org}</b> has been reset by an administrator.</p>
    <ul>
        <li>Email: <b>{to_email}</b></li>
        <li>New Password: <b>{password}</b></li>
        <li>Login: <a href="{site_url}/login/">{site_url}/login/</a></li>
    </ul>
    <p>This is your only password and it cannot be changed. Please keep it safe.</p>
    """
    async with httpx.AsyncClient() as client:
        await client.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {RESEND_API}"},
            json={
                "from": RESEND_EMAIL,
                "to": [to_email],
                "subject": subject,
                "html": html_body,
            },
            timeout=10
        )