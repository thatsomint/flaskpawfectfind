from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
from flask_jwt_extended import JWTManager, create_access_token, jwt_required, get_jwt_identity
import pyodbc
import os
from datetime import datetime, timedelta
import bcrypt
from dotenv import load_dotenv
from azure.servicebus import ServiceBusClient, ServiceBusMessage
import json
import stripe
import bcrypt

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

# Azure Service Bus configuration (MOVE THIS UP)
SERVICE_BUS_CONNECTION_STRING = os.getenv('SERVICE_BUS_CONNECTION_STRING')
BOOKING_QUEUE_NAME = "booking-queue"

def send_booking_to_queue(booking_data):
    """Send booking to Azure Service Bus queue"""
    try:
        servicebus_client = ServiceBusClient.from_connection_string(SERVICE_BUS_CONNECTION_STRING)
        with servicebus_client:
            sender = servicebus_client.get_queue_sender(BOOKING_QUEUE_NAME)
            with sender:
                message = ServiceBusMessage(json.dumps(booking_data))
                sender.send_messages(message)
        return True
    except Exception as e:
        print(f"Error sending to Service Bus: {e}")
        return False

# Stripe configuration (MOVE THIS UP)
stripe.api_key = os.getenv('STRIPE_SECRET_KEY')

# Complete authentication and user management routes
@app.route('/api/auth/register', methods=['POST'])
def register():
    """Register a new user"""
    try:
        data = request.get_json()
        
        # Validate required fields
        required_fields = ['email', 'password', 'full_name']
        for field in required_fields:
            if field not in data:
                return jsonify({'error': f'Missing required field: {field}'}), 400
        
        email = data['email']
        password = data['password']
        full_name = data['full_name']
        phone_number = data.get('phone_number')
        
        # Check if user already exists
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM users WHERE email = ?", email)
        if cursor.fetchone():
            return jsonify({'error': 'User already exists with this email'}), 400
        
        # Hash password
        password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        
        # Create user
        cursor.execute("""
            INSERT INTO users (email, password_hash, full_name, phone_number)
            VALUES (?, ?, ?, ?)
        """, email, password_hash, full_name, phone_number)
        
        user_id = cursor.fetchval("SELECT SCOPE_IDENTITY()")
        conn.commit()
        
        # Generate JWT token
        access_token = create_access_token(identity=user_id)
        
        return jsonify({
            'message': 'User registered successfully',
            'access_token': access_token,
            'user': {
                'id': user_id,
                'email': email,
                'full_name': full_name,
                'phone_number': phone_number
            }
        }), 201
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        if 'conn' in locals():
            conn.close()

