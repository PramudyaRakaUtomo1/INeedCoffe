import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st


st.set_page_config(
    page_title="Kopi & Stok",
    page_icon="☕",
    layout="wide",
    initial_sidebar_state="expanded",
)

DB_PATH = Path(os.getenv("STOCK_DB_PATH", "data/coffee_stock.db"))


@contextmanager
def database():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize_database():
    with database() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sku TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                category TEXT NOT NULL,
                unit TEXT NOT NULL,
                stock_qty INTEGER NOT NULL DEFAULT 0 CHECK (stock_qty >= 0),
                min_stock INTEGER NOT NULL DEFAULT 0 CHECK (min_stock >= 0),
                buy_price INTEGER NOT NULL DEFAULT 0 CHECK (buy_price >= 0),
                sell_price INTEGER NOT NULL DEFAULT 0 CHECK (sell_price >= 0),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS stock_transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER,
                product_name TEXT NOT NULL,
                sku TEXT NOT NULL,
                transaction_type TEXT NOT NULL CHECK (transaction_type IN ('Masuk', 'Keluar')),
                quantity INTEGER NOT NULL CHECK (quantity > 0),
                note TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE SET NULL
            );
            """
        )
        count = connection.execute("SELECT COUNT(*) FROM products").fetchone()[0]
        if count == 0:
            connection.executemany(
                """
                INSERT INTO products
                    (sku, name, category, unit, stock_qty, min_stock, buy_price, sell_price)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    ("BN-001", "Biji Kopi Arabika", "Bahan Baku", "kg", 12, 5, 145000, 0),
                    ("BN-002", "Susu Fresh Milk", "Bahan Baku", "liter", 8, 4, 22000, 0),
                    ("BN-003", "Sirup Gula Aren", "Bahan Baku", "botol", 3, 5, 38000, 0),
                    ("PK-001", "Cup 12 oz", "Kemasan", "pcs", 120, 40, 900, 0),
                    ("PK-002", "Tutup Cup 12 oz", "Kemasan", "pcs", 85, 40, 350, 0),
                    ("PR-001", "Croissant Butter", "Produk Siap Jual", "pcs", 18, 8, 12000, 22000),
                ],
            )


def read_products():
    with database() as connection:
        rows = connection.execute(
            "SELECT * FROM products ORDER BY category, name"
        ).fetchall()
    return [dict(row) for row in rows]


def read_transactions(limit=None):
    query = """
        SELECT id, product_name, sku, transaction_type, quantity, note, created_at
        FROM stock_transactions
        ORDER BY datetime(created_at) DESC, id DESC
    """
    if limit is not None:
        query += " LIMIT ?"
    with database() as connection:
        rows = connection.execute(query, (limit,) if limit is not None else ()).fetchall()
    return [dict(row) for row in rows]


def save_product(product_id, sku, name, category, unit, stock_qty, min_stock, buy_price, sell_price):
    values = (sku.strip(), name.strip(), category.strip(), unit.strip(), stock_qty, min_stock, buy_price, sell_price)
    with database() as connection:
        if product_id is None:
            connection.execute(
                """
                INSERT INTO products
                    (sku, name, category, unit, stock_qty, min_stock, buy_price, sell_price)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                values,
            )
        else:
            connection.execute(
                """
                UPDATE products
                SET sku = ?, name = ?, category = ?, unit = ?, stock_qty = ?,
                    min_stock = ?, buy_price = ?, sell_price = ?
                WHERE id = ?
                """,
                values + (product_id,),
            )


def record_transaction(product_id, transaction_type, quantity, note):
    with database() as connection:
        product = connection.execute(
            "SELECT id, sku, name, stock_qty FROM products WHERE id = ?",
            (product_id,),
        ).fetchone()
        if product is None:
            raise ValueError("Produk tidak ditemukan.")
        if transaction_type == "Keluar" and quantity > product["stock_qty"]:
            raise ValueError(f"Stok tidak cukup. Stok tersedia: {product['stock_qty']}.")

        adjustment = quantity if transaction_type == "Masuk" else -quantity
        connection.execute(
            "UPDATE products SET stock_qty = stock_qty + ? WHERE id = ?",
            (adjustment, product_id),
        )
        connection.execute(
            """
            INSERT INTO stock_transactions
                (product_id, product_name, sku, transaction_type, quantity, note)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (product["id"], product["name"], product["sku"], transaction_type, quantity, note.strip()),
        )


