from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
from flask_jwt_extended import JWTManager, create_access_token, jwt_required, get_jwt_identity
import pyodbc
import os
from datetime import datetime, timedelta
from hashlib import sha256
from dotenv import load_dotenv
from azure.servicebus import ServiceBusClient, ServiceBusMessage
import json
import stripe

# Load environment variables
load_dotenv()

app = Flask(__name__)

# Configure JWT first
app.config['JWT_SECRET_KEY'] = os.getenv('JWT_SECRET_KEY', 'your-secret-key-change-in-production')
app.config['JWT_ACCESS_TOKEN_EXPIRES'] = timedelta(hours=24)

# Configure CORS properly
CORS(app, resources={
    r"/api/*": {
        "origins": [
            "http://localhost:3000",
            "http://localhost:5000",
            "https://pawfectfind.azurewebsites.net",
            "https://pawfectfind-backend.azurewebsites.net"
        ],
        "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        "allow_headers": ["Content-Type", "Authorization"]
    }
})

# Initialize JWT after app configuration
jwt = JWTManager(app)

# Azure SQL Database connection
def get_db_connection():
    server = os.getenv('AZURE_SQL_SERVER')
    database = os.getenv('AZURE_SQL_DATABASE')
    username = os.getenv('AZURE_SQL_USERNAME')
    password = os.getenv('AZURE_SQL_PASSWORD')
    driver = '{ODBC Driver 18 for SQL Server}'
    
    # Print diagnostic information
    print("Attempting database connection...")
    print(f"Server: {server}")
    print(f"Database: {database}")
    
    connection_string = f"""
        DRIVER={driver};
        SERVER={server};
        DATABASE={database};
        UID={username};
        PWD={password};
        Encrypt=yes;
        TrustServerCertificate=no;
        Connection Timeout=30;
    """
    
    return pyodbc.connect(connection_string)

# Initialize database tables with extended availability
def init_db():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Create users table
        cursor.execute("""
            IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='users' AND xtype='U')
            CREATE TABLE users (
                id INT IDENTITY(1,1) PRIMARY KEY,
                email NVARCHAR(255) UNIQUE NOT NULL,
                password_hash NVARCHAR(255) NOT NULL,
                full_name NVARCHAR(255) NOT NULL,
                phone_number NVARCHAR(20),
                created_at DATETIME2 DEFAULT GETDATE()
            )
        """)
        
        # Create pets table
        cursor.execute("""
            IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='pets' AND xtype='U')
            CREATE TABLE pets (
                id INT IDENTITY(1,1) PRIMARY KEY,
                user_id INT FOREIGN KEY REFERENCES users(id),
                name NVARCHAR(255) NOT NULL,
                type NVARCHAR(100) NOT NULL,
                breed NVARCHAR(255),
                age INT,
                created_at DATETIME2 DEFAULT GETDATE()
            )
        """)
        
        # Create bookings table
        cursor.execute("""
            IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='bookings' AND xtype='U')
            CREATE TABLE bookings (
                id INT IDENTITY(1,1) PRIMARY KEY,
                user_id INT FOREIGN KEY REFERENCES users(id),
                pet_id INT FOREIGN KEY REFERENCES pets(id),
                service_type NVARCHAR(100) NOT NULL,
                vendor_id NVARCHAR(100) NOT NULL,
                booking_date DATE NOT NULL,
                booking_time NVARCHAR(50) NOT NULL,
                status NVARCHAR(50) DEFAULT 'pending',
                created_at DATETIME2 DEFAULT GETDATE()
            )
        """)
        

# ===== VENDORS ROUTES =====

@app.route('/api/vendors', methods=['GET'])
def get_vendors():
    """Get all vendors from Azure SQL database"""
    try:
        print("Attempting to fetch vendors...")
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Query to get all vendors with additional details
        cursor.execute("SELECT id, name, rating, price, services FROM Vendors ORDER BY rating DESC")
        
        vendors = []
        for row in cursor.fetchall():
            # Parse the services JSON string
            try:
                services = json.loads(row.services) if row.services else []
            except:
                services = []
            
            vendors.append({
                'id': row.id,
                'name': row.name,
                'rating': float(row.rating),
                'price': row.price,
                'services': services
            })
        
        print(f"Successfully fetched {len(vendors)} vendors")
        return jsonify(vendors)
        
    except Exception as e:
        print(f"Error fetching vendors from database: {str(e)}")
        # Fallback to minimal data if database fails
        fallback_vendors = [
            {
                'id': 1,
                'name': 'Paws & Claws Grooming',
                'rating': 4.8,
                'price': 'From $45',
                'services': ['Grooming', 'Bathing', 'Nail Trimming'],
            }
        ]
        return jsonify(fallback_vendors)
    finally:
        if 'conn' in locals():
            conn.close()

@app.route('/api/vendors/<int:vendor_id>/availability/<date>', methods=['GET'])
def get_vendor_availability(vendor_id, date):
    """Get vendor availability from Azure SQL database"""
    try:
        # Validate date format
        try:
            datetime.strptime(date, '%Y-%m-%d')
        except ValueError:
            return jsonify({'error': 'Invalid date format. Use YYYY-MM-DD'}), 400
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Query to get availability for specific vendor and date
        cursor.execute("""
            SELECT available_slots 
            FROM VendorAvailability 
            WHERE vendor_id = ? AND date = ?
        """, vendor_id, date)
        
        result = cursor.fetchone()
        
        if result:
            try:
                available_slots = json.loads(result.available_slots) if result.available_slots else []
            except:
                available_slots = []
        else:
            # No availability found for this date
            available_slots = []
        
        return jsonify({
            'vendor_id': vendor_id,
            'date': date,
            'availableSlots': available_slots
        })
        
    except Exception as e:
        print(f"Error fetching vendor availability: {str(e)}")
        # Fallback to generated availability
        fallback_data = generate_fallback_availability()
        return jsonify({
            'vendor_id': vendor_id,
            'date': date,
            'availableSlots': fallback_data.get(date, [])
        })
    finally:
        if 'conn' in locals():
            conn.close()

# ===== SERVICES ROUTES =====

@app.route('/api/services', methods=['GET'])
def get_services():
    services = [
        {
            'id': 1,
            'name': 'Premium Pet Grooming',
            'description': 'Professional grooming services with certified groomers across Singapore.',
            'price': 'From $45',
            'features': ['Full wash & dry service', 'Nail trimming & ear cleaning', 'Professional styling']
        },
        {
            'id': 2,
            'name': 'Reliable Pet Sitting',
            'description': 'Experienced pet sitters for day care or overnight stays in your home.',
            'price': 'From $30/day',
            'features': ['Background-checked sitters', 'Daily photo updates', 'Exercise & playtime']
        },
        {
            'id': 3,
            'name': 'Premium Pet Hotels',
            'description': '5-star boarding facilities with round-the-clock care and supervision.',
            'price': 'From $60/night',
            'features': ['Climate-controlled suites', '24/7 veterinary support', 'Daily exercise programs']
        },
        {
            'id': 4,
            'name': 'Professional Pet Training',
            'description': 'Certified trainers for obedience training and behavioral modification.',
            'price': 'From $75/session',
            'features': ['Obedience training', 'Puppy classes', 'Behavioral consultation']
        }
    ]
    return jsonify(services)

# ===== HEALTH CHECK =====

@app.route('/api/health', methods=['GET'])
def health_check():
    return jsonify({'status': 'healthy', 'message': 'PawfectFind API is running'})

if __name__ == '__main__':
    init_db()
    app.run(debug=os.getenv('FLASK_ENV') == 'development', host='0.0.0.0', port=5000)
