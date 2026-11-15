from io import BytesIO
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st
import xlwt


st.set_page_config(
    page_title="I Need Coffee",
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
            CREATE TABLE IF NOT EXISTS categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE
            );
            CREATE TABLE IF NOT EXISTS stock_transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER,
                product_name TEXT NOT NULL,
                sku TEXT NOT NULL,
                unit TEXT NOT NULL DEFAULT '',
                transaction_type TEXT NOT NULL CHECK (transaction_type IN ('Masuk', 'Keluar')),
                quantity INTEGER NOT NULL CHECK (quantity > 0),
                note TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE SET NULL
            );
            """
        )
        transaction_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(stock_transactions)")
        }
        if "unit" not in transaction_columns:
            connection.execute(
                "ALTER TABLE stock_transactions ADD COLUMN unit TEXT NOT NULL DEFAULT ''"
            )
        count = connection.execute("SELECT COUNT(*) FROM products").fetchone()[0]
        if count == 0:
            connection.executemany(
                """
                INSERT INTO products
                    (sku, name, category, unit, stock_qty, min_stock)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    ("BN-001", "Biji Kopi Arabika", "Bahan Baku", "kg", 12, 5),
                    ("BN-002", "Susu Fresh Milk", "Bahan Baku", "liter", 8, 4),
                    ("BN-003", "Sirup Gula Aren", "Bahan Baku", "botol", 3, 5),
                    ("PK-001", "Cup 12 oz", "Kemasan", "pcs", 120, 40),
                    ("PK-002", "Tutup Cup 12 oz", "Kemasan", "pcs", 85, 40),
                    ("PR-001", "Croissant Butter", "Produk Siap Jual", "pcs", 18, 8),
                ],
            )
        connection.execute(
            """
            INSERT OR IGNORE INTO categories (name)
            SELECT DISTINCT TRIM(category)
            FROM products
            WHERE TRIM(category) != ''
            """
        )
        transaction_count = connection.execute(
            "SELECT COUNT(*) FROM stock_transactions"
        ).fetchone()[0]
        if transaction_count == 0:
            connection.execute(
                """
                INSERT INTO stock_transactions
                    (product_id, product_name, sku, unit, transaction_type, quantity, note)
                SELECT id, name, sku, unit, 'Masuk', stock_qty, 'Stok awal'
                FROM products
                WHERE stock_qty > 0
                """
            )


def read_categories():
    with database() as connection:
        rows = connection.execute("SELECT name FROM categories ORDER BY name").fetchall()
    return [row["name"] for row in rows]


def save_category(name):
    normalized_name = name.strip()
    if not normalized_name:
        raise ValueError("Nama kategori wajib diisi.")
    with database() as connection:
        connection.execute("INSERT INTO categories (name) VALUES (?)", (normalized_name,))


def read_products():
    with database() as connection:
        rows = connection.execute(
            "SELECT * FROM products ORDER BY category, name"
        ).fetchall()
    return [dict(row) for row in rows]


def read_transactions(limit=None):
    query = """
        SELECT t.id, t.product_name, t.transaction_type, t.quantity,
               COALESCE(NULLIF(t.unit, ''), p.unit, '') AS unit,
               t.note, t.created_at
        FROM stock_transactions AS t
        LEFT JOIN products AS p ON p.id = t.product_id
        ORDER BY datetime(t.created_at) DESC, t.id DESC
    """
    if limit is not None:
        query += " LIMIT ?"
    with database() as connection:
        rows = connection.execute(query, (limit,) if limit is not None else ()).fetchall()
    return [dict(row) for row in rows]