@app.route('/api/auth/login', methods=['POST'])
def login():
    """Login user"""
    try:
        data = request.get_json()
        
        # Validate required fields
        if 'email' not in data or 'password' not in data:
            return jsonify({'error': 'Email and password are required'}), 400
        
        email = data['email']
        password = data['password']
        
        # Find user
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, email, password_hash, full_name, phone_number 
            FROM users WHERE email = ?
        """, email)
        
        user = cursor.fetchone()
        if not user:
            return jsonify({'error': 'Invalid email or password'}), 401
        
        # Verify password
        if not bcrypt.checkpw(password.encode('utf-8'), user.password_hash.encode('utf-8')):
            return jsonify({'error': 'Invalid email or password'}), 401
        
        # Generate JWT token
        access_token = create_access_token(identity=user.id)
        
        return jsonify({
            'message': 'Login successful',
            'access_token': access_token,
            'user': {
                'id': user.id,
                'email': user.email,
                'full_name': user.full_name,
                'phone_number': user.phone_number
            }
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        if 'conn' in locals():
            conn.close()

@app.route('/api/profile', methods=['GET'])
@jwt_required()
def get_profile():
    """Get user profile"""
    try:
        user_id = get_jwt_identity()
        
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, email, full_name, phone_number, created_at 
            FROM users WHERE id = ?
        """, user_id)
        
        user = cursor.fetchone()
        if not user:
            return jsonify({'error': 'User not found'}), 404
        
        return jsonify({
            'id': user.id,
            'email': user.email,
            'full_name': user.full_name,
            'phone_number': user.phone_number,
            'created_at': user.created_at.isoformat() if user.created_at else None
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        if 'conn' in locals():
            conn.close()

@app.route('/api/pets', methods=['GET'])
@jwt_required()
def get_user_pets():
    """Get all pets for the current user"""
    try:
        user_id = get_jwt_identity()
        
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, name, type, breed, age, created_at 
            FROM pets WHERE user_id = ? ORDER BY created_at DESC
        """, user_id)
        
        pets = []
        for row in cursor.fetchall():
            pets.append({
                'id': row.id,
                'name': row.name,
                'type': row.type,
                'breed': row.breed,
                'age': row.age,
                'created_at': row.created_at.isoformat() if row.created_at else None
            })
        
        return jsonify(pets)
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        if 'conn' in locals():
            conn.close()

@app.route('/api/pets', methods=['POST'])
@jwt_required()
def add_pet():
    """Add a new pet for the current user"""
    try:
        user_id = get_jwt_identity()
        data = request.get_json()
        
        # Validate required fields
        required_fields = ['name', 'type']
        for field in required_fields:
            if field not in data:
                return jsonify({'error': f'Missing required field: {field}'}), 400
        
        name = data['name']
        pet_type = data['type']
        breed = data.get('breed')
        age = data.get('age')
        
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO pets (user_id, name, type, breed, age)
            VALUES (?, ?, ?, ?, ?)
        """, user_id, name, pet_type, breed, age)
        
        pet_id = cursor.fetchval("SELECT SCOPE_IDENTITY()")
        conn.commit()
        
        return jsonify({
            'message': 'Pet added successfully',
            'pet_id': pet_id
        }), 201
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        if 'conn' in locals():
            conn.close()

@app.route('/api/bookings', methods=['GET'])
@jwt_required()
def get_user_bookings():
    """Get all bookings for the current user"""
    try:
        user_id = get_jwt_identity()
        
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT b.id, b.service_type, b.vendor_id, b.booking_date, b.status, b.created_at,
                   p.name as pet_name, p.type as pet_type
            FROM bookings b
            LEFT JOIN pets p ON b.pet_id = p.id
            WHERE b.user_id = ? 
            ORDER BY b.booking_date DESC
        """, user_id)
        
        bookings = []
        for row in cursor.fetchall():
            bookings.append({
                'id': row.id,
                'service_type': row.service_type,
                'vendor_id': row.vendor_id,
                'booking_date': row.booking_date.isoformat() if row.booking_date else None,
                'status': row.status,
                'pet_name': row.pet_name,
                'pet_type': row.pet_type,
                'created_at': row.created_at.isoformat() if row.created_at else None
            })
        
        return jsonify(bookings)
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        if 'conn' in locals():
            conn.close()

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

@app.route('/api/bookings', methods=['POST'])
@jwt_required()
def create_booking():
    """Create a new booking with Service Bus integration"""
    try:
        user_id = get_jwt_identity()
        data = request.get_json()
        
        # Validate required fields
        required_fields = ['pet_id', 'service_type', 'vendor_id', 'booking_date', 'booking_time']
        for field in required_fields:
            if field not in data:
                return jsonify({'error': f'Missing required field: {field}'}), 400
        
        # Create booking in database
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO bookings (user_id, pet_id, service_type, vendor_id, booking_date, status)
            VALUES (?, ?, ?, ?, ?, 'pending')
        """, user_id, data['pet_id'], data['service_type'], data['vendor_id'], data['booking_date'])
        
        booking_id = cursor.fetchval("SELECT SCOPE_IDENTITY()")
        conn.commit()
        
        # Prepare booking data for Service Bus
        booking_data = {
            'booking_id': booking_id,
            'user_id': user_id,
            'service_type': data['service_type'],
            'vendor_id': data['vendor_id'],
            'booking_date': data['booking_date'],
            'booking_time': data['booking_time'],
            'status': 'pending'
        }
        
        # Send to Service Bus queue
        if send_booking_to_queue(booking_data):
            return jsonify({
                'message': 'Booking created successfully',
                'booking_id': booking_id,
                'status': 'pending'
            }), 201
        else:
            return jsonify({'error': 'Booking created but queue service unavailable'}), 201
            
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/create-payment-intent', methods=['POST'])
@jwt_required()
def create_payment_intent():
    try:
        data = request.get_json()
        amount = data['amount']  # Amount in cents
        
        # Create PaymentIntent
        intent = stripe.PaymentIntent.create(
            amount=amount,
            currency='sgd',
            metadata={
                'booking_id': data.get('booking_id'),
                'user_id': get_jwt_identity()
            }
        )
        
        return jsonify({
            'clientSecret': intent.client_secret
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    init_db()
    app.run(debug=os.getenv('FLASK_ENV') == 'development', host='0.0.0.0', port=5000)

