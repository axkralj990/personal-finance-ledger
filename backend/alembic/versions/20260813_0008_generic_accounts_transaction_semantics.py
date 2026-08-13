"""Add generic accounts and sign-based transaction semantics.

Revision ID: 20260813_0008
Revises: 20260812_0007
"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260813_0008"
down_revision: str | None = "20260812_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ACCOUNT_NAMESPACE = uuid.UUID("8927873d-f129-49d6-bbd4-e400552a471b")
UNKNOWN_NAME = "Unknown"
UNKNOWN_ID = str(uuid.uuid5(ACCOUNT_NAMESPACE, UNKNOWN_NAME))
LEGACY_ACCOUNTS = {
    str(uuid.uuid5(ACCOUNT_NAMESPACE, "Legacy historical ledger")): (
        "LEGACY",
        "Legacy historical ledger",
    ),
    str(uuid.uuid5(ACCOUNT_NAMESPACE, "Revolut Personal EUR")): (
        "REVOLUT",
        "Revolut Personal EUR",
    ),
    str(uuid.uuid5(ACCOUNT_NAMESPACE, "Revolut Joint EUR")): (
        "REVOLUT",
        "Revolut Joint EUR",
    ),
    str(uuid.uuid5(ACCOUNT_NAMESPACE, "DBS EUR")): ("DBS", "DBS EUR"),
    str(uuid.uuid5(ACCOUNT_NAMESPACE, "Mastercard EUR")): ("MASTERCARD", "Mastercard EUR"),
    str(uuid.uuid5(ACCOUNT_NAMESPACE, "Manual EUR")): ("MANUAL", "Manual EUR"),
}
OLD_KINDS = ("EXPENSE", "INCOME", "REFUND", "FEE", "TRANSFER")
NEW_KINDS = ("EXPENSE", "INCOME")
ISO_CURRENCY_CODES = tuple(
    """
    AED AFN ALL AMD ANG AOA ARS AUD AWG AZN BAM BBD BDT BGN BHD BIF BMD BND BOB BOV
    BRL BSD BTN BWP BYN BZD CAD CDF CHE CHF CHW CLF CLP CNY COP COU CRC CUC CUP CVE
    CZK DJF DKK DOP DZD EGP ERN ETB EUR FJD FKP GBP GEL GHS GIP GMD GNF GTQ GYD HKD
    HNL HTG HUF IDR ILS INR IQD IRR ISK JMD JOD JPY KES KGS KHR KMF KPW KRW KWD KYD
    KZT LAK LBP LKR LRD LSL LYD MAD MDL MGA MKD MMK MNT MOP MRU MUR MVR MWK MXN MXV
    MYR MZN NAD NGN NIO NOK NPR NZD OMR PAB PEN PGK PHP PKR PLN PYG QAR RON RSD RUB RWF
    SAR SBD SCR SDG SEK SGD SHP SLE SLL SOS SRD SSP STN SVC SYP SZL THB TJS TMT TND TOP
    TRY TTD TWD TZS UAH UGX USD USN UYI UYU UYW UZS VED VES VND VUV WST XAF XAG XAU XBA
    XBB XBC XBD XCD XDR XOF XPD XPF XPT XSU XTS XUA XXX YER ZAR ZMW ZWL
    """.split()  # noqa: SIM905 - compact audited ISO 4217 data is clearer here.
)


def upgrade() -> None:
    connection = op.get_bind()
    _require_safe_sqlite_rebuild_connection(connection)
    has_zero = connection.scalar(
        sa.text("SELECT EXISTS(SELECT 1 FROM transactions WHERE amount_minor = 0)")
    )
    if has_zero:
        raise RuntimeError("Cannot migrate committed transactions with a zero amount")
    invalid_currency = next(
        (
            currency
            for currency in connection.exec_driver_sql(
                "SELECT DISTINCT default_currency FROM source_accounts"
            ).scalars()
            if currency not in ISO_CURRENCY_CODES
        ),
        None,
    )
    if invalid_currency is not None:
        raise RuntimeError(f"Cannot migrate unknown account currency: {invalid_currency}")

    op.rename_table("source_accounts", "accounts")
    _rename_column("import_batches", "source_account_id", "account_id")
    _rename_column("import_mapping_templates", "source_account_id", "account_id")
    _rename_column("staged_transactions", "ledger_account_id", "account_id")
    _rename_column("transactions", "source_account_id", "account_id")
    _rename_column("tag_rules", "source_account_id", "account_id")

    now = connection.exec_driver_sql("SELECT CURRENT_TIMESTAMP").scalar_one()
    connection.execute(
        sa.text(
            "INSERT OR IGNORE INTO accounts "
            "(id, provider, display_name, default_currency, is_active, created_at) "
            "VALUES (:id, 'MANUAL', :name, 'EUR', 1, :now)"
        ),
        {"id": UNKNOWN_ID, "name": UNKNOWN_NAME, "now": now},
    )
    if op.get_context().config.attributes.get("fresh_install", False):
        connection.execute(
            sa.text("DELETE FROM accounts WHERE id != :unknown_id"),
            {"unknown_id": UNKNOWN_ID},
        )
    connection.exec_driver_sql(
        "CREATE TABLE accounts_new ("
        "id VARCHAR(36) NOT NULL PRIMARY KEY, name VARCHAR(120) NOT NULL UNIQUE, "
        "default_currency VARCHAR(3) NOT NULL, is_active BOOLEAN NOT NULL, "
        "created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL, "
        "CONSTRAINT ck_accounts_default_currency CHECK (default_currency IN ("
        f"{_sql_values(ISO_CURRENCY_CODES)})))"
    )
    connection.exec_driver_sql(
        "INSERT INTO accounts_new "
        "(id, name, default_currency, is_active, created_at, updated_at) "
        "SELECT id, display_name, default_currency, is_active, created_at, created_at FROM accounts"
    )
    op.drop_table("accounts")
    op.rename_table("accounts_new", "accounts")
    _rebuild_tag_rules(connection)

    connection.exec_driver_sql(
        "UPDATE transactions SET kind = CASE WHEN amount_minor > 0 THEN 'INCOME' ELSE 'EXPENSE' END"
    )
    connection.exec_driver_sql(
        "UPDATE staged_transactions SET kind = CASE "
        "WHEN amount_minor > 0 THEN 'INCOME' WHEN amount_minor < 0 THEN 'EXPENSE' ELSE NULL END"
    )
    _rebuild_kind_columns()
    _replace_indexes()
    _validate_integrity(connection)


def downgrade() -> None:
    connection = op.get_bind()
    _require_safe_sqlite_rebuild_connection(connection)
    _refuse_lossy_downgrade(connection)
    _rebuild_kind_columns(downgrade=True)

    connection.exec_driver_sql(
        "CREATE TABLE source_accounts_new ("
        "id VARCHAR(36) NOT NULL PRIMARY KEY, provider VARCHAR(10) NOT NULL, "
        "display_name VARCHAR(120) NOT NULL UNIQUE, default_currency VARCHAR(3) NOT NULL, "
        "is_active BOOLEAN NOT NULL, created_at DATETIME NOT NULL, "
        "CONSTRAINT provider CHECK (provider IN "
        "('LEGACY', 'REVOLUT', 'DBS', 'MASTERCARD', 'MANUAL')), "
        "CHECK (length(default_currency) = 3))"
    )
    for account_id, (provider, name) in LEGACY_ACCOUNTS.items():
        connection.execute(
            sa.text(
                "INSERT INTO source_accounts_new "
                "(id, provider, display_name, default_currency, is_active, created_at) "
                "SELECT id, :provider, :name, default_currency, is_active, created_at "
                "FROM accounts WHERE id = :id"
            ),
            {"id": account_id, "provider": provider, "name": name},
        )
    _rebuild_tag_rules(connection, downgrade=True)
    op.drop_table("accounts")
    op.rename_table("source_accounts_new", "source_accounts")
    op.create_index("ix_source_accounts_provider", "source_accounts", ["provider"])

    _rename_column("transactions", "account_id", "source_account_id")
    _rename_column("staged_transactions", "account_id", "ledger_account_id")
    _rename_column("import_mapping_templates", "account_id", "source_account_id")
    _rename_column("import_batches", "account_id", "source_account_id")
    _replace_indexes(downgrade=True)
    _validate_integrity(connection)


def _rename_column(table: str, old: str, new: str) -> None:
    op.execute(sa.text(f'ALTER TABLE "{table}" RENAME COLUMN "{old}" TO "{new}"'))


def _rebuild_kind_columns(*, downgrade: bool = False) -> None:
    target_kinds = OLD_KINDS if downgrade else NEW_KINDS
    with op.batch_alter_table("staged_transactions", recreate="always") as batch:
        batch.drop_constraint("transactionkind", type_="check")
        batch.alter_column(
            "kind", existing_type=sa.String(8), type_=sa.String(8), existing_nullable=True
        )
        batch.create_check_constraint("transactionkind", f"kind IN ({_sql_values(target_kinds)})")
    with op.batch_alter_table("transactions", recreate="always") as batch:
        batch.drop_constraint("transactionkind", type_="check")
        batch.alter_column(
            "kind", existing_type=sa.String(8), type_=sa.String(8), existing_nullable=False
        )
        batch.create_check_constraint("transactionkind", f"kind IN ({_sql_values(target_kinds)})")
        if not downgrade:
            batch.create_check_constraint(
                "ck_transactions_amount_kind",
                "(amount_minor > 0 AND kind = 'INCOME') OR (amount_minor < 0 AND kind = 'EXPENSE')",
            )
        else:
            batch.drop_constraint("ck_transactions_amount_kind", type_="check")


def _sql_values(values: Sequence[str]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def _rebuild_tag_rules(connection: sa.Connection, *, downgrade: bool = False) -> None:
    if downgrade:
        connection.exec_driver_sql(
            "CREATE TABLE tag_rules_new ("
            "id VARCHAR(36) NOT NULL PRIMARY KEY, normalized_description TEXT NOT NULL, "
            "scope VARCHAR(8) NOT NULL, source_account_id VARCHAR(36), provider VARCHAR(10), "
            "category_id VARCHAR(36) NOT NULL, subcategory_id VARCHAR(36), "
            "is_enabled BOOLEAN NOT NULL, created_at DATETIME NOT NULL, "
            "updated_at DATETIME NOT NULL, "
            "CONSTRAINT rulescope CHECK (scope IN ('GLOBAL', 'PROVIDER', 'ACCOUNT')), "
            "CONSTRAINT provider CHECK (provider IN "
            "('LEGACY', 'REVOLUT', 'DBS', 'MASTERCARD', 'MANUAL')), "
            "CONSTRAINT ck_tag_rule_scope CHECK ("
            "(scope = 'GLOBAL' AND source_account_id IS NULL AND provider IS NULL) OR "
            "(scope = 'PROVIDER' AND source_account_id IS NULL AND provider IS NOT NULL) OR "
            "(scope = 'ACCOUNT' AND source_account_id IS NOT NULL AND provider IS NULL)), "
            "FOREIGN KEY(source_account_id) REFERENCES source_accounts (id), "
            "FOREIGN KEY(category_id) REFERENCES categories (id), "
            "FOREIGN KEY(subcategory_id) REFERENCES subcategories (id), "
            "CONSTRAINT fk_rule_taxonomy_parent FOREIGN KEY(subcategory_id, category_id) "
            "REFERENCES subcategories (id, category_id))"
        )
        connection.exec_driver_sql(
            "INSERT INTO tag_rules_new (id, normalized_description, scope, source_account_id, "
            "provider, category_id, subcategory_id, is_enabled, created_at, updated_at) "
            "SELECT id, normalized_description, scope, account_id, NULL, category_id, "
            "subcategory_id, is_enabled, created_at, updated_at FROM tag_rules"
        )
    else:
        provider_accounts = {
            provider: account_id
            for account_id, (provider, _name) in LEGACY_ACCOUNTS.items()
            if provider != "REVOLUT"
        }
        connection.exec_driver_sql(
            "CREATE TABLE tag_rules_new ("
            "id VARCHAR(36) NOT NULL PRIMARY KEY, normalized_description TEXT NOT NULL, "
            "scope VARCHAR(7) NOT NULL, account_id VARCHAR(36), "
            "category_id VARCHAR(36) NOT NULL, subcategory_id VARCHAR(36), "
            "is_enabled BOOLEAN NOT NULL, created_at DATETIME NOT NULL, "
            "updated_at DATETIME NOT NULL, "
            "CONSTRAINT rulescope CHECK (scope IN ('GLOBAL', 'ACCOUNT')), "
            "CONSTRAINT ck_tag_rule_scope CHECK ("
            "(scope = 'GLOBAL' AND account_id IS NULL) OR "
            "(scope = 'ACCOUNT' AND account_id IS NOT NULL)), "
            "FOREIGN KEY(account_id) REFERENCES accounts (id), "
            "FOREIGN KEY(category_id) REFERENCES categories (id), "
            "FOREIGN KEY(subcategory_id) REFERENCES subcategories (id), "
            "CONSTRAINT fk_rule_taxonomy_parent FOREIGN KEY(subcategory_id, category_id) "
            "REFERENCES subcategories (id, category_id))"
        )
        connection.execute(
            sa.text(
                "INSERT INTO tag_rules_new (id, normalized_description, scope, account_id, "
                "category_id, subcategory_id, is_enabled, created_at, updated_at) "
                "SELECT id, normalized_description, "
                "CASE WHEN scope = 'ACCOUNT' THEN 'ACCOUNT' "
                "WHEN scope = 'PROVIDER' AND provider != 'REVOLUT' THEN 'ACCOUNT' "
                "ELSE 'GLOBAL' END, "
                "CASE WHEN scope = 'ACCOUNT' THEN account_id ELSE CASE provider "
                "WHEN 'LEGACY' THEN :legacy WHEN 'DBS' THEN :dbs "
                "WHEN 'MASTERCARD' THEN :mastercard WHEN 'MANUAL' THEN :manual ELSE NULL END END, "
                "category_id, subcategory_id, "
                "CASE WHEN scope = 'PROVIDER' AND provider = 'REVOLUT' THEN 0 ELSE is_enabled END, "
                "created_at, updated_at FROM tag_rules"
            ),
            {
                "legacy": provider_accounts["LEGACY"],
                "dbs": provider_accounts["DBS"],
                "mastercard": provider_accounts["MASTERCARD"],
                "manual": provider_accounts["MANUAL"],
            },
        )
    op.drop_table("tag_rules")
    op.rename_table("tag_rules_new", "tag_rules")


def _replace_indexes(*, downgrade: bool = False) -> None:
    pairs = (
        ("ix_import_batches_source_account_id", "ix_import_batches_account_id", "import_batches"),
        (
            "ix_staged_transactions_ledger_account_id",
            "ix_staged_transactions_account_id",
            "staged_transactions",
        ),
        ("ix_transactions_source_account_id", "ix_transactions_account_id", "transactions"),
    )
    for old, new, table in pairs:
        source, target = (new, old) if downgrade else (old, new)
        op.drop_index(source, table_name=table)
        column = (
            "source_account_id"
            if downgrade and table != "staged_transactions"
            else ("ledger_account_id" if downgrade else "account_id")
        )
        op.create_index(target, table, [column])


def _require_safe_sqlite_rebuild_connection(connection: sa.Connection) -> None:
    if connection.dialect.name != "sqlite":
        raise RuntimeError("Migration 0008 currently supports SQLite only")
    if connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() != 0:
        raise RuntimeError("Migration 0008 requires foreign_keys disabled during SQLite rebuilds")


def _validate_integrity(connection: sa.Connection) -> None:
    violations = connection.exec_driver_sql("PRAGMA foreign_key_check").all()
    if violations:
        raise RuntimeError(f"Foreign key check failed after account migration: {violations!r}")
    if connection.exec_driver_sql("PRAGMA integrity_check").scalar_one() != "ok":
        raise RuntimeError("SQLite integrity check failed after account migration")


def _refuse_lossy_downgrade(connection: sa.Connection) -> None:
    rows = connection.exec_driver_sql("SELECT id, name FROM accounts").all()
    allowed = {*LEGACY_ACCOUNTS, UNKNOWN_ID}
    if any(account_id not in allowed for account_id, _ in rows):
        raise RuntimeError("Cannot downgrade while generic accounts exist")
    names = dict(rows)
    renamed = any(
        names.get(account_id) != expected[1]
        for account_id, expected in LEGACY_ACCOUNTS.items()
        if account_id in names
    )
    if renamed:
        raise RuntimeError("Cannot downgrade after legacy accounts have been renamed")
    if UNKNOWN_ID in names:
        statements = (
            "SELECT count(*) FROM import_batches WHERE account_id = :id",
            "SELECT count(*) FROM import_mapping_templates WHERE account_id = :id",
            "SELECT count(*) FROM staged_transactions WHERE account_id = :id",
            "SELECT count(*) FROM transactions WHERE account_id = :id",
            "SELECT count(*) FROM tag_rules WHERE account_id = :id",
        )
        references = sum(
            int(connection.scalar(sa.text(statement), {"id": UNKNOWN_ID}) or 0)
            for statement in statements
        )
        if references:
            raise RuntimeError("Cannot downgrade while Unknown account data exists")
