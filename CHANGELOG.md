# Changelog - Raja Ongkir

Modul `raja_ongkir` — cek ongkos kirim via RajaOngkir / Komerce dari Sales
Order dan Delivery Order.

## v0.11 — 2026-10-08: Label UI diubah dari "Raja Ongkir" menjadi "Biteship"

### Yang berubah

Hanya **label yang tampil di layar**. Nama teknis modul tetap `raja_ongkir`
(folder, `__manifest__` name, xmlid, dan dependency) supaya tidak perlu migrasi.

| Lokasi | Sebelum | Sesudah |
|---|---|---|
| Nama modul di Apps | `Raja Ongkir` | `Biteship` |
| Menu Inventory → Configuration | `Raja Ongkir` | `Biteship` |
| Judul form / list konfigurasi API | `API Raja Ongkir` | `Biteship API` |
| Action window konfigurasi | `Api Raja Ongkir` | `Biteship API` |
| Label field di Sales Order | `Raja Ongkir Api` | `Biteship Api` |
| Judul notifikasi sync | `Raja Ongkir - Province` | `Biteship - Province` |
| Pesan error tombol | `Raja Ongkir timeout: ...` | `Shipping API timeout: ...` |
| Pesan error tombol | `No service returned by Raja Ongkir` | `No service returned by the shipping API` |

### Kenapa nama teknis TIDAK diganti

Mengganti nama teknis (`raja_ongkir` → `biteship`) berarti memigrasikan
**191 record `ir_model_data`**, **7.584 baris data master** (474 kota, 6.480
kecamatan, 2 config, 628 penawaran), **2.696 referensi FK** dari Sales Order &
customer, plus dependency `agi_additional_fields` dan reinstall modul. Risiko
kehilangan data jauh melebihi manfaat kerapian nama internal yang tidak pernah
dilihat pengguna.

### Catatan

Modul ini **masih mendukung 3 provider** (Biteship, RajaOngkir, Komerce) —
provider dipilih dari field `api_url` pada record konfigurasi. Label "Biteship"
mengikuti provider yang dipakai sekarang.

Test: **87 test, 0 failed** (tidak ada perubahan perilaku; hanya teks).

## v0.10 — 2026-10-08: Dukungan API Biteship (modul tetap `raja_ongkir`)

### Latar belakang

Tarif Komerce/RajaOngkir tidak sama dengan web resmi JNE. Akun Biteship
mengembalikan **JNE REG Rp315.000, 1-2 hari** untuk Jaten (Karanganyar) →
Jember 15 kg — persis angka web resmi JNE. Modul `raja_ongkir` kini bisa
memakai Biteship **tanpa mengganti modul atau tombolnya**: tombol
**Compute Cost Delivery** di Sales Order dan tab Raja Ongkir di Delivery Order
tetap sama, hanya provider di belakangnya yang berubah.

### Cara mengaktifkan

Cukup ubah **API Url** pada record `api.list`:

- Biteship: `https://api.biteship.com` (isi **API Key** Biteship,
  prefix `biteship_live.` / `biteship_test.`)
- RajaOngkir: `https://pro.rajaongkir.com`
- Komerce: `https://rajaongkir.komerce.id/api/v1`

Provider dideteksi otomatis dari `api_url`. Ketiganya tetap didukung.

### Yang ditambahkan

- `ongkir_utils`: `is_biteship`, `biteship_headers`, `biteship_area_query`,
  `pick_biteship_area`, `resolve_biteship_area`, `biteship_search_areas`,
  `parse_biteship_pricing`.
- `stock.picking._fetch_biteship_services()` — `POST /v1/rates/couriers`.
  Biteship memakai `area_id` (bukan `city_id`/`subdistrict_id`) dan
  mengembalikan **semua** layanan kurir yang diminta dalam **satu** permintaan.
- Field baru `biteship_area_id` di `res.country.city` dan
  `res.city.subdistrict` sebagai cache, sehingga hanya kutipan pertama untuk
  suatu kecamatan yang membayar panggilan `/v1/maps/areas`.
- Tombol SO kini memakai satu jalur kode bersama `stock.picking`
  (`_fetch_ongkir_services`), jadi SO dan DO tidak bisa lagi menyimpang.

