from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt
from flask_cors import CORS
from flask_jwt_extended import JWTManager, create_access_token, jwt_required, get_jwt_identity
import os
from datetime import timedelta
from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient
import pyodbc
import urllib.parse
import logging
import ssl

# Initialize Flask app
app = Flask(__name__)
CORS(app, supports_credentials=True)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize extensions
bcrypt = Bcrypt(app)
jwt = JWTManager(app)

# Azure Key Vault configuration (for production)
KEY_VAULT_NAME = os.environ.get("KEY_VAULT_NAME", "pawfectfind-kv")
KEY_VAULT_URI = f"https://{KEY_VAULT_NAME}.vault.azure.net/"

def get_secret(secret_name):
    """Get secret from Azure Key Vault or environment variables"""
    if os.environ.get("FLASK_ENV") == "production" and KEY_VAULT_NAME != "pawfectfind-kv":
        try:
            credential = DefaultAzureCredential()
            client = SecretClient(vault_url=KEY_VAULT_URI, credential=credential)
            secret = client.get_secret(secret_name)
            return secret.value
        except Exception as e:
            logger.error(f"Error fetching secret {secret_name}: {str(e)}")
            return os.environ.get(secret_name)
    else:
        return os.environ.get(secret_name)

# Configuration
app.config["SECRET_KEY"] = get_secret("FLASK_SECRET_KEY") or "dev-secret-key-change-in-production"
app.config["JWT_SECRET_KEY"] = get_secret("JWT_SECRET_KEY") or "jwt-secret-key-change-in-production"
app.config["JWT_ACCESS_TOKEN_EXPIRES"] = timedelta(hours=24)

# Azure SQL Database configuration
def get_azure_sql_connection_string():
    """Build Azure SQL connection string"""
    server = os.environ.get('DB_SERVER', 'pawfectfinddb.database.windows.net')
    database = os.environ.get('DB_NAME', 'pawfectfind')
    username = os.environ.get('pawfectadmin')
    password = os.environ.get('Password!123')
    
    if not all([server, database, username, password]):
        logger.error("Missing database configuration")
        return None
    
    # For Azure SQL
    driver = '{ODBC Driver 17 for SQL Server}'
    connection_string = f"""
        Driver={driver};
        Server={server};
        Database={database};
        Uid={username};
        Pwd={password};
        Encrypt=yes;
        TrustServerCertificate=no;
        Connection Timeout=30;
    """
    
    return connection_string

# Set SQLAlchemy database URI
connection_string = get_azure_sql_connection_string()
if connection_string:
    params = urllib.parse.quote_plus(connection_string)
    app.config['SQLALCHEMY_DATABASE_URI'] = f"mssql+pyodbc:///?odbc_connect={params}"
else:
    # Fallback for development (you can use SQLite for local dev)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///pawfectfind.db'

app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
    "pool_recycle": 300,
    "pool_pre_ping": True,
}

# Initialize database
db = SQLAlchemy(app)

# Models
class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    first_name = db.Column(db.String(50), nullable=False)
    last_name = db.Column(db.String(50), nullable=False)
    phone = db.Column(db.String(20))
    user_type = db.Column(db.String(20), nullable=False)  # 'customer' or 'vendor'
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    
    # Vendor-specific fields (nullable for customers)
    business_name = db.Column(db.String(100))
    business_address = db.Column(db.Text)
    services_offered = db.Column(db.Text)  # JSON string of services
    rating = db.Column(db.Float, default=0.0)
    is_verified = db.Column(db.Boolean, default=False)

    def set_password(self, password):
        self.password_hash = bcrypt.generate_password_hash(password).decode('utf-8')

    def check_password(self, password):
        return bcrypt.check_password_hash(self.password_hash, password)

    def to_dict(self):
        return {
            'id': self.id,
            'email': self.email,
            'first_name': self.first_name,
            'last_name': self.last_name,
            'phone': self.phone,
            'user_type': self.user_type,
            'business_name': self.business_name,
            'business_address': self.business_address,
            'services_offered': self.services_offered,
            'rating': self.rating,
            'is_verified': self.is_verified,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

# Routes
@app.route('/')
def home():
    return jsonify({"message": "PawfectFind API Server", "status": "healthy"})

@app.route('/api/register', methods=['POST'])
def register():
    try:
        data = request.get_json()
        
        # Validate required fields
        required_fields = ['email', 'password', 'first_name', 'last_name', 'user_type']
        for field in required_fields:
            if field not in data:
                return jsonify({"error": f"Missing required field: {field}"}), 400
        
        # Check if user already exists
        if User.query.filter_by(email=data['email']).first():
            return jsonify({"error": "User already exists"}), 409
        
        # Create new user
        new_user = User(
            email=data['email'],
            first_name=data['first_name'],
            last_name=data['last_name'],
            user_type=data['user_type'],
            phone=data.get('phone')
        )
        
        # Set vendor-specific fields if applicable
        if data['user_type'] == 'vendor':
            new_user.business_name = data.get('business_name')
            new_user.business_address = data.get('business_address')
            new_user.services_offered = data.get('services_offered')
        
        new_user.set_password(data['password'])
        
        db.session.add(new_user)
        db.session.commit()
        
        # Generate access token
        access_token = create_access_token(identity=str(new_user.id))
        
        return jsonify({
            "message": "User created successfully",
            "user": new_user.to_dict(),
            "access_token": access_token
        }), 201
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Registration error: {str(e)}")
        return jsonify({"error": "Internal server error"}), 500

@app.route('/api/login', methods=['POST'])
def login():
    try:
        data = request.get_json()
        
        if not data or 'email' not in data or 'password' not in data:
            return jsonify({"error": "Email and password required"}), 400
        
        user = User.query.filter_by(email=data['email']).first()
        
        if not user or not user.check_password(data['password']):
            return jsonify({"error": "Invalid credentials"}), 401
        
        # Generate access token
        access_token = create_access_token(identity=str(user.id))
        
        return jsonify({
            "message": "Login successful",
            "user": user.to_dict(),
            "access_token": access_token
        }), 200
        
    except Exception as e:
        logger.error(f"Login error: {str(e)}")
        return jsonify({"error": "Internal server error"}), 500

@app.route('/api/profile', methods=['GET'])
@jwt_required()
def get_profile():
    try:
        user_id = get_jwt_identity()
        user = User.query.get(user_id)
        
        if not user:
            return jsonify({"error": "User not found"}), 404
        
        return jsonify({"user": user.to_dict()}), 200
        
    except Exception as e:
        logger.error(f"Profile fetch error: {str(e)}")
        return jsonify({"error": "Internal server error"}), 500

# Health check endpoint for Azure
@app.route('/health')
def health():
    try:
        # Test database connection
        db.session.execute('SELECT 1')
        return jsonify({
            "status": "healthy", 
            "database": "connected"
        }), 200
    except Exception as e:
        return jsonify({
            "status": "unhealthy", 
            "database": "disconnected",
            "error": str(e)
        }), 500

# Initialize database
@app.before_first_request
def create_tables():
    try:
        db.create_all()
        logger.info("Database tables created successfully")
    except Exception as e:
        logger.error(f"Error creating database tables: {str(e)}")

if __name__ == '__main__':
    # For development
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=os.environ.get('FLASK_ENV') == 'development')
