from backend.scripts.seed_demo import seed_demo_data
from backend.app.core.database import SessionLocal
from backend.app.models.entities import Merchant, Rider, Order


def test_seed_demo_execution():
    seed_demo_data()

    db = SessionLocal()
    try:
        merchants = db.query(Merchant).all()
        assert len(merchants) >= 3
        for m in merchants:
            assert "SIMULATED" in m.name

        riders = db.query(Rider).all()
        assert len(riders) >= 3
        for r in riders:
            assert "SIMULATED" in r.display_name

        orders = db.query(Order).all()
        assert len(orders) >= 4
    finally:
        db.close()
