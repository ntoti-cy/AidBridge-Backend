import os

from dotenv import load_dotenv
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_cors import CORS

load_dotenv()

db = SQLAlchemy()

migrate = Migrate()


def create_app():

    app = Flask(__name__)

    DATABASE_URL = os.getenv("DATABASE_URL")

    if not DATABASE_URL:

        raise RuntimeError("DATABASE_URL environment variable is not set")

    # Fix old postgres:// format

    if DATABASE_URL.startswith("postgres://"):

        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

    # Neon requires SSL

    if "neon.tech" in DATABASE_URL and "sslmode" not in DATABASE_URL:

        DATABASE_URL += "?sslmode=require"

    # Configs

    app.config["SQLALCHEMY_DATABASE_URI"] = DATABASE_URL

    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    app.config["SECRET_KEY"] = os.getenv(
        "SECRET_KEY", "#aidbridge_super_secret_key_2026"
    )

    app.config["SESSION_PERMANENT"] = False

    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
        "pool_pre_ping": True,  # Automatically tests connection health before executing queries
    "pool_recycle": 300,

    }

    
    CORS(app)

    # Initialize extensions

    db.init_app(app)

    migrate.init_app(app, db)

    # Register blueprint

    from app.routes.auth_routes import auth_bp

    from app.routes.user_crud_routes import user_bp

    from app.routes.officer_crud_routes import officer_bp

    from app.routes.admin_crud_routes import admin_bp

    from app.routes.crud_routes import crud_bp

    from app.Admin.auth import admin_auth

    
    app.register_blueprint(auth_bp, url_prefix="/api/auth")

    app.register_blueprint(user_bp, url_prefix="/api/user")

    app.register_blueprint(officer_bp, url_prefix="/api/officer")

    app.register_blueprint(admin_bp, url_prefix="/api/admin")

    app.register_blueprint(crud_bp, url_prefix="/api/crud")

    app.register_blueprint(admin_auth)



    @app.route("/")
    def home():

        return "AidBridge API is running"

    # Initialize Admin Panel

    from app.Admin.admin import init_admin

    init_admin(app)


    return app
