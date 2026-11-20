# implement authentication/sign in


from __future__ import annotations  # flexible type hints


import base64
import hashlib
import io
from datetime import UTC, datetime, timedelta
from functools import wraps
import click
import pyotp  # mfa
import qrcode
from argon2 import PasswordHasher
from argon2.exceptions import (
    InvalidHashError,
    VerificationError,
    VerifyMismatchError,
)
from qrcode.image.svg import SvgPathImage

# user session imports
from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_login import (
    LoginManager,
    current_user,
    login_required,
    login_user,
    logout_user,
)

# sqlalchemy
from sqlalchemy import delete, func, or_, select
from sqlalchemy.exc import IntegrityError

# internal imports
from database.create_db import db
from models import Log, PasswordResetToken, Role, User, utc_now
from services.security import consume_rate_limit, rate_limit, validate_csrf
from services.validation import (
    is_valid_email,
    is_valid_password,
    is_valid_person_name,
    is_valid_username,
)

# group auth pages together
auth = Blueprint("auth", __name__)
login_manager = LoginManager()
login_manager.login_view = "auth.login"  # protect pages (sign in)
password_hasher = PasswordHasher()
BASELINE_HASH = password_hasher.hash("expected_invalid_password")
MAX_FAILED_LOGINS = 5
LOCKOUT_MINUTES = 15
MFA_TIME_LIMIT = timedelta(minutes=5)
RESET_REQUEST_RETENTION_DAYS = 30


# convert timezones to utc
def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


