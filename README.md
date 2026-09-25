# Raja Ongkir

Modul Odoo 16 untuk mengecek ongkos kirim (biaya pengiriman) via API RajaOngkir pada suatu kabupaten/kota / kecamatan. Versi lokal terdahulu oleh `Legian Wahyu P`, dikembangkan di `anwarutility`.

## Fitur

- Cek ongkos kirim dari **Sales Order** (estimasi biaya kirim) dan **Delivery Order** (estimasi + biaya realisasi).
- Dukungan tipe asal/tujuan **Kabupaten/Kota** maupun **Kecamatan** (`originType` / `destinationType`).
- Support **API RajaOngkir** (`pro.rajaongkir.com`) dan **Komerce** (`rajaongkir.komerce.id`, layout berbeda) — terdeteksi otomatis dari `api_url`.
- **26 kurir** (JNE, POS, TIKI, Wahana, SiCepat, J&T, Ninja Xpress, Lion Parcel, Anteraja, dll).
- Berat otomatis dari move/delivery line (`berat produk x qty`), tetap bisa diedit manual (minimum 1 kg).
- **Estimasi ongkir** (per kurir terpilih): 1 opsi langsung terisi otomatis, banyak opsi muncul di popup "List Ongkir" untuk dipilih layanannya.
- **Realisasi ongkir**: bandingkan semua kurir dalam satu popup, pilih kurir/layanan untuk dijadikan biaya realisasi.
- **Buat tagihan biaya kirim** (vendor bill `in_invoice`) satu klik dari Delivery Order, dengan partner/produk/akun dari konfigurasi API.
- Sinkronisasi data **Provinsi, Kota/Kabupaten, Kecamatan** dari API RajaOngkir.

## Konfigurasi API

1. Buka **Inventory > Configuration > Raja Ongkir > Api**.
2. Buat record API (sebelum di-enable field bisa diisi):
   - **Name** — nama konfigurasi.
   - **API Key** — key akun RajaOngkir (Pro).
   - **API URL** — default `https://pro.rajaongkir.com` (untuk Komerce isi base `https://rajaongkir.komerce.id/api/v1`).
   - **Origin City Type / Origin City (atau Origin Subdistrict)** — asal kirim, default dari config.
   - **Origin Courier** — kurir default untuk cek ongkir.
   - **Destination City Type Default** — tipe tujuan default.
   - **Accounting Delivery Cost** — Partner, Produk, dan Akun untuk pembuatan tagihan biaya kirim.
3. Klik tombol **Sync Province / Sync City / Sync Subdistrict** untuk mengisi data master, lalu tombol **Enable**.
4. Setelah enable, field API terkunci (readonly).

> Keamanan: API key tidak boleh di-hardcode — diinput manual via menu di atas setelah module dideploy.

## Cara Pakai

### Sales Order

1. Set **Raja Ongkir Api** ($ koneksi ke `api.list`), pilih partner → `city_id`/`subdistrict_id` mengikuti partner (`onchange_partner_id`).
2. Berat total terhitung otomatis dari `order_line.weight_subtotal`.
3. Klik tombol **Hitung Ongkir** → isi field `courier_name`, `service_name`, `cost_delivery`, `etd` (termurah).

> `weight_subtotal` dihitung dari `product.qty x product.weight` (weight dibaca dari product master).

### Delivery Order (outgoing)

Tab Raja Ongkir berisi:

- **Estimation** — `courier`, `courier_name`, `service_name`, `cost_delivery`, `etd`. Tombol **Compute Estimation Ongkir** menghitung tarif kurir terpilih (1 opsi langsung terisi; banyak opsi → popup pilih layanan).
- **Realitation** — `realitation_courier_name`, `realitation_service_name`, `realitation_cost_delivery`, `realitation_etd`. Tombol **Get Biaya** menghitung tarif SEMUA kurir sekaligus di popup `ongkir.list`.
- Berat terisi otomatis dari move lines (`_auto_weight_from_moves`); nilai manual selalu dihormati.
- **Create Delivery Bill** — buat vendor bill dari `realitation_cost_delivery`, terhubung ke GD/Out via `picking_id` & `source_document` di `account.move`.

### Popup "List Ongkir"

Model `ongkir.list` menampilkan daftar tarif yang diurutkan termurah (`_order = 'value, name, service'`). Pilih salah satu layanan → `pilihLayanan()` menulis ke field Estimasi (mode `estimation`) atau Realisasi (mode `realitation`).

## Catatan Teknis

- `api.list` mendukung multiple config; hanya config berstatus **Enable** yang bisa dipakai.
- `_fetch_ongkir_services()` menormalkan response klasik RajaOngkir (`/api/cost`) dan Komerce (`/calculate/district/domestic-cost`) menjadi satu format service.
- `_ongkir_weight_grams()` memaksa minimum 1 kg (syarat API RajaOngkir).
- `account.move` di-extend: field `picking_id` (link ke GD/Out) dan `source_document` (`origin`) untuk attribusi vendor bill.
- Kurir default di Delivery Order bisa diisi field `courier` di tab, atau fallback ke `origin_courier` dari `api.list` / SO.

## Known Limitations

- **Sinkronisasi daerah** (provinsi/kota/kecamatan) dipicu manual per record API (tombol Sync) — belum ada scheduler otomatis.
- Versi lama `compute_ongkir()` di `sale.order` hanya mengambil layanan **termurah pertama** per kurir; versi `stock.picking` lebih lengkap (semua layanan bisa dipilih).
- API `pro.rajaongkir.com` pakai paket **Pro/Starter** — beberapa fitur (`originType` kecamatan) butuh paket yang mendukung.