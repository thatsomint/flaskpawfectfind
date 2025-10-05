from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
import pyodbc
import os
from datetime import datetime, timedelta
import json
from dotenv import load_dotenv
import time

load_dotenv()

app = Flask(__name__)

# TEST ROUTE - Add this at the very top
@app.route('/test')
def test():
    return "Flask is working!"
    
# Configure CORS properly
CORS(app, resources={
    r"/api/*": {
        "origins": ["*"],  # Allow all for demo
        "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        "allow_headers": ["Content-Type", "Authorization", "Accept"]
    }
})

# Azure SQL Database connection
# ===== HARDCODED WITH FALLBACK =====
# Use hardcoded values if environment variables aren't set
AZURE_SQL_SERVER = "pawfectfinddb.database.windows.net"
AZURE_SQL_DATABASE = "pawfectfinddb"
AZURE_SQL_USERNAME = "pawfectadmin"
AZURE_SQL_PASSWORD = "Password!123"
# ===================================

def get_db_connection():
    driver = '{ODBC Driver 18 for SQL Server}'
    
    connection_string = f"""
        DRIVER={driver};
        SERVER={AZURE_SQL_SERVER};
        DATABASE={AZURE_SQL_DATABASE};
        UID={AZURE_SQL_USERNAME};
        PWD={AZURE_SQL_PASSWORD};
        Encrypt=yes;
        TrustServerCertificate=no;
        Connection Timeout=30;
    """
    
    return pyodbc.connect(connection_string)

# Simple initialization - just check if vendors exist
def init_db():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Check if vendors exist
        cursor.execute("SELECT COUNT(*) FROM Vendors")
        vendor_count = cursor.fetchone()[0]
        
        if vendor_count == 0:
            print("No vendors found. Please run the SQL script to populate vendors.")
        else:
            print(f"Found {vendor_count} vendors in database")
        
    except Exception as e:
        print(f"Database initialization error: {str(e)}")
    finally:
        if 'conn' in locals():
            conn.close()

# ===== VENDORS ROUTES =====

@app.route('/api/vendors', methods=['GET'])
def get_vendors():
    """Get all vendors with their availability"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT id, name, rating, price, services, availability, location, description 
            FROM Vendors 
            ORDER BY rating DESC
        """)
        
        vendors = []
        for row in cursor.fetchall():
            try:
                services = json.loads(row.services) if row.services else []
                availability = json.loads(row.availability) if row.availability else {}
            except:
                services = []
                availability = {}
            
            vendor = {
                'id': row.id,
                'name': row.name,
                'rating': float(row.rating),
                'price': row.price,
                'services': services,
                'availableSlots': availability,  # ← CRITICAL: Changed from 'availability' to 'availableSlots'
                'location': row.location,
                'description': row.description
            }
            vendors.append(vendor)
        
        print(f"Successfully fetched {len(vendors)} vendors")
        return jsonify(vendors)
        
    except Exception as e:
        print(f"Error fetching vendors: {str(e)}")
        # Fallback to ensure frontend works
        return jsonify([])
    finally:
        if 'conn' in locals():
            conn.close()

@app.route('/api/vendors/<vendor_id>/availability/<date>', methods=['GET'])
def get_vendor_availability(vendor_id, date):
    """Get vendor availability for a specific date"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Get vendor's full availability
        cursor.execute("SELECT availability FROM Vendors WHERE id = ?", vendor_id)
        result = cursor.fetchone()
        
        available_slots = []
        
        if result and result.availability:
            try:
                availability_data = json.loads(result.availability)
                available_slots = availability_data.get(date, [])
            except Exception as e:
                print(f"Error parsing availability: {e}")
        
        # If no slots found for that date, return empty array
        return jsonify({
            'vendor_id': vendor_id,
            'date': date,
            'availableSlots': available_slots
        })
        
    except Exception as e:
        print(f"Error fetching vendor availability: {str(e)}")
        return jsonify({
            'vendor_id': vendor_id,
            'date': date,
            'availableSlots': []
        })
    finally:
        if 'conn' in locals():
            conn.close()

def get_demo_bookings():
    """Get all demo bookings from localStorage (for debugging)"""
    # This would normally come from your database
    return jsonify({
        'message': 'Service Bus simulation - these bookings would be processed',
        'bookings': []  # You could store these in a temporary table
    })

@app.route('/api/debug/db-test', methods=['GET'])
def debug_db_test():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM Bookings")
        count = cursor.fetchone()[0]
        conn.close()
        return jsonify({"bookings_count": count, "status": "success"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# @app.route('/api/debug/service-bus-test', methods=['POST'])
# def test_service_bus():
#     """Test endpoint to simulate Service Bus message processing"""
#     try:
#         booking_data = request.json
        
#         # Log the simulated Service Bus processing
#         print("🔔 SERVICE BUS SIMULATION - Processing booking:")
#         print(f"   Booking ID: {booking_data.get('bookingId')}")
#         print(f"   Service: {booking_data.get('booking', {}).get('service')}")
#         print(f"   Vendor: {booking_data.get('booking', {}).get('vendor')}")
#         print(f"   Customer: {booking_data.get('customer', {}).get('name')}")
        
#         # Simulate processing delay
#         time.sleep(1)
        
#         return jsonify({
#             'status': 'processed',
#             'message': 'Booking would be processed by Service Bus consumer',
#             'booking_id': booking_data.get('bookingId'),
#             'processed_at': datetime.now().isoformat()
#         })
        
#     except Exception as e:
#         print(f"Service Bus test error: {e}")
#         return jsonify({'error': str(e)}), 400

# ===== BOOKINGS ROUTES =====
@app.route('/api/bookings', methods=['POST', 'OPTIONS'])
def create_booking():
    """Create a new booking from booking-confirmation.html"""
    if request.method == 'OPTIONS':
        return '', 200  # Handle CORS preflight
    
    try:
        booking_data = request.json
        print(f"📝 Creating booking: {booking_data}")
        
        # Get user_id from request (no fallback)
        user_id = booking_data.get('user_id')
        if not user_id:
            return jsonify({'error': 'User ID is required'}), 400
        
        print(f"🔧 Connecting to database...")
        conn = get_db_connection()
        cursor = conn.cursor()
        
        print(f"🔧 Executing INSERT query...")
        cursor.execute("""
            INSERT INTO Bookings (
                user_id, service_type, vendor_name, booking_date, booking_time, 
                price, customer_name, customer_email, customer_phone, special_instructions
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            user_id,
            booking_data.get('service_type'),
            booking_data.get('vendor_name'),
            booking_data.get('booking_date'),
            booking_data.get('booking_time'),
            booking_data.get('price'),
            booking_data.get('customer_name'),
            booking_data.get('customer_email'),
            booking_data.get('customer_phone'),
            booking_data.get('special_instructions', '')
        ))
        
        conn.commit()
        print(f"✅ Booking created successfully for user: {user_id}")
        
        return jsonify({
            'success': True,
            'message': 'Booking created successfully'
        })
        
    except Exception as e:
        print(f"❌ Error creating booking: {str(e)}")
        return jsonify({'error': str(e)}), 500
    finally:
        if 'conn' in locals():
            conn.close()