def format_rupiah(amount):
    return f"Rp {amount:,.0f}".replace(",", ".")


def render_product_table(products):
    if not products:
        st.info("Belum ada produk yang cocok dengan pencarian.")
        return
    rows = []
    for product in products:
        status = "Habis" if product["stock_qty"] == 0 else (
            "Stok menipis" if product["stock_qty"] <= product["min_stock"] else "Aman"
        )
        rows.append(
            {
                "SKU": product["sku"],
                "Nama produk": product["name"],
                "Kategori": product["category"],
                "Stok": f'{product["stock_qty"]} {product["unit"]}',
                "Batas minimum": f'{product["min_stock"]} {product["unit"]}',
                "Harga beli": format_rupiah(product["buy_price"]),
                "Harga jual": format_rupiah(product["sell_price"]) if product["sell_price"] else "—",
                "Status": status,
            }
        )
    st.dataframe(rows, width="stretch", hide_index=True)


def render_dashboard(products, transactions):
    st.title("☕ Ringkasan")
    st.caption(f"Pantau persediaan kedai Anda · {datetime.now().strftime('%d %B %Y')}")

    low_stock = [p for p in products if p["stock_qty"] <= p["min_stock"]]
    total_units = sum(p["stock_qty"] for p in products)
    inventory_value = sum(p["stock_qty"] * p["buy_price"] for p in products)
    metric_cols = st.columns(4)
    metric_cols[0].metric("Total produk", len(products))
    metric_cols[1].metric("Unit tersedia", f"{total_units:,}".replace(",", "."))
    metric_cols[2].metric("Perlu restock", len(low_stock), delta_color="inverse")
    metric_cols[3].metric("Nilai persediaan", format_rupiah(inventory_value))

    left, right = st.columns([1.25, 1])
    with left:
        st.subheader("Pergerakan stok · 14 hari")
        start = (datetime.now() - timedelta(days=13)).strftime("%Y-%m-%d")
        with database() as connection:
            rows = connection.execute(
                """
                SELECT date(created_at) AS tanggal, transaction_type, SUM(quantity) AS jumlah
                FROM stock_transactions
                WHERE date(created_at) >= date(?)
                GROUP BY date(created_at), transaction_type
                ORDER BY tanggal
                """,
                (start,),
            ).fetchall()
        if rows:
            movement = pd.DataFrame([dict(row) for row in rows])
            movement = movement.pivot(index="tanggal", columns="transaction_type", values="jumlah").fillna(0)
            for kind in ("Masuk", "Keluar"):
                if kind not in movement.columns:
                    movement[kind] = 0
            st.bar_chart(movement[["Masuk", "Keluar"]], color=["#9a6548", "#d9a36a"])
        else:
            st.info("Grafik akan tampil setelah ada transaksi stok.")

    with right:
        st.subheader("Perlu perhatian")
        if low_stock:
            for product in low_stock[:6]:
                st.warning(
                    f'**{product["name"]}** — {product["stock_qty"]} {product["unit"]} '
                    f'(minimum {product["min_stock"]})'
                )
        else:
            st.success("Semua produk berada di atas batas minimum.")

    st.subheader("Aktivitas terbaru")
    if transactions:
        recent = []
        for item in transactions[:6]:
            recent.append(
                {
                    "Waktu": item["created_at"],
                    "Produk": item["product_name"],
                    "Jenis": item["transaction_type"],
                    "Jumlah": item["quantity"],
                    "Catatan": item["note"] or "—",
                }
            )
        st.dataframe(recent, width="stretch", hide_index=True)
    else:
        st.info("Belum ada aktivitas. Catat transaksi pertama Anda di menu Transaksi.")


