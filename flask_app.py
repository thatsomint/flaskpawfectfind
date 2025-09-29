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

# Load environment variables
load_dotenv()

app = Flask(__name__)

# Configure JWT first
app.config['JWT_SECRET_KEY'] = os.getenv('JWT_SECRET_KEY', 'your-secret-key-change-in-production')
app.config['JWT_ACCESS_TOKEN_EXPIRES'] = timedelta(hours=24)

# Configure CORS properly (ONCE)
CORS(app, origins=[
    "http://localhost:3000",  # Local frontend
    "http://localhost:5000",  # Local backend
    "https://pawfectfind.azurewebsites.net",  # Production frontend
    "https://pawfectfind-backend.azurewebsites.net"    # Production backend
])

# Initialize JWT after app configuration
jwt = JWTManager(app)

# Azure SQL Database connection
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
        
        # Create Vendors table if not exists
        cursor.execute("""
            IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='Vendors' AND xtype='U')
            CREATE TABLE Vendors (
                id INT IDENTITY(1,1) PRIMARY KEY,
                name NVARCHAR(100) NOT NULL,
                rating DECIMAL(2,1) NOT NULL,
                price NVARCHAR(50) NOT NULL,
                services NVARCHAR(MAX) NOT NULL,
                location NVARCHAR(100),
                description NVARCHAR(500),
                created_at DATETIME2 DEFAULT GETDATE()
            )
        """)
        
        # Create VendorAvailability table if not exists
        cursor.execute("""
            IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='VendorAvailability' AND xtype='U')
            CREATE TABLE VendorAvailability (
                id INT IDENTITY(1,1) PRIMARY KEY,
                vendor_id INT NOT NULL,
                date DATE NOT NULL,
                available_slots NVARCHAR(MAX) NOT NULL,
                FOREIGN KEY (vendor_id) REFERENCES Vendors(id),
                UNIQUE (vendor_id, date)
            )
        """)
        
        # Check if vendors already exist
        cursor.execute("SELECT COUNT(*) FROM Vendors")
        vendor_count = cursor.fetchone()[0]
        
        if vendor_count == 0:
            print("Initializing vendors and availability data...")
            
            # Insert comprehensive vendor data
            vendors_data = [
                ('Paws & Claws Grooming', 4.8, 'From $45', '["Grooming", "Bathing", "Nail Trimming", "Haircut"]', 'Central Singapore', 'Professional grooming with certified experts'),
                ('Happy Tails Pet Hotel', 4.9, 'From $60/night', '["Pet Hotel", "Boarding", "Day Care", "Luxury Suites"]', 'East Singapore', '5-star luxury pet boarding facility'),
                ('Pet Paradise Sitters', 4.7, 'From $30/day', '["Sitter", "Pet Sitting", "Home Visits", "Overnight Stays"]', 'West Singapore', 'Trusted in-home pet sitting services'),
                ('Elite Pet Training', 4.6, 'From $80/session', '["Training", "Behavioral Training", "Obedience", "Puppy Classes"]', 'North Singapore', 'Certified professional dog trainers'),
                ('Premium Pet Groomers', 4.8, 'From $55', '["Grooming", "Styling", "Spa Treatment", "De-shedding"]', 'Central Singapore', 'Premium grooming with spa treatments'),
                ('Cosy Pet Retreat', 4.9, 'From $70/night', '["Pet Hotel", "Luxury Boarding", "Play Areas", "Webcam Access"]', 'South Singapore', 'Luxury retreat with 24/7 webcam access'),
                ('Trusted Pet Minders', 4.7, 'From $35/day', '["Sitter", "Overnight Stays", "Walking", "Medication"]', 'Central Singapore', 'Experienced pet minders for all needs'),
                ('Professional Pet Trainers', 4.5, 'From $75/session', '["Training", "Puppy Training", "Agility", "Behavioral"]', 'East Singapore', 'Specialized training programs')
            ]
            
            for vendor in vendors_data:
                cursor.execute("""
                    INSERT INTO Vendors (name, rating, price, services, location, description)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, vendor[0], vendor[1], vendor[2], vendor[3], vendor[4], vendor[5])
            
            # Generate availability for the next 90 days with realistic patterns
            base_date = datetime.now()
            print("Generating availability data for 90 days...")
            
            for i in range(90):  # 90 days of availability
                current_date = (base_date + timedelta(days=i))
                date_str = current_date.strftime('%Y-%m-%d')
                day_of_week = current_date.weekday()
                
                # Different availability patterns based on vendor type and day of week
                for vendor_id in range(1, 9):  # For all 8 vendors
                    if vendor_id in [1, 5]:  # Grooming services
                        if day_of_week in [5, 6]:  # Weekend
                            slots = ['09:00 AM', '10:30 AM', '02:00 PM', '03:30 PM']
                        else:  # Weekday
                            slots = ['09:00 AM', '10:00 AM', '11:00 AM', '02:00 PM', '03:00 PM', '04:00 PM']
                    
                    elif vendor_id in [2, 6]:  # Pet hotels
                        if day_of_week in [5, 6]:  # Weekend
                            slots = ['08:00 AM', '10:00 AM', '12:00 PM', '02:00 PM', '04:00 PM']
                        else:  # Weekday
                            slots = ['07:00 AM', '09:00 AM', '11:00 AM', '01:00 PM', '03:00 PM', '05:00 PM']
                    
                    elif vendor_id in [3, 7]:  # Pet sitters
                        if day_of_week in [5, 6]:  # Weekend
                            slots = ['08:00 AM', '12:00 PM', '04:00 PM', '06:00 PM']
                        else:  # Weekday
                            slots = ['07:00 AM', '08:00 AM', '05:00 PM', '06:00 PM', '07:00 PM']
                    
                    else:  # Training services (4, 8)
                        if day_of_week in [5, 6]:  # Weekend
                            slots = ['09:00 AM', '11:00 AM', '02:00 PM', '04:00 PM']
                        else:  # Weekday
                            slots = ['08:00 AM', '10:00 AM', '01:00 PM', '03:00 PM', '05:00 PM']
                    
                    # Add some random unavailability (10% chance for any given date)
                    import random
                    if random.random() > 0.1:  # 90% available
                        cursor.execute("""
                            INSERT INTO VendorAvailability (vendor_id, date, available_slots)
                            VALUES (?, ?, ?)
                        """, vendor_id, date_str, json.dumps(slots))
            
            conn.commit()
            print("Vendors and availability data initialized successfully")
        else:
            print(f"Vendors table already contains {vendor_count} vendors")
        
        print("All database tables initialized successfully")
        
    except Exception as e:
        print(f"Error initializing database: {str(e)}")
    finally:
        if 'conn' in locals():
            conn.close()

# Helper function to generate fallback availability data
def generate_fallback_availability():
    """Generate fallback availability data for 30 days"""
    base_date = datetime.now()
    availability_data = {}
    
    for i in range(30):
        date_str = (base_date + timedelta(days=i)).strftime('%Y-%m-%d')
        day_of_week = (base_date + timedelta(days=i)).weekday()
        
        if day_of_week in [5, 6]:  # Weekend
            availability_data[date_str] = ['09:00 AM', '11:00 AM', '02:00 PM', '04:00 PM']
        else:  # Weekday
            availability_data[date_str] = ['08:00 AM', '09:00 AM', '10:00 AM', '02:00 PM', '03:00 PM', '04:00 PM']
    
    return availability_data

# Azure Service Bus configuration
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

# Stripe configuration
stripe.api_key = os.getenv('STRIPE_SECRET_KEY')

# ===== AUTHENTICATION ROUTES =====

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

# ===== PETS ROUTES =====

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

# ===== BOOKINGS ROUTES =====

@app.route('/api/bookings', methods=['GET'])
@jwt_required()
def get_user_bookings():
    """Get all bookings for the current user"""
    try:
        user_id = get_jwt_identity()
        
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT b.id, b.service_type, b.vendor_id, b.booking_date, b.booking_time, b.status, b.created_at,
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
                'booking_time': row.booking_time,
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
            INSERT INTO bookings (user_id, pet_id, service_type, vendor_id, booking_date, booking_time, status)
            VALUES (?, ?, ?, ?, ?, ?, 'confirmed')
        """, user_id, data['pet_id'], data['service_type'], data['vendor_id'], data['booking_date'], data['booking_time'])
        
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
            'status': 'confirmed'
        }
        
        # Send to Service Bus queue
        if send_booking_to_queue(booking_data):
            return jsonify({
                'message': 'Booking created successfully',
                'booking_id': booking_id,
                'status': 'confirmed'
            }), 201
        else:
            return jsonify({'error': 'Booking created but queue service unavailable'}), 201
            
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ===== VENDORS ROUTES =====