### Perbaikan yang ikut terbawa

- **Pencocokan nama layanan.** Biteship menamai layanan regulernya
  `"Reguler"`, sedangkan RajaOngkir `"REG"`. `pick_service()` kini mencoba
  kecocokan persis lalu **prefix** (`REG` ⊂ `REGULER`). Tanpa ini, konfigurasi
  `service = REG` diam-diam jatuh ke layanan **termurah** dan quotation
  terharga dengan JNE Trucking, bukan JNE Reguler.
- **Satu kurir per permintaan di jalur SO.** Beberapa kurir sama-sama menamai
  layanannya "Reguler"; meminta semua kurir lalu memilih lintas kurir bisa
  mengutip kurir yang salah. Jalur SO meminta satu kurir (field `origin_courier`
  / `courier`), sedangkan **Get Biaya** di DO meminta semuanya sekaligus.
- **Kuota.** `getBiaya()` dulu memanggil API sekali per kurir (20+ permintaan per
  klik). Dengan Biteship cukup **satu** permintaan.
- `courier` pada SO kini diisi dari **kode** yang dikembalikan provider
  (`resolve_courier_code`), bukan dari nama dagang.

### Test

`tests/test_biteship.py` baru (17 test) — deteksi provider, query/pemilihan area
(kecamatan menang, kode pos unik diterima, kode pos ambigu & kota-saja ditolak),
parsing harga, tombol SO memakai Biteship + API key di header Authorization
(bukan body), area di-cache, tujuan ambigu ditolak (tidak ditebak), 401 & pesan
error API diteruskan, `getBiaya` hanya **satu** permintaan, dan jalur SO hanya
meminta satu kurir.

```bash
odoo-bin -d agi_test --stop-after-init --test-enable \
  --test-tags=/raja_ongkir -u raja_ongkir
```

Hasil: **0 failed, 0 error(s) of 67 tests** (87 test pada statistik modul).

## v0.9 — 2026-10-08: Rute Komerce memakai endpoint & ID yang benar (SO = DO)

### Bug yang dilaporkan

Tarif di Odoo tidak sama dengan web resmi JNE. Rute **Jaten, Karanganyar →
Sumber Sari, Jember, 15 kg**:

| Sumber | Hasil |
|---|---|
| Web resmi JNE | REG **315.000**, 1-2 hari |
| Odoo (sebelum perbaikan) | CTC **525.000**, **11 hari** |
| Setelah perbaikan | REG **765.000**, 3 hari (endpoint kecamatan + ID kecamatan) |

ETD 11 hari untuk rute Jawa→Jawa adalah tanda pertama bahwa areanya salah
dibaca.

### Penyebab

Komerce punya **dua endpoint tarif dengan dua ruang ID berbeda**:

- `/calculate/domestic-cost` → ID **kabupaten/kota**
- `/calculate/district/domestic-cost` → ID **kecamatan**

`SaleOrder.compute_ongkir()` selalu memakai endpoint **kecamatan**, tetapi
mengirim **`city_id`**:

```python
komerce_origin = api.origin_subdistrict_id.city_rel.city_id   # city_id (169)
endpoint = '/calculate/district/domestic-cost'                # endpoint kecamatan
```

Komerce **tidak menolak** ID kota di endpoint kecamatan — ia tetap menjawab
HTTP 200, tetapi menafsirkan kota sebagai kecamatan sehingga tarif dan ETD
menunjuk area yang salah. Padahal modul sudah menyimpan ID kecamatan yang
benar (2355 = Jaten, 2227 = Sumber Sari).

Akibat tambahan: jalur **Sales Order** dan **Delivery Order** memakai aturan
berbeda (`stock.py` mengirim ID kecamatan ke endpoint kecamatan), sehingga
kedua tombol menghasilkan tarif berbeda untuk rute yang sama.

### Perbaikan

- Modul baru `models/ongkir_utils.py` berisi helper bersama
  (`is_komerce`, `ongkir_url`, `komerce_route`) — URL dan pasangan
  endpoint/ID tidak lagi diduplikasi di dua model.