def render_inventory(products):
    st.title("📦 Produk")
    st.caption("Kelola katalog, harga, dan batas minimum persediaan.")
    list_tab, add_tab, edit_tab = st.tabs(["Daftar produk", "Tambah produk", "Edit / hapus"])

    with list_tab:
        search_col, category_col, status_col = st.columns([2, 1, 1])
        search = search_col.text_input("Cari produk", placeholder="Nama atau SKU...")
        categories = ["Semua kategori"] + sorted({p["category"] for p in products})
        category = category_col.selectbox("Kategori", categories)
        status = status_col.selectbox("Status stok", ["Semua", "Aman", "Stok menipis", "Habis"])
        filtered = products
        if search:
            query = search.casefold()
            filtered = [p for p in filtered if query in p["name"].casefold() or query in p["sku"].casefold()]
        if category != "Semua kategori":
            filtered = [p for p in filtered if p["category"] == category]
        if status != "Semua":
            filtered = [
                p for p in filtered
                if ("Habis" if p["stock_qty"] == 0 else (
                    "Stok menipis" if p["stock_qty"] <= p["min_stock"] else "Aman"
                )) == status
            ]
        render_product_table(filtered)

    with add_tab:
        st.subheader("Tambah produk baru")
        with st.form("add_product_form", clear_on_submit=True):
            col1, col2 = st.columns(2)
            sku = col1.text_input("SKU", placeholder="Contoh: BN-004")
            name = col2.text_input("Nama produk")
            category = col1.text_input("Kategori", placeholder="Bahan Baku")
            unit = col2.text_input("Satuan", placeholder="kg, liter, pcs...")
            col3, col4, col5 = st.columns(3)
            stock_qty = col3.number_input("Stok awal", min_value=0, step=1)
            min_stock = col4.number_input("Batas minimum", min_value=0, step=1)
            buy_price = col5.number_input("Harga beli (Rp)", min_value=0, step=1000)
            sell_price = st.number_input("Harga jual (Rp, opsional)", min_value=0, step=1000)
            submitted = st.form_submit_button("Simpan produk", type="primary")
        if submitted:
            if not all((sku.strip(), name.strip(), category.strip(), unit.strip())):
                st.error("SKU, nama, kategori, dan satuan wajib diisi.")
            else:
                try:
                    save_product(None, sku, name, category, unit, int(stock_qty), int(min_stock), int(buy_price), int(sell_price))
                except sqlite3.IntegrityError:
                    st.error("SKU sudah digunakan. Gunakan SKU yang berbeda.")
                else:
                    st.success("Produk berhasil ditambahkan.")
                    st.rerun()

    with edit_tab:
        if not products:
            st.info("Belum ada produk untuk diedit.")
        else:
            product_options = {f'{p["sku"]} · {p["name"]}': p for p in products}
            selected_label = st.selectbox("Pilih produk", list(product_options))
            selected = product_options[selected_label]
            st.caption("Gunakan menu Transaksi untuk menyesuaikan jumlah stok agar riwayat tetap tercatat.")
            with st.form("edit_product_form"):
                col1, col2 = st.columns(2)
                sku = col1.text_input("SKU", value=selected["sku"])
                name = col2.text_input("Nama produk", value=selected["name"])
                category = col1.text_input("Kategori", value=selected["category"])
                unit = col2.text_input("Satuan", value=selected["unit"])
                col3, col4, col5 = st.columns(3)
                stock_qty = col3.number_input("Stok saat ini", min_value=0, value=selected["stock_qty"], step=1, disabled=True)
                min_stock = col4.number_input("Batas minimum", min_value=0, value=selected["min_stock"], step=1)
                buy_price = col5.number_input("Harga beli (Rp)", min_value=0, value=selected["buy_price"], step=1000)
                sell_price = st.number_input("Harga jual (Rp)", min_value=0, value=selected["sell_price"], step=1000)
                save = st.form_submit_button("Simpan perubahan", type="primary")
            if save:
                if not all((sku.strip(), name.strip(), category.strip(), unit.strip())):
                    st.error("SKU, nama, kategori, dan satuan wajib diisi.")
                else:
                    try:
                        save_product(
                            selected["id"], sku, name, category, unit,
                            selected["stock_qty"], int(min_stock), int(buy_price), int(sell_price),
                        )
                    except sqlite3.IntegrityError:
                        st.error("SKU sudah digunakan oleh produk lain.")
                    else:
                        st.success("Perubahan produk berhasil disimpan.")
                        st.rerun()

            with st.expander("Hapus produk"):
                st.warning("Riwayat transaksi akan tetap tersimpan, tetapi tidak lagi terhubung ke produk.")
                confirm_delete = st.checkbox(f"Saya yakin ingin menghapus {selected['name']}", key=f"confirm_{selected['id']}")
                if st.button("Hapus produk ini", disabled=not confirm_delete, type="secondary"):
                    with database() as connection:
                        connection.execute("DELETE FROM products WHERE id = ?", (selected["id"],))
                    st.success("Produk berhasil dihapus.")
                    st.rerun()


