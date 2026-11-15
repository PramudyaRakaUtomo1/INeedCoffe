# Kopi & Stok

Aplikasi manajemen inventaris sederhana untuk coffee shop, dibuat dengan Streamlit dan SQLite.

## Fitur

- Dashboard ringkasan stok, nilai persediaan, dan peringatan stok minimum.
- Tambah, cari, filter, edit, dan hapus produk.
- Catat transaksi stok masuk dan keluar dengan validasi stok tersedia.
- Riwayat transaksi dengan filter, pencarian, dan ekspor Excel `.xls`.
- Contoh produk dimuat otomatis saat database pertama kali dibuat.

## Jalankan lokal

```bash
python -m venv .venv
```

Aktifkan virtual environment, lalu jalankan:

```bash
pip install -r requirements.txt
streamlit run app.py
```

Database default tersimpan di `data/coffee_stock.db`. Lokasinya dapat diubah dengan environment variable `STOCK_DB_PATH`.

## Deploy ke Streamlit Community Cloud

1. Push `app.py`, `requirements.txt`, `.streamlit/config.toml`, dan `README.md` ke repository GitHub.
2. Buat aplikasi baru di [Streamlit Community Cloud](https://share.streamlit.io/).
3. Pilih repository dan branch, lalu set **Main file path** ke `app.py`.
4. Deploy aplikasi.

SQLite lokal cocok untuk demo atau penggunaan sederhana. Penyimpanan filesystem pada layanan hosting gratis dapat bersifat sementara dan tidak cocok sebagai satu-satunya penyimpanan untuk data bisnis penting. Untuk penggunaan produksi, gunakan database persisten terkelola dan arahkan `STOCK_DB_PATH` atau integrasi database aplikasi ke penyedia tersebut.
