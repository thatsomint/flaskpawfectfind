import os
import json
import logging
import time
from azure.servicebus import ServiceBusClient, ServiceBusMessage
import pyodbc

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

# Service Bus configuration
SERVICE_BUS_CONNECTION_STRING = os.getenv('SERVICE_BUS_CONNECTION_STRING')
BOOKING_QUEUE_NAME = "booking-queue"

# Database connection function (same as in flask_app.py)
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

def process_booking_message(booking_data):
    """Process booking message - this is where the actual work happens"""
    try:
        logger.info(f"🔄 Processing booking ID: {booking_data.get('booking_id')}")
        
        # Simulate some processing work (replace with your actual logic)
        logger.info(f"📋 Booking details: {booking_data.get('service_type')} with vendor {booking_data.get('vendor_id')}")
        
        # Example processing tasks:
        # 1. Update booking status in database
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            UPDATE bookings 
            SET status = 'confirmed' 
            WHERE id = ?
        """, booking_data['booking_id'])
        
        conn.commit()
        conn.close()
        
        # 2. Here you could add:
        # - Send confirmation email
        # - Notify the vendor
        # - Update calendar systems
        # - Process payment (if not done upfront)
        
        logger.info(f"✅ Booking {booking_data['booking_id']} processed successfully")
        return True
        
    except Exception as e:
        logger.error(f"❌ Error processing booking {booking_data.get('booking_id')}: {str(e)}")
        # Re-raise the exception to trigger Service Bus retry
        raise e

def receive_messages():
    """Receive and process messages from Service Bus queue"""
    try:
        servicebus_client = ServiceBusClient.from_connection_string(SERVICE_BUS_CONNECTION_STRING)
        
        with servicebus_client:
            # Create a receiver that waits for messages
            receiver = servicebus_client.get_queue_receiver(
                queue_name=BOOKING_QUEUE_NAME,
                max_wait_time=30  # Wait up to 30 seconds for messages
            )
            
            with receiver:
                logger.info("👂 Listening for messages on booking queue...")
                
                for msg in receiver:
                    try:
                        logger.info(f"📨 Received message: {msg.message_id}")
                        
                        # Parse the message
                        booking_data = json.loads(str(msg))
                        
                        # Process the message
                        process_booking_message(booking_data)
                        
                        # If successful, complete the message (remove from queue)
                        receiver.complete_message(msg)
                        logger.info(f"✅ Message {msg.message_id} processed successfully")
                        
                    except Exception as e:
                        logger.error(f"❌ Failed to process message {msg.message_id}: {str(e)}")
                        
                        # Abandon the message (Service Bus will retry based on Max Delivery Count)
                        receiver.abandon_message(msg)
                        logger.info("🔄 Message abandoned, will be retried")
                        
    except Exception as e:
        logger.error(f"💥 Service Bus connection error: {str(e)}")
        raise e

def main():
    """Main loop to keep the consumer running"""
    logger.info("🚀 Starting PawfectFind Booking Queue Consumer")
    
    while True:
        try:
            receive_messages()
        except KeyboardInterrupt:
            logger.info("⏹️ Consumer stopped by user")
            break
        except Exception as e:
            logger.error(f"💥 Consumer error: {str(e)}")
            logger.info("🔄 Restarting consumer in 10 seconds...")
            time.sleep(10)  # Wait before restarting

if __name__ == "__main__":
    main()