def save_product(product_id, name, category, unit, stock_qty, min_stock):
    values = (name.strip(), category.strip(), unit.strip(), stock_qty, min_stock)
    with database() as connection:
        if product_id is None:
            connection.execute(
                """
                INSERT INTO products
                    (sku, name, category, unit, stock_qty, min_stock)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (f"AUTO-{uuid.uuid4().hex[:12].upper()}",) + values,
            )
        else:
            connection.execute(
                """
                UPDATE products
                SET name = ?, category = ?, unit = ?, stock_qty = ?, min_stock = ?
                WHERE id = ?
                """,
                values + (product_id,),
            )


def record_transaction(product_id, transaction_type, quantity, note):
    with database() as connection:
        product = connection.execute(
            "SELECT id, sku, name, unit, stock_qty FROM products WHERE id = ?",
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
                (product_id, product_name, sku, unit, transaction_type, quantity, note)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                product["id"],
                product["name"],
                product["sku"],
                product["unit"],
                transaction_type,
                quantity,
                note.strip(),
            ),
        )


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
                "Nama produk": product["name"],
                "Kategori": product["category"],
                "Stok": f'{product["stock_qty"]} {product["unit"]}',
                "Batas minimum": f'{product["min_stock"]} {product["unit"]}',
                "Status": status,
            }
        )
    styled_rows = (
        pd.DataFrame(rows)
        .style.set_table_styles(
            [
                {
                    "selector": "th",
                    "props": [
                        ("background-color", "#1B5E20"),
                        ("color", "#FFFFFF"),
                        ("font-weight", "600"),
                    ],
                },
                {
                    "selector": "td",
                    "props": [
                        ("background-color", "#FFFFFF"),
                        ("color", "#1B3320"),
                    ],
                },
            ]
        )
    )
    st.dataframe(styled_rows, width="stretch", hide_index=True)


def render_dashboard(products, transactions):
    st.title("☕ Ringkasan")
    st.caption(f"Pantau persediaan kedai Anda · {datetime.now().strftime('%d %B %Y')}")

    low_stock = [p for p in products if p["stock_qty"] <= p["min_stock"]]
    total_units = sum(p["stock_qty"] for p in products)
    metric_cols = st.columns(3)
    metric_cols[0].metric("Total produk", len(products))
    metric_cols[1].metric("Unit tersedia", f"{total_units:,}".replace(",", "."))
    metric_cols[2].metric("Perlu restock", len(low_stock), delta_color="inverse")

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
            st.bar_chart(movement[["Masuk", "Keluar"]], color=["#1B5E20", "#388E3C"])
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
                    "Jumlah": f'{item["quantity"]} {item["unit"]}'.strip(),
                    "Catatan": item["note"] or "—",
                }
            )
        st.dataframe(recent, width="stretch", hide_index=True)
    else:
        st.info("Belum ada aktivitas. Catat transaksi pertama Anda di menu Transaksi.")


def render_inventory(products):
    st.title("📦 Produk")
    st.caption("Kelola katalog, stok, dan batas minimum persediaan.")
    list_tab, add_tab, edit_tab, delete_tab, categories_tab = st.tabs(
        ["Daftar produk", "Tambah produk", "Edit produk", "Hapus produk", "Kategori"]
    )
    category_options = read_categories()

    with list_tab:
        search_col, category_col, status_col = st.columns([2, 1, 1])
        search = search_col.text_input("Cari produk", placeholder="Nama produk...")
        categories = ["Semua kategori"] + category_options
        category = category_col.selectbox("Kategori", categories)
        status = status_col.selectbox("Status stok", ["Semua", "Aman", "Stok menipis", "Habis"])
        filtered = products
        if search:
            query = search.casefold()
            filtered = [p for p in filtered if query in p["name"].casefold()]
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
            name = col1.text_input("Nama produk")
            category = col2.selectbox("Kategori", category_options)
            unit = col1.text_input("Satuan", placeholder="kg, liter, pcs...")
            col3, col4 = st.columns(2)
            stock_qty = col3.number_input("Stok awal", min_value=0, step=1)
            min_stock = col4.number_input("Batas minimum", min_value=0, step=1)
            submitted = st.form_submit_button("Simpan produk", type="primary")
        if submitted:
            if not all((name.strip(), category.strip(), unit.strip())):
                st.error("Nama, kategori, dan satuan wajib diisi.")
            else:
                save_product(None, name, category, unit, int(stock_qty), int(min_stock))
                st.success("Produk berhasil ditambahkan.")
                st.rerun()

    with edit_tab:
        if not products:
            st.info("Belum ada produk untuk diedit.")
        else:
            product_options = {p["id"]: p for p in products}
            selected_id = st.selectbox(
                "Pilih produk",
                list(product_options),
                format_func=lambda product_id: (
                    f'{product_options[product_id]["name"]} · '
                    f'{product_options[product_id]["category"]}'
                ),
            )
            selected = product_options[selected_id]
            st.caption("Gunakan menu Transaksi untuk menyesuaikan jumlah stok agar riwayat tetap tercatat.")
            with st.form("edit_product_form"):
                col1, col2 = st.columns(2)
                name = col1.text_input("Nama produk", value=selected["name"])
                edit_category_options = sorted(set(category_options) | {selected["category"]})
                category = col2.selectbox(
                    "Kategori",
                    edit_category_options,
                    index=edit_category_options.index(selected["category"]),
                )
                unit = col1.text_input("Satuan", value=selected["unit"])
                col3, col4 = st.columns(2)
                stock_qty = col3.number_input("Stok saat ini", min_value=0, value=selected["stock_qty"], step=1, disabled=True)
                min_stock = col4.number_input("Batas minimum", min_value=0, value=selected["min_stock"], step=1)
                save = st.form_submit_button("Simpan perubahan", type="primary")
            if save:
                if not all((name.strip(), category.strip(), unit.strip())):
                    st.error("Nama, kategori, dan satuan wajib diisi.")
                else:
                    save_product(
                        selected["id"], name, category, unit,
                        selected["stock_qty"], int(min_stock),
                    )
                    st.success("Perubahan produk berhasil disimpan.")
                    st.rerun()

    with delete_tab:
        if not products:
            st.info("Belum ada produk untuk dihapus.")
        else:
            st.caption("Pilih produk pada kolom Hapus, lalu konfirmasi tindakan di bawah tabel.")
            delete_table = pd.DataFrame(
                [
                    {
                        "ID": product["id"],
                        "Hapus": False,
                        "Nama produk": product["name"],
                        "Kategori": product["category"],
                        "Stok": f'{product["stock_qty"]} {product["unit"]}',
                        "Batas minimum": f'{product["min_stock"]} {product["unit"]}',
                    }
                    for product in products
                ]
            )
            with st.form("delete_products_form"):
                selected_products = st.data_editor(
                    delete_table,
                    column_config={
                        "ID": None,
                        "Hapus": st.column_config.CheckboxColumn(
                            "Hapus",
                            help="Centang produk yang ingin dihapus.",
                            default=False,
                        ),
                    },
                    disabled=["ID", "Nama produk", "Kategori", "Stok", "Batas minimum"],
                    hide_index=True,
                    num_rows="fixed",
                    width="stretch",
                )
                confirm_delete = st.checkbox(
                    "Saya yakin ingin menghapus produk yang dipilih."
                )
                submitted = st.form_submit_button("Hapus produk terpilih", type="primary")
            if submitted:
                product_ids = selected_products.loc[
                    selected_products["Hapus"], "ID"
                ].astype(int).tolist()
                if not product_ids:
                    st.warning("Pilih setidaknya satu produk pada tabel.")
                elif not confirm_delete:
                    st.warning("Centang konfirmasi sebelum menghapus produk.")
                else:
                    with database() as connection:
                        connection.executemany(
                            "DELETE FROM products WHERE id = ?",
                            [(product_id,) for product_id in product_ids],
                        )
                    st.success(f"{len(product_ids)} produk berhasil dihapus.")
                    st.rerun()

    with categories_tab:
        st.subheader("Tambah kategori produk")
        with st.form("add_category_form", clear_on_submit=True):
            new_category = st.text_input("Nama kategori", placeholder="Contoh: Minuman")
            add_category = st.form_submit_button("Tambah kategori", type="primary")
        if add_category:
            if not new_category.strip():
                st.error("Nama kategori wajib diisi.")
            else:
                try:
                    save_category(new_category)
                except sqlite3.IntegrityError:
                    st.error("Kategori tersebut sudah tersedia.")
                else:
                    st.success(f'Kategori "{new_category.strip()}" berhasil ditambahkan.')
                    st.rerun()

        st.subheader("Kategori tersedia")
        if category_options:
            st.dataframe(
                pd.DataFrame({"Kategori": category_options}),
                width="stretch",
                hide_index=True,
            )
        else:
            st.info("Belum ada kategori.")


def render_transactions(products):
    st.title("Produk masuk & keluar")
    st.caption("Catat stok masuk dari pemasok atau stok keluar untuk pemakaian dan penjualan.")
    if not products:
        st.info("Tambahkan produk terlebih dahulu di menu Produk.")
        return

    product_options = {p["id"]: p for p in products}
    with st.form("stock_transaction_form", clear_on_submit=True):
        selected_id = st.selectbox(
            "Produk",
            list(product_options),
            format_func=lambda product_id: (
                f'{product_options[product_id]["name"]} '
                f'({product_options[product_id]["stock_qty"]} '
                f'{product_options[product_id]["unit"]})'
            ),
        )
        product = product_options[selected_id]
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


def export_history_xls(dataframe):
    workbook = xlwt.Workbook(encoding="utf-8")
    worksheet = workbook.add_sheet("Riwayat Stok")
    for column_index, column in enumerate(dataframe.columns):
        worksheet.write(0, column_index, str(column))

    for row_index, row in enumerate(dataframe.itertuples(index=False, name=None), start=1):
        for column_index, value in enumerate(row):
            worksheet.write(row_index, column_index, "" if pd.isna(value) else str(value))

    for column_index, column in enumerate(dataframe.columns):
        values = dataframe[column].fillna("").astype(str)
        width = max([len(str(column))] + [len(value) for value in values])
        worksheet.col(column_index).width = min(max(width + 2, 12), 50) * 256

    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


def render_history(transactions):
    st.title("🧾 Riwayat transaksi")
    st.caption("Catatan stok produk yang masuk dan keluar.")
    if not transactions:
        st.info("Belum ada transaksi stok.")
        return
    data = pd.DataFrame(transactions)
    filter_col, search_col = st.columns([1, 2])
    transaction_type = filter_col.selectbox("Jenis", ["Semua", "Masuk", "Keluar"])
    search = search_col.text_input("Cari produk", placeholder="Ketik nama produk...")
    if transaction_type != "Semua":
        data = data[data["transaction_type"] == transaction_type]
    if search:
        data = data[data["product_name"].str.contains(search, case=False, na=False)]

    metric_cols = st.columns(2)
    metric_cols[0].metric(
        "Transaksi masuk",
        int((data["transaction_type"] == "Masuk").sum()),
    )
    metric_cols[1].metric(
        "Transaksi keluar",
        int((data["transaction_type"] == "Keluar").sum()),
    )
    data["Jumlah"] = data.apply(
        lambda item: f'{item["quantity"]} {item["unit"]}'.strip(),
        axis=1,
    )
    shown = data.rename(
        columns={
            "created_at": "Waktu",
            "product_name": "Produk",
            "transaction_type": "Jenis",
            "note": "Catatan",
        }
    )[["Waktu", "Produk", "Jenis", "Jumlah", "Catatan"]]
    st.dataframe(shown, width="stretch", hide_index=True)
    st.download_button(
        "Unduh Excel (.xls)",
        data=export_history_xls(shown),
        file_name=f"riwayat-stok-{datetime.now():%Y%m%d}.xls",
        mime="application/vnd.ms-excel",
    )


def main():
    initialize_database()
    products = read_products()
    transactions = read_transactions()

    with st.sidebar:
        st.markdown("# ☕ I Need Coffee")
        st.caption("Manajemen inventaris kedai")
        page = st.radio(
            "Navigasi",
            ["Ringkasan", "Produk", "Stok", "Riwayat"],
            label_visibility="collapsed",
        )
        st.divider()
        st.caption("")

    if page == "Ringkasan":
        render_dashboard(products, transactions)
    elif page == "Produk":
        render_inventory(products)
    elif page == "Stok":
        render_transactions(products)
    else:
        render_history(transactions)


if __name__ == "__main__":
    main()