- `komerce_route(origin, destination)` memilih endpoint **sesuai tipe area**:
  dua kecamatan → endpoint kecamatan + ID kecamatan; dua kota → endpoint kota +
  ID kota.
- Rute **campuran** (satu kota, satu kecamatan) diturunkan ke tarif **kota**
  memakai kota induk. Penurunan dipilih karena menaikkan kota ke kecamatan
  sembarang akan mengarang rute yang tidak pernah dipilih pengguna.
- `models/sale_order.py` dan `models/stock.py` sama-sama memakai helper ini,
  jadi SO dan DO kini menghitung rute yang sama.
- `_resolve_ongkir_origin()` / `_resolve_ongkir_destination()` di `stock.py`
  mengembalikan dict `{'type', 'city_id', 'subdistrict_id'}` (sebelumnya tuple
  id + tipe), dan `_fetch_ongkir_services()` menerima dict tersebut.

### Catatan penting: tarif Komerce ≠ tarif JNE resmi

Perbaikan ini membuat rute yang dihitung **benar**, tetapi **tidak** membuat
angka Komerce sama dengan web JNE. Komerce tidak menyediakan tarif JNE resmi.
Untuk angka resmi JNE dibutuhkan sumber tarif resmi:

- `pro.rajaongkir.com` — dari server ini koneksinya **timeout** (DNS resolve ke
  64.227.6.154, tetapi TCP tidak tersambung); butuh API key RajaOngkir Pro.
- API JNE langsung — butuh akun korporat JNE.

Selama akun masih Komerce, angka Komerce tetap dipakai; biaya resmi bisa
dimasukkan manual (field `cost_delivery` dapat diedit, atau lewat
**Get Biaya** → **Create Delivery Bill** untuk biaya realisasi).

### Test

`tests/test_courier.py` ditambah 6 test: `TestKomerceRoute` (dua kecamatan →
endpoint kecamatan + ID kecamatan; dua kota → endpoint kota + ID kota; rute
campuran turun ke kota; kecamatan tanpa ID turun ke kota; pembentukan URL) dan
`TestOngkirRouteMatchesBetweenSalesAndDelivery` (tombol SO dan DO memanggil
endpoint yang sama dengan ID yang sama, dan tarif REG yang dikembalikan
tersimpan di SO).

Regresi terverifikasi: dengan `komerce_route` dikembalikan ke perilaku lama,
**6 test gagal**.

```bash
odoo-bin -d agi_test --stop-after-init --test-enable \
  --test-tags=/raja_ongkir -u raja_ongkir
```

Hasil: **0 failed, 0 error(s) of 47 tests** (61 test pada statistik modul).

## v0.8 — 2026-10-08: Tombol "Compute Cost Delivery" tidak lagi error di rute tanpa REG

### Bug yang dilaporkan

Klik **Compute Cost Delivery** pada Sales Order / Quotation gagal dengan:

```
User Error
No service returned by Raja Ongkir for courier jne.
```

padahal API menjawab sukses. Hasil tangkapan respons asli (SO S01473,
Komerce `rajaongkir.komerce.id/api/v1`):

```json
{"meta": {"message": "Success Calculate Domestic Shipping cost",
          "code": 200, "status": "success"},
 "data": [{"name": "Jalur Nugraha Ekakurir (JNE)", "code": "jne",
           "service": "CTC", "description": "JNE City Courier",
           "cost": 525000, "etd": "11 day"}]}
```

### Penyebab

`SaleOrder.compute_ongkir()` mengunci layanan ke **REG** saja (untuk Komerce
dan layout klasik). Komerce tidak mengembalikan `REG` di semua rute —
rute di atas hanya menyediakan `CTC` (JNE City Courier). Karena tidak ada baris
yang cocok, `compute_service_cost` tetap kosong lalu `UserError` dilempar.
Bukti bahwa integrasi API-nya sendiri sehat: SO lama S01472/S01470 berhasil
terisi `REG` dari API yang sama.

### Perbaikan

- Field baru **`api.list.service`** (default `REG`, bisa diubah per record API:
  `REG`, `YES`, `CTC`, `JTR`, dst) — muncul di form dan tree konfigurasi API.