@app.route('/api/vendors', methods=['GET'])
def get_vendors():
    """Get all vendors from Azure SQL database"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Query to get all vendors with additional details
        cursor.execute("SELECT id, name, rating, price, services, location, description FROM Vendors ORDER BY rating DESC")
        
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
                'services': services,
                'location': row.location,
                'description': row.description
            })
        
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
                'location': 'Central Singapore',
                'description': 'Professional grooming services'
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

# ===== PAYMENT ROUTES =====

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

# ===== HEALTH CHECK =====

@app.route('/api/health', methods=['GET'])
def health_check():
    return jsonify({'status': 'healthy', 'message': 'PawfectFind API is running'})

# ===== AVAILABILITY BULK CHECK =====

@app.route('/api/vendors/availability/bulk', methods=['POST'])
def get_bulk_availability():
    """Get availability for multiple vendors and dates at once"""
    try:
        data = request.get_json()
        vendor_ids = data.get('vendor_ids', [])
        dates = data.get('dates', [])
        
        if not vendor_ids or not dates:
            return jsonify({'error': 'vendor_ids and dates are required'}), 400
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Build query for multiple vendors and dates
        placeholders = []
        params = []
        for vendor_id in vendor_ids:
            for date in dates:
                placeholders.append('(vendor_id = ? AND date = ?)')
                params.extend([vendor_id, date])
        
        query = f"""
            SELECT vendor_id, date, available_slots 
            FROM VendorAvailability 
            WHERE {' OR '.join(placeholders)}
        """
        
        cursor.execute(query, params)
        results = cursor.fetchall()
        
        availability_map = {}
        for row in results:
            vendor_id = row.vendor_id
            date = row.date.strftime('%Y-%m-%d')
            try:
                slots = json.loads(row.available_slots) if row.available_slots else []
            except:
                slots = []
            
            if vendor_id not in availability_map:
                availability_map[vendor_id] = {}
            availability_map[vendor_id][date] = slots
        
        return jsonify(availability_map)
        
    except Exception as e:
        print(f"Error in bulk availability check: {str(e)}")
        return jsonify({'error': 'Failed to fetch bulk availability'}), 500
    finally:
        if 'conn' in locals():
            conn.close()

if __name__ == '__main__':
    init_db()
    app.run(debug=os.getenv('FLASK_ENV') == 'development', host='0.0.0.0', port=5000)