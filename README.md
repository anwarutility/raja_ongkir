# Biteship

Modul Odoo 16 untuk mengecek ongkos kirim (biaya pengiriman) pada suatu kabupaten/kota / kecamatan. Versi lokal terdahulu oleh `Legian Wahyu P`, dikembangkan di `anwarutility`.

> **Nama teknis modul tetap `raja_ongkir`.** Yang berubah hanya label yang tampil
> di layar (nama modul, menu, judul form, label field). Nama teknis sengaja
> dibiarkan agar 191 record data, 7.584 baris data master, dan dependency modul
> lain tidak perlu dimigrasikan.

Tiga provider didukung, **dipilih otomatis dari field `api_url`**:

| `api_url` | Provider | Catatan |
|---|---|---|
| `https://api.biteship.com` | **Biteship** | Tarif sesuai kurir resmi (JNE REG Jaten→Jember 15 kg = **Rp315.000, 1-2 hari**) |
| `https://pro.rajaongkir.com` | RajaOngkir | Butuh key Pro/Starter |
| `https://rajaongkir.komerce.id/api/v1` | Komerce | Tarif versi Komerce, **bukan** tarif resmi JNE |

> Untuk tarif yang sama dengan web resmi JNE, gunakan **Biteship**. Komerce
> memakai tarif versinya sendiri, dan API RajaOngkir resmi
> (`pro.rajaongkir.com`) tidak dapat dijangkau dari server ini.

## Fitur

- Cek ongkos kirim dari **Sales Order** (estimasi biaya kirim) dan **Delivery Order** (estimasi + biaya realisasi).
- Dukungan tipe asal/tujuan **Kabupaten/Kota** maupun **Kecamatan** (`originType` / `destinationType`).
- Support **Biteship** (`api.biteship.com`), **RajaOngkir** (`pro.rajaongkir.com`), dan **Komerce** (`rajaongkir.komerce.id`, layout berbeda) — terdeteksi otomatis dari `api_url`.
- **26 kurir** (JNE, POS, TIKI, Wahana, SiCepat, J&T, Ninja Xpress, Lion Parcel, Anteraja, dll).
- Berat otomatis dari move/delivery line (`berat produk x qty`), tetap bisa diedit manual (minimum 1 kg).
- **Estimasi ongkir** (per kurir terpilih): 1 opsi langsung terisi otomatis, banyak opsi muncul di popup "List Ongkir" untuk dipilih layanannya.
- **Realisasi ongkir**: bandingkan semua kurir dalam satu popup, pilih kurir/layanan untuk dijadikan biaya realisasi.
- **Buat tagihan biaya kirim** (vendor bill `in_invoice`) satu klik dari Delivery Order, dengan partner/produk/akun dari konfigurasi API.
- Sinkronisasi data **Provinsi, Kota/Kabupaten, Kecamatan** dari API RajaOngkir.

## Konfigurasi API

1. Buka **Inventory > Configuration > Biteship > Api**.
2. Buat record API (sebelum di-enable field bisa diisi):
   - **Name** — nama konfigurasi.
   - **API Key** — key akun sesuai provider. Untuk Biteship isi API Key Biteship (prefix `biteship_live.` / `biteship_test.`).
   - **API URL** — `https://api.biteship.com` (Biteship), `https://pro.rajaongkir.com` (RajaOngkir), atau `https://rajaongkir.komerce.id/api/v1` (Komerce).
   - **Origin City Type / Origin City (atau Origin Subdistrict)** — asal kirim, default dari config.
   - **Origin Courier** — kurir default untuk cek ongkir.
   - **Service** — layanan yang diutamakan tombol **Compute Cost Delivery** di Sales Order (default `REG`; bisa `YES`, `CTC`, `JTR`, dst). Bila provider tidak menyediakan layanan tersebut pada rute itu, modul otomatis memakai layanan termurah yang tersedia.
   - **Destination City Type Default** — tipe tujuan default.
   - **Accounting Delivery Cost** — Partner, Produk, dan Akun untuk pembuatan tagihan biaya kirim.
3. Klik tombol **Sync Province / Sync City / Sync Subdistrict** untuk mengisi data master, lalu tombol **Enable**.
4. Setelah enable, field API terkunci (readonly).

> **Sync hanya bisa dipakai dengan API RajaOngkir resmi** (`pro.rajaongkir.com`).
> Akun **Komerce tidak menyediakan endpoint daftar provinsi/kota/kecamatan** —
> `GET /province`, `/city`, dan `/subdistrict` di `rajaongkir.komerce.id`
> menjawab `404 page not found`; Komerce hanya melayani endpoint
> `/calculate/...`. Karena itu klik tombol sync dengan akun Komerce akan
> menampilkan pesan jelas, bukan traceback. Data kota/kecamatan di database ini
> sudah terisi (34 provinsi, 474 kota, 6480 kecamatan), jadi sync tidak
> diperlukan untuk memakai Komerce.

