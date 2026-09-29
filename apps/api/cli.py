import argparse
import json

from sqlalchemy import select

from apps.api.auth import hash_password
from db.models.access import User
from db.models.evidence import CSE
from db.session import SessionLocal


def create_admin(username: str, password: str, entity_scope: str = "*") -> None:
    db = SessionLocal()
    try:
        stmt = select(User).where(User.username == username)
        existing = db.execute(stmt).scalar_one_or_none()
        if existing:
            print(f"User '{username}' already exists. Updating password and role to admin...")
            existing.password_hash = hash_password(password)
            existing.role = "admin"
            existing.entity_scope = json.dumps([entity_scope] if entity_scope != "*" else ["*"])
            existing.is_active = True
        else:
            scope_list = ["*"] if entity_scope == "*" else [entity_scope]
            new_user = User(
                username=username,
                password_hash=hash_password(password),
                role="admin",
                entity_scope=json.dumps(scope_list),
                is_active=True,
            )
            db.add(new_user)
            print(f"Admin user '{username}' created successfully.")
        db.commit()
    finally:
        db.close()


def create_examiner(username: str, password: str, entity_ids: list[str]) -> None:
    db = SessionLocal()
    try:
        stmt = select(User).where(User.username == username)
        existing = db.execute(stmt).scalar_one_or_none()
        if existing:
            print(f"User '{username}' already exists. Updating password...")
            existing.password_hash = hash_password(password)
            existing.role = "examiner"
            existing.entity_scope = json.dumps(entity_ids)
            existing.is_active = True
        else:
            new_user = User(
                username=username,
                password_hash=hash_password(password),
                role="examiner",
                entity_scope=json.dumps(entity_ids),
                is_active=True,
            )
            db.add(new_user)
            print(f"Examiner '{username}' created with entity scope: {entity_ids}")
        db.commit()
    finally:
        db.close()


def seed_cse(code: str, name: str) -> None:
    db = SessionLocal()
    try:
        cse = db.get(CSE, code)
        if not cse:
            cse = CSE(id=code, code=code, name=name)
            db.add(cse)
            db.commit()
            print(f"CSE '{code}' ({name}) seeded.")
        else:
            print(f"CSE '{code}' already exists.")
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(description="SAT-SA Administrative CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # create-admin
    admin_parser = subparsers.add_parser("create-admin", help="Bootstrap admin account")
    admin_parser.add_argument("--username", default="admin", help="Username")
    admin_parser.add_argument("--password", required=True, help="Admin password")
    admin_parser.add_argument("--entity-scope", default="*", help="Entity scope (* for all)")

    # create-examiner
    exam_parser = subparsers.add_parser("create-examiner", help="Create examiner account")
    exam_parser.add_argument("--username", required=True, help="Username")
    exam_parser.add_argument("--password", required=True, help="Password")
    exam_parser.add_argument("--entities", nargs="+", required=True, help="Allowed entity IDs")

    # seed-cse
    cse_parser = subparsers.add_parser("seed-cse", help="Seed a CSE entity")
    cse_parser.add_argument("--code", required=True, help="CSE code e.g. CSE-BANK-01")
    cse_parser.add_argument("--name", required=True, help="CSE name")

    args = parser.parse_args()

    if args.command == "create-admin":
        create_admin(args.username, args.password, args.entity_scope)
    elif args.command == "create-examiner":
        create_examiner(args.username, args.password, args.entities)
    elif args.command == "seed-cse":
        seed_cse(args.code, args.name)


if __name__ == "__main__":
    main()
