from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_cors import CORS


db = SQLAlchemy()
migrate = Migrate()

def create_app():
    app = Flask(__name__)

    # Configs

    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///app.db'
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {"connect_args": {"check_same_thread": False}}
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SECRET_KEY'] = 'This is the secret-key'

       
    CORS(app)

    # Initialize extensions
    db.init_app(app)
    migrate.init_app(app, db)

    # Register blueprint
    from app.routes.auth_routes import auth_bp
    from app.routes.user_crud_routes import user_bp
    from app.routes.officer_crud_routes import officer_bp

    app.register_blueprint(auth_bp, url_prefix='/api/auth')
    app.register_blueprint(user_bp, url_prefix='/api/user')
    app.register_blueprint(officer_bp, url_prefix='/api/officer')
    return app