@app.route('/api/bookings/<user_id>', methods=['GET'])
def get_user_bookings(user_id):
    """Get all bookings for userdashboard.html calendar"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT 
                service_type,
                vendor_name,
                booking_date,
                booking_time,
                price,
                customer_name,
                status
            FROM Bookings 
            WHERE user_id = ?
            ORDER BY booking_date, booking_time
        """, user_id)
        
        bookings = []
        for row in cursor.fetchall():
            booking = {
                'service_type': row.service_type,
                'vendor_name': row.vendor_name,
                'booking_date': row.booking_date.isoformat() if row.booking_date else None,
                'booking_time': row.booking_time,
                'price': float(row.price) if row.price else 0,
                'customer_name': row.customer_name,
                'status': row.status
            }
            bookings.append(booking)
        
        print(f"✅ Found {len(bookings)} bookings for user {user_id}")
        return jsonify(bookings)
        
    except Exception as e:
        print(f"❌ Error fetching bookings: {str(e)}")
        return jsonify({'error': str(e)}), 500
    finally:
        if 'conn' in locals():
            conn.close()

@app.route('/api/bookings/upcoming/<user_id>', methods=['GET'])
def get_upcoming_bookings(user_id):
    """Get upcoming bookings (next 30 days)"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT 
                service_type,
                vendor_name,
                booking_date,
                booking_time,
                customer_name,
                status
            FROM Bookings 
            WHERE user_id = ? 
                AND booking_date >= CAST(GETDATE() AS DATE)
                AND booking_date <= DATEADD(DAY, 30, CAST(GETDATE() AS DATE))
                AND status = 'confirmed'
            ORDER BY booking_date, booking_time
        """, user_id)
        
        upcoming = []
        for row in cursor.fetchall():
            booking = {
                'service_type': row.service_type,
                'vendor_name': row.vendor_name,
                'booking_date': row.booking_date.isoformat() if row.booking_date else None,
                'booking_time': row.booking_time,
                'customer_name': row.customer_name,
                'status': row.status
            }
            upcoming.append(booking)
        
        return jsonify(upcoming)
        
    except Exception as e:
        print(f"Error fetching upcoming bookings: {str(e)}")
        return jsonify({'error': str(e)}), 500
    finally:
        if 'conn' in locals():
            conn.close()

@app.route('/api/bookings/history/<user_id>', methods=['GET'])
def get_booking_history(user_id):
    """Get past bookings (service history)"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT 
                service_type,
                vendor_name,
                booking_date,
                booking_time,
                customer_name,
                status,
                price
            FROM Bookings 
            WHERE user_id = ? 
                AND booking_date < CAST(GETDATE() AS DATE)
            ORDER BY booking_date DESC
        """, user_id)
        
        history = []
        for row in cursor.fetchall():
            booking = {
                'service_type': row.service_type,
                'vendor_name': row.vendor_name,
                'booking_date': row.booking_date.isoformat() if row.booking_date else None,
                'booking_time': row.booking_time,
                'customer_name': row.customer_name,
                'status': row.status,
                'price': float(row.price) if row.price else 0
            }
            history.append(booking)
        
        return jsonify(history)
        
    except Exception as e:
        print(f"Error fetching booking history: {str(e)}")
        return jsonify({'error': str(e)}), 500
    finally:
        if 'conn' in locals():
            conn.close()

# ===== HEALTH CHECK =====
@app.route('/api/health', methods=['GET'])
def health_check():
    try:
        # Test database connection
        conn = get_db_connection()
        conn.close()
        return jsonify({
            'status': 'healthy', 
            'message': 'PawfectFind API is running',
            'database': 'connected'
        })
    except Exception as e:
        return jsonify({
            'status': 'unhealthy',
            'message': 'Database connection failed',
            'error': str(e)
        }), 500

if __name__ == '__main__':
    init_db()
    app.run(debug=True, host='0.0.0.0', port=8000)
