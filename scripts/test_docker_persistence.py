"""
Verification script for Docker container persistence, recovery, and backup/restore.
Tests containerized PostgreSQL 16 on port 5434.
"""
import sys
import psycopg

CONN_STR = "postgresql://pool_staging_user:staging_insecure_development_password@127.0.0.1:5434/pool_engine_staging"

def insert_test_record():
    with psycopg.connect(CONN_STR) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO vehicles (
                    vehicle_id, driver_id, total_seat_capacity, luggage_capacity_units,
                    current_latitude, current_longitude, is_active, updated_at
                )
                VALUES (
                    'veh-persist-dock-01', 'drv-persist-01', 4, 2,
                    8.5241, 76.9366, true, NOW()
                )
                ON CONFLICT (vehicle_id) DO UPDATE SET total_seat_capacity = 4
                RETURNING vehicle_id, driver_id, total_seat_capacity, current_latitude, current_longitude;
            """)
            row = cur.fetchone()
            conn.commit()
            print(f"[PASS] Inserted test vehicle: {row}")
            return row

def verify_test_record():
    with psycopg.connect(CONN_STR) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT vehicle_id, driver_id, total_seat_capacity, current_latitude, current_longitude, is_active
                FROM vehicles
                WHERE vehicle_id = 'veh-persist-dock-01';
            """)
            row = cur.fetchone()
            if row and row[0] == 'veh-persist-dock-01':
                print(f"[PASS] Verified persisted record exists: {row}")
                return True
            else:
                print(f"[FAIL] Record not found! Got: {row}")
                return False

if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else "verify"
    if action == "insert":
        insert_test_record()
    elif action == "verify":
        success = verify_test_record()
        sys.exit(0 if success else 1)
