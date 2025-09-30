from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
import pyodbc
import os
from datetime import datetime, timedelta
import json
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
CORS(app)

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

# ===== HEALTH CHECK =====

@app.route('/api/health', methods=['GET'])
def health_check():
    return jsonify({'status': 'healthy', 'message': 'PawfectFind API is running'})

if __name__ == '__main__':
    init_db()
    app.run(debug=True, host='0.0.0.0', port=5000)