- Helper baru `pick_service(results, wanted_service)` di `models/sale_order.py`:
  1. cari baris yang `service`-nya sama dengan layanan terkonfigurasi
     (case/spasi dinormalkan);
  2. bila tidak ada, pakai **layanan termurah** yang dikembalikan provider,
     bukan melempar error;
  3. bila provider tidak mengembalikan tarif sama sekali → tetap `UserError`
     yang jelas.
- `compute_ongkir()` (layout Komerce **dan** klasik) memakai helper ini.
  Layout klasik kini meratakan seluruh `costs`/`cost` dulu, sehingga tidak lagi
  berhenti di kurir/layanan pertama.
- Nilai biaya dinormalkan lewat `_cost_value()` (tahan string/null).

### Test

`tests/test_courier.py` ditambah 9 test (HTTP di-mock): `pick_service`
layanan terpilih menang, fallback termurah saat REG tidak ada, cocok
case/spasi, layanan terkonfigurasi (`YES`), jawaban kosong; serta
`TestComputeCostDeliveryOnSaleOrder` — layanan terkonfigurasi tersimpan,
rute tanpa REG jatuh ke CTC tanpa error (regresi persis kasus produksi),
layanan terkonfigurasi menang atas REG, dan tarif kosong tetap error jelas.

```bash
odoo-bin -d agi_test --stop-after-init --test-enable \
  --test-tags=/raja_ongkir -u raja_ongkir
```

## v0.7 — 2026-10-05: Field `courier` tidak lagi kosong setelah pilih layanan

### Bug yang ditemukan saat investigasi tarif JNE

`ongkir.list.pilihLayanan()` menyimpan `stock.picking.courier` dengan cara
mencocokkan **nama** kurir dari API ke label selection:

```python
record.write({'courier': {label: code for code, label in courier_code}.get(self.name)})
```

Komerce mengembalikan `name: "Jalur Nugraha Ekakurir (JNE)"`, sedangkan key
label modul adalah `"JNE"`. `.get()` mengembalikan `None`, jadi `courier` ditulis
kosong. Gejalanya terlihat di produksi: hampir semua picking lama punya
`service_name` terisi (`REG`/`YES`/`JTR`) tetapi kolom `courier` kosong, padahal
tarifnya sudah terisi.

Penyebabnya provider mengembalikan nama dagang/legal, bukan kode mesin.

### Perbaikan

- `ongkir.list` dapat field baru `code`, diisi dari `code` yang dikembalikan API
  (`_fetch_ongkir_services()` sudah mengambil field ini di kedua layout API).
- Helper baru `resolve_courier_code(code, name)` di `models/stock.py`:
  1. `code` dari API — sumber otoritatif dan sudah sesuai key selection;
  2. fallback ke `name`: cocok persis (case/spasi dinormalkan), lalu label yang
     menjadi substring dari nama;
  3. mengembalikan `None` bila kurir tidak dikenal — bukan lagi diam-diam
     menyimpan nilai kosong.
- `pilihLayanan()` memakai `self.picking_id` langsung (bukan `search()`) dan
  `ensure_one()`, lalu melempar `UserError` yang jelas bila kurir tidak ada di
  selection.
- `compute_estimation_ongkir()` dan `getBiaya()` menyimpan `code` di setiap baris
  popup.

Baris `ongkir.list` lama yang belum punya `code` tetap bisa dipilih: fallback
nama Estimate/REG/etc. tetap bekerja.

### Test

`tests/test_courier.py` (18 test, HTTP di-mock): `code` API menang atas nama,
nama dagang Komerce terpetakan, pencocokan nama tahan case/spasi, label di
dalam nama lebih panjang, kurir asing `None`, alur `compute_estimation_ongkir`
→ `pilihLayanan` mengisi `courier`/`cost_delivery`/`etd`, baris lama tanpa
`code`, error terbaca untuk kurir tak dikenal, dan mode realisasi tidak
menyentuh `courier`.

Regresi `test_choosing_a_service_stores_the_courier` sudah diverifikasi gagal
(`AssertionError: False != 'jne'`) saat `pilihLayanan` dikembalikan ke kode
lama.

```bash
odoo-bin -d agi_test --stop-after-init --test-enable \
  --test-tags=/raja_ongkir -u raja_ongkir
```

