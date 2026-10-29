from backend.scripts.seed_demo import seed_demo_data
from backend.app.core.database import SessionLocal
from backend.app.models.entities import Merchant, Rider, Order


def test_seed_demo_execution():
    seed_demo_data()

    db = SessionLocal()
    try:
        demo_merchant_ids = ["M-MUM-01", "M-MUM-02", "M-MUM-03"]
        merchants = db.query(Merchant).filter(Merchant.id.in_(demo_merchant_ids)).all()
        assert len(merchants) == 3
        for m in merchants:
            assert "SIMULATED" in m.name

        demo_rider_ids = ["R-MUM-01", "R-MUM-02", "R-MUM-03"]
        riders = db.query(Rider).filter(Rider.id.in_(demo_rider_ids)).all()
        assert len(riders) == 3
        for r in riders:
            assert "SIMULATED" in r.display_name

        orders = db.query(Order).all()
        assert len(orders) >= 4
    finally:
        db.close()
