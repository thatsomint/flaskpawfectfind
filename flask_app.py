from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
from flask_jwt_extended import JWTManager, create_access_token, jwt_required, get_jwt_identity
import pyodbc
import os
from datetime import datetime, timedelta
import bcrypt
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

app = Flask(__name__)

# ✅ CORRECTED: Configure JWT first
app.config['JWT_SECRET_KEY'] = os.getenv('JWT_SECRET_KEY', 'your-secret-key-change-in-production')
app.config['JWT_ACCESS_TOKEN_EXPIRES'] = timedelta(hours=24)

# ✅ CORRECTED: Configure CORS properly (ONCE)
CORS(app, origins=[
    "http://localhost:3000",  # Local frontend
    "http://localhost:5000",  # Local backend
    "https://pawfectfind.azurewebsites.net",  # Production frontend
    "https://pawfectfind-backend.azurewebsites.net"    # Production backend
])

# ✅ Initialize JWT after app configuration
jwt = JWTManager(app)

# Azure SQL Database connection (keep your existing function)
def get_db_connection():
    server = os.getenv('AZURE_SQL_SERVER')
    database = os.getenv('AZURE_SQL_DATABASE')
    username = os.getenv('AZURE_SQL_USERNAME')
    password = os.getenv('AZURE_SQL_PASSWORD')
    driver = '{ODBC Driver 18 for SQL Server}'
    
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

