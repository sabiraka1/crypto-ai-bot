# V006_add_trades_indexes.py
def up(conn):
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_trades_client_id_unique
        ON trades(client_order_id)
        WHERE client_order_id IS NOT NULL AND client_order_id <> '';
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_trades_broker_order_id
        ON trades(broker_order_id);
        """
    )
    conn.commit()
