import sys
import os
from datetime import datetime, timedelta, timezone

# Ensure backend root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from backend.app.core.database import SessionLocal, init_db
from backend.app.models.entities import Merchant, Rider, Order, OrderStatus


def seed_demo_data():
    """Seed a deterministic, idempotent Mumbai logistics demo dataset."""
    print("Initializing database tables...")
    init_db()
    db = SessionLocal()

    try:
        now = datetime.now(timezone.utc)

        # 1. Seed Merchants (3 Mumbai clusters: Bandra, Dadar, Lower Parel)
        merchants_data = [
            {
                "id": "M-MUM-01",
                "name": "Bandra Artisan Bakery (SIMULATED)",
                "merchant_type": "Bakery",
                "pickup_latitude": 19.0596,
                "pickup_longitude": 72.8295,
                "is_active": True,
            },
            {
                "id": "M-MUM-02",
                "name": "Dadar Fresh Produce (SIMULATED)",
                "merchant_type": "Grocery",
                "pickup_latitude": 19.0178,
                "pickup_longitude": 72.8478,
                "is_active": True,
            },
            {
                "id": "M-MUM-03",
                "name": "Lower Parel Medix (SIMULATED)",
                "merchant_type": "Pharmacy",
                "pickup_latitude": 18.9953,
                "pickup_longitude": 72.8288,
                "is_active": True,
            },
        ]

        print("Seeding Merchants...")
        for m_data in merchants_data:
            existing = db.get(Merchant, m_data["id"])
            if not existing:
                db.add(Merchant(**m_data, created_at=now))
                print(f"  + Created Merchant: {m_data['name']} [{m_data['id']}]")
            else:
                for k, v in m_data.items():
                    setattr(existing, k, v)
                print(f"  * Updated Merchant: {m_data['name']} [{m_data['id']}]")

        # 2. Seed Riders (3 Fleet Delivery Riders)
        riders_data = [
            {
                "id": "R-MUM-01",
                "display_name": "Aarav Sharma (SIMULATED)",
                "current_latitude": 19.0550,
                "current_longitude": 72.8350,
                "weight_capacity_kg": 25.0,
                "package_count_capacity": 12,
                "is_available": True,
            },
            {
                "id": "R-MUM-02",
                "display_name": "Rohan Patel (SIMULATED)",
                "current_latitude": 19.0200,
                "current_longitude": 72.8420,
                "weight_capacity_kg": 20.0,
                "package_count_capacity": 8,
                "is_available": True,
            },
            {
                "id": "R-MUM-03",
                "display_name": "Vikram Jadhav (SIMULATED)",
                "current_latitude": 18.9900,
                "current_longitude": 72.8300,
                "weight_capacity_kg": 30.0,
                "package_count_capacity": 15,
                "is_available": True,
            },
        ]

        print("Seeding Fleet Riders...")
        for r_data in riders_data:
            existing = db.get(Rider, r_data["id"])
            if not existing:
                db.add(Rider(**r_data, created_at=now))
                print(f"  + Created Rider: {r_data['display_name']} [{r_data['id']}]")
            else:
                for k, v in r_data.items():
                    setattr(existing, k, v)
                print(f"  * Updated Rider: {r_data['display_name']} [{r_data['id']}]")

        # 3. Seed Orders (4 Simulated Mumbai Deliveries)
        orders_data = [
            {
                "id": "ORD-MUM-01",
                "merchant_id": "M-MUM-01",
                "pickup_latitude": 19.0596,
                "pickup_longitude": 72.8295,
                "delivery_latitude": 19.0680,
                "delivery_longitude": 72.8385,
                "delivery_deadline": now + timedelta(hours=2),
                "package_type": "PERISHABLE",
                "handling_requirements": "Keep upright, temperature sensitive (SIMULATED)",
                "weight_kg": 2.5,
                "package_count": 2,
                "customer_priority": "PREMIUM",
                "merchant_priority": 1,
                "status": OrderStatus.PENDING.value,
            },
            {
                "id": "ORD-MUM-02",
                "merchant_id": "M-MUM-01",
                "pickup_latitude": 19.0596,
                "pickup_longitude": 72.8295,
                "delivery_latitude": 19.0760,
                "delivery_longitude": 72.8420,
                "delivery_deadline": now + timedelta(hours=3),
                "package_type": "PARCEL",
                "handling_requirements": "Fragile confectioneries (SIMULATED)",
                "weight_kg": 1.8,
                "package_count": 1,
                "customer_priority": "STANDARD",
                "merchant_priority": 2,
                "status": OrderStatus.PENDING.value,
            },
            {
                "id": "ORD-MUM-03",
                "merchant_id": "M-MUM-02",
                "pickup_latitude": 19.0178,
                "pickup_longitude": 72.8478,
                "delivery_latitude": 19.0120,
                "delivery_longitude": 72.8310,
                "delivery_deadline": now + timedelta(hours=1, minutes=30),
                "package_type": "PERISHABLE",
                "handling_requirements": "Organic vegetables box (SIMULATED)",
                "weight_kg": 6.0,
                "package_count": 3,
                "customer_priority": "VIP",
                "merchant_priority": 1,
                "status": OrderStatus.PENDING.value,
            },
            {
                "id": "ORD-MUM-04",
                "merchant_id": "M-MUM-03",
                "pickup_latitude": 18.9953,
                "pickup_longitude": 72.8288,
                "delivery_latitude": 18.9810,
                "delivery_longitude": 72.8240,
                "delivery_deadline": now + timedelta(hours=1),
                "package_type": "MEDICAL",
                "handling_requirements": "Urgent prescription pharmaceuticals (SIMULATED)",
                "weight_kg": 0.8,
                "package_count": 1,
                "customer_priority": "VIP",
                "merchant_priority": 1,
                "status": OrderStatus.PENDING.value,
            },
        ]

        print("Seeding Orders...")
        for o_data in orders_data:
            existing = db.get(Order, o_data["id"])
            if not existing:
                db.add(Order(**o_data, created_at=now))
                print(f"  + Created Order: [{o_data['id']}] for {o_data['merchant_id']}")
            else:
                for k, v in o_data.items():
                    setattr(existing, k, v)
                print(f"  * Updated Order: [{o_data['id']}]")

        db.commit()
        print("\nDemo data seeding completed successfully! [All records marked as SIMULATED]")
    except Exception as e:
        db.rollback()
        print(f"Error seeding demo data: {e}", file=sys.stderr)
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed_demo_data()
