from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
import pyodbc
import os
from datetime import datetime, timedelta
import json
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
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

@app.route('/api/debug/service-bus-test', methods=['POST'])
def test_service_bus():
    """Test endpoint to simulate Service Bus message processing"""
    try:
        booking_data = request.json
        
        # Log the simulated Service Bus processing
        print("🔔 SERVICE BUS SIMULATION - Processing booking:")
        print(f"   Booking ID: {booking_data.get('bookingId')}")
        print(f"   Service: {booking_data.get('booking', {}).get('service')}")
        print(f"   Vendor: {booking_data.get('booking', {}).get('vendor')}")
        print(f"   Customer: {booking_data.get('customer', {}).get('name')}")
        
        # Simulate processing delay
        time.sleep(1)
        
        return jsonify({
            'status': 'processed',
            'message': 'Booking would be processed by Service Bus consumer',
            'booking_id': booking_data.get('bookingId'),
            'processed_at': datetime.now().isoformat()
        })
        
    except Exception as e:
        print(f"Service Bus test error: {e}")
        return jsonify({'error': str(e)}), 400

# ===== HEALTH CHECK =====

@app.route('/api/health', methods=['GET'])
def health_check():
    return jsonify({'status': 'healthy', 'message': 'PawfectFind API is running'})

if __name__ == '__main__':
    init_db()
    app.run(debug=True, host='0.0.0.0', port=8000)
