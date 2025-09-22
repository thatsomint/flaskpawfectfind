from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
from flask_jwt_extended import JWTManager, create_access_token, jwt_required, get_jwt_identity
import pyodbc
import os
from datetime import timedelta
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

# Azure SQL Database connection
def get_db_connection():
    # Use environment variable NAMES, not the actual values
    server = os.getenv('AZURE_SQL_SERVER')  # This should be 'pawfectfinddb.database.windows.net' in your .env
    database = os.getenv('AZURE_SQL_DATABASE')  # This should be 'pawfectfinddb' in your .env
    username = os.getenv('AZURE_SQL_USERNAME')  # This should be 'pawfectadmin' in your .env
    password = os.getenv('AZURE_SQL_PASSWORD')  # This should be 'Password!123' in your .env
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

# Initialize database tables
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

# Auth Routes
@app.route('/api/auth/register', methods=['POST'])
def register():
    try:
        data = request.get_json()
        email = data.get('email')
        password = data.get('password')
        full_name = data.get('full_name')
        phone_number = data.get('phone_number')
        
        if not email or not password or not full_name:
            return jsonify({'error': 'Email, password, and full name are required'}), 400
        
        # Hash password
        password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Check if user already exists
        cursor.execute("SELECT id FROM users WHERE email = ?", (email,))
        if cursor.fetchone():
            return jsonify({'error': 'User already exists'}), 409
        
        # Insert new user
        cursor.execute("""
            INSERT INTO users (email, password_hash, full_name, phone_number)
            OUTPUT INSERTED.id
            VALUES (?, ?, ?, ?)
        """, (email, password_hash, full_name, phone_number))
        
        user_id = cursor.fetchone()[0]
        conn.commit()
        
        # Create access token
        access_token = create_access_token(identity=str(user_id))
        
        return jsonify({
            'message': 'User registered successfully',
            'access_token': access_token,
            'user': {
                'id': user_id,
                'email': email,
                'full_name': full_name
            }
        }), 201
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        if 'conn' in locals():
            conn.close()

@app.route('/api/auth/login', methods=['POST'])
def login():
    try:
        data = request.get_json()
        email = data.get('email')
        password = data.get('password')
        
        if not email or not password:
            return jsonify({'error': 'Email and password are required'}), 400
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT id, email, password_hash, full_name FROM users WHERE email = ?
        """, (email,))
        
        user = cursor.fetchone()
        
        if not user or not bcrypt.checkpw(password.encode('utf-8'), user[2].encode('utf-8')):
            return jsonify({'error': 'Invalid credentials'}), 401
        
        access_token = create_access_token(identity=str(user[0]))
        
        return jsonify({
            'message': 'Login successful',
            'access_token': access_token,
            'user': {
                'id': user[0],
                'email': user[1],
                'full_name': user[3]
            }
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        if 'conn' in locals():
            conn.close()

# Protected Routes
@app.route('/api/profile', methods=['GET'])
@jwt_required()
def get_profile():
    try:
        user_id = get_jwt_identity()
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT id, email, full_name, phone_number, created_at 
            FROM users WHERE id = ?
        """, (user_id,))
        
        user = cursor.fetchone()
        
        if not user:
            return jsonify({'error': 'User not found'}), 404
        
        return jsonify({
            'user': {
                'id': user[0],
                'email': user[1],
                'full_name': user[2],
                'phone_number': user[3],
                'created_at': user[4]
            }
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        if 'conn' in locals():
            conn.close()

@app.route('/api/pets', methods=['GET'])
@jwt_required()
def get_user_pets():
    try:
        user_id = get_jwt_identity()
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT id, name, type, breed, age, created_at 
            FROM pets WHERE user_id = ? ORDER BY created_at DESC
        """, (user_id,))
        
        pets = []
        for row in cursor.fetchall():
            pets.append({
                'id': row[0],
                'name': row[1],
                'type': row[2],
                'breed': row[3],
                'age': row[4],
                'created_at': row[5]
            })
        
        return jsonify({'pets': pets})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        if 'conn' in locals():
            conn.close()

@app.route('/api/pets', methods=['POST'])
@jwt_required()
def add_pet():
    try:
        user_id = get_jwt_identity()
        data = request.get_json()
        
        name = data.get('name')
        pet_type = data.get('type')
        breed = data.get('breed')
        age = data.get('age')
        
        if not name or not pet_type:
            return jsonify({'error': 'Name and type are required'}), 400
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO pets (user_id, name, type, breed, age)
            OUTPUT INSERTED.id
            VALUES (?, ?, ?, ?, ?)
        """, (user_id, name, pet_type, breed, age))
        
        pet_id = cursor.fetchone()[0]
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

@app.route('/api/bookings', methods=['POST'])
@jwt_required()
def create_booking():
    try:
        user_id = get_jwt_identity()
        data = request.get_json()
        
        pet_id = data.get('pet_id')
        service_type = data.get('service_type')
        vendor_id = data.get('vendor_id')
        booking_date = data.get('booking_date')
        
        if not all([pet_id, service_type, vendor_id, booking_date]):
            return jsonify({'error': 'All fields are required'}), 400
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO bookings (user_id, pet_id, service_type, vendor_id, booking_date)
            OUTPUT INSERTED.id
            VALUES (?, ?, ?, ?, ?)
        """, (user_id, pet_id, service_type, vendor_id, booking_date))
        
        booking_id = cursor.fetchone()[0]
        conn.commit()
        
        return jsonify({
            'message': 'Booking created successfully',
            'booking_id': booking_id
        }), 201
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        if 'conn' in locals():
            conn.close()

@app.route('/api/bookings', methods=['GET'])
@jwt_required()
def get_user_bookings():
    try:
        user_id = get_jwt_identity()
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT b.id, b.service_type, b.vendor_id, b.booking_date, b.status, b.created_at,
                   p.name as pet_name
            FROM bookings b
            JOIN pets p ON b.pet_id = p.id
            WHERE b.user_id = ?
            ORDER BY b.created_at DESC
        """, (user_id,))
        
        bookings = []
        for row in cursor.fetchall():
            bookings.append({
                'id': row[0],
                'service_type': row[1],
                'vendor_id': row[2],
                'booking_date': row[3].isoformat() if row[3] else None,
                'status': row[4],
                'created_at': row[5].isoformat() if row[5] else None,
                'pet_name': row[6]
            })
        
        return jsonify({'bookings': bookings})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        if 'conn' in locals():
            conn.close()

# Public routes
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
        }
    ]
    return jsonify(services)

@app.route('/api/vendors', methods=['GET'])
def get_vendors():
    vendors = [
        {
            'id': 'paws',
            'name': 'Paws & Claws Grooming',
            'rating': 4.9,
            'services': ['Grooming', 'Breed Specialist'],
            'price': 'From $45',
            'availability': {}
        },
        {
            'id': 'happy',
            'name': 'Happy Tails Pet Hotel',
            'rating': 4.7,
            'services': ['Pet Hotel', 'Boarding', 'Day Care'],
            'price': 'From $60/night',
            'availability': {}
        }
    ]
    return jsonify(vendors)

@app.route('/api/health', methods=['GET'])
def health_check():
    return jsonify({'status': 'healthy', 'message': 'PawfectFind API is running'})

if __name__ == '__main__':
    init_db()
    app.run(debug=os.getenv('FLASK_ENV') == 'development', host='0.0.0.0', port=5000)