Suku RajaOngkir saja: **0 failed, 0 error(s)** (37 test pada statistik modul).

## v0.6 — 2026-10-05: Tombol Sync City tidak lagi RPC_ERROR

### Bug yang dilaporkan

Klik **Sync City** (dan **Sync Province / Sync Subdistrict**) menghasilkan
`RPC_ERROR: Odoo Server Error` dengan dua lapis error:

1. `requests.exceptions.JSONDecodeError: Extra data: line 1 column 5 (char 4)`
   dari `requests.get(...).json()`;
2. `UnboundLocalError: cannot access local variable 'e' where it is not
   associated with a value` — jadi pesan aslinya justru hilang.

### Penyebab

- Kode lama memanggil `.json()` tanpa memeriksa status HTTP maupun
  content-type. Akun yang dipakai (`rajaongkir.komerce.id/api/v1`) tidak
  menyediakan endpoint daftar provinsi/kota/kecamatan dan menjawab
  `404 page not found` (plain text). `json.loads("404 page not found")`
  mengurai `404` sebagai angka lalu melaporkan `page not found` sebagai
  "Extra data" — persis pesan pada traceback.
- Handler terakhir `except requests.exceptions.RequestException as err:`
  mencetak `e`. Di Python 3 nama exception di-`del` saat blok `except`
  selesai, sehingga `e` tidak terikat dan error kedua menimpa error asli.
- Semua error ditelan dengan `print()` ke log server, jadi tombol terlihat
  "berhasil" padahal tidak melakukan apa pun.

### Perbaikan

- `_api_get_json()`: GET bersih tanpa body, timeout 30 detik, cek status HTTP
  dan content-type. Timeout, connection error, body kosong, dan body non-JSON
  semuanya jadi `UserError` yang menyebut URL dan cara memperbaikinya.
- `_api_results()`: ekstrak `rajaongkir.results` dengan aman; kunci `results`
  yang hilang (key salah / akun belum aktif) dilaporkan jelas.
- `_api_unsupported_message()`: untuk host tanpa daftar wilayah (Komerce),
  pesan menjelaskan bahwa sync butuh API resmi `pro.rajaongkir.com`.
- Provider yang memblokir seluruh request tidak lagi menggagalkan separuh
  pekerjaan: error per provinsi/kota dikumpulkan dan dilaporkan sebagai
  notifikasi peringatan di akhir, sehingga provinsi yang berhasil tetap
  tersimpan. Dirollback (yang mengembalikan transaksi) hanya bila **tidak
  ada** satu pun yang berhasil.
- Ganti `print()` dengan `_logger` (info untuk sukses, error+warning untuk
  kegagalan) dan kembalikan `display_notification` berisi ringkasan
  created/updated.
- `_api_check_ready()` memakai `status != 'enable'`; sebelumnya
  `not self.status` selalu false karena nilainya `'enable'`/`'disable'`,
  sehingga API nonaktif tetap bisa dipakai.
- `_api_country()` memberi pesan jelas bila negara "Indonesia" tidak ada,
  alih-alih membuat provinsi tanpa negara (`country_id` required).
- Pencocokan nama tidak lagi lintas provinsi/negara. Sebelumnya
  `search([('name', '=', ...)])` polos bisa menulis `city_id`/`province_id`
  ke kota bernama sama di provinsi lain atau state bernama sama di negara lain;
  sekarang dicocokkan dengan `province_rel`/`country_id` juga.
- Entry yang tidak valid (bukan dict / tanpa id) di-skip dengan log warning
  alih-alih menghentikan seluruh sync.

### Test

`tests/test_api.py` (16 test, semua HTTP di-mock): normalisasi URL, 404
Komerce, body HTML, timeout, connection error, body kosong, `results` hilang,
GET tanpa body, ensure API aktif, import idempoten, dan ketiga kasus
saling-tumpang tindih di atas.

```bash
odoo-bin -d agi_test --stop-after-init --test-enable \
  --test-tags=/raja_ongkir -u raja_ongkir
```

Regression gabungan dengan dua modul lain: **0 failed, 0 error(s) of 122 tests**.