# argon2 hash comparison
def _verify_password(encoded_hash: str, password: str) -> bool:
    try:
        return password_hasher.verify(encoded_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


# log entries
def _log(action: str, user_id: int | None = None, entity_id: int | None = None) -> None:
    db.session.add(
        Log(
            user_id=user_id,
            action=action,
            entity_type="USER" if entity_id is not None else None,  # pairing
            entity_id=entity_id,
        )
    )
    db.session.commit()


def _purge_reset_tokens(older_than_days: int = RESET_REQUEST_RETENTION_DAYS) -> int:
    now = utc_now()
    result = db.session.execute(
        delete(PasswordResetToken).where(
            or_(
                PasswordResetToken.used_at.is_not(None),
                PasswordResetToken.expires_at <= now,
                PasswordResetToken.requested_at < now - timedelta(days=older_than_days),
            )
        )
    )
    return result.rowcount or 0


# get role
def _role_name(user: User) -> str:
    role = db.session.get(Role, user.role_id)
    return role.name if role else ""


# protect pages (role)
def role_required(*allowed_roles):
    def decorate(function):
        @wraps(function)
        @login_required
        def wrapped(*args, **kwargs):
            if _role_name(current_user) not in allowed_roles:
                abort(403)  # block if unauthorised
            return function(*args, **kwargs)  # allow if authorised

        return wrapped

    return decorate


# verify sessions and register load user with flask login
@login_manager.user_loader
def load_user(user_id: str) -> User | None:
    try:
        user = db.session.get(User, int(user_id))  # str -> int for db
    except (TypeError, ValueError):
        return None
    # missing accounts aren't signed in
    if not user or not user.is_active:
        return None
    authenticated_at = session.get("auth_at")
    if not isinstance(authenticated_at, (int, float)):
        return None
    # if password changed while in this session, reject old one
    if authenticated_at < _utc(user.password_changed_at).timestamp():
        return None
    return user  # user approved if checks passed


# mfa pre checks
def pending_mfa_user() -> User | None:
    user_id = session.get("mfa_pending_user_id")
    started_at = session.get("mfa_pending_at")
    if not isinstance(user_id, int) or not isinstance(started_at, (int, float)):
        return None
    if (
        datetime.now(UTC).timestamp() -
        started_at > MFA_TIME_LIMIT.total_seconds()
    ):  # reject time outed MFA
        session.pop("mfa_pending_user_id", None)
        session.pop("mfa_pending_at", None)
        return None
    user = db.session.get(User, user_id)
    if not user or not user.is_active:  # missing accounts
        return None
    # reject locked accounts and remove session
    if user.locked_until and _utc(user.locked_until) > datetime.now(UTC):
        session.pop("mfa_pending_user_id", None)
        session.pop("mfa_pending_at", None)
        return None
    return user  # user approved if checks passed


# start the mfa process
def _start_mfa(user: User, setup: bool) -> object:
    session.clear()  # new slate and then set to pending
    session["mfa_pending_user_id"] = user.user_id
    session["mfa_pending_at"] = datetime.now(UTC).timestamp()
    session.permanent = True
    # new users directed to setup, else verify their existing code
    endpoint = "auth.mfa_setup" if setup else "auth.mfa_verify"
    return redirect(url_for(endpoint))


# successful sign in
def _finish_login(user: User) -> None:
    # clear previous fails and locks
    user.failed_logins = 0
    user.locked_until = None
    db.session.commit()
    _log("LOGIN_SUCCESS", user.user_id, user.user_id)
    session.clear()
    session.permanent = True  # temp mfa -> perm signed in session
    login_user(user, fresh=True)
    session["auth_at"] = _utc(user.password_changed_at).timestamp()


# mfa fails
def _log_mfa_fail(user: User) -> None:
    user.failed_logins += 1
    _log("MFA_FAILED", entity_id=user.user_id)
    if user.failed_logins >= MAX_FAILED_LOGINS:  # lock on repeat fails
        user.failed_logins = 0
        user.locked_until = utc_now() + timedelta(minutes=LOCKOUT_MINUTES)
        _log("ACCOUNT_LOCKED", entity_id=user.user_id)
        # remove temp mfa session on fail
        session.pop("mfa_pending_user_id", None)
        session.pop("mfa_pending_at", None)
    else:  # save updated fail count
        db.session.commit()


# setup for auth app
def _qr_data_uri(secret: str, username: str) -> str:
    uri = pyotp.TOTP(secret).provisioning_uri(
        name=username, issuer_name="ABC Solutions"
    )
    image = qrcode.make(uri, image_factory=SvgPathImage)
    # generate qr svg in memory and convert to embeddable text
    output = io.BytesIO()
    image.save(output)
    encoded = base64.b64encode(output.getvalue()).decode("ascii")
    # html format
    return f"data:image/svg+xml;base64,{encoded}"


# show/submit register form
@auth.route("/register", methods=["GET", "POST"])
@rate_limit(5, 3600, "registration")  # 5 attempts ph
def register() -> str:
    if request.method == "POST":
        validate_csrf()  # check form submitted from this app
        # read values and remove spaces
        first_name = request.form.get("first_name", "").strip()
        last_name = request.form.get("last_name", "").strip()
        email = request.form.get("email", "").strip().lower()
        username = request.form.get("username", "").strip()
        requested_role = request.form.get("requested_role", "").strip().upper()
        password = request.form.get("password", "")
        confirmation = request.form.get("confirm_password", "")
        # do not accept manager or admin requests
        role_name = {"EMPLOYEE": "Employee",
                     "BUSINESS": "Business"}.get(requested_role)
        if (
            not is_valid_person_name(first_name)
            or not is_valid_person_name(last_name)
            or not is_valid_username(username)
            or not is_valid_email(email)
            or not is_valid_password(password)
            or password != confirmation
            or role_name is None
        ):
            flash("Check and complete all fields. Password may be invalid.", "error")
        else:
            # look for existing account
            duplicate = db.session.scalar(
                select(User.user_id).where(
                    or_(
                        func.lower(User.username) == username.lower(),
                        func.lower(User.email) == email,
                    )
                )
            )
            if duplicate:
                flash("Cannot create an account with these details.", "error")
            else:
                role = db.session.scalar(
                    select(Role).where(Role.name == role_name))
                if role is None:
                    raise RuntimeError("Please initialise the database first.")
                user = User(
                    first_name=first_name,
                    last_name=last_name,
                    username=username,
                    email=email,
                    role_id=role.role_id,
                    password_hash=password_hasher.hash(password),
                    is_active=False,
                )
                db.session.add(user)
                try:
                    db.session.flush()
                except IntegrityError:
                    # if two requests passed checks at the same time, db rejects the second attempt
                    db.session.rollback()
                    flash("Cannot create an account with these details.", "error")
                else:
                    _log("USER_REGISTERED", entity_id=user.user_id)
                    flash(
                        "Account request received. Awaiting Admin/Manager approval.",
                        "success",
                    )
                    return redirect(url_for("auth.login"))
    return render_template("auth/register.html", page_title="Request an account")


# show/submit reset form
@auth.route("/password-reset/request", methods=["GET", "POST"])
@rate_limit(5, 3600, "password_reset_request")  # 5 requests ph
def password_reset_request() -> str:
    submitted = request.method == "POST"
    if submitted:
        # remove old reset records before handling a new request
        _purge_reset_tokens()
        # read values and remove spaces and capitalisation
        identifier = request.form.get("username_or_email", "").strip().lower()
        user = (
            db.session.scalar(
                select(User).where(
                    or_(
                        func.lower(User.username) == identifier,
                        func.lower(User.email) == identifier,
                    )
                )
            )
            if identifier
            else None
        )  # don't search db if empty
        if user:
            pending_request = db.session.scalar(
                select(PasswordResetToken.token_id).where(
                    PasswordResetToken.user_id == user.user_id,
                    PasswordResetToken.token_hash.is_(None),
                    PasswordResetToken.approved_by.is_(None),
                    PasswordResetToken.used_at.is_(None),
                )
            )
            if pending_request is None:
                db.session.add(PasswordResetToken(user_id=user.user_id))
                db.session.flush()
        _log(
            "PASSWORD_RESET_REQUESTED",
            entity_id=user.user_id if user else None,
        )
    return render_template(
        "auth/password_reset_request.html",
        page_title="Request a password reset",
        submitted=submitted,
    )


def _find_reset_token(token: str) -> PasswordResetToken | None:
    # hash before searching (do not store original token)
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    # find match
    return db.session.scalar(
        select(PasswordResetToken).where(
            PasswordResetToken.token_hash == token_hash)
        # prevent two requests using the same token at the same time
        .with_for_update()
    )


# validate token
def _reset_token_is_valid(reset: PasswordResetToken | None) -> bool:
    return bool(
        reset
        and reset.used_at is None
        and reset.expires_at is not None
        and _utc(reset.expires_at) > datetime.now(UTC)
    )


# use url token
@auth.route("/password-reset/set/<token>", methods=["GET", "POST"])
def set_password(token: str) -> str:
    reset = _find_reset_token(token)
    if not _reset_token_is_valid(reset):
        return render_template(
            "auth/set_password.html",
            page_title="Set a new password",
            expired=True,
        )
    if request.method == "POST":
        password = request.form.get("password", "")
        confirmation = request.form.get("confirm_password", "")
        if not is_valid_password(password) or password != confirmation:
            flash("Passwords must match and use 12 to 128 characters.", "error")
            return render_template(
                "auth/set_password.html",
                page_title="Set a new password",
                expired=False,
                token=token,
            )
        # find the linked account
        user = db.session.get(User, reset.user_id)
        if user is None:
            return render_template(
                "auth/set_password.html",
                page_title="Set a new password",
                expired=True,
            )
        now = utc_now()
        user.password_hash = password_hasher.hash(password)
        user.password_changed_at = now
        user.failed_logins = 0
        user.locked_until = None
        reset.used_at = now  # mark token as used
        _log("PASSWORD_RESET_COMPLETED", entity_id=user.user_id)
        session.clear()
        flash("Password changed.", "success")
        return redirect(url_for("auth.login"))  # direct to sign in
    return render_template(
        "auth/set_password.html",
        page_title="Set a new password",
        expired=False,
        token=token,
    )


# refer to sign in or process submitted creds
@auth.route("/login", methods=["GET", "POST"])
def login() -> str:
    if request.method == "POST":
        validate_csrf()  # check form submitted from this app
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        # find match
        user = db.session.scalar(
            select(User).where(
                or_(
                    func.lower(User.username) == username.lower(),
                    func.lower(User.email) == username.lower(),
                )
            )
        )
        if user is None:
            _verify_password(BASELINE_HASH, password)
            if not consume_rate_limit(10, 60, "unknown_login"):
                _log("LOGIN_BLOCKED")
                abort(429)
            _log("LOGIN_FAILED")
            flash("Sign in failed.", "error")
            return render_template("auth/login.html", page_title="Sign in"), 401
        if not user.is_active:
            _verify_password(BASELINE_HASH, password)
            _log("LOGIN_FAILED", entity_id=user.user_id)
            # similar generic error
            flash("Sign in failed.", "error")
            return render_template("auth/login.html", page_title="Sign in"), 401
        # convert locked time to utc, or set to none
        locked_until = _utc(user.locked_until) if user.locked_until else None
        if locked_until and locked_until > datetime.now(UTC):
            _verify_password(BASELINE_HASH, password)
            _log("LOGIN_BLOCKED", entity_id=user.user_id)
            flash("Sign in failed.", "error")
            return render_template("auth/login.html", page_title="Sign in"), 401
        # incorrect password
        if not _verify_password(user.password_hash, password):
            user.failed_logins += 1
            if user.failed_logins >= MAX_FAILED_LOGINS:  # lock if out of tries
                user.failed_logins = 0
                user.locked_until = utc_now() + timedelta(minutes=LOCKOUT_MINUTES)
                db.session.commit()
                _log("ACCOUNT_LOCKED", entity_id=user.user_id)
            else:
                db.session.commit()  # add a fail
            _log("LOGIN_FAILED", entity_id=user.user_id)
            flash("Sign in failed.", "error")
            return render_template("auth/login.html", page_title="Sign in"), 401
        # update the hash if argon2 settings were changed
        if password_hasher.check_needs_rehash(user.password_hash):
            user.password_hash = password_hasher.hash(password)
            user.password_changed_at = utc_now()
            db.session.commit()
        # mfa required: setup/verify
        if current_app.config["MFA_REQUIRED"]:
            return _start_mfa(user, setup=not user.mfa_enabled)
        _finish_login(user)
        # complete sign in and refer to the home page
        return redirect(url_for("home"))
    return render_template("auth/login.html", page_title="Sign in")


# show mfa setup/process code
@auth.route("/mfa/setup", methods=["GET", "POST"])
@rate_limit(10, 60, "mfa", post_only=False)  # 10 requests pm
def mfa_setup() -> str:
    user = pending_mfa_user()
    if user is None:
        # if the user is not pending mfa, send to sign in
        return redirect(url_for("auth.login"))
    if user.mfa_enabled:
        # if the user is set up, they should verify
        return redirect(url_for("auth.mfa_verify"))
    if not user.mfa_secret:
        # first start of mfa setup needs a secret created/saved
        user.mfa_secret = pyotp.random_base32()
        db.session.commit()
    if request.method == "POST":
        validate_csrf()  # check form submitted from this app
        code = request.form.get("code", "")
        if pyotp.TOTP(user.mfa_secret).verify(code, valid_window=1):
            user.mfa_enabled = True
            _log("MFA_ENABLED", entity_id=user.user_id)
            _finish_login(user)
            return redirect(url_for("home"))  # check mfa code with auth app
        _log_mfa_fail(user)
        flash("The code could not be verified.", "error")
    # display the qr and key
    return render_template(
        "auth/mfa_setup.html",
        page_title="Set up authenticator",
        qr_data_uri=_qr_data_uri(user.mfa_secret, user.username),
        manual_key=user.mfa_secret,
    )


# show mfa verify/process code
@auth.route("/mfa/verify", methods=["GET", "POST"])
@rate_limit(10, 60, "mfa", post_only=False)  # 10 requests pm
def mfa_verify() -> str:
    user = pending_mfa_user()
    if user is None:
        return redirect(url_for("auth.login"))
    if not user.mfa_enabled or not user.mfa_secret:
        return redirect(url_for("auth.mfa_setup"))  # send to setup
    if request.method == "POST":
        validate_csrf()  # check form submitted from this app
        code = request.form.get("code", "")
        # check the code against mfa secret
        # allow a small window for code changes
        if pyotp.TOTP(user.mfa_secret).verify(code, valid_window=1):
            _finish_login(user)  # incorrect code decision
            return redirect(url_for("home"))
        _log_mfa_fail(user)
        flash("The code could not be verified.", "error")
    return render_template("auth/mfa_verify.html", page_title="Verify your account")


@auth.post("/logout")
@login_required  # cannot log out if not logged in
def logout() -> str:
    validate_csrf()  # check form submitted from this app
    user_id = int(current_user.get_id())
    _log("LOGOUT", user_id, user_id)
    # catch flask login up
    logout_user()
    session.clear()
    flash("Signed out.", "success")
    return redirect(url_for("auth.login"))


# use url user id
@auth.post("/admin/users/<int:user_id>/unlock")
@login_required
def unlock_user(user_id: int) -> str:
    requester_role = _role_name(current_user)
    target = db.session.get(User, user_id)
    if not target:
        abort(404)
    if target.user_id == current_user.user_id:
        abort(403)  # cannot unlock own account
    target_role = _role_name(target)
    # admins unlock other accounts
    # managers can unlock employees
    if requester_role != "Admin" and not (
        requester_role == "Manager" and target_role == "Employee"
    ):
        abort(403)
    # clear fails and locks
    target.failed_logins = 0
    target.locked_until = None
    db.session.commit()
    _log("USER_UNLOCKED", entity_id=target.user_id)
    flash("Account unlocked.", "success")
    return redirect(url_for("app_users"))


# reset a users mfa
@auth.post("/admin/users/<int:user_id>/mfa/reset")
@login_required
def reset_user_mfa(user_id: int) -> str:
    target = db.session.get(User, user_id)
    if not target:
        abort(404)
    # only admins can reset mfa (but not their own)
    if _role_name(current_user) != "Admin" or target.user_id == current_user.user_id:
        abort(403)
    # remove mfa from the user
    target.mfa_enabled = False
    target.mfa_secret = None
    db.session.commit()
    _log("MFA_RESET", entity_id=target.user_id)
    flash("MFA reset.", "success")
    return redirect(url_for("app_users"))


@auth.post("/mfa/logout")
def pending_logout() -> str:
    validate_csrf()  # check form submitted from this app
    # password checked but mfa not complete
    user = pending_mfa_user()
    if user:
        _log("LOGOUT", entity_id=user.user_id)
    session.clear()
    # remove pending login details and refer to login
    return redirect(url_for("auth.login"))


# flask command to make the admin account
@auth.cli.command("create-admin")
def create_admin() -> None:
    """Create Admin using ADMIN_* environment variables."""
    import os

    # required settings
    required = (
        "ADMIN_FIRST_NAME",
        "ADMIN_LAST_NAME",
        "ADMIN_EMAIL",
        "ADMIN_USERNAME",
        "ADMIN_PASSWORD",
    )
    missing = [key for key in required if not os.environ.get(key)]
    if missing:
        raise RuntimeError(
            f"Missing environment variables: {', '.join(missing)}")
    # minimum password length
    password = os.environ["ADMIN_PASSWORD"]
    if len(password) < 12:
        raise RuntimeError(
            "ADMIN_PASSWORD must contain at least 12 characters.")
    # admin role must exist first
    role = db.session.scalar(select(Role).where(Role.name == "Admin"))
    if role is None:
        raise RuntimeError("Run create the database before the admin.")
    # check the username/email is not in use already
    existing = db.session.scalar(
        select(User.user_id).where(
            or_(
                func.lower(User.username)
                == os.environ["ADMIN_USERNAME"].strip().lower(),
                func.lower(
                    User.email) == os.environ["ADMIN_EMAIL"].strip().lower(),
            )
        )
    )
    if existing:
        print("Admin account already exists.")
        return
    # create admin account
    user = User(
        first_name=os.environ["ADMIN_FIRST_NAME"][:50],
        last_name=os.environ["ADMIN_LAST_NAME"][:50],
        email=os.environ["ADMIN_EMAIL"].strip().lower(),
        username=os.environ["ADMIN_USERNAME"].strip(),
        password_hash=password_hasher.hash(password),
        role_id=role.role_id,
        is_active=True,
    )
    db.session.add(user)
    db.session.commit()
    print("Admin account created.")


# flask command to reset mfa
@auth.cli.command("reset-mfa")
@click.argument("username")
def reset_mfa(username: str) -> None:
    # find account
    user = db.session.scalar(select(User).where(User.username == username))
    if user is None:
        raise RuntimeError("User not found.")
    # turn off mfa
    user.mfa_enabled = False
    user.mfa_secret = None
    db.session.commit()
    _log("MFA_RESET", entity_id=user.user_id)
    print("MFA reset.")


@auth.cli.command("purge-reset-tokens")
@click.option(
    "--older-than-days",
    type=click.IntRange(min=1),
    default=RESET_REQUEST_RETENTION_DAYS,
    show_default=True,
)
def purge_reset_tokens(older_than_days: int) -> None:
    removed = _purge_reset_tokens(older_than_days)
    db.session.commit()
    click.echo(f"Removed {removed} password reset records.")
