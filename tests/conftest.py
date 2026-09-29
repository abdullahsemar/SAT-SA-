import json
import shutil
import tempfile
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from apps.api.auth import create_user_session, hash_password
from apps.api.config import settings
from apps.api.main import app
from db.models.access import User
from db.models.evidence import CSE
from db.session import Base, get_db


@pytest.fixture(scope="session")
def temp_storage_dir():
    temp_dir = tempfile.mkdtemp(prefix="sat_sa_test_storage_")
    orig_storage = settings.storage_dir
    settings.storage_dir = temp_dir
    yield temp_dir
    settings.storage_dir = orig_storage
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture(scope="function")
def db_session(temp_storage_dir) -> Generator[Session, None, None]:
    # Use in-memory SQLite with foreign keys and StaticPool so all threads share the exact same db
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    with engine.connect() as conn:
        conn.exec_driver_sql("PRAGMA foreign_keys = ON;")

    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestingSessionLocal()

    # Pre-seed CSEs
    cse1 = CSE(id="CSE-BANK-01", code="CSE-BANK-01", name="First National Bank CSE")
    cse2 = CSE(id="CSE-FINTECH-02", code="CSE-FINTECH-02", name="Fintech Payments CSE")
    session.add_all([cse1, cse2])
    session.commit()

    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def client(db_session: Session) -> Generator[TestClient, None, None]:
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture(scope="function")
def admin_user(db_session: Session) -> User:
    user = User(
        username="admin_test",
        password_hash=hash_password("AdminPass123!"),
        role="admin",
        entity_scope=json.dumps(["*"]),
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture(scope="function")
def bank_examiner(db_session: Session) -> User:
    user = User(
        username="bank_examiner_test",
        password_hash=hash_password("ExaminerPass123!"),
        role="examiner",
        entity_scope=json.dumps(["CSE-BANK-01"]),
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture(scope="function")
def fintech_examiner(db_session: Session) -> User:
    user = User(
        username="fintech_examiner_test",
        password_hash=hash_password("FintechPass123!"),
        role="examiner",
        entity_scope=json.dumps(["CSE-FINTECH-02"]),
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def authenticate_user(client: TestClient, user: User, db_session: Session) -> dict[str, str]:
    token, csrf_token, _ = create_user_session(user, db_session)
    client.cookies.set("sat_session", token)
    return {
        "X-CSRF-Token": csrf_token,
        "X-Session-Token": token,
    }