# Initialize database tables (keep your existing function)
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
                status NVARCHAR(50) DEFAULT 'pending',
                created_at DATETIME2 DEFAULT GETDATE()
            )
        """)
        
        conn.commit()
        print("Database tables initialized successfully")
        
    except Exception as e:
        print(f"Error initializing database: {str(e)}")
    finally:
        if 'conn' in locals():
            conn.close()

# Helper function to generate availability data
def generate_availability_data():
    """Generate realistic availability data for vendors"""
    # Generate dates for the next 30 days
    base_date = datetime.now()
    availability_data = {}
    
    for i in range(30):
        date_str = (base_date + timedelta(days=i)).strftime('%Y-%m-%d')
        
        # Different availability patterns for different days of the week
        day_of_week = (base_date + timedelta(days=i)).weekday()
        
        if day_of_week in [5, 6]:  # Weekend - more limited availability
            availability_data[date_str] = ['10:00 AM', '02:00 PM', '04:00 PM']
        else:  # Weekday - more availability
            availability_data[date_str] = ['09:00 AM', '10:00 AM', '11:00 AM', '02:00 PM', '03:00 PM', '04:00 PM']
    
    return availability_data

def generate_hotel_availability():
    """Generate different availability pattern for pet hotels"""
    base_date = datetime.now()
    availability_data = {}
    
    for i in range(30):
        date_str = (base_date + timedelta(days=i)).strftime('%Y-%m-%d')
        day_of_week = (base_date + timedelta(days=i)).weekday()
        
        # Hotels have different time slots (check-in/check-out times)
        if day_of_week in [5, 6]:  # Weekend
            availability_data[date_str] = ['09:00 AM', '11:00 AM', '03:00 PM', '05:00 PM']
        else:  # Weekday
            availability_data[date_str] = ['08:00 AM', '10:00 AM', '12:00 PM', '02:00 PM', '04:00 PM', '06:00 PM']
    
    return availability_data

def generate_training_availability():
    """Generate availability for training services"""
    base_date = datetime.now()
    availability_data = {}
    
    for i in range(30):
        date_str = (base_date + timedelta(days=i)).strftime('%Y-%m-%d')
        day_of_week = (base_date + timedelta(days=i)).weekday()
        
        # Training sessions typically have specific time blocks
        if day_of_week in [5, 6]:  # Weekend
            availability_data[date_str] = ['09:00 AM', '11:00 AM', '02:00 PM']
        else:  # Weekday
            availability_data[date_str] = ['08:00 AM', '10:00 AM', '01:00 PM', '03:00 PM', '05:00 PM']
    
    return availability_data

# Keep all your existing auth routes (register, login, profile, pets, bookings)
@app.route('/api/auth/register', methods=['POST'])
def register():
    # ... keep your existing register code ...

@app.route('/api/auth/login', methods=['POST'])
def login():
    # ... keep your existing login code ...

@app.route('/api/profile', methods=['GET'])
@jwt_required()
def get_profile():
    # ... keep your existing profile code ...

@app.route('/api/pets', methods=['GET'])
@jwt_required()
def get_user_pets():
    # ... keep your existing pets code ...

@app.route('/api/pets', methods=['POST'])
@jwt_required()
def add_pet():
    # ... keep your existing add_pet code ...

@app.route('/api/bookings', methods=['POST'])
@jwt_required()
def create_booking():
    # ... keep your existing create_booking code ...

@app.route('/api/bookings', methods=['GET'])
@jwt_required()
def get_user_bookings():
    # ... keep your existing get_bookings code ...

# UPDATED Public routes with proper availability data
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

# UPDATED Vendors endpoint with proper availability data
@app.route('/api/vendors', methods=['GET'])
def get_vendors():
    vendors = [
        {
            'id': 'paws',
            'name': 'Paws & Claws Grooming',
            'rating': 4.9,
            'services': ['Grooming', 'Breed Specialist'],
            'price': 'From $45',
            'availableSlots': generate_availability_data()  # CHANGED from 'availability' to 'availableSlots'
        },
        {
            'id': 'happy',
            'name': 'Happy Tails Pet Hotel',
            'rating': 4.7,
            'services': ['Pet Hotel', 'Boarding', 'Day Care'],
            'price': 'From $60/night',
            'availableSlots': generate_hotel_availability()  # CHANGED from 'availability' to 'availableSlots'
        },
        {
            'id': 'bark',
            'name': 'Bark Avenue Training',
            'rating': 4.8,
            'services': ['Obedience Training', 'Puppy Classes', 'Behavioral'],
            'price': 'From $75/session',
            'availableSlots': generate_training_availability()  # CHANGED from 'availability' to 'availableSlots'
        },
        {
            'id': 'whiskers',
            'name': 'Whiskers Wellness',
            'rating': 4.6,
            'services': ['Veterinary', 'Wellness', 'Dental Care'],
            'price': 'From $55',
            'availableSlots': generate_availability_data()  # CHANGED from 'availability' to 'availableSlots'
        },
        {
            'id': 'furry',
            'name': 'Furry Friends Grooming',
            'rating': 4.5,
            'services': ['Grooming', 'Small Animals'],
            'price': 'From $35',
            'availableSlots': generate_availability_data()  # CHANGED from 'availability' to 'availableSlots'
        }
    ]
    return jsonify(vendors)

# New endpoint to get vendor availability for a specific date
@app.route('/api/vendors/<vendor_id>/availability/<date>', methods=['GET'])
def get_vendor_availability(vendor_id, date):
    """Get specific availability for a vendor on a given date"""
    try:
        # Validate date format
        try:
            datetime.strptime(date, '%Y-%m-%d')
        except ValueError:
            return jsonify({'error': 'Invalid date format. Use YYYY-MM-DD'}), 400
        
        vendors_data = {
            'paws': generate_availability_data(),
            'happy': generate_hotel_availability(),
            'bark': generate_training_availability(),
            'whiskers': generate_availability_data(),
            'furry': generate_availability_data()
        }
        
        if vendor_id not in vendors_data:
            return jsonify({'error': 'Vendor not found'}), 404
        
        availability = vendors_data[vendor_id].get(date, [])
        
        return jsonify({
            'vendor_id': vendor_id,
            'date': date,
            'availableSlots': availability
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/health', methods=['GET'])
def health_check():
    return jsonify({'status': 'healthy', 'message': 'PawfectFind API is running'})

if __name__ == '__main__':
    init_db()
    app.run(debug=os.getenv('FLASK_ENV') == 'development', host='0.0.0.0', port=5000)