> **Biteship tidak memakai data provinsi/kota/kecamatan di atas.** Biteship
> menagih rute memakai `area_id` miliknya sendiri. Modul memetakan kecamatan
> (atau kota) tujuan ke `area_id` Biteship secara otomatis lewat
> `/v1/maps/areas`, lalu **menyimpannya di field `Biteship Area ID`** pada
> master City / Subdistrict — jadi hanya kutipan pertama untuk suatu kecamatan
> yang perlu pencarian area. Karena itu tombol **Sync Province/City/Subdistrict**
> tidak perlu dipakai dengan Biteship.

> Biteship mencari alamat secara **kabur**. Bila satu kode pos dipakai beberapa
> kecamatan dan kecamatannya tidak diketahui, modul **menolak** menghitung
> (pesan jelas) daripada menebak zona yang salah. Lengkapi
> **Destination Subdistrict** pada customer / kota tujuan.

> Keamanan: API key tidak boleh di-hardcode — diinput manual via menu di atas setelah module dideploy.

## Cara Pakai

### Sales Order

1. Set **Biteship Api** ($ koneksi ke `api.list`), pilih partner → `city_id`/`subdistrict_id` mengikuti partner (`onchange_partner_id`).
2. Berat total terhitung otomatis dari `order_line.weight_subtotal`.
3. Klik tombol **Compute Cost Delivery** → isi field `courier_name`, `service_name`, `cost_delivery`, `etd`.

> Layanan yang dipilih mengikuti field **Service** pada konfigurasi API
> (default `REG`). Provider menamai layanan berbeda-beda — RajaOngkir `REG`,
> Biteship `Reguler` — jadi modul mencocokkan persis lalu **prefix**
> (`REG` ⊂ `REGULER`). Bila layanan itu tidak ada pada rute tersebut, dipakai
> layanan termurah yang tersedia.

> Dengan Biteship, permintaan hanya untuk **satu** kurir (field
> `origin_courier`), karena beberapa kurir sama-sama menamai layanannya
> "Reguler" — memilih lintas kurir bisa mengutip kurir yang salah.

> `weight_subtotal` dihitung dari `product.qty x product.weight` (weight dibaca dari product master).

### Delivery Order (outgoing)

Tab Cost Delivery berisi:

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
- Field `courier` diisi dari **kode** kurir yang dikembalikan API (disimpan di `ongkir.list.code`), bukan dari nama kurir. Provider seperti Komerce mengembalikan nama dagang/legal (`Jalur Nugraha Ekakurir (JNE)`) yang tidak sama dengan label selection, sehingga pencocokan berbasis nama membuat `courier` kosong.

## Known Limitations

- **Sinkronisasi daerah** (provinsi/kota/kecamatan) dipicu manual per record API (tombol Sync) — belum ada scheduler otomatis.
- Versi `compute_ongkir()` di `sale.order` mengutamakan layanan yang dikonfigurasi pada `api.list.service` (default **REG**); bila layanan itu tidak tersedia pada rute, dipakai layanan **termurah** yang dikembalikan provider. Versi `stock.picking` lebih lengkap (semua layanan bisa dipilih lewat popup).
- API `pro.rajaongkir.com` pakai paket **Pro/Starter** — beberapa fitur (`originType` kecamatan) butuh paket yang mendukung.
- **Komerce tidak bisa dipakai untuk tarif JNE yang sesuai web resmi JNE.** Tarif `JNE REG` yang dikembalikan Komerce minimal `Rp35.000/kg` (asal `2355` → `1482` = `Rp47.000/kg`), sedangkan JNE resmi untuk rute domestik Jawa `Rp10.000/kg`. Komerce juga tidak menyediakan endpoint referensi (`/province`, `/city`, `/subdistrict` semuanya `404`) sehingga id daerah yang dikirim modul tidak dapat diverifikasi atau dipetakan ke id lokal, dan layanan `OKE`/`YES` tidak dikembalikan. **Gunakan Biteship** atau kalkulator resmi JNE sebagai sumber tarif.
- **Kuota harian Komerce cepat habis.** Endpoint tarif dipanggil satu kali per kurir pada `Get Biaya` (25 kurir per klik); hitung ulang berulang akan memicu `Daily limit exceeded`.

## Test

```bash
odoo-bin -d agi_test --stop-after-init --test-enable \
  --test-tags=/raja_ongkir -u raja_ongkir
```

Jalankan dari `/tmp` (user `odoo` tidak bisa membaca `/home/oem`). Cakupan:
client reference-data (province/city/subdistrict), pemetaan kode kurir,
layanan terpilih/fallback, rute Komerce (endpoint mengikuti tipe area), dan
jalur Biteship (deteksi provider, pemilihan area, cache `area_id`, parsing
harga, satu permintaan untuk semua kurir, dan penolakan zona ambigu).