def render_transactions(products):
    st.title("↕️ Transaksi stok")
    st.caption("Catat stok masuk dari pemasok atau stok keluar untuk pemakaian dan penjualan.")
    if not products:
        st.info("Tambahkan produk terlebih dahulu di menu Produk.")
        return

    product_options = {f'{p["sku"]} · {p["name"]} ({p["stock_qty"]} {p["unit"]})': p for p in products}
    with st.form("stock_transaction_form", clear_on_submit=True):
        selected_label = st.selectbox("Produk", list(product_options))
        product = product_options[selected_label]
        col1, col2 = st.columns(2)
        transaction_type = col1.radio("Jenis transaksi", ["Masuk", "Keluar"], horizontal=True)
        quantity = col2.number_input("Jumlah", min_value=1, step=1)
        note = st.text_input("Catatan", placeholder="Contoh: Pembelian dari supplier")
        submitted = st.form_submit_button("Simpan transaksi", type="primary")
    if submitted:
        try:
            record_transaction(product["id"], transaction_type, int(quantity), note)
        except ValueError as error:
            st.error(str(error))
        else:
            st.success(f"Stok {transaction_type.lower()} berhasil dicatat untuk {product['name']}.")
            st.rerun()

    st.divider()
    st.subheader("Stok terkini")
    render_product_table(products)


def render_history(transactions):
    st.title("🧾 Riwayat transaksi")
    st.caption("Semua perubahan stok yang tercatat.")
    if not transactions:
        st.info("Belum ada transaksi stok.")
        return
    data = pd.DataFrame(transactions)
    filter_col, search_col = st.columns([1, 2])
    transaction_type = filter_col.selectbox("Jenis", ["Semua", "Masuk", "Keluar"])
    search = search_col.text_input("Cari produk / SKU", placeholder="Ketik nama produk atau SKU...")
    if transaction_type != "Semua":
        data = data[data["transaction_type"] == transaction_type]
    if search:
        mask = (
            data["product_name"].str.contains(search, case=False, na=False)
            | data["sku"].str.contains(search, case=False, na=False)
        )
        data = data[mask]

    shown = data.rename(
        columns={
            "created_at": "Waktu",
            "product_name": "Produk",
            "sku": "SKU",
            "transaction_type": "Jenis",
            "quantity": "Jumlah",
            "note": "Catatan",
        }
    )[["Waktu", "Produk", "SKU", "Jenis", "Jumlah", "Catatan"]]
    st.dataframe(shown, width="stretch", hide_index=True)
    st.download_button(
        "Unduh CSV",
        data=shown.to_csv(index=False).encode("utf-8-sig"),
        file_name=f"riwayat-stok-{datetime.now():%Y%m%d}.csv",
        mime="text/csv",
    )


def main():
    initialize_database()
    products = read_products()
    transactions = read_transactions()

    with st.sidebar:
        st.markdown("# ☕ Kopi & Stok")
        st.caption("Manajemen inventaris kedai")
        page = st.radio(
            "Navigasi",
            ["Ringkasan", "Produk", "Transaksi", "Riwayat"],
            label_visibility="collapsed",
        )
        st.divider()
        st.caption("Data tersimpan di SQLite lokal.")

    if page == "Ringkasan":
        render_dashboard(products, transactions)
    elif page == "Produk":
        render_inventory(products)
    elif page == "Transaksi":
        render_transactions(products)
    else:
        render_history(transactions)


if __name__ == "__main__":
